"""Meaningful evaluator checks: paired family uncertainty and decision metrics."""

import copy
from pathlib import Path
import tempfile
import unittest

import numpy as np

from aqc.statistics import (
    _family_weights, _weighted_quantile, paired_comparisons, plot_risk_calls, summarize,
)


def row(molecule, family, policy, regret, calls, fallback=False, n=8):
    return {
        "molecule_id": molecule, "family_id": family, "policy": policy,
        "n_candidates": n, "regret_kcal": regret, "expensive_calls": calls,
        "fallback": fallback,
    }


class StatisticsTests(unittest.TestCase):
    def setUp(self):
        self.rows = []
        # Unequal family sizes make family versus molecule resampling observable.
        for molecule, family, regret in (
            ("m1", "family-a", 0.0), ("m2", "family-a", 1.0),
            ("m3", "family-a", 2.0), ("m4", "family-b", 0.2),
            ("m5", "family-c", 0.4),
        ):
            self.rows.extend([
                row(molecule, family, "fixed_top_k", regret, 4),
                row(molecule, family, "adaptive", regret, 3),
                row(molecule, family, "full_rerank", 0.0, 8),
                row(molecule, family, "cheap_only", regret + 0.2, 0),
            ])

    def test_summary_metrics_threshold_and_linear_tail(self):
        result = {item["policy"]: item for item in summarize(self.rows, bootstrap=100)}["fixed_top_k"]
        self.assertEqual(result["n_molecules"], 5)
        self.assertEqual(result["n_families"], 3)
        self.assertEqual(result["success_rate"], 0.8)
        self.assertEqual(result["median_regret_kcal"], 0.4)
        self.assertAlmostEqual(result["p95_regret_kcal"], 1.8)
        self.assertEqual(result["max_regret_kcal"], 2.0)
        self.assertEqual(result["total_calls"], 20)
        self.assertEqual(result["mean_call_fraction"], 0.5)

    def test_success_boundary_tolerance(self):
        rows = [row("m1", "a", "fixed_top_k", 1 + 5e-10, 1), row("m2", "b", "fixed_top_k", 1 + 2e-9, 1)]
        result = summarize(rows, bootstrap=0)[0]
        self.assertEqual(result["success_rate"], 0.5)
        self.assertIsNone(result["success_rate_ci_low"])

    def test_family_bootstrap_retains_entire_unequal_clusters(self):
        groups = [item for item in self.rows if item["policy"] == "fixed_top_k"]
        weights = _family_weights(groups, 100, 1729)
        np.testing.assert_array_equal(weights[:, 0], weights[:, 1])
        np.testing.assert_array_equal(weights[:, 1], weights[:, 2])
        self.assertTrue(np.any(weights.sum(axis=1) != len(groups)))

    def test_weighted_quantile_equals_explicit_cluster_repetitions(self):
        values = np.array([5.0, 1.0, 8.0, 2.0])
        weights = np.array([[0, 2, 1, 0], [3, 0, 0, 1], [1, 1, 1, 1], [0, 0, 1, 0]])
        actual = _weighted_quantile(values, weights, 0.95)
        expected = [np.quantile(np.repeat(values, w), 0.95) for w in weights]
        np.testing.assert_allclose(actual, expected)

    def test_paired_effects_keep_molecule_pairs(self):
        comparisons = paired_comparisons(self.rows, bootstrap=200, seed=91)
        result = next(item for item in comparisons if item["policy"] == "adaptive" and item["comparator"] == "fixed_top_k")
        self.assertEqual(result["delta_success_rate"], 0.0)
        self.assertEqual(result["delta_success_rate_ci_low"], 0.0)
        self.assertEqual(result["delta_success_rate_ci_high"], 0.0)
        self.assertEqual(result["delta_mean_calls"], -1.0)
        self.assertEqual(result["delta_mean_calls_ci_low"], -1.0)
        self.assertEqual(result["delta_mean_calls_ci_high"], -1.0)
        self.assertEqual(result["relative_call_savings"], 0.25)
        self.assertEqual(result["relative_call_savings_ci_low"], 0.25)
        self.assertEqual(result["relative_call_savings_ci_high"], 0.25)
        self.assertFalse(any(item["policy"] == "cheap_only" for item in comparisons))

    def test_rejects_mismatched_molecule_pools(self):
        rows = [item for item in self.rows if not (item["policy"] == "adaptive" and item["molecule_id"] == "m5")]
        with self.assertRaisesRegex(ValueError, "identical molecule pools"):
            paired_comparisons(rows)

    def test_rejects_family_mismatch(self):
        rows = copy.deepcopy(self.rows)
        rows[1]["family_id"] = "wrong-family"
        with self.assertRaisesRegex(ValueError, "family or pool size mismatch"):
            paired_comparisons(rows)

    def test_rejects_candidate_pool_size_mismatch(self):
        rows = copy.deepcopy(self.rows)
        rows[1]["n_candidates"] += 1
        with self.assertRaisesRegex(ValueError, "family or pool size mismatch"):
            paired_comparisons(rows)

    def test_deterministic_under_row_order(self):
        self.assertEqual(summarize(self.rows, 120, 31), summarize(list(reversed(self.rows)), 120, 31))
        self.assertEqual(paired_comparisons(self.rows, 120, 31), paired_comparisons(list(reversed(self.rows)), 120, 31))

    def test_empty_and_invalid_records_rejected(self):
        with self.assertRaises(ValueError):
            summarize([])
        with self.assertRaises(ValueError):
            summarize([row("m", "f", "adaptive", float("nan"), 1)])
        with self.assertRaises(ValueError):
            summarize([row("m", "f", "adaptive", 0, 0)])
        with self.assertRaises(ValueError):
            summarize([row("m", "f", "adaptive", 0, 9)])
        with self.assertRaises(ValueError):
            summarize([self.rows[0], self.rows[0]])

    def test_one_family_uncertainty_warning(self):
        result = summarize([row("m", "f", "adaptive", 0.0, 1)], 20)[0]
        self.assertIn("no between-family", result["uncertainty_warning"])

    def test_all_success_non_ceiling_warns_about_bootstrap_boundary(self):
        rows = [row("a", "fa", "sequential", 0.1, 1), row("b", "fb", "sequential", 0.2, 1)]
        result = summarize(rows, 30)[0]
        self.assertEqual(result["success_rate_ci_low"], 1.0)
        self.assertIn("does not bound unobserved failure risk", result["uncertainty_warning"])

    def test_identical_pairs_have_explicit_zero_variance_warning(self):
        result = next(r for r in paired_comparisons(self.rows, 30)
                      if r["policy"] == "adaptive" and r["comparator"] == "fixed_top_k")
        self.assertIn("zero observed variance", result["uncertainty_warning"])
        self.assertIn("not unseen-family equivalence", result["uncertainty_warning"])

    def test_custom_paid_comparator_supports_cv_role(self):
        rows = [dict(r, policy="matched_simple" if r["policy"] == "fixed_top_k" else r["policy"])
                for r in self.rows]
        result = paired_comparisons(rows, 20, comparators=("matched_simple",))
        self.assertTrue(any(r["policy"] == "adaptive" and r["comparator"] == "matched_simple" for r in result))
        self.assertTrue(all(r["comparator"] == "matched_simple" for r in result))
        with self.assertRaisesRegex(ValueError, "never a denominator"):
            paired_comparisons(rows, 20, comparators=("cheap_only",))

    def test_cv_bootstrap_keeps_family_draw_count_within_each_fold(self):
        rows = [dict(row(f"m{i}", f"f{i}", "sequential", 0.1, 1), fold_id=i // 2)
                for i in range(6)]
        weights = _family_weights(rows, 60, 18, stratify_by="fold_id")
        for start in (0, 2, 4):
            np.testing.assert_array_equal(weights[:, start:start + 2].sum(axis=1), np.full(60, 2))
        result = summarize(rows, 60, stratify_by="fold_id")[0]
        self.assertIn("within fixed fold_id strata", result["interval_method"])

    def test_cv_bootstrap_rejects_family_crossing_folds(self):
        rows = [dict(row("m1", "same", "sequential", .1, 1), fold_id=0),
                dict(row("m2", "same", "sequential", .1, 1), fold_id=1)]
        with self.assertRaisesRegex(ValueError, "crosses bootstrap strata"):
            summarize(rows, 20, stratify_by="fold_id")

    def test_plot_creates_exportable_png(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "risk.png"
            result = plot_risk_calls(summarize(self.rows, 50), path, "Synthetic fixture", 3)
            self.assertEqual(result, str(path))
            self.assertGreater(path.stat().st_size, 1000)
            self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
