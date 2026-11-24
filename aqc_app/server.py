"""Loopback-only HTTP interface with an explicit public-file allowlist."""
from __future__ import annotations

import http.server
import json
from pathlib import Path
import re
import socket
import sys
import threading
from urllib.parse import urlsplit

from . import __version__
from .data import DevelopmentStore, strict_json
from .sessions import APIError, SessionManager

MAX_BODY_BYTES = 32768
SOCKET_TIMEOUT_SECONDS = 5.0
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/assets/client.js": ("assets/client.js", "text/javascript; charset=utf-8"),
    "/assets/app.js": ("assets/app.js", "text/javascript; charset=utf-8"),
    "/assets/styles.css": ("assets/styles.css", "text/css; charset=utf-8"),
    "/assets/molecule-viewer.js": ("assets/molecule-viewer.js", "text/javascript; charset=utf-8"),
}
SESSION_TOKEN = re.compile(r"[A-Za-z0-9_-]{32}")
IDEMPOTENCY_TOKEN = re.compile(r"[A-Za-z0-9_.:-]{1,80}")


class LocalHTTPServer(http.server.ThreadingHTTPServer):
    """Always IPv4 loopback; constructor exposes no remote bind parameter."""
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 16

    def __init__(self, *, store=None, app_dir=None, port=8765, max_sessions=32,
                 session_ttl=900.0, worker_timeout=5.0, max_requests=16,
                 transport_factory=None, quiet=False):
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("port must be an integer between 0 and 65535")
        self.store = DevelopmentStore() if store is None else store
        self.app_dir = (Path(app_dir) if app_dir is not None else self.store.root / "app").resolve()
        self.quiet = quiet
        self._slots = threading.BoundedSemaphore(max_requests)
        self.max_requests = max_requests
        options = {"max_sessions": max_sessions, "ttl": session_ttl, "worker_timeout": worker_timeout}
        if transport_factory is not None:
            options["transport_factory"] = transport_factory
        self.sessions = SessionManager(self.store, **options)
        self._janitor_stop = threading.Event()
        self._janitor = None
        try:
            super().__init__(("127.0.0.1", port), RequestHandler)
        except BaseException:
            self.sessions.close()
            raise
        self._janitor = threading.Thread(target=self._expire_sessions, name="aqc-session-expiry", daemon=True)
        self._janitor.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_address[1]}/"

    def _expire_sessions(self):
        while not self._janitor_stop.wait(1.0):
            self.sessions.purge()

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            try:
                body = b'{"error":{"code":"server_busy","message":"Local request capacity reached; retry shortly."}}'
                request.sendall(b"HTTP/1.1 429 Too Many Requests\r\nContent-Type: application/json\r\nConnection: close\r\nCache-Control: no-store\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def server_close(self):
        self._janitor_stop.set()
        if self._janitor is not None and self._janitor is not threading.current_thread():
            self._janitor.join(timeout=2)
        self.sessions.close()
        super().server_close()


class RequestHandler(http.server.BaseHTTPRequestHandler):
    server_version = "AQC-Local/1"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(SOCKET_TIMEOUT_SECONDS)

    def log_message(self, format, *args):
        if not self.server.quiet:
            message = (format % args).replace("\n", " ").replace("\r", " ")
            sys.stderr.write("AQC local: " + message + "\n")

    def _send(self, status, raw, content_type, *, filename=None):
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; frame-src 'none'")
        if filename is not None:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def _json(self, status, value, *, filename=None):
        raw = (json.dumps(value, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")
        self._send(status, raw, "application/json; charset=utf-8", filename=filename)

    def _check_request(self):
        hosts = self.headers.get_all("Host", [])
        port = self.server.server_address[1]
        allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            allowed_hosts.update({"127.0.0.1", "localhost"})
        if len(hosts) != 1 or hosts[0].lower() not in allowed_hosts:
            raise APIError(403, "unsafe_host", "Host must name this loopback server and its actual port.")
        origins = self.headers.get_all("Origin", [])
        if len(origins) > 1 or (origins and origins[0] != "http://" + hosts[0].lower()):
            raise APIError(403, "unsafe_origin", "Cross-origin requests are not accepted.")
        if self.headers.get("Sec-Fetch-Site", "").lower() == "cross-site" and (self.command not in ("GET", "HEAD") or self.path.startswith("/api/")):
            raise APIError(403, "unsafe_origin", "Cross-site API requests are not accepted.")
        if self.headers.get_all("Transfer-Encoding"):
            raise APIError(400, "unsupported_transfer_encoding", "Chunked request bodies are not accepted.")
        if self.headers.get("Content-Encoding", "identity").lower() != "identity":
            raise APIError(415, "unsupported_content_encoding", "Compressed request bodies are not accepted.")
        if self.headers.get_all("Expect"):
            raise APIError(417, "unsupported_expectation", "Expect headers are not accepted.")
        if len(self.headers) > 40:
            raise APIError(431, "too_many_headers", "Too many request headers.")
        if any(char in self.path for char in ("%", "\\", "\x00")) or not self.path.startswith("/") or "//" in self.path:
            raise APIError(400, "invalid_path", "Invalid request path.")
        parsed = urlsplit(self.path)
        if parsed.query or parsed.fragment or parsed.netloc or any(part in (".", "..") for part in parsed.path.split("/")):
            raise APIError(400, "invalid_path", "Only canonical app and API paths are accepted.")
        return parsed.path

    def _body(self):
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not re.fullmatch(r"\d+", lengths[0]):
            raise APIError(411 if not lengths else 400, "invalid_content_length", "Supply exactly one valid Content-Length.")
        if len(lengths[0]) > 8:
            raise APIError(413, "body_too_large", f"JSON body exceeds {MAX_BODY_BYTES} bytes.")
        size = int(lengths[0])
        if size > MAX_BODY_BYTES:
            raise APIError(413, "body_too_large", f"JSON body exceeds {MAX_BODY_BYTES} bytes.")
        if self.headers.get_content_type() != "application/json":
            raise APIError(415, "json_required", "Use application/json for session actions.")
        charset = self.headers.get_content_charset()
        if charset is not None and charset.lower() not in ("utf-8", "utf8"):
            raise APIError(415, "utf8_required", "JSON must use UTF-8.")
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise APIError(400, "incomplete_body", "The request body was incomplete.")
        try:
            value = strict_json(raw.decode("utf-8"))
        except (ValueError, UnicodeError, RecursionError) as error:
            raise APIError(400, "invalid_json", "JSON must be a finite, unambiguous object.") from error
        if not isinstance(value, dict):
            raise APIError(400, "invalid_json", "JSON must be an object.")
        return value

    def _operation_id(self):
        values = self.headers.get_all("Idempotency-Key", [])
        if len(values) > 1 or (values and not IDEMPOTENCY_TOKEN.fullmatch(values[0])):
            raise APIError(400, "invalid_idempotency_key", "Use a single short ASCII Idempotency-Key.")
        return values[0] if values else None

    def _respond_session(self, session, *, status=200):
        value = session.state() if not isinstance(session, dict) else session
        if value["status"] == "failed":
            self._json(502, {"error": {"code": "policy_execution_failed", "message": "The policy process failed; all charged queries remain in this session."}, "session": value})
        else:
            self._json(status, value)

    def _get(self, path):
        if path == "/api/health":
            self._json(200, {"status": "ok", "app_version": __version__, "api_version": 1,
                             "scope": "original_development_only", "reference_boundary": "server_authoritative",
                             "counts": self.server.store.counts, "no_optional_dependencies": True,
                             "limits": {"max_sessions": self.server.sessions.max_sessions,
                                        "idle_ttl_seconds": self.server.sessions.ttl,
                                        "max_json_body_bytes": MAX_BODY_BYTES,
                                        "max_concurrent_requests": self.server.max_requests},
                             "provenance": self.server.store.provenance})
            return
        if path == "/api/catalog":
            self._json(200, self.server.store.public_catalog())
            return
        if path == "/api/results":
            self._json(200, self.server.store.public_results())
            return
        if path.startswith("/api/results/"):
            name = path.removeprefix("/api/results/")
            try:
                raw = self.server.store.export(name)
            except KeyError as error:
                raise APIError(404, "unknown_export", "Only saved aggregate summaries and the risk plot are downloadable here.") from error
            self._send(200, raw, "image/png" if name.endswith(".png") else "text/csv; charset=utf-8", filename="aqc-" + name)
            return
        if path.startswith("/api/molecules/"):
            molecule_id = path.removeprefix("/api/molecules/")
            try:
                value = self.server.store.public_molecule(molecule_id)
            except KeyError as error:
                raise APIError(404, "unknown_molecule", "Unknown development molecule.") from error
            self._json(200, value)
            return
        match = re.fullmatch(r"/api/sessions/([A-Za-z0-9_-]{32})(?:/(export\.json|export\.csv))?", path)
        if match:
            session = self.server.sessions.get(match[1])
            if match[2] == "export.json":
                self._json(200, session.export_json(), filename="aqc-session-" + session.session_id + ".json")
            elif match[2] == "export.csv":
                self._send(200, session.export_csv(), "text/csv; charset=utf-8", filename="aqc-session-" + session.session_id + ".csv")
            else:
                self._respond_session(session)
            return
        if path in STATIC_FILES:
            relative, content_type = STATIC_FILES[path]
            target = (self.server.app_dir / relative).resolve()
            if not target.is_relative_to(self.server.app_dir) or not target.is_file():
                raise APIError(503, "app_asset_missing", "The local app bundle is incomplete. Restore app/ from this release.")
            self._send(200, target.read_bytes(), content_type)
            return
        raise APIError(404, "not_found", "Unknown app or API path.")

    def _post(self, path):
        payload = self._body()
        operation_id = self._operation_id()
        if path == "/api/sessions":
            if set(payload) != {"molecule_id", "config"} or not isinstance(payload["molecule_id"], str) or len(payload["molecule_id"]) > 128:
                raise APIError(400, "invalid_session_request", "Supply only molecule_id and a policy config.")
            session = self.server.sessions.create(payload["molecule_id"], payload["config"])
            self._respond_session(session, status=201)
            return
        match = re.fullmatch(r"/api/sessions/([A-Za-z0-9_-]{32})/(step|run|query|finish|reset)", path)
        if not match:
            raise APIError(404, "not_found", "Unknown session action.")
        action = match[2]
        if action == "query":
            if set(payload) != {"candidate_id"} or not isinstance(payload["candidate_id"], str) or not 1 <= len(payload["candidate_id"]) <= 128:
                raise APIError(400, "invalid_query", "Supply one nonempty candidate_id string.")
        elif payload:
            raise APIError(400, "unexpected_fields", "This action takes an empty JSON object.")
        session = self.server.sessions.get(match[1])
        self._respond_session(session.perform(action, payload, operation_id=operation_id))

    def _delete(self, path):
        match = re.fullmatch(r"/api/sessions/([A-Za-z0-9_-]{32})", path)
        if not match:
            raise APIError(404, "not_found", "Unknown session.")
        lengths = self.headers.get_all("Content-Length", [])
        if lengths and lengths != ["0"]:
            raise APIError(400, "unexpected_body", "DELETE takes no request body.")
        self.server.sessions.remove(match[1])
        self._json(200, {"closed": True, "session_id": match[1]})

    def _dispatch(self):
        try:
            path = self._check_request()
            if self.command in ("GET", "HEAD"):
                if self.headers.get_all("Content-Length") not in (None, ["0"]):
                    raise APIError(400, "unexpected_body", "GET and HEAD take no request body.")
                self._get(path)
            elif self.command == "POST":
                self._post(path)
            elif self.command == "DELETE":
                self._delete(path)
            else:
                raise APIError(405, "method_not_allowed", "Use GET, POST, or DELETE on documented routes.")
        except APIError as error:
            value = {"error": {"code": error.code, "message": error.message}}
            if error.session is not None:
                value["session"] = error.session
            self._json(error.status, value)
        except (TimeoutError, socket.timeout):
            self._json(408, {"error": {"code": "request_timeout", "message": "The local request timed out."}})
        except (BrokenPipeError, ConnectionResetError):
            # Session state remains server-side, including already charged work.
            self.close_connection = True
        except Exception as error:
            sys.stderr.write(f"AQC local internal error: {type(error).__name__}: {error}\n")
            self._json(500, {"error": {"code": "internal_error", "message": "The local request failed. Existing session ledgers remain available."}})

    do_GET = do_HEAD = do_POST = do_DELETE = do_OPTIONS = do_PUT = do_PATCH = _dispatch

    def handle_expect_100(self):
        self._json(417, {"error": {"code": "unsupported_expectation", "message": "Expect headers are not accepted."}})
        return False
