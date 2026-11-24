"""Evaluator-owned paid oracle and a JSON-only boundary around policy code.

The worker is an isolated Python interpreter in an empty temporary directory.
This prevents accidental label sharing through objects, imports, forked memory,
dataframe columns, or normalization. It is not an OS sandbox against malicious
code: the worker runs as the same user. Only trusted built-in policies run here.
"""

from __future__ import annotations

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


class PolicyExecutionError(RuntimeError):
    """A failed policy run, retaining charged jobs for the evaluator's audit."""

    def __init__(self, message: str, oracle: "Oracle | None" = None):
        super().__init__(message)
        self.queries = [] if oracle is None else oracle.events
        self.expensive_calls = 0 if oracle is None else oracle.expensive_calls


class Oracle:
    """Evaluator-side label store. Only ``query`` responses cross the boundary.

    A first query of a valid ID is one charged expensive job, including a job
    whose output is unavailable. Repeated queries are cache hits and uncharged.
    Unknown IDs are rejected and logged without inventing an expensive job.
    """

    def __init__(
        self, candidate_ids: Iterable[str], references: Mapping[str, float | None]
    ) -> None:
        ids = list(candidate_ids)
        if not ids or any(not isinstance(cid, str) or not cid for cid in ids):
            raise ValueError("candidate IDs must be nonempty strings")
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate candidate IDs")
        self._ids = frozenset(ids)
        if set(references) - self._ids:
            raise ValueError("references contain IDs outside this candidate pool")
        self._labels = dict(references)
        self._observed: dict[str, float] = {}
        self._cache: dict[str, dict[str, Any]] = {}
        self._events: list[dict[str, Any]] = []

    @property
    def events(self) -> list[dict[str, Any]]:
        return [dict(event) for event in self._events]

    @property
    def observations(self) -> dict[str, float]:
        return dict(self._observed)

    @property
    def expensive_calls(self) -> int:
        return sum(event["charged"] for event in self._events)

    def query(self, candidate_id: str) -> dict[str, Any]:
        event: dict[str, Any] = {
            "order": len(self._events) + 1,
            "candidate_id": candidate_id,
            "charged": 0,
        }
        if candidate_id not in self._ids:
            event.update(status="rejected", error="unknown_candidate")
            self._events.append(event)
            raise ValueError(f"unknown candidate ID: {candidate_id}")

        if candidate_id in self._cache:
            response = dict(self._cache[candidate_id], cached=True)
            event["status"] = "cached" if response["ok"] else "cached_failure"
        else:
            event["charged"] = 1
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
        if response["ok"]:
            event["reference_kcal"] = response["reference_kcal"]
        else:
            event["error"] = response["error"]
        self._events.append(event)
        return response

    def validate_selected(self, candidate_id: str | None) -> None:
        if self.expensive_calls < 1:
            raise PolicyExecutionError("paid policy made no expensive query", self)
        if not self._observed:
            raise PolicyExecutionError("no reference-verified candidate available", self)
        expected = min(self._observed, key=lambda cid: (self._observed[cid], cid))
        if candidate_id != expected:
            raise PolicyExecutionError(
                "policy must return the best reference-verified queried candidate", self
            )


def policy_payload(
    candidates: list[dict[str, Any]], config: dict[str, Any]
) -> dict[str, Any]:
    """Construct a strict, cheap-only message. Reject undeclared feature fields."""
    if not candidates:
        raise ValueError("empty candidate pool")
    clean: list[dict[str, Any]] = []
    for row in candidates:
        if set(row) != {"candidate_id", "cheap_kcal"}:
            raise ValueError("policy candidate schema allows only candidate_id and cheap_kcal")
        cid, energy = row["candidate_id"], row["cheap_kcal"]
        if not isinstance(cid, str) or not cid:
            raise ValueError("candidate_id must be a nonempty string")
        if isinstance(energy, bool) or not isinstance(energy, (int, float)):
            raise ValueError("cheap energy must be a finite number")
        if not math.isfinite(energy):
            raise ValueError("cheap energy must be finite")
        clean.append({"candidate_id": cid, "cheap_kcal": float(energy)})
    if len({row["candidate_id"] for row in clean}) != len(clean):
        raise ValueError("duplicate candidate IDs")
    kind = config.get("kind")
    allowed = {
        "full": {"kind"},
        "fixed": {"kind", "k"},
        "adaptive": {"kind", "k", "gap", "cap"},
    }
    if kind not in allowed or set(config) != allowed[kind]:
        raise ValueError("invalid policy configuration schema")
    clean_config = dict(config)
    if kind in {"fixed", "adaptive"}:
        if type(config["k"]) is not int or config["k"] < 1:
            raise ValueError("k must be an integer >= 1")
    if kind == "adaptive":
        if type(config["cap"]) is not int or config["cap"] < config["k"]:
            raise ValueError("cap must be an integer >= k")
        gap = config["gap"]
        if isinstance(gap, bool) or not isinstance(gap, (int, float)):
            raise ValueError("gap must be a finite nonnegative number")
        if not math.isfinite(gap) or gap < 0:
            raise ValueError("gap must be finite and nonnegative")
        clean_config["gap"] = float(gap)
    # No reference-based centering, sorting, scales, or summaries occur here.
    return {"type": "run", "candidates": clean, "config": clean_config}


class PolicySession:
    """Reuse one label-blind interpreter, resetting all policy state every run.

    Development tuning and final evaluation should use separate sessions.
    A fresh Oracle is created for every run, so repeated pools/policies pay for
    their own jobs; neither labels nor query caches cross runs.
    """

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self._timeout = timeout_seconds
        self._directory: tempfile.TemporaryDirectory[str] | None = None
        self._process: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._reader: threading.Thread | None = None

    def __enter__(self) -> "PolicySession":
        if self._process is not None:
            raise RuntimeError("policy session already opened")
        self._directory = tempfile.TemporaryDirectory(prefix="aqc-policy-")
        worker = Path(__file__).with_name("policy_worker.py").resolve()
        # No inherited dataset paths, PYTHONPATH, tokens, or application env.
        env = {"PATH": os.defpath, "LC_ALL": "C.UTF-8"}
        if os.name == "nt" and "SystemRoot" in os.environ:
            env["SystemRoot"] = os.environ["SystemRoot"]
        self._process = subprocess.Popen(
            [sys.executable, "-I", "-B", str(worker)],
            cwd=self._directory.name,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        assert self._process.stdout is not None
        stream = self._process.stdout

        def read_output() -> None:
            try:
                for line in stream:
                    self._lines.put(line)
            finally:
                self._lines.put(None)

        self._reader = threading.Thread(target=read_output, daemon=True)
        self._reader.start()
        return self

    def _send(self, value: dict[str, Any]) -> None:
        assert self._process is not None and self._process.stdin is not None
        self._process.stdin.write(json.dumps(value, allow_nan=False) + "\n")
        self._process.stdin.flush()

    def run(
        self,
        candidates: list[dict[str, Any]],
        references: Mapping[str, float | None],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        if self._process is None:
            raise RuntimeError("use PolicySession as a context manager")
        payload = policy_payload(candidates, config)
        oracle = Oracle((row["candidate_id"] for row in payload["candidates"]), references)
        self._send(payload)
        deadline = time.monotonic() + self._timeout
        messages = 0
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PolicyExecutionError("policy worker timed out", oracle)
                try:
                    line = self._lines.get(timeout=remaining)
                except queue.Empty as exc:
                    raise PolicyExecutionError("policy worker timed out", oracle) from exc
                if line is None:
                    raise PolicyExecutionError("policy worker exited before a decision", oracle)
                message = json.loads(line)
                messages += 1
                if messages > 2 * len(candidates) + 10:
                    raise PolicyExecutionError("policy exceeded protocol message limit", oracle)
                if message.get("type") == "query":
                    if set(message) != {"type", "candidate_id"}:
                        raise PolicyExecutionError("invalid query protocol", oracle)
                    self._send({"type": "observation", **oracle.query(message["candidate_id"])})
                elif message.get("type") == "done":
                    oracle.validate_selected(message.get("selected_candidate"))
                    return {
                        "selected_candidate": message["selected_candidate"],
                        "queries": oracle.events,
                        "expensive_calls": oracle.expensive_calls,
                        "fallback": bool(message.get("fallback", False)),
                        "stop_reason": message["stop_reason"],
                        "observations": oracle.observations,
                        "policy_events": message.get("policy_events", []),
                    }
                else:
                    raise PolicyExecutionError("invalid worker protocol message", oracle)
        except Exception:
            # A broken protocol must never leave stale observations for a later run.
            self.close()
            raise

    def close(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            if self._reader is not None:
                self._reader.join(timeout=1)
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()


def run_policy(
    candidates: list[dict[str, Any]],
    references: Mapping[str, float | None],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Run one policy in a fresh interpreter and return its complete audit."""
    with PolicySession() as session:
        return session.run(candidates, references, config)
