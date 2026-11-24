"""Paid oracle and protocol-v2 boundary for trusted, label-blind policies.

Workers receive IDs, cheap energies, configuration and paid observations only.
Decision events stream before completion. All failures in run(), including
transport/decoding, retain charged jobs and original exception causes. The
isolated interpreter and empty cwd prevent accidental sharing, not malicious
filesystem access; this is not an OS sandbox.
"""
from __future__ import annotations

from collections import deque
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Iterable, Mapping

PROTOCOL_VERSION = 2
NUMERICAL_TOLERANCE = 1e-9
_WORKER_PATH = Path(__file__).with_name("policy_worker.py")
_MAX_MESSAGE_CHARS = 1024 * 1024
_EVENT_TYPES = frozenset({"query_decision", "query_failure", "fallback", "escalation",
                         "cheap_window", "cheap_separation", "empirical_envelope", "stop"})


class PolicyExecutionError(RuntimeError):
    """A failed run with its complete paid ledger and underlying failure cause."""
    def __init__(self, message, oracle=None, *, failure_stage=None, cause=None,
                 policy_events=None, cleanup_errors=None, worker_stderr=""):
        super().__init__(message)
        self.queries = [] if oracle is None else oracle.events
        self.expensive_calls = 0 if oracle is None else oracle.expensive_calls
        self.observations = {} if oracle is None else oracle.observations
        self.failure_stage = failure_stage
        self.cause_type = type(cause).__name__ if cause is not None else None
        self.policy_events = list(policy_events or [])
        self.cleanup_errors = list(cleanup_errors or [])
        self.worker_stderr = worker_stderr


class WorkerProtocolError(ValueError):
    """Invalid or ambiguous worker protocol."""


class Oracle:
    """Parent-only labels. First valid requests cost one job, including failure.

    Repeat requests are uncharged cache hits; invalid IDs are logged rejections.
    A paid ledger entry is appended before resolving its reference value.
    """
    def __init__(self, candidate_ids: Iterable[str], references: Mapping[str, float | None]):
        ids = list(candidate_ids)
        if not ids or any(not isinstance(cid, str) or not cid for cid in ids):
            raise ValueError("candidate IDs must be nonempty strings")
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate candidate IDs")
        self._ids = frozenset(ids)
        if set(references) - self._ids:
            raise ValueError("references contain IDs outside this candidate pool")
        self._labels = dict(references)
        self._observed = {}
        self._cache = {}
        self._events = []

    @property
    def events(self):
        return [dict(event) for event in self._events]

    @property
    def observations(self):
        return dict(self._observed)

    @property
    def expensive_calls(self):
        return sum(event["charged"] for event in self._events)

    def query(self, candidate_id):
        event = {"order": len(self._events) + 1,
                 "candidate_id": candidate_id if isinstance(candidate_id, str) else None,
                 "charged": 0}
        self._events.append(event)
        if not isinstance(candidate_id, str) or not candidate_id:
            event.update(status="rejected", error="invalid_candidate_id_type",
                         received_type=type(candidate_id).__name__)
            raise ValueError("candidate ID must be a nonempty string")
        if candidate_id not in self._ids:
            event.update(status="rejected", error="unknown_candidate")
            raise ValueError(f"unknown candidate ID: {candidate_id}")
        if candidate_id in self._cache:
            response = dict(self._cache[candidate_id], cached=True)
            event["status"] = "cached" if response["ok"] else "cached_failure"
        else:
            event.update(charged=1, status="pending")
            try:
                value = self._labels.get(candidate_id)
                if value is None:
                    response = {"ok": False, "error": "missing_reference"}
                elif isinstance(value, bool) or not isinstance(value, (int, float)):
                    response = {"ok": False, "error": "invalid_reference"}
                elif not math.isfinite(value):
                    response = {"ok": False, "error": "nonfinite_reference"}
                else:
                    response = {"ok": True, "reference_kcal": float(value)}
                    self._observed[candidate_id] = float(value)
                response.update(candidate_id=candidate_id, cached=False)
                self._cache[candidate_id] = dict(response)
                event["status"] = "succeeded" if response["ok"] else "failed"
            except Exception as error:
                event.update(status="failed", error="reference_resolution_error",
                             cause_type=type(error).__name__)
                raise
        if response["ok"]:
            event["reference_kcal"] = response["reference_kcal"]
        else:
            event["error"] = response["error"]
        return response

    def validate_selected(self, candidate_id):
        if self.expensive_calls < 1:
            raise PolicyExecutionError("paid policy made no expensive query", self)
        if not self._observed:
            raise PolicyExecutionError("no reference-verified candidate available", self)
        expected = min(self._observed, key=lambda cid: (self._observed[cid], cid))
        if candidate_id != expected:
            raise PolicyExecutionError("policy must return the best reference-verified queried candidate", self)


def _finite_number(value, name, *, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and number < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{name} must be <= {maximum}")
    return number


def policy_payload(candidates, config):
    """Strict cheap-only payload; reference values never normalize features.

    sequential keys: kind, one_gap>=0, one_ratio in [0,1], error_scale>=1,
    slack>=0, cap integer>=2. Its separation/envelope stops are calibrated
    heuristics, never confidence guarantees.
    """
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("empty or invalid candidate pool")
    clean = []
    for row in candidates:
        if not isinstance(row, dict) or set(row) != {"candidate_id", "cheap_kcal"}:
            raise ValueError("policy candidate schema allows only candidate_id and cheap_kcal")
        cid = row["candidate_id"]
        if not isinstance(cid, str) or not cid:
            raise ValueError("candidate_id must be a nonempty string")
        clean.append({"candidate_id": cid, "cheap_kcal": _finite_number(row["cheap_kcal"], "cheap energy")})
    if len({row["candidate_id"] for row in clean}) != len(clean):
        raise ValueError("duplicate candidate IDs")
    cheap_values = [row["cheap_kcal"] for row in clean]
    if not math.isfinite(max(cheap_values) - min(cheap_values)):
        raise ValueError("cheap energy span overflows finite arithmetic")
    if not isinstance(config, dict):
        raise ValueError("invalid policy configuration schema")
    kind = config.get("kind")
    allowed = {"full": {"kind"}, "fixed": {"kind", "k"},
               "adaptive": {"kind", "k", "gap", "cap"},
               "sequential": {"kind", "one_gap", "one_ratio", "error_scale", "slack", "cap"}}
    if not isinstance(kind, str) or kind not in allowed or set(config) != allowed[kind]:
        raise ValueError("invalid policy configuration schema")
    clean_config = dict(config)
    if kind in {"fixed", "adaptive"}:
        if type(config["k"]) is not int or config["k"] < 1:
            raise ValueError("k must be an integer >= 1")
    if kind == "adaptive":
        if type(config["cap"]) is not int or config["cap"] < config["k"]:
            raise ValueError("cap must be an integer >= k")
        clean_config["gap"] = _finite_number(config["gap"], "gap", minimum=0)
    elif kind == "sequential":
        if type(config["cap"]) is not int or config["cap"] < 2:
            raise ValueError("sequential cap must be an integer >= 2")
        for name in ("one_gap", "slack"):
            clean_config[name] = _finite_number(config[name], name, minimum=0)
        clean_config["one_ratio"] = _finite_number(config["one_ratio"], "one_ratio", minimum=0, maximum=1)
        clean_config["error_scale"] = _finite_number(config["error_scale"], "error_scale", minimum=1)
    return {"type": "run", "candidates": clean, "config": clean_config}


def _strict_json(line):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise WorkerProtocolError(f"duplicate protocol key: {key}")
            result[key] = value
        return result
    def reject_constant(value):
        raise WorkerProtocolError(f"nonfinite protocol number: {value}")
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise WorkerProtocolError(f"overflowing protocol number: {value}")
        return number
    message = json.loads(line, object_pairs_hook=unique_object,
                         parse_constant=reject_constant, parse_float=finite_float)
    if not isinstance(message, dict):
        raise WorkerProtocolError("worker protocol message must be an object")
    return message


class PolicySession:
    """Reusable label-blind worker with per-case oracle/event reset.

    Writers acknowledge completion under the same deadline as reads, so a
    worker that stops consuming stdin cannot bypass timeouts. stderr is drained
    concurrently and bounded. Cleanup preserves rather than masks causes.
    """
    def __init__(self, timeout_seconds=30.0):
        self._timeout = _finite_number(timeout_seconds, "timeout_seconds", minimum=0)
        if self._timeout == 0:
            raise ValueError("timeout_seconds must be positive")
        self._directory = None
        self._process = None
        self._lines = queue.Queue(maxsize=512)
        self._outbound = queue.Queue()
        self._threads = []
        self._stop = threading.Event()
        self._stderr = deque(maxlen=16)
        self._cleanup_errors = []
        self._cleanup_causes = []
        self._deadline = None
        self._last_oracle = None
        self._policy_events = []

    def __enter__(self):
        if self._process is not None:
            raise RuntimeError("policy session already opened")
        self._lines = queue.Queue(maxsize=512)
        self._outbound = queue.Queue()
        self._stop = threading.Event()
        self._stderr.clear()
        self._cleanup_errors = []
        self._cleanup_causes = []
        self._threads = []
        self._last_oracle = None
        self._policy_events = []
        try:
            self._directory = tempfile.TemporaryDirectory(prefix="aqc-policy-")
            env = {"PATH": os.defpath, "LC_ALL": "C.UTF-8"}
            if os.name == "nt" and "SystemRoot" in os.environ:
                env["SystemRoot"] = os.environ["SystemRoot"]
            self._process = subprocess.Popen(
                [sys.executable, "-I", "-B", str(_WORKER_PATH.resolve())], cwd=self._directory.name,
                env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", bufsize=1)
            process = self._process
            assert process.stdin is not None and process.stdout is not None and process.stderr is not None

            def enqueue(kind, value):
                while not self._stop.is_set():
                    try:
                        self._lines.put((kind, value), timeout=.1)
                        return
                    except queue.Full:
                        continue

            def read_output():
                try:
                    while not self._stop.is_set():
                        line = process.stdout.readline(_MAX_MESSAGE_CHARS + 1)
                        if not line:
                            enqueue("eof", None)
                            return
                        if len(line) > _MAX_MESSAGE_CHARS:
                            raise WorkerProtocolError("worker protocol line exceeds size limit")
                        enqueue("line", line)
                except Exception as error:
                    enqueue("error", error)

            def read_stderr():
                try:
                    while True:
                        text = process.stderr.readline(512)
                        if not text:
                            return
                        self._stderr.append(text)
                except Exception as error:
                    self._stderr.append(f"[stderr read error: {type(error).__name__}: {error}]")

            def write_input():
                try:
                    while True:
                        item = self._outbound.get()
                        if item is None:
                            return
                        line, acknowledgment = item
                        try:
                            process.stdin.write(line)
                            process.stdin.flush()
                        except Exception as error:
                            acknowledgment.put(error)
                        else:
                            acknowledgment.put(None)
                finally:
                    try:
                        process.stdin.close()
                    except Exception as error:
                        self._record_cleanup("stdin.close", error)

            for name, target in [("stdout", read_output), ("stderr", read_stderr), ("stdin", write_input)]:
                thread = threading.Thread(target=target, name=f"aqc-policy-{name}", daemon=True)
                self._threads.append(thread)
                thread.start()
            return self
        except Exception as error:
            self._safe_close()
            raise self._wrap_error(error, "startup", None) from error

    def _record_cleanup(self, operation, error):
        self._cleanup_errors.append({"operation": operation, "cause_type": type(error).__name__, "message": str(error)})
        self._cleanup_causes.append(error)

    def _remaining(self):
        remaining = 0 if self._deadline is None else self._deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("policy worker timed out")
        return remaining

    def _send(self, value):
        line = json.dumps(value, allow_nan=False) + "\n"
        acknowledgment = queue.Queue(maxsize=1)
        self._outbound.put((line, acknowledgment))
        try:
            result = acknowledgment.get(timeout=self._remaining())
        except queue.Empty as error:
            raise TimeoutError("policy worker timed out while sending payload/observation") from error
        if result is not None:
            raise result

    def _wrap_error(self, error, stage, oracle):
        if isinstance(error, PolicyExecutionError):
            error.failure_stage = error.failure_stage or stage
            if oracle is not None:
                error.queries, error.expensive_calls, error.observations = oracle.events, oracle.expensive_calls, oracle.observations
            error.policy_events = list(self._policy_events)
            error.cleanup_errors.extend(e for e in self._cleanup_errors if e not in error.cleanup_errors)
            error.worker_stderr = "".join(self._stderr)
            return error
        return PolicyExecutionError(f"policy worker failed during {stage}: {type(error).__name__}: {error}",
                                    oracle, failure_stage=stage, cause=error, policy_events=self._policy_events,
                                    cleanup_errors=self._cleanup_errors, worker_stderr="".join(self._stderr))

    def run(self, candidates, references, config):
        oracle = None
        stage = "payload_validation"
        self._policy_events = []
        self._last_oracle = None
        try:
            if self._process is None:
                raise RuntimeError("use PolicySession as a context manager")
            payload = policy_payload(candidates, config)
            oracle = Oracle((row["candidate_id"] for row in payload["candidates"]), references)
            self._last_oracle = oracle
            self._deadline = time.monotonic() + self._timeout
            stage = "payload_send"
            self._send(payload)
            messages = 0
            while True:
                stage = "worker_response"
                try:
                    kind, value = self._lines.get(timeout=self._remaining())
                except queue.Empty as error:
                    raise TimeoutError("policy worker timed out waiting for response") from error
                if kind == "error":
                    raise value
                if kind == "eof":
                    raise EOFError("policy worker exited before a decision")
                stage = "protocol_decode"
                message = _strict_json(value)
                messages += 1
                if messages > 8 * len(candidates) + 40:
                    raise WorkerProtocolError("policy exceeded protocol message limit")
                stage = "protocol_validation"
                if message.get("type") == "event":
                    if set(message) != {"type", "event"} or not isinstance(message["event"], dict):
                        raise WorkerProtocolError("invalid event protocol")
                    event = message["event"]
                    if (not isinstance(event.get("event"), str) or event["event"] not in _EVENT_TYPES
                            or type(event.get("event_order")) is not int
                            or event["event_order"] != len(self._policy_events) + 1):
                        raise WorkerProtocolError("invalid event type or order")
                    self._policy_events.append(event)
                elif message.get("type") == "query":
                    if set(message) != {"type", "candidate_id"}:
                        raise WorkerProtocolError("invalid query protocol")
                    stage = "oracle_query"
                    observation = oracle.query(message["candidate_id"])
                    stage = "observation_send"
                    self._send({"type": "observation", **observation})
                elif message.get("type") == "done":
                    expected = {"type", "protocol_version", "selected_candidate", "fallback", "stop_reason"}
                    if (set(message) != expected or type(message["protocol_version"]) is not int
                            or message["protocol_version"] != PROTOCOL_VERSION
                            or type(message["fallback"]) is not bool
                            or not isinstance(message["stop_reason"], str) or not message["stop_reason"]
                            or len(message["stop_reason"]) > 256
                            or (message["selected_candidate"] is not None and not isinstance(message["selected_candidate"], str))):
                        raise WorkerProtocolError("invalid completion protocol")
                    stage = "decision_validation"
                    oracle.validate_selected(message["selected_candidate"])
                    return {"protocol_version": PROTOCOL_VERSION, "selected_candidate": message["selected_candidate"],
                            "queries": oracle.events, "expensive_calls": oracle.expensive_calls,
                            "fallback": message["fallback"], "stop_reason": message["stop_reason"],
                            "observations": oracle.observations, "policy_events": list(self._policy_events)}
                else:
                    raise WorkerProtocolError("invalid worker protocol message type")
        except Exception as error:
            self._safe_close()
            wrapped = self._wrap_error(error, stage, oracle)
            if wrapped is error:
                raise
            raise wrapped from error
        finally:
            self._deadline = None

    def _safe_close(self):
        try:
            self.close()
        except Exception as error:
            self._record_cleanup("close", error)

    def close(self):
        """Try every cleanup step; return secondary failures, never mask a cause."""
        before = len(self._cleanup_errors)
        process, self._process = self._process, None
        self._stop.set()
        self._outbound.put(None)
        if process is not None:
            try:
                process.wait(timeout=.5)
            except subprocess.TimeoutExpired:
                try:
                    process.terminate()
                    process.wait(timeout=.5)
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                        process.wait(timeout=2)
                    except Exception as error:
                        self._record_cleanup("process.kill/wait", error)
                except Exception as error:
                    self._record_cleanup("process.terminate/wait", error)
                    try:
                        process.kill()
                        process.wait(timeout=2)
                    except Exception as second:
                        self._record_cleanup("process.kill/wait", second)
            except Exception as error:
                self._record_cleanup("process.wait", error)
                try:
                    process.kill()
                    process.wait(timeout=2)
                except Exception as second:
                    self._record_cleanup("process.kill/wait", second)
            for thread in self._threads:
                try:
                    thread.join(timeout=1)
                    if thread.is_alive():
                        self._record_cleanup(thread.name, TimeoutError("worker IO thread did not stop"))
                except Exception as error:
                    self._record_cleanup(thread.name, error)
            for name in ("stdout", "stderr", "stdin"):
                stream = getattr(process, name, None)
                owner = next((t for t in self._threads if t.name == f"aqc-policy-{name}"), None)
                if stream is not None and (owner is None or not owner.is_alive()):
                    try:
                        stream.close()
                    except Exception as error:
                        self._record_cleanup(f"{name}.close", error)
        directory, self._directory = self._directory, None
        if directory is not None:
            try:
                directory.cleanup()
            except Exception as error:
                self._record_cleanup("temporary_directory.cleanup", error)
        return self._cleanup_errors[before:]

    def __exit__(self, exc_type, exc, tb):
        before = len(self._cleanup_errors)
        self._safe_close()
        if len(self._cleanup_errors) > before:
            if isinstance(exc, PolicyExecutionError):
                self._wrap_error(exc, "cleanup", self._last_oracle)
            elif exc is not None:
                if hasattr(exc, "add_note"):
                    exc.add_note("Policy cleanup also failed: " + str(self._cleanup_errors[before:]))
            else:
                cause = self._cleanup_causes[before]
                raise self._wrap_error(cause, "cleanup", self._last_oracle) from cause


def run_policy(candidates, references, config):
    """Run one policy in a fresh interpreter and return its complete audit."""
    with PolicySession() as session:
        return session.run(candidates, references, config)
