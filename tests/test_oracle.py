import ast
import inspect
import json
from pathlib import Path
import unittest

from aqc.oracle import Oracle, PolicyExecutionError, PolicySession, policy_payload, run_policy


def candidates(*energies):
    return [{"candidate_id": chr(97 + i), "cheap_kcal": energy}
            for i, energy in enumerate(energies)]


class OracleAccountingTests(unittest.TestCase):
    def test_success_and_duplicate_are_one_paid_job(self):
        oracle = Oracle(["a", "b"], {"a": 3.0, "b": 1.0})
        self.assertEqual(oracle.query("a")["reference_kcal"], 3.0)
        self.assertTrue(oracle.query("a")["cached"])
        self.assertEqual(oracle.expensive_calls, 1)
        self.assertEqual([e["charged"] for e in oracle.events], [1, 0])
        self.assertEqual([e["order"] for e in oracle.events], [1, 2])
        self.assertNotIn("b", oracle.observations)

    def test_missing_and_nonfinite_outputs_are_charged_once(self):
        oracle = Oracle(["a", "b", "c"], {"b": float("nan"), "c": None})
        for cid in ["a", "b", "c"]:
            self.assertFalse(oracle.query(cid)["ok"])
            self.assertTrue(oracle.query(cid)["cached"])
        self.assertEqual(oracle.expensive_calls, 3)
        self.assertEqual(oracle.observations, {})
        self.assertEqual(oracle.events[1]["status"], "cached_failure")

    def test_unknown_id_rejected_without_inventing_job(self):
        oracle = Oracle(["a"], {"a": 0.0})
        with self.assertRaises(ValueError):
            oracle.query("b")
        self.assertEqual(oracle.expensive_calls, 0)
        self.assertEqual(oracle.events[0]["status"], "rejected")

    def test_selected_must_be_best_paid_reference(self):
        oracle = Oracle(["a", "b", "c"], {"a": 5.0, "b": 2.0, "c": -10.0})
        with self.assertRaises(PolicyExecutionError):
            oracle.validate_selected("c")
        oracle.query("a")
        oracle.query("b")
        oracle.validate_selected("b")
        for invalid in ["a", "c", None]:
            with self.assertRaises(PolicyExecutionError):
                oracle.validate_selected(invalid)


class PolicyTests(unittest.TestCase):
    def test_rank_reversal_and_full_rerank(self):
        cheap = candidates(0.0, 0.1, 3.0)
        refs = {"a": 2.4, "b": 0.0, "c": 0.9}
        first = run_policy(cheap, refs, {"kind": "fixed", "k": 1})
        full = run_policy(cheap, refs, {"kind": "full"})
        self.assertEqual(first["selected_candidate"], "a")
        self.assertEqual(first["expensive_calls"], 1)
        self.assertEqual(full["selected_candidate"], "b")
        self.assertEqual(full["expensive_calls"], 3)
        self.assertEqual(refs[full["selected_candidate"]] - min(refs.values()), 0.0)

    def test_escalation_helps(self):
        result = run_policy(candidates(0.0, 0.1, 4.0), {"a": 2.0, "b": 0.0, "c": 5.0},
                            {"kind": "adaptive", "k": 1, "gap": 0.5, "cap": 2})
        self.assertEqual(result["selected_candidate"], "b")
        self.assertEqual(result["expensive_calls"], 2)
        self.assertFalse(result["fallback"])
        self.assertEqual(result["policy_events"][0]["event"], "escalation")

    def test_escalation_wastes_calls(self):
        result = run_policy(candidates(0.0, 0.1, 4.0), {"a": 0.0, "b": 0.5, "c": 5.0},
                            {"kind": "adaptive", "k": 1, "gap": 0.5, "cap": 2})
        self.assertEqual(result["selected_candidate"], "a")
        self.assertEqual(result["expensive_calls"], 2)

    def test_crowded_at_cap_falls_back_to_full(self):
        result = run_policy(candidates(0.0, 0.1, 0.2, 10.0),
                            {"a": 2.0, "b": 1.0, "c": 0.5, "d": -2.0},
                            {"kind": "adaptive", "k": 1, "gap": 0.5, "cap": 2})
        self.assertEqual(result["selected_candidate"], "d")
        self.assertEqual(result["expensive_calls"], 4)
        self.assertTrue(result["fallback"])
        self.assertEqual(result["stop_reason"], "full_rerank_fallback_crowded_at_cap")
        self.assertEqual([e["candidate_id"] for e in result["queries"]], list("abcd"))

    def test_ties_are_stable_under_input_permutation(self):
        cheap = candidates(0.0, 0.0, 0.0)
        refs = {"a": 0.0, "b": 0.0, "c": 1.0}
        for rows in [cheap, list(reversed(cheap))]:
            result = run_policy(rows, refs, {"kind": "full"})
            self.assertEqual(result["selected_candidate"], "a")
            self.assertEqual([e["candidate_id"] for e in result["queries"]], list("abc"))

    def test_missing_reference_triggers_charged_fallback(self):
        result = run_policy(candidates(0.0, 1.0, 2.0), {"a": None, "b": 2.0, "c": 0.0},
                            {"kind": "fixed", "k": 1})
        self.assertTrue(result["fallback"])
        self.assertEqual(result["expensive_calls"], 3)
        self.assertEqual(result["selected_candidate"], "c")
        self.assertEqual(result["queries"][0]["status"], "failed")

    def test_no_successful_reference_is_failure_with_accounting(self):
        with self.assertRaises(PolicyExecutionError) as caught:
            run_policy(candidates(0.0, 1.0), {}, {"kind": "fixed", "k": 1})
        self.assertEqual(caught.exception.expensive_calls, 2)
        self.assertEqual(len(caught.exception.queries), 2)

    def test_k_larger_than_pool_still_queries_every_candidate_once(self):
        result = run_policy(candidates(0.0, 1.0), {"a": 1.0, "b": 0.0},
                            {"kind": "fixed", "k": 100})
        self.assertEqual(result["expensive_calls"], 2)
        self.assertEqual(result["selected_candidate"], "b")

    def test_session_resets_observations_and_charges_between_runs(self):
        cheap = candidates(0.0, 1.0)
        with PolicySession() as session:
            first = session.run(cheap, {"a": 10.0, "b": 0.0}, {"kind": "full"})
            second = session.run(cheap, {"a": 0.0, "b": 10.0}, {"kind": "fixed", "k": 1})
        self.assertEqual(first["expensive_calls"], 2)
        self.assertEqual(second["expensive_calls"], 1)
        self.assertEqual(second["observations"], {"a": 0.0})
        self.assertEqual(second["selected_candidate"], "a")

    def test_unqueried_labels_do_not_change_query_order_or_decision(self):
        cheap = candidates(0.0, 2.0, 3.0)
        config = {"kind": "adaptive", "k": 1, "gap": 0.5, "cap": 2}
        one = run_policy(cheap, {"a": 0.0, "b": -5000.0, "c": 5000.0}, config)
        two = run_policy(cheap, {"a": 0.0, "b": 5000.0, "c": -5000.0}, config)
        self.assertEqual(one, two)


class IsolationTests(unittest.TestCase):
    def test_feature_contract_rejects_reference_or_family_fields(self):
        for forbidden in ["reference_kcal", "family_id", "molecule_id", "reference_rank"]:
            row = {"candidate_id": "a", "cheap_kcal": 0.0, forbidden: 123}
            with self.assertRaisesRegex(ValueError, "schema"):
                policy_payload([row], {"kind": "full"})

    def test_wire_payload_has_no_reference_summary(self):
        payload = policy_payload(candidates(10.0, 12.0), {"kind": "fixed", "k": 1})
        self.assertEqual(set(payload), {"type", "candidates", "config"})
        self.assertEqual(payload["candidates"], candidates(10.0, 12.0))
        self.assertNotIn("reference", json.dumps(payload))

    def test_worker_imports_only_json_and_sys(self):
        source = Path(inspect.getfile(Oracle)).with_name("policy_worker.py").read_text()
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
        self.assertEqual(imported, {"json", "sys"})

    def test_invalid_policy_and_nonfinite_features_fail_closed(self):
        invalid = [
            {"kind": "fixed", "k": 0},
            {"kind": "fixed", "k": True},
            {"kind": "adaptive", "k": 2, "gap": 0.5, "cap": 1},
            {"kind": "adaptive", "k": 1, "gap": float("nan"), "cap": 2},
            {"kind": "full", "reference_min": 0.0},
        ]
        for config in invalid:
            with self.assertRaises(ValueError):
                policy_payload(candidates(0.0), config)
        with self.assertRaises(ValueError):
            policy_payload(candidates(float("nan")), {"kind": "full"})


if __name__ == "__main__":
    unittest.main()
