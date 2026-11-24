"""Sequential-policy behavior and real subprocess fault-injection audits.

Fault cases run actual child interpreters through PolicySession.run and
benchmark.evaluate_logged; no preconstructed PolicyExecutionError stands in for
transport, parsing, timeout or cleanup failures.
"""
from contextlib import contextmanager
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from aqc.benchmark import evaluate_logged
from aqc import oracle as module
from aqc.oracle import PolicyExecutionError, PolicySession, policy_payload, run_policy


def candidates(*values):
    return [{"candidate_id": chr(97 + i), "cheap_kcal": value} for i, value in enumerate(values)]


def config(**changes):
    return {"kind": "sequential", "one_gap": 8.0, "one_ratio": .3,
            "error_scale": 2.0, "slack": .25, "cap": 2, **changes}


def decision(result):
    return (tuple(q["candidate_id"] for q in result["queries"]), result["selected_candidate"],
            result["expensive_calls"], result["fallback"], result["stop_reason"])


class SequentialPolicyTests(unittest.TestCase):
    def test_observed_reference_disagreement_changes_query_decision(self):
        cheap = candidates(0, .25, .5, 4)
        matching = run_policy(cheap, dict(zip("abcd", [0, .25, .5, 4])), config())
        discrepancy = run_policy(cheap, dict(zip("abcd", [0, 4, -2, 5])), config())
        self.assertEqual(matching["expensive_calls"], 2)
        self.assertEqual(matching["stop_reason"], "sequential_empirical_envelope")
        self.assertEqual(discrepancy["expensive_calls"], 4)
        self.assertTrue(discrepancy["fallback"])
        self.assertEqual(discrepancy["selected_candidate"], "c")
        self.assertEqual(discrepancy["stop_reason"], "full_rerank_fallback_empirical_unresolved_at_cap")

    def test_one_query_requires_both_separation_conditions(self):
        cheap = candidates(0, 2, 10)
        refs = {"a": 0, "b": 2, "c": 10}
        allowed = run_policy(cheap, refs, config(one_gap=2, one_ratio=.2))
        gap_fails = run_policy(cheap, refs, config(one_gap=2.1, one_ratio=.2))
        ratio_fails = run_policy(cheap, refs, config(one_gap=2, one_ratio=.21))
        self.assertEqual(allowed["expensive_calls"], 1)
        self.assertEqual(allowed["stop_reason"], "sequential_cheap_separation_heuristic")
        self.assertEqual(gap_fails["expensive_calls"], 2)
        self.assertEqual(ratio_fails["expensive_calls"], 2)

    def test_tied_cheap_minima_never_pass_one_query_gate(self):
        result = run_policy(candidates(0, 0, 0), {"a": 1, "b": 0, "c": 2},
                            config(one_gap=0, one_ratio=0, error_scale=1))
        self.assertGreaterEqual(result["expensive_calls"], 2)
        gate = next(e for e in result["policy_events"] if e["event"] == "cheap_separation")
        self.assertEqual(gate["gap_ratio"], 0)
        self.assertEqual(gate["action"], "query_next")
        self.assertEqual(result["selected_candidate"], "b")

    def test_singleton_pays_one_and_finishes(self):
        result = run_policy(candidates(10), {"a": -20}, config())
        self.assertEqual(result["expensive_calls"], 1)
        self.assertEqual(result["stop_reason"], "all_candidates_queried")
        self.assertFalse(result["fallback"])

    def test_cheap_and_reference_constant_offsets_do_not_change_decisions(self):
        base_candidates = candidates(0, .25, .5, 4)
        base_refs = dict(zip("abcd", [0, 4, -2, 5]))
        expected = decision(run_policy(base_candidates, base_refs, config()))
        for cheap_shift, ref_shift in [(1000, -1_000_000), (-1000, 1_000_000), (0, 90), (80, 0)]:
            rows = [dict(r, cheap_kcal=r["cheap_kcal"] + cheap_shift) for r in base_candidates]
            refs = {cid: value + ref_shift for cid, value in base_refs.items()}
            self.assertEqual(decision(run_policy(rows, refs, config())), expected)

    def test_unqueried_labels_never_change_stopping(self):
        cheap = candidates(0, .25, 2, 4)
        first = run_policy(cheap, {"a": 0, "b": .25, "c": -999, "d": 999}, config())
        second = run_policy(cheap, {"a": 0, "b": .25, "c": 999, "d": -999}, config())
        self.assertEqual(first, second)

    def test_envelope_can_escalate_then_stop_before_cap(self):
        # After b: E=1.75 and d_next=.5 -> unresolved. After c: b=-1,
        # E=3.25 and d_next=4 -> the empirical condition now passes.
        result = run_policy(candidates(0, .25, .5, 4, 5),
                            dict(zip("abcde", [0, 1, -1, 4, 5])), config(cap=4))
        self.assertEqual(result["expensive_calls"], 3)
        self.assertFalse(result["fallback"])
        self.assertEqual(result["selected_candidate"], "c")
        self.assertEqual([e["action"] for e in result["policy_events"] if e["event"] == "empirical_envelope"],
                         ["query_next", "stop"])

    def test_empirical_condition_checked_before_cap_fallback(self):
        result = run_policy(candidates(0, .25, .5), {"a": 0, "b": .25, "c": .5}, config(cap=2))
        self.assertEqual(result["expensive_calls"], 2)
        self.assertFalse(result["fallback"])
        self.assertEqual(result["stop_reason"], "sequential_empirical_envelope")

    def test_missing_first_or_later_output_falls_back_and_charges(self):
        for missing in ["a", "b", "c"]:
            refs = dict(zip("abcd", [0, 4, -2, 5]))
            refs[missing] = None
            result = run_policy(candidates(0, .25, .5, 4), refs, config(cap=4))
            self.assertEqual(result["expensive_calls"], 4)
            self.assertTrue(result["fallback"])
            self.assertEqual(result["stop_reason"], "full_rerank_fallback_failed_output")
            successful = {cid: value for cid, value in refs.items() if value is not None}
            self.assertEqual(result["selected_candidate"], min(successful, key=lambda cid: (successful[cid], cid)))
            self.assertEqual(sum(q["status"] == "failed" for q in result["queries"]), 1)

    def test_all_missing_outputs_raise_with_complete_paid_audit(self):
        with self.assertRaises(PolicyExecutionError) as caught:
            run_policy(candidates(0, .25, .5), {}, config())
        self.assertEqual(caught.exception.expensive_calls, 3)
        self.assertEqual([q["candidate_id"] for q in caught.exception.queries], list("abc"))
        self.assertTrue(any(e["event"] == "fallback" for e in caught.exception.policy_events))

    def test_decision_event_stream_is_ordered_and_contains_stop(self):
        result = run_policy(candidates(0, .25, .5), {"a": 0, "b": .25, "c": .5}, config())
        events = result["policy_events"]
        self.assertEqual(result["protocol_version"], 2)
        self.assertEqual([e["event_order"] for e in events], list(range(1, len(events) + 1)))
        self.assertEqual(events[-1]["event"], "stop")
        self.assertEqual(events[-1]["selected_candidate"], result["selected_candidate"])
        self.assertEqual([e["candidate_id"] for e in events if e["event"] == "query_decision"],
                         [q["candidate_id"] for q in result["queries"]])

    def test_reference_ties_and_reordered_input_keep_deterministic_selection(self):
        rows = candidates(0, 0, 3)
        refs = {"a": 0, "b": 0, "c": -10}
        one = run_policy(rows, refs, config())
        two = run_policy(rows[::-1], refs, config())
        self.assertEqual(one, two)
        self.assertEqual(one["selected_candidate"], "a")

    def test_sequential_validation_rejects_optimistic_scale_and_undeclared_fields(self):
        for change in [dict(error_scale=.9), dict(one_ratio=1.1), dict(one_ratio=-.1),
                       dict(one_gap=-1), dict(slack=-1), dict(cap=1), dict(cap=True),
                       dict(one_gap=float("inf")), dict(reference_min=-100)]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                policy_payload(candidates(0, 1), config(**change))

    def test_session_resets_sequential_evidence_between_molecules(self):
        rows = candidates(0, .25, .5, 4)
        with PolicySession() as session:
            many = session.run(rows, dict(zip("abcd", [0, 4, -2, 5])), config())
            few = session.run(rows, dict(zip("abcd", [0, .25, .5, 4])), config())
        self.assertEqual(many["expensive_calls"], 4)
        self.assertEqual(few["expensive_calls"], 2)
        self.assertEqual(set(few["observations"]), {"a", "b"})


WORKER_HEADER = '''import json,sys,os,time
payload=json.loads(sys.stdin.readline())
def send(value):
    print(json.dumps(value),flush=True)
def paid_query():
    send({"type":"event","event":{"event":"query_decision","event_order":1,"candidate_id":"a","action":"query"}})
    send({"type":"query","candidate_id":"a"})
    return json.loads(sys.stdin.readline())
'''


class WorkerFaultAuditTests(unittest.TestCase):
    def setUp(self):
        self.pool = {"molecule_id": "fault_fixture", "family_id": "synthetic_faults",
                     "candidates": candidates(0, 1), "references": {"a": 0.0, "b": 1.0}}

    @contextmanager
    def worker(self, body, timeout=2):
        with tempfile.TemporaryDirectory(prefix="aqc-injected-worker-") as tmp:
            path = Path(tmp) / "worker.py"
            path.write_text(WORKER_HEADER + body + "\n")
            with mock.patch.object(module, "_WORKER_PATH", path), PolicySession(timeout) as session:
                yield session

    def run_failure(self, body, *, timeout=2, charged=1, exception_type=None):
        stream = io.StringIO()
        with self.worker(body, timeout) as session:
            with self.assertRaises(PolicyExecutionError) as caught:
                evaluate_logged(self.pool, "sequential", config(), session, "development", stream)
        error = caught.exception
        self.assertEqual(error.expensive_calls, charged)
        self.assertEqual(sum(q["charged"] for q in error.queries), charged)
        trace = json.loads(stream.getvalue())["result"]
        self.assertEqual(trace["expensive_calls"], charged)
        self.assertEqual(trace["queries"], error.queries)
        self.assertEqual(trace["failure_stage"], error.failure_stage)
        self.assertEqual(trace["cause_type"], error.cause_type)
        if exception_type is not None:
            self.assertIsInstance(error.__cause__, exception_type)
        if charged:
            self.assertEqual(trace["observations"], {"a": 0.0})
        return error, trace

    def test_malformed_json_after_paid_query_is_logged(self):
        error, trace = self.run_failure("paid_query()\nprint('not-json',flush=True)",
                                       exception_type=json.JSONDecodeError)
        self.assertEqual(error.failure_stage, "protocol_decode")
        self.assertEqual(trace["policy_events"][0]["event"], "query_decision")

    def test_broken_pipe_after_charge_is_logged(self):
        # Close the OS read end before announcing the query: the parent charges
        # it, then its real attempt to write the observation hits EPIPE.
        body = "os.close(0)\nsend({'type':'query','candidate_id':'a'})\ntime.sleep(10)"
        error, _ = self.run_failure(body, exception_type=BrokenPipeError)
        self.assertEqual(error.failure_stage, "observation_send")

    def test_unknown_id_after_paid_query_preserves_rejected_attempt(self):
        error, _ = self.run_failure("paid_query()\nsend({'type':'query','candidate_id':'unknown'})",
                                   exception_type=ValueError)
        self.assertEqual(len(error.queries), 2)
        self.assertEqual(error.queries[-1]["status"], "rejected")
        self.assertEqual(error.queries[-1]["charged"], 0)

    def test_wrongly_typed_id_after_paid_query_is_logged(self):
        error, _ = self.run_failure("paid_query()\nsend({'type':'query','candidate_id':[]})",
                                   exception_type=ValueError)
        self.assertEqual(error.queries[-1]["error"], "invalid_candidate_id_type")
        self.assertEqual(error.queries[-1]["received_type"], "list")

    def test_nonobject_message_after_query_is_logged(self):
        self.run_failure("paid_query()\nprint('[]',flush=True)", exception_type=module.WorkerProtocolError)

    def test_duplicate_and_nonfinite_json_keys_are_rejected_with_audit(self):
        for raw in ['{"type":"query","type":"done","candidate_id":"a"}',
                    '{"type":"event","event":{"event":"stop","event_order":NaN}}',
                    '{"type":"event","event":{"event":"stop","event_order":2,"gap":1e999}}']:
            with self.subTest(raw=raw):
                self.run_failure("paid_query()\nprint(" + repr(raw) + ",flush=True)",
                                 exception_type=module.WorkerProtocolError)

    def test_malformed_completion_and_event_types_are_logged(self):
        bad = [
            {"type": "done", "protocol_version": 2, "selected_candidate": "a", "fallback": "yes", "stop_reason": "x"},
            {"type": "event", "event": {"event": "invented", "event_order": 2}},
            {"type": "event", "event": {"event": "stop", "event_order": True}},
            {"type": "query", "candidate_id": "b", "reference_kcal": 10},
        ]
        for message in bad:
            with self.subTest(message=message):
                self.run_failure("paid_query()\nsend(" + repr(message) + ")", exception_type=module.WorkerProtocolError)

    def test_worker_eof_after_query_retains_ledger_and_stderr(self):
        error, _ = self.run_failure("paid_query()\nprint('injected crash detail',file=sys.stderr,flush=True)\nsys.exit(17)",
                                   exception_type=EOFError)
        self.assertIn("injected crash detail", error.worker_stderr)

    def test_timeout_after_paid_query_is_logged(self):
        start = time.monotonic()
        error, _ = self.run_failure("paid_query()\ntime.sleep(10)", timeout=.5, exception_type=TimeoutError)
        self.assertEqual(error.failure_stage, "worker_response")
        self.assertLess(time.monotonic() - start, 4)

    def test_initial_payload_send_failure_has_zero_charge_audit(self):
        stream = io.StringIO()
        with PolicySession() as session:
            session._process.kill()
            session._process.wait(timeout=2)
            with self.assertRaises(PolicyExecutionError) as caught:
                evaluate_logged(self.pool, "sequential", config(), session, "development", stream)
        error = caught.exception
        self.assertEqual(error.expensive_calls, 0)
        self.assertEqual(error.failure_stage, "payload_send")
        self.assertIsInstance(error.__cause__, BrokenPipeError)
        self.assertEqual(json.loads(stream.getvalue())["result"]["expensive_calls"], 0)

    def test_worker_not_reading_large_payload_cannot_bypass_timeout(self):
        with tempfile.TemporaryDirectory(prefix="aqc-blocked-payload-") as tmp:
            path = Path(tmp) / "worker.py"
            path.write_text("import time\ntime.sleep(10)\n")
            rows = [{"candidate_id": f"c{i:06d}", "cheap_kcal": float(i)} for i in range(5000)]
            refs = {row["candidate_id"]: row["cheap_kcal"] for row in rows}
            start = time.monotonic()
            with mock.patch.object(module, "_WORKER_PATH", path), PolicySession(.25) as session:
                with self.assertRaises(PolicyExecutionError) as caught:
                    session.run(rows, refs, config())
            self.assertEqual(caught.exception.expensive_calls, 0)
            self.assertEqual(caught.exception.failure_stage, "payload_send")
            self.assertIsInstance(caught.exception.__cause__, TimeoutError)
            self.assertLess(time.monotonic() - start, 4)

    def test_primary_decode_failure_survives_cleanup_failure(self):
        stream = io.StringIO()
        with self.worker("paid_query()\nprint('bad-json',flush=True)") as session:
            actual_cleanup = session._directory.cleanup
            try:
                with mock.patch.object(session._directory, "cleanup", side_effect=OSError("injected cleanup denial")):
                    with self.assertRaises(PolicyExecutionError) as caught:
                        evaluate_logged(self.pool, "sequential", config(), session, "development", stream)
            finally:
                actual_cleanup()
        error = caught.exception
        self.assertIsInstance(error.__cause__, json.JSONDecodeError)
        self.assertEqual(error.expensive_calls, 1)
        self.assertEqual(error.failure_stage, "protocol_decode")
        self.assertEqual(error.cleanup_errors[0]["cause_type"], "OSError")
        self.assertEqual(json.loads(stream.getvalue())["result"]["cleanup_errors"], error.cleanup_errors)

    def test_cleanup_only_failure_retains_successful_query_ledger(self):
        session = PolicySession()
        session.__enter__()
        actual_cleanup = session._directory.cleanup
        try:
            result = session.run(self.pool["candidates"], self.pool["references"], {"kind": "full"})
            with mock.patch.object(session._directory, "cleanup", side_effect=OSError("injected cleanup denial")):
                with self.assertRaises(PolicyExecutionError) as caught:
                    session.__exit__(None, None, None)
        finally:
            actual_cleanup()
            session.close()
        self.assertEqual(caught.exception.expensive_calls, result["expensive_calls"])
        self.assertEqual(caught.exception.failure_stage, "cleanup")
        self.assertIsInstance(caught.exception.__cause__, OSError)

    def test_invalid_input_is_logged_as_zero_charge_failure(self):
        stream = io.StringIO()
        with PolicySession() as session:
            with self.assertRaises(PolicyExecutionError) as caught:
                evaluate_logged(self.pool, "sequential", config(cap=0), session, "development", stream)
        self.assertEqual(caught.exception.expensive_calls, 0)
        self.assertEqual(caught.exception.failure_stage, "payload_validation")
        self.assertEqual(json.loads(stream.getvalue())["result"]["queries"], [])

    def test_large_stderr_is_drained_and_diagnostic_is_bounded(self):
        body = "paid_query()\nsys.stderr.write('diagnostic\\n'*20000)\nsys.stderr.flush()\nsys.exit(1)"
        error, _ = self.run_failure(body, exception_type=EOFError)
        self.assertIn("diagnostic", error.worker_stderr)
        self.assertLessEqual(len(error.worker_stderr), 8192)

    def test_session_can_reopen_after_failed_run_without_stale_observations(self):
        session = PolicySession()
        with session:
            with self.assertRaises(PolicyExecutionError):
                session.run(self.pool["candidates"], {}, {"kind": "full"})
        with session:
            result = session.run(self.pool["candidates"], self.pool["references"], {"kind": "fixed", "k": 1})
        self.assertEqual(result["expensive_calls"], 1)
        self.assertEqual(result["observations"], {"a": 0.0})


if __name__ == "__main__":
    unittest.main()
