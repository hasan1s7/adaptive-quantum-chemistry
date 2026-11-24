"""Bounded paid sessions, using the unchanged scientific worker and Oracle.

No policy formula is implemented here: the original isolated worker decides
which candidate is next, and waits for the HTTP operator to authorize a query.
"""
from __future__ import annotations

from collections import OrderedDict, deque
import copy
import csv
import io
import math
import queue
import secrets
import threading
import time

from aqc.oracle import (Oracle, PolicySession, PolicyExecutionError, WorkerProtocolError,
                        PROTOCOL_VERSION, _EVENT_TYPES, _strict_json, policy_payload)
from .data import canonical


class APIError(Exception):
    def __init__(self, status, code, message, session=None):
        super().__init__(message)
        self.status, self.code, self.message, self.session = status, code, message, session


class PaidSession:
    """One operator session; all mutations are serialized by its own lock."""
    def __init__(self, molecule_id, candidates, references, config, *, ttl=900.0,
                 worker_timeout=5.0, transport_factory=PolicySession, clock=time.monotonic):
        if config == {"kind": "manual"}:
            policy_payload(candidates, {"kind": "full"})
        else:
            policy_payload(candidates, config)
        self.session_id = secrets.token_urlsafe(24)
        self.molecule_id = molecule_id
        self.candidates = [dict(row) for row in candidates]
        self._references = dict(references)
        self.config = dict(config)
        self.mode = "manual" if config["kind"] == "manual" else "policy"
        self.lock = threading.RLock()
        self._clock, self._ttl = clock, float(ttl)
        self._last_access = clock()
        self._worker_timeout, self._transport_factory = worker_timeout, transport_factory
        self._transport = None
        self._history = []
        self._prior_calls = 0
        self._prior_query_events = 0
        self._operation_count = 0
        self._idempotency = OrderedDict()
        self.revision = 0
        self.reset_count = 0
        self.closed = False
        count = len(candidates)
        self.limits = {"max_paid_calls": 10 * count, "max_resets": 9,
                       "max_query_events": 20 * count + 64, "max_operations": 40 * count + 128,
                       "max_idempotency_keys": 128,
                       "idle_ttl_seconds": self._ttl, "worker_timeout_seconds": worker_timeout}
        self._initialize_run()

    def _initialize_run(self):
        self.oracle = Oracle((row["candidate_id"] for row in self.candidates), self._references)
        self.status = "active"
        self.pending_candidate = None
        self.pending_reason = None
        self.selected_candidate = None
        self.stop_reason = None
        self.fallback = False
        self.evaluation = None
        self.failure = None
        self.policy_events = []
        self._message_count = 0
        if self.mode == "policy":
            stage = "startup"
            try:
                self._transport = self._transport_factory(timeout_seconds=self._worker_timeout)
                self._transport.__enter__()
                self._transport._last_oracle = self.oracle
                self._transport._policy_events = self.policy_events
                self._deadline()
                stage = "payload_send"
                self._transport._send(policy_payload(self.candidates, self.config))
                stage = "worker_response"
                self._read_boundary()
            except Exception as error:
                self._fail(error, stage)
            finally:
                if self._transport is not None:
                    self._transport._deadline = None

    def _deadline(self):
        self._transport._deadline = time.monotonic() + self._worker_timeout

    def _read_boundary(self):
        """Read protocol-v2 events up to the next uncharged query or completion."""
        transport = self._transport
        while True:
            try:
                kind, value = transport._lines.get(timeout=transport._remaining())
            except queue.Empty as error:
                raise TimeoutError("policy worker timed out waiting for its next action") from error
            if kind == "error":
                raise value
            if kind == "eof":
                raise EOFError("policy worker exited before a decision")
            message = _strict_json(value)
            self._message_count += 1
            if self._message_count > 8 * len(self.candidates) + 40:
                raise WorkerProtocolError("policy exceeded protocol message limit")
            if message.get("type") == "event":
                if set(message) != {"type", "event"} or not isinstance(message["event"], dict):
                    raise WorkerProtocolError("invalid event protocol")
                event = message["event"]
                if (not isinstance(event.get("event"), str) or event["event"] not in _EVENT_TYPES or
                        type(event.get("event_order")) is not int or event["event_order"] != len(self.policy_events) + 1):
                    raise WorkerProtocolError("invalid event type or order")
                self.policy_events.append(event)
                if event["event"] == "fallback":
                    self.fallback = True
            elif message.get("type") == "query":
                if set(message) != {"type", "candidate_id"}:
                    raise WorkerProtocolError("invalid query protocol")
                candidate_id = message["candidate_id"]
                if not isinstance(candidate_id, str) or candidate_id not in {row["candidate_id"] for row in self.candidates}:
                    # The original Oracle records rejection without charging a job.
                    self.oracle.query(candidate_id)
                    raise WorkerProtocolError("unknown worker candidate")
                self.pending_candidate = candidate_id
                self.pending_reason = next((event.get("reason") for event in reversed(self.policy_events)
                                            if event["event"] == "query_decision" and event.get("candidate_id") == candidate_id), None)
                return
            elif message.get("type") == "done":
                expected = {"type", "protocol_version", "selected_candidate", "fallback", "stop_reason"}
                if (set(message) != expected or type(message["protocol_version"]) is not int or
                        message["protocol_version"] != PROTOCOL_VERSION or type(message["fallback"]) is not bool or
                        not isinstance(message["stop_reason"], str) or not message["stop_reason"] or
                        len(message["stop_reason"]) > 256 or
                        (message["selected_candidate"] is not None and not isinstance(message["selected_candidate"], str))):
                    raise WorkerProtocolError("invalid completion protocol")
                self.oracle.validate_selected(message["selected_candidate"])
                self.selected_candidate = message["selected_candidate"]
                self.stop_reason = message["stop_reason"]
                self.fallback = message["fallback"]
                self.pending_candidate = self.pending_reason = None
                self.status = "completed"
                self._score_after_stop()
                self._close_transport(raise_errors=True)
                return
            else:
                raise WorkerProtocolError("invalid worker protocol message type")

    def _close_transport(self, *, raise_errors=False):
        transport, self._transport = self._transport, None
        if transport is None:
            return []
        try:
            errors = transport.close()
        except Exception as error:
            transport._record_cleanup("interactive_transport.close", error)
            wrapped = transport._wrap_error(error, "cleanup", self.oracle)
            wrapped.policy_events = list(self.policy_events)
            raise wrapped from error
        if errors and raise_errors:
            cause = RuntimeError("policy cleanup failed")
            wrapped = transport._wrap_error(cause, "cleanup", self.oracle)
            wrapped.policy_events = list(self.policy_events)
            raise wrapped from cause
        return errors

    def _fail(self, error, stage):
        transport = self._transport
        cleanup_errors = []
        if transport is not None:
            try:
                cleanup_errors = self._close_transport()
            except Exception as cleanup_error:
                cleanup_errors = [{"operation": "close", "cause_type": type(cleanup_error).__name__, "message": str(cleanup_error)}]
            wrapped = transport._wrap_error(error, stage, self.oracle)
        elif isinstance(error, PolicyExecutionError):
            wrapped = error
        else:
            wrapped = PolicyExecutionError(str(error), self.oracle, failure_stage=stage,
                                           cause=error, policy_events=self.policy_events)
        self.status = "failed"
        self.stop_reason = "runtime_failure"
        self.pending_candidate = self.pending_reason = None
        self.evaluation = None
        self.failure = {"code": "policy_execution_failed", "message": str(wrapped),
                        "failure_stage": wrapped.failure_stage or stage,
                        "cause_type": wrapped.cause_type or type(error).__name__,
                        "cleanup_errors": list(wrapped.cleanup_errors) + [entry for entry in cleanup_errors if entry not in wrapped.cleanup_errors],
                        "worker_stderr": wrapped.worker_stderr}

    def _score_after_stop(self):
        # Evaluator-only access occurs only after a verified final selection.
        if self.status != "completed":
            raise RuntimeError("cannot evaluate an active session")
        observed = self.oracle.observations[self.selected_candidate]
        finite_references = [float(value) for value in self._references.values()
                             if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)]
        if not finite_references:
            raise RuntimeError("no evaluator references available")
        regret = observed - min(finite_references)
        self.evaluation = {"regret_kcal": regret, "success_within_1_kcal": regret <= 1.0 + 1e-9,
                           "selected_reference_kcal": observed}

    def _check_active(self):
        if self.status != "active":
            raise APIError(409, "session_stopped", "This run has stopped. Reset it to start a new charged run.")

    def _check_query_budget(self, candidate_id):
        if self._prior_query_events + len(self.oracle.events) >= self.limits["max_query_events"]:
            raise APIError(429, "session_query_limit", "Session query-event limit reached; export the ledger and start a new session.")
        already_charged = any(event["candidate_id"] == candidate_id and event["charged"] for event in self.oracle.events)
        if not already_charged and self._prior_calls + self.oracle.expensive_calls >= self.limits["max_paid_calls"]:
            raise APIError(429, "session_paid_limit", "Session paid-query limit reached; export the ledger and start a new session.")

    def _step(self):
        self._check_active()
        if self.mode != "policy":
            raise APIError(409, "manual_mode", "Manual sessions use query and finish actions.")
        cid = self.pending_candidate
        if cid is None:
            raise APIError(409, "no_pending_query", "The policy has no pending query.")
        self._check_query_budget(cid)
        stage = "oracle_query"
        try:
            observation = self.oracle.query(cid)
            self.pending_candidate = self.pending_reason = None
            self._deadline()
            stage = "observation_send"
            self._transport._send({"type": "observation", **observation})
            stage = "worker_response"
            self._read_boundary()
        except Exception as error:
            self._fail(error, stage)
        finally:
            if self._transport is not None:
                self._transport._deadline = None

    def _manual_query(self, candidate_id):
        self._check_active()
        if self.mode != "manual":
            raise APIError(409, "policy_mode", "Policy sessions use step or run; choose Manual for custom queries.")
        self._check_query_budget(candidate_id)
        try:
            self.oracle.query(candidate_id)
        except ValueError as error:
            raise APIError(400, "invalid_candidate", str(error)) from error
        except Exception as error:
            self._fail(error, "oracle_query")

    def _finish(self):
        self._check_active()
        if self.mode != "manual":
            raise APIError(409, "policy_mode", "Only a manual session can be finished manually.")
        observations = self.oracle.observations
        if not observations:
            raise APIError(409, "verification_required", "Query at least one available reference before finishing.")
        self.selected_candidate = min(observations, key=lambda cid: (observations[cid], cid))
        self.oracle.validate_selected(self.selected_candidate)
        self.stop_reason = "manual_complete"
        self.status = "completed"
        self._score_after_stop()

    def _reset(self):
        if self.reset_count >= self.limits["max_resets"]:
            raise APIError(429, "session_reset_limit", "Session reset limit reached; export its ledger and start a new session.")
        previous = self._snapshot()
        previous["ended_by_reset"] = self.status == "active"
        self._history.append(previous)
        self._prior_calls += self.oracle.expensive_calls
        self._prior_query_events += len(self.oracle.events)
        try:
            cleanup_errors = self._close_transport()
        except Exception as error:
            cleanup_errors = [{"operation": "close", "cause_type": type(error).__name__, "message": str(error)}]
        if cleanup_errors:
            self._history[-1]["reset_cleanup_errors"] = cleanup_errors
        self.reset_count += 1
        self._initialize_run()

    def expired(self):
        return self.closed or self._clock() - self._last_access >= self._ttl

    def _touch(self):
        if self.expired():
            raise APIError(410, "session_expired", "This session expired. Its browser-saved trace remains readable; start a new session to query.")
        self._last_access = self._clock()

    def _snapshot(self):
        observations = self.oracle.observations
        best = min(observations, key=lambda cid: (observations[cid], cid)) if observations else None
        return {"session_id": self.session_id, "molecule_id": self.molecule_id,
                "config": dict(self.config), "mode": self.mode, "status": self.status,
                "stopped": self.status != "active", "revision": self.revision,
                "expensive_calls": self.oracle.expensive_calls,
                "session_expensive_calls": self._prior_calls + self.oracle.expensive_calls,
                "queries": self.oracle.events, "observations": observations,
                "best_verified": None if best is None else {"candidate_id": best, "reference_kcal": observations[best]},
                "pending_candidate": self.pending_candidate, "pending_reason": self.pending_reason,
                "policy_events": copy.deepcopy(self.policy_events),
                "selected_candidate": self.selected_candidate, "stop_reason": self.stop_reason,
                "fallback": self.fallback, "evaluation": copy.deepcopy(self.evaluation),
                "failure": copy.deepcopy(self.failure), "reset_count": self.reset_count,
                "previous_run_count": len(self._history), "limits": dict(self.limits),
                "expires_in_seconds": max(0, round(self._ttl - (self._clock() - self._last_access), 3)),
                "scope": "development_only_offline_replay"}

    def state(self):
        with self.lock:
            self._touch()
            return self._snapshot()

    def perform(self, action, payload, *, operation_id=None):
        with self.lock:
            self._touch()
            identity = canonical({"action": action, "payload": payload})
            if operation_id is not None and operation_id in self._idempotency:
                prior_identity, prior_state = self._idempotency[operation_id]
                if identity != prior_identity:
                    raise APIError(409, "idempotency_conflict", "Idempotency-Key was already used for a different action.")
                return copy.deepcopy(prior_state)
            if operation_id is not None and len(self._idempotency) >= self.limits["max_idempotency_keys"]:
                raise APIError(429, "idempotency_capacity", "Session retry-key capacity reached; export its ledger and start a new session.")
            if self._operation_count >= self.limits["max_operations"]:
                raise APIError(429, "session_operation_limit", "Session operation limit reached; export the ledger and start a new session.")
            self._operation_count += 1
            try:
                if action == "step":
                    self._step()
                elif action == "run":
                    self._check_active()
                    if self.mode != "policy":
                        raise APIError(409, "manual_mode", "Manual sessions use query and finish actions.")
                    while self.status == "active":
                        self._step()
                elif action == "query":
                    self._manual_query(payload["candidate_id"])
                elif action == "finish":
                    self._finish()
                elif action == "reset":
                    self._reset()
                else:
                    raise APIError(404, "unknown_action", "Unknown session action.")
            except APIError as error:
                self.revision += 1
                error.session = self._snapshot()
                raise
            self.revision += 1
            state = self._snapshot()
            if operation_id is not None:
                self._idempotency[operation_id] = (identity, copy.deepcopy(state))
            return state

    def export_json(self):
        with self.lock:
            self._touch()
            return {"schema_version": 1, "session": self._snapshot(),
                    "previous_runs": copy.deepcopy(self._history),
                    "candidates": [dict(row) for row in self.candidates],
                    "accounting": {"runs": self.reset_count + 1,
                                   "charged_jobs": self._prior_calls + self.oracle.expensive_calls,
                                   "meaning": "Offline paid-query equivalents; reset does not erase prior charges"},
                    "label_scope": "Queried references only. Evaluator regret appears only for completed runs."}

    def export_csv(self):
        record = self.export_json()
        output = io.StringIO(newline="")
        fields = ["session_id", "molecule_id", "run_index", "order", "candidate_id", "charged",
                  "status", "reference_kcal", "error", "run_status", "selected_candidate", "stop_reason", "regret_kcal"]
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for index, run in enumerate([*record["previous_runs"], record["session"]]):
            for event in run["queries"]:
                row = {key: event.get(key, "") for key in ("order", "candidate_id", "charged", "status", "reference_kcal", "error")}
                row.update(session_id=self.session_id, molecule_id=self.molecule_id, run_index=index,
                           run_status=run["status"], selected_candidate=run["selected_candidate"] or "",
                           stop_reason=run["stop_reason"] or "", regret_kcal=(run["evaluation"] or {}).get("regret_kcal", ""))
                writer.writerow(row)
        return output.getvalue().encode("utf-8")

    def close(self):
        with self.lock:
            self.closed = True
            errors = self._close_transport()
            if errors and self.failure is not None:
                self.failure["cleanup_errors"].extend(errors)


class SessionManager:
    def __init__(self, store, *, max_sessions=32, ttl=900.0, worker_timeout=5.0,
                 transport_factory=PolicySession, clock=time.monotonic):
        self.store = store
        self.max_sessions = max_sessions
        self.ttl, self.worker_timeout = float(ttl), worker_timeout
        self.transport_factory, self.clock = transport_factory, clock
        self._sessions = {}
        self._expired_ids = deque(maxlen=128)
        self._lock = threading.RLock()

    def create(self, molecule_id, config):
        try:
            candidates, references = self.store.session_inputs(molecule_id)
        except KeyError as error:
            raise APIError(404, "unknown_molecule", "Unknown development molecule.") from error
        try:
            if config != {"kind": "manual"}:
                policy_payload(candidates, config)
        except (ValueError, TypeError, OverflowError) as error:
            raise APIError(400, "invalid_config", str(error)) from error
        self.purge()
        with self._lock:
            if len(self._sessions) >= self.max_sessions:
                raise APIError(429, "session_capacity", "Local session capacity reached. Close old sessions or wait for their idle expiry.")
            session = PaidSession(molecule_id, candidates, references, config, ttl=self.ttl,
                                  worker_timeout=self.worker_timeout, transport_factory=self.transport_factory,
                                  clock=self.clock)
            self._sessions[session.session_id] = session
            return session

    def get(self, session_id):
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                if session_id in self._expired_ids:
                    raise APIError(410, "session_expired", "This session expired. Start a new session.")
                raise APIError(404, "unknown_session", "Unknown session.")
            if session.expired():
                self._sessions.pop(session_id)
                self._expired_ids.append(session_id)
                session.close()
                raise APIError(410, "session_expired", "This session expired. Start a new session.")
            return session

    def remove(self, session_id):
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            raise APIError(404, "unknown_session", "Unknown session.")
        session.close()

    def purge(self):
        with self._lock:
            expired = [key for key, session in self._sessions.items() if session.expired()]
            sessions = [self._sessions.pop(key) for key in expired]
            self._expired_ids.extend(expired)
        for session in sessions:
            session.close()

    def close(self):
        with self._lock:
            sessions, self._sessions = list(self._sessions.values()), {}
        for session in sessions:
            session.close()
