"""Registered grid, family selection isolation, and audited replay accounting."""
from contextlib import redirect_stdout
from copy import deepcopy
import csv
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np

from aqc.data import canonical_json, load_pools
from aqc.experiments import (
    _empty_outcomes, _execute_registry, _replay_selected, build_configurations, choose_from_training, make_family_folds,
    reconstruct_trace, run_experiments, select_fold_choices, split_trace,
    training_statistics, validate_family_folds, verify_experiment_run,
)
from aqc.fixture import prepare_fixture
from aqc.integrity import verify_artifact_seal
from aqc.oracle import Oracle, PolicyExecutionError, run_policy


def small_configurations():
    desired = {"fixed_k_01", "fixed_k_02", "adaptive_k01_gap0.5_cap02",
               "sequential_gap0.5_ratio0_error2_cap02", "full_rerank", "cheap_only"}
    return [entry for entry in build_configurations() if entry["config_id"] in desired]


def family_pools():
    return [{"molecule_id": f"m{family}_{member}", "family_id": f"family{family}",
             "candidates": [{"candidate_id": "a", "cheap_kcal": 0.0},
                            {"candidate_id": "b", "cheap_kcal": .2},
                            {"candidate_id": "c", "cheap_kcal": 3.0}],
             "references": {"a": 2.0, "b": 0.0, "c": 4.0}}
            for family in range(5) for member in range(2)]


class RegistrationAndFoldTests(unittest.TestCase):
    def test_registry_contains_1020_distinct_parameterizations(self):
        entries = build_configurations(10)
        self.assertEqual(len(entries), 1020)
        self.assertEqual(sum(e["generation"] == "original" for e in entries), 204)
        self.assertEqual(sum(e["generation"] == "new" for e in entries), 816)
        self.assertEqual(len({canonical_json(e["config"]) for e in entries}), 1020)
        self.assertEqual(len({e["config_id"] for e in entries}), 1020)
        self.assertEqual(sum(e["kind"] == "sequential" for e in entries), 816)

    def test_family_folds_are_deterministic_and_label_independent(self):
        pools = family_pools()
        expected = make_family_folds(pools)
        altered = deepcopy(pools[::-1])
        for pool in altered:
            pool["references"] = {key: value + 100000 for key, value in pool["references"].items()}
        self.assertEqual(make_family_folds(altered), expected)
        by_family = {}
        for row in expected["assignments"]:
            self.assertEqual(by_family.setdefault(row["family_id"], row["fold_id"]), row["fold_id"])
        self.assertEqual(len(expected["folds"]), 5)

    def test_fold_validation_rejects_family_and_molecule_leakage(self):
        pools = family_pools()
        folds = make_family_folds(pools)
        altered = deepcopy(folds)
        altered["assignments"][1]["fold_id"] = (altered["assignments"][0]["fold_id"] + 1) % 5
        with self.assertRaisesRegex(ValueError, "leaks across folds"):
            validate_family_folds(altered, pools)
        altered = deepcopy(folds)
        altered["assignments"].append(altered["assignments"][0])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_family_folds(altered, pools)

    def test_mutating_validation_outcomes_cannot_change_its_training_choice(self):
        pools, entries = family_pools(), small_configurations()
        folds = make_family_folds(pools)
        outcomes = _empty_outcomes(len(entries), len(pools))
        for i, entry in enumerate(entries):
            outcomes["regrets"][i, :] = 0.0 if entry["kind"] != "diagnostic" else 2.0
            outcomes["calls"][i, :] = 0 if entry["kind"] == "diagnostic" else (3 if entry["kind"] == "full" else 2)
        fold_id = 0
        original_training = training_statistics(entries, outcomes, pools, folds, fold_id)
        original_choice = choose_from_training(entries, original_training)
        assigned = {a["molecule_id"]: a["fold_id"] for a in folds["assignments"]}
        changed = {key: value.copy() for key, value in outcomes.items()}
        validation_indexes = [i for i, pool in enumerate(pools) if assigned[pool["molecule_id"]] == fold_id]
        changed["regrets"][:, validation_indexes] = np.arange(len(entries))[:, None] * 1000.0
        changed["calls"][:, validation_indexes] = 10000
        changed["fallbacks"][:, validation_indexes] = True
        changed_training = training_statistics(entries, changed, pools, folds, fold_id)
        self.assertEqual(original_training, changed_training)
        self.assertEqual(original_choice, choose_from_training(entries, changed_training))

    def test_matched_simple_compares_both_fixed_and_original_window(self):
        entries = small_configurations()
        metrics = {}
        for entry in entries:
            kind = entry["kind"]
            success = {"fixed": .98, "adaptive": .98, "sequential": .97, "full": 1., "diagnostic": .8}[kind]
            calls = {"fixed": 200, "adaptive": 180, "sequential": 140, "full": 300, "diagnostic": 0}[kind]
            metrics[entry["config_id"]] = {"success_rate": success, "total_calls": calls, "p95_regret_kcal": .5}
        selected = choose_from_training(entries, metrics)
        self.assertEqual(selected["matched_simple"]["kind"], "adaptive")
        self.assertEqual(selected["matched_simple"]["minimum_training_success"], .97)
        self.assertFalse(selected["matched_simple"]["selection_fallback"])

    def test_trace_deduplication_preserves_every_result_field(self):
        pool = family_pools()[0]
        result = run_policy(pool["candidates"], pool["references"], {"kind": "fixed", "k": 2})
        core, annotations = split_trace(pool, result)
        rebuilt = reconstruct_trace(core, annotations)
        self.assertEqual(rebuilt["result"], result)
        self.assertEqual(sum(q["charged"] for q in core["result"]["queries"]), 2)
        self.assertIn("protocol_version", annotations)
        self.assertIn("policy_events", annotations)
        with self.assertRaises(ValueError):
            reconstruct_trace(core, {"expensive_calls": 0})


class ExperimentPipelineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.prepared = self.root / "prepared"
        prepare_fixture(self.prepared)

    def test_registry_is_written_before_the_first_experiment(self):
        out = self.root / "registered"

        def first_execution(configurations, pools, folds, actual_out):
            self.assertEqual(actual_out, out)
            self.assertTrue((out / "experiment_registry.json").is_file())
            registry = json.loads((out / "experiment_registry.json").read_text())
            self.assertTrue(registry["registered_before_execution"])
            self.assertEqual(registry["configuration_count"], 1020)
            self.assertEqual(len(configurations), 1020)
            self.assertTrue((out / "folds.json").is_file())
            raise RuntimeError("stop after observing the pre-execution registration boundary")

        with mock.patch("aqc.experiments._execute_registry", side_effect=first_execution):
            with self.assertRaisesRegex(RuntimeError, "registration boundary"):
                run_experiments(self.prepared, out, bootstrap=100)
        with self.assertRaisesRegex(ValueError, "never overwrite"):
            run_experiments(self.prepared, out, bootstrap=100)

    def test_small_registered_run_audits_all_jobs_and_only_development_labels(self):
        out = self.root / "experiments"
        entries = small_configurations()
        with (mock.patch("aqc.experiments.build_configurations", return_value=entries),
              mock.patch("aqc.experiments.load_pools", wraps=load_pools) as loader,
              redirect_stdout(io.StringIO())):
            decision = run_experiments(self.prepared, out, bootstrap=100, seed=21)
            verified = verify_experiment_run(self.prepared, out, replay_selected=True)
        self.assertEqual(decision["analysis_scope"], "development_family_cv")
        self.assertFalse(decision["fresh_external_holdout"])
        self.assertFalse(decision["historical_evaluation_labels_loaded"])
        self.assertNotIn("bootstrap_joint_evidence", decision)
        self.assertTrue(all(call.args[1] == "development" for call in loader.call_args_list))
        self.assertTrue(verified["verified"])
        n_pools = len(load_pools(self.prepared, "development"))
        self.assertEqual(verified["ledger_decisions_verified"], len(entries) * n_pools)
        self.assertEqual(verified["oof_role_results_verified"], 6 * n_pools)
        self.assertLess(verified["unique_query_traces_verified"], verified["ledger_decisions_verified"])
        self.assertTrue(verified["fresh_selected_policy_replay"])
        self.assertTrue(verify_artifact_seal(out, require_complete=True)["verified"])
        with gzip.open(out / "decision_ledger.jsonl.gz", "rt") as stream:
            ledger = [json.loads(line) for line in stream]
        self.assertEqual(sum(row["expensive_calls"] for row in ledger), verified["charged_jobs_verified"])
        # Trace sharing must never turn a repeated acquisition into a free job.
        paid = [row for row in ledger if row["verified_selection"]]
        self.assertTrue(all(row["expensive_calls"] >= 1 for row in paid))
        self.assertGreater(verified["verification_charged_jobs"], 0)
        changed_decision = json.loads((out / "decision.json").read_text())
        changed_decision["observed_joint_target_met"] = not changed_decision["observed_joint_target_met"]
        (out / "decision.json").write_text(json.dumps(changed_decision))
        with mock.patch("aqc.experiments.build_configurations", return_value=entries):
            with self.assertRaisesRegex(ValueError, "decision fields/target flags"):
                verify_experiment_run(self.prepared, out)

    def test_registry_and_verification_failures_preserve_paid_fault_history(self):
        pools = family_pools()
        entry = small_configurations()[0]
        oracle = Oracle([c["candidate_id"] for c in pools[0]["candidates"]], pools[0]["references"])
        oracle.query("a")
        failure = PolicyExecutionError(
            "injected post-query worker failure", oracle, failure_stage="worker_protocol",
            cause=OSError("test exit"), policy_events=[{"event": "query_decision", "candidate_id": "a"}],
            cleanup_errors=["injected cleanup error"], worker_stderr="test worker stderr",
        )
        for stage, filename in (("registry", "decision_ledger.jsonl.gz"), ("verification", "verification_replays.jsonl.gz")):
            out = self.root / stage
            out.mkdir()
            with mock.patch("aqc.experiments._evaluate_result", side_effect=failure), self.assertRaises(PolicyExecutionError):
                if stage == "registry":
                    _execute_registry([entry], pools, make_family_folds(pools), out)
                else:
                    selected = {(entry["config_id"], pools[0]["molecule_id"]): {"trace_sha256": "expected"}}
                    _replay_selected(pools, [entry], selected, {}, out)
            with gzip.open(out / filename, "rt") as stream:
                record = json.loads(next(stream))
            self.assertEqual(record["expensive_calls"], 1)
            self.assertEqual(record["queries"], oracle.events)
            self.assertEqual(record["observations"], oracle.observations)
            self.assertEqual(record["failure_stage"], "worker_protocol")
            self.assertEqual(record["cause_type"], "OSError")
            self.assertEqual(record["policy_events"], failure.policy_events)
            self.assertEqual(record["cleanup_errors"], failure.cleanup_errors)
            self.assertEqual(record["worker_stderr"], failure.worker_stderr)


if __name__ == "__main__":
    unittest.main()
