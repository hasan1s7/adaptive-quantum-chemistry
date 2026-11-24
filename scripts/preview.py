#!/usr/bin/env python3
"""Adapt the managed preview CLI flags to the loopback-only local app."""
from pathlib import Path
import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1"])
    parser.add_argument("--port", type=int, default=4173)
    parser.add_argument("--strictPort", action="store_true")
    parser.add_argument("--responsive-check", action="store_true", help="Enable a preview-only iframe layout harness")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    if not args.responsive_check:
        from aqc_app.__main__ import main as run_app
        return run_app(["--port", str(args.port), "--no-open"])
    from aqc_app.server import LocalHTTPServer, RequestHandler
    root = Path(__file__).resolve().parents[1]

    class PreviewHandler(RequestHandler):
        def do_GET(self):
            if self.path not in ("/__qa__/responsive", "/__qa__/app"):
                return super().do_GET()
            try:
                self._check_request()
            except Exception:
                return super().do_GET()
            document = ("<!doctype html><html><head><meta charset='utf-8'><title>AQC responsive QA</title>"
                "<style>body{font:16px system-ui;margin:0;background:#e5e8eb}header{padding:12px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}button{padding:10px}iframe{display:block;border:1px solid #aaa;margin:0 auto;background:white;height:760px;max-width:100%}</style>"
                "</head><body><header><strong>Responsive browser QA</strong><span>CSS viewport; not physical-device acceptance</span>"
                "<button data-width='320'>320 px</button><button data-width='360'>360 px</button><button data-width='430'>430 px</button><button data-width='1024'>1024 px</button><output>360 px</output></header>"
                "<iframe title='AQC at selected viewport width' width='360' src='/__qa__/app'></iframe>"
                "<script>document.querySelectorAll('button[data-width]').forEach(b=>b.addEventListener('click',()=>{document.querySelector('iframe').width=b.dataset.width;document.querySelector('output').textContent=b.dataset.width+' px';}));</script></body></html>")
            if self.path == "/__qa__/app":
                document = (root / "app/index.html").read_text(encoding="utf-8")
            encoded = document.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(encoded)

    server = LocalHTTPServer(port=args.port)
    server.RequestHandlerClass = PreviewHandler
    print(f"AQC development preview: {server.url}", flush=True)
    print(f"Responsive QA: {server.url}__qa__/responsive", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
