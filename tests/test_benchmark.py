"""Selection, leakage, and freeze checks using synthetic data only."""

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from aqc import benchmark
from aqc.data import digest, sha256_file, write_json
from aqc.fixture import prepare_fixture
from aqc.oracle import Oracle, PolicyExecutionError


def point(name, success, calls, tail):
    return {"policy": name, "success_rate": success,
            "total_calls": calls, "p95_regret_kcal": tail}


class OperatingPointTests(unittest.TestCase):
    def test_rejects_cheaper_point_that_misses_risk_target(self):
        frontier = [point("unsafe", .949, 100, 2),
                    point("eligible", .95, 200, 1),
                    point("full", 1.0, 800, 0)]
        self.assertEqual(benchmark.select_operating_point(frontier, .95)["policy"],
                         "eligible")

    def test_minimizes_calls_among_risk_eligible_points(self):
        frontier = [point("minimum_cost", .96, 100, .9),
                    point("more_accurate", 1.0, 200, 0)]
        self.assertEqual(benchmark.select_operating_point(frontier, .95)["policy"],
                         "minimum_cost")

    def test_tie_breaks_by_tail_then_success_then_stable_name(self):
        frontier = [point("tail_worse", .99, 100, 1.0),
                    point("success_worse", .95, 100, .5),
                    point("z_final_tie", .96, 100, .5),
                    point("a_final_tie", .96, 100, .5)]
        for rows in [frontier, list(reversed(frontier))]:
            self.assertEqual(benchmark.select_operating_point(rows, .95)["policy"],
                             "a_final_tie")

    def test_no_feasible_point_is_explicit(self):
        self.assertIsNone(benchmark.select_operating_point(
            [point("unsafe", .90, 100, 2)], .95))
        self.assertIsNone(benchmark.select_operating_point([], .95))

    def test_matched_risk_comparator_can_differ_from_95pct_baseline(self):
        frontier = [point("fixed_k_02", .95, 200, 1),
                    point("fixed_k_03", .98, 300, .5),
                    point("fixed_k_04", 1.0, 400, 0)]
        self.assertEqual(benchmark.select_operating_point(frontier, .95)["policy"],
                         "fixed_k_02")
        self.assertEqual(benchmark.select_operating_point(frontier, .975)["policy"],
                         "fixed_k_03")


class FailureTraceTests(unittest.TestCase):
    def test_failed_policy_preserves_charged_queries_before_abort(self):
        pool = {"molecule_id": "synthetic", "family_id": "invented",
                "candidates": [{"candidate_id": "a", "cheap_kcal": 0.0},
                               {"candidate_id": "b", "cheap_kcal": 1.0}],
                "references": {"a": 2.0, "b": 0.0}}
        oracle = Oracle(["a", "b"], pool["references"])
        oracle.query("a")
        error = PolicyExecutionError("intentional_test_failure", oracle)
        session = mock.Mock()
        session.run.side_effect = error
        trace_stream = io.StringIO()
        with self.assertRaises(PolicyExecutionError):
            benchmark.evaluate_logged(pool, "adaptive", {"kind": "full"},
                                      session, "development", trace_stream)
        result = json.loads(trace_stream.getvalue())["result"]
        self.assertIsNone(result["selected_candidate"])
        self.assertEqual(result["expensive_calls"], 1)
        self.assertEqual(result["queries"][0]["charged"], 1)
        self.assertEqual(result["queries"][0]["candidate_id"], "a")
        self.assertEqual(result["stop_reason"], "policy_execution_failure")
        self.assertEqual(result["error"], "intentional_test_failure")


class FrozenExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = tempfile.TemporaryDirectory(prefix="aqc-freeze-test-")
        cls.template_root = Path(cls.template.name)
        prepare_fixture(cls.template_root / "prepared")
        # This small *test-only* grid exercises freezing without repeating the
        # complete experiment for every unit test. No real labels are loaded.
        with mock.patch.multiple(benchmark, GAPS=[.5], CAPS=[2, 6], INITIAL_K=[1, 3]), \
                redirect_stdout(io.StringIO()):
            cls.frozen = benchmark.tune(cls.template_root / "prepared",
                                        cls.template_root / "results")

    @classmethod
    def tearDownClass(cls):
        cls.template.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="aqc-freeze-case-")
        self.root = Path(self.tmp.name)
        self.prepared = self.root / "prepared"
        self.out = self.root / "results"
        shutil.copytree(self.template_root / "prepared", self.prepared)
        shutil.copytree(self.template_root / "results", self.out)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def rehash(frozen):
        frozen.pop("config_sha256", None)
        frozen["config_sha256"] = digest(frozen)

    def test_unmodified_frozen_experiment_validates(self):
        benchmark.validate_frozen(self.prepared, deepcopy(self.frozen))

    def test_changed_config_rejected(self):
        frozen = deepcopy(self.frozen)
        frozen["policies"]["fixed_top_k"] = {"kind": "fixed", "k": 99}
        with self.assertRaisesRegex(ValueError, "Frozen config content changed"):
            benchmark.validate_frozen(self.prepared, frozen)

    def test_changed_prepared_label_file_rejected(self):
        path = self.prepared / "evaluation_references.jsonl"
        path.write_text(path.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "Prepared dataset changed"):
            benchmark.validate_frozen(self.prepared, deepcopy(self.frozen))

    def test_synthetic_cannot_be_relabelled_as_real_after_freeze(self):
        audit_path = self.prepared / "audit.json"
        audit = json.loads(audit_path.read_text())
        audit["dataset_kind"] = "real"
        write_json(audit_path, audit)
        with self.assertRaisesRegex(ValueError, "provenance changed"):
            benchmark.validate_frozen(self.prepared, deepcopy(self.frozen))

    def test_changed_source_digest_rejected(self):
        frozen = deepcopy(self.frozen)
        frozen["source_code_sha256"]["policy_worker.py"] = "0" * 64
        self.rehash(frozen)
        with self.assertRaisesRegex(ValueError, "Benchmark code changed"):
            benchmark.validate_frozen(self.prepared, frozen)

    def test_missing_module_in_frozen_source_manifest_rejected(self):
        frozen = deepcopy(self.frozen)
        frozen["source_code_sha256"].pop("policy_worker.py")
        self.rehash(frozen)
        with self.assertRaisesRegex(ValueError, "module set changed"):
            benchmark.validate_frozen(self.prepared, frozen)

    def test_split_manifest_modification_rejected(self):
        path = self.prepared / "split_manifest.json"
        split = json.loads(path.read_text())
        split["assignments"][0]["n_candidates"] += 1
        write_json(path, split)
        with self.assertRaisesRegex(ValueError, "Split manifest content changed"):
            benchmark.validate_frozen(self.prepared, deepcopy(self.frozen))

    def test_feature_family_must_match_manifest_even_with_updated_file_digest(self):
        path = self.prepared / "development_features.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]["family_id"] = "different_family"
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        audit_path = self.prepared / "audit.json"
        audit = json.loads(audit_path.read_text())
        audit["prepared_files_sha256"][path.name] = sha256_file(path)
        write_json(audit_path, audit)
        with self.assertRaisesRegex(ValueError, "do not match split manifest"):
            benchmark.verify_prepared(self.prepared)

    def test_tuning_does_not_parse_any_evaluation_reference_rows(self):
        # Deliberately invalid held-out JSON is still hashable. Tuning must
        # succeed without trying to parse it; evaluation would reject it.
        path = self.prepared / "evaluation_references.jsonl"
        path.write_text("not valid reference JSON\n")
        audit_path = self.prepared / "audit.json"
        audit = json.loads(audit_path.read_text())
        audit["prepared_files_sha256"][path.name] = sha256_file(path)
        write_json(audit_path, audit)
        actual_loader = benchmark.load_pools
        loaded_splits = []

        def development_only(directory, split):
            loaded_splits.append(split)
            self.assertEqual(split, "development")
            return actual_loader(directory, split)

        with mock.patch.multiple(benchmark, GAPS=[.5], CAPS=[2, 6], INITIAL_K=[1, 3]), \
                mock.patch.object(benchmark, "load_pools", side_effect=development_only), \
                redirect_stdout(io.StringIO()):
            frozen = benchmark.tune(self.prepared, self.root / "new_results")
        self.assertEqual(loaded_splits, ["development"])
        self.assertEqual(frozen["policies"], self.frozen["policies"])

    def test_existing_freeze_blocks_retuning_before_loading_labels(self):
        with mock.patch.object(benchmark, "load_pools", side_effect=AssertionError("labels loaded")), \
                self.assertRaisesRegex(ValueError, "Frozen config already exists"):
            benchmark.tune(self.prepared, self.out)

    def test_sealed_evaluation_blocks_second_evaluation_before_loading_labels(self):
        write_json(self.out / "evaluation_seal.json", {"sealed": True})
        with mock.patch.object(benchmark, "load_pools", side_effect=AssertionError("labels loaded")), \
                self.assertRaisesRegex(ValueError, "Evaluation is sealed"):
            benchmark.evaluate(self.prepared, self.out, bootstrap=100)

    def test_invalid_bootstrap_rejected_before_opening_evaluation_labels(self):
        for value in [0, 1, 99, -1, True, 100.5]:
            with self.subTest(value=value), \
                    mock.patch.object(benchmark, "load_pools", side_effect=AssertionError("labels loaded")), \
                    self.assertRaisesRegex(ValueError, "at least 100"):
                benchmark.evaluate(self.prepared, self.out, bootstrap=value)


if __name__ == "__main__":
    unittest.main()
