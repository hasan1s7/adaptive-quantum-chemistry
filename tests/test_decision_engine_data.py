"""Independent data-boundary checks for the oxide replay and group calibration."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

from erkidu_decision.prepare import (
    assignment, conformal_quantile, digest, eligible, fit,
    parse_formula, reduced_composition, validate_splits,
)


def write(path, data):
    path.write_text(json.dumps(data, sort_keys=True, allow_nan=False) + "\n")


def fit_fixture(path, heldout_offset=0., calibration_multiplier=1.):
    path.mkdir()
    pools, refs = [], {}
    specifications = [("train", i) for i in range(3)] + [("calibration", i) for i in range(12)] + [("test", 0), ("shift_li", 0)]
    for split, index in specifications:
        group = f"{split}-{index}"
        rows = []
        for j in range(3):
            cid = f"{group}-c{j}"
            mean = j * .05
            rows.append({"candidate_id": cid, "mean_eV_atom": mean,
                         "disagreement_eV_atom": j * .04 + .01,
                         "support_distance": .03 * index + .01 * j})
            discrepancy = [0., -.04, .09][j] * (1 + index / 10)
            if split == "calibration":
                discrepancy *= calibration_multiplier
            if split in {"test", "shift_li"}:
                discrepancy += heldout_offset * j
            refs[cid] = -20. + mean + discrepancy
        pools.append({"group_id": group, "split": split,
                      "pool_id": group, "anchor_id": rows[0]["candidate_id"],
                      "candidates": rows})
    write(path / "pools.json", pools)
    write(path / "references_private.json", {"labels": refs})
    write(path / "preregistered_protocol.json", {"synthetic_fixture": True})
    write(path / "preparation_seal.json", {p.name: digest(p) for p in path.iterdir() if p.is_file()})


class OxideFormulaAndSplitTests(unittest.TestCase):
    def test_formula_reduction_and_restriction(self):
        self.assertEqual(reduced_composition("Si4 O8"), {"O": 2, "Si": 1})
        self.assertTrue(eligible(reduced_composition("Li2SiO3")))
        self.assertTrue(eligible(reduced_composition("Al2O3")))
        self.assertFalse(eligible(reduced_composition("Fe2O3")))
        self.assertFalse(eligible(reduced_composition("LiO2")))
        self.assertFalse(eligible(reduced_composition("Si")))
        for value in ("Si0O2", "Si0.5O2", "Si(OH)4", "not-a-formula", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_formula(value)

    def test_whole_system_split_order_invariance_and_li_shift(self):
        systems = [f"O-X{i}" for i in range(10)] + ["Li-O-Si", "Al-Li-O"]
        result = assignment(systems)
        self.assertEqual(result, assignment(list(reversed(systems))))
        self.assertEqual(result["Li-O-Si"], "shift_li")
        self.assertEqual(result["Al-Li-O"], "shift_li")
        self.assertEqual(sum(v == "train" for v in result.values()), 4)
        self.assertEqual(sum(v == "calibration" for v in result.values()), 3)
        self.assertEqual(sum(v == "test" for v in result.values()), 3)

    def test_cross_split_group_and_duplicate_candidate_rejected(self):
        pool = {"group_id": "O-Si", "split": "train", "composition": "O2Si1",
                "candidates": [{"candidate_id": "a", "initial_prototype": "p1"}]}
        other = {"group_id": "O-Si", "split": "test", "composition": "O1Si1",
                 "candidates": [{"candidate_id": "b", "initial_prototype": "p2"}]}
        with self.assertRaisesRegex(ValueError, "chemical system crosses"):
            validate_splits([pool, other])
        other["group_id"], other["composition"] = "Al-O", "Al2O3"
        other["candidates"][0]["candidate_id"] = "a"
        with self.assertRaisesRegex(ValueError, "candidate duplicate"):
            validate_splits([pool, other])

    def test_composition_prototype_duplicates_rejected_without_labels(self):
        pool = {"group_id": "O-Si", "split": "test", "composition": "O2Si1",
                "candidates": [{"candidate_id": "a", "initial_prototype": "p1"},
                               {"candidate_id": "b", "initial_prototype": "p1"}]}
        with self.assertRaisesRegex(ValueError, "prototype duplicate"):
            validate_splits([pool])

    def test_finite_sample_group_quantile_including_insufficient_groups(self):
        self.assertIsNone(conformal_quantile([], .1))
        self.assertIsNone(conformal_quantile(list(range(8)), .1))
        self.assertEqual(conformal_quantile(list(range(9)), .1), 8)
        self.assertEqual(conformal_quantile(list(range(12)), .1), 11)
        self.assertIsNone(conformal_quantile(list(range(12)), .05))


class FitVisibilityTests(unittest.TestCase):
    def test_fit_rejects_tampered_frozen_input_before_creating_output(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            fit_fixture(base / "a")
            with (base / "a/pools.json").open("a") as stream:
                stream.write(" ")
            with self.assertRaisesRegex(ValueError, "preparation seal mismatch"):
                fit(base / "a", base / "fit")
            self.assertFalse((base / "fit").exists())

    def test_missing_training_label_is_explicit_unsupported_not_excluded(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            fit_fixture(base / "a")
            path = base / "a/references_private.json"
            data = json.loads(path.read_text())
            data["labels"]["train-0-c1"] = None
            write(path, data)
            seal_path = base / "a/preparation_seal.json"
            seal = json.loads(seal_path.read_text())
            seal["references_private.json"] = digest(path)
            write(seal_path, seal)
            with self.assertRaisesRegex(ValueError, "unsupported fit.*no candidates were silently excluded"):
                fit(base / "a", base / "fit")
            self.assertFalse((base / "fit").exists())

    def test_heldout_reference_perturbation_cannot_change_fit_or_calibration(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            fit_fixture(base / "a", heldout_offset=0.)
            fit_fixture(base / "b", heldout_offset=100000.)
            first = fit(base / "a", base / "fa")
            second = fit(base / "b", base / "fb")
            for key in ("coefficients", "intervals", "ood_cutoff", "training_residuals",
                        "mean_training_anchored_error_eV_atom"):
                self.assertEqual(first[key], second[key], key)

    def test_calibration_labels_change_intervals_but_not_trained_scale(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            fit_fixture(base / "a", calibration_multiplier=1.)
            fit_fixture(base / "b", calibration_multiplier=10.)
            first = fit(base / "a", base / "fa")
            second = fit(base / "b", base / "fb")
            self.assertEqual(first["coefficients"], second["coefficients"])
            self.assertEqual(first["ood_cutoff"], second["ood_cutoff"])
            for method in first["intervals"]:
                self.assertGreater(second["intervals"][method]["q"], first["intervals"][method]["q"])
                self.assertEqual(first["intervals"][method]["n_calibration_groups"], 12)
                self.assertIsNone(first["intervals"][method]["q_95"])


if __name__ == "__main__":
    unittest.main()
