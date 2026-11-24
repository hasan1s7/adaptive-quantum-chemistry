"""Data invariants: exact IDs, physical energy direction, geometry, and grouping."""

from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
import unittest

from aqc.data import (
    HARTREE_TO_KCAL,
    digest,
    family_for_smiles,
    geometry_identity,
    load_pools,
    make_split,
    parse_energies,
    to_kcal,
    validate_split,
)


def gfn_row(molecule="m", geometry="rmsd1-opt", hartree=1.0):
    return f"{molecule} {geometry}.out2 atomizationE : {hartree:.7f} {hartree * HARTREE_TO_KCAL:.2f}"


def cc_row(molecule="m", geometry="rmsd1-opt", hartree=-10.0):
    return f"{molecule} {geometry}.out.bz2 FINAL SINGLE POINT ENERGY {hartree:.12f}"


class EnergyTests(unittest.TestCase):
    def test_unit_conversion_and_atomization_sign(self):
        self.assertAlmostEqual(to_kcal(1.0, "hartree"), HARTREE_TO_KCAL)
        self.assertAlmostEqual(to_kcal(4.184, "kJ/mol"), 1.0)
        self.assertEqual(to_kcal(5.0, "kcal/mol", atomization=True), -5.0)
        # Larger atomization means LOWER molecular energy and a better conformer.
        self.assertLess(to_kcal(101.0, "kcal/mol", atomization=True),
                        to_kcal(100.0, "kcal/mol", atomization=True))

    def test_total_hartree_regret_has_correct_sign(self):
        best, selected = -100.0, -100.0 + 1.0 / HARTREE_TO_KCAL
        regret = to_kcal(selected - best, "hartree")
        self.assertAlmostEqual(regret, 1.0, places=10)

    def test_unknown_units_and_nonfinite_values_fail_closed(self):
        for unit in ["Ha", "eV", "kcal", ""]:
            with self.assertRaises(ValueError):
                to_kcal(1.0, unit)
        for value in [math.nan, math.inf, -math.inf]:
            with self.assertRaises(ValueError):
                to_kcal(value, "hartree")

    def parse(self, lines, method):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "energies.txt"
            path.write_text("\n".join(lines) + "\n")
            return parse_energies(path, method)

    def test_row_reordering_cannot_change_energy_key_pairing(self):
        cheap_lines = [gfn_row("m", "rmsd2-opt", 2.0), gfn_row("m", "rmsd1-opt", 1.0)]
        ref_lines = [cc_row("m", "rmsd1-opt", -10.0), cc_row("m", "rmsd2-opt", -11.0)]
        cheap, _, _ = self.parse(cheap_lines, "gfn2")
        refs, _, _ = self.parse(ref_lines, "ccsdt")
        cheap_reversed, _, _ = self.parse(cheap_lines[::-1], "gfn2")
        refs_reversed, _, _ = self.parse(ref_lines[::-1], "ccsdt")
        pairing = {k: (v["value"], refs[k]["value"]) for k, v in cheap.items()}
        reversed_pairing = {k: (v["value"], refs_reversed[k]["value"])
                            for k, v in cheap_reversed.items()}
        self.assertEqual(pairing, reversed_pairing)
        self.assertEqual(pairing[("m", "rmsd1-opt")], (627.51, -10.0))
        self.assertEqual(pairing[("m", "rmsd2-opt")], (1255.02, -11.0))

    def test_molecule_and_entire_geometry_stem_are_both_keys(self):
        parsed, _, _ = self.parse([gfn_row("one", "rmsd1-opt"),
                                   gfn_row("two", "rmsd1-opt")], "gfn2")
        self.assertEqual(set(parsed), {("one", "rmsd1-opt"), ("two", "rmsd1-opt")})
        self.assertEqual(parsed[("one", "rmsd1-opt")]["filename"], "rmsd1-opt.out2")

    def test_missing_reference_remains_unmatched_not_positional(self):
        cheap, _, _ = self.parse([gfn_row(geometry="rmsd1-opt"),
                                  gfn_row(geometry="rmsd2-opt")], "gfn2")
        refs, _, _ = self.parse([cc_row(geometry="rmsd2-opt")], "ccsdt")
        self.assertEqual(set(cheap) - set(refs), {("m", "rmsd1-opt")})
        self.assertEqual(set(cheap) & set(refs), {("m", "rmsd2-opt")})

    def test_nonopt_geometries_are_explicit_exclusions(self):
        parsed, exclusions, counts = self.parse([
            gfn_row(geometry="rmsd1-opt"), gfn_row(geometry="rmsd1-mmff"),
            gfn_row(geometry="rmsd1-pm7")], "gfn2")
        self.assertEqual(set(parsed), {("m", "rmsd1-opt")})
        self.assertEqual({r["conformer_id"] for r in exclusions}, {"rmsd1-mmff", "rmsd1-pm7"})
        self.assertEqual(counts, {"raw_rows": 3, "opt_rows": 1, "non_opt_rows": 2})

    def test_blank_lines_are_not_zero_energy_rows(self):
        parsed, _, counts = self.parse(["", "  ", cc_row()], "ccsdt")
        self.assertEqual(counts["raw_rows"], 1)
        self.assertEqual(parsed[("m", "rmsd1-opt")]["value"], -10.0)

    def test_duplicate_energy_ids_fail_closed(self):
        for method, row in [("gfn2", gfn_row()), ("ccsdt", cc_row())]:
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                self.parse([row, row], method)

    def test_malformed_nonfinite_and_wrong_energy_types_fail_closed(self):
        bad_rows = [
            ("ccsdt", "m rmsd1-opt.out.bz2 FINAL SINGLE POINT ENERGY"),
            ("ccsdt", "m rmsd1-opt.out.bz2 FINAL SINGLE POINT ENERGY nan"),
            ("ccsdt", "m rmsd1-opt.out.bz2 FINAL SINGLE POINT ENERGY garbage"),
            ("ccsdt", "m rmsd1-opt.out.bz2 SCF SINGLE POINT ENERGY -10"),
            ("gfn2", "m rmsd1-opt.out2 totalE : 1.0 627.51"),
            ("gfn2", "m rmsd1-opt.out2 atomizationE : 1.0 inf"),
        ]
        for method, line in bad_rows:
            with self.subTest(method=method, line=line), self.assertRaises(ValueError):
                self.parse([line], method)

    def test_unknown_method_fails_closed(self):
        with self.assertRaises(ValueError):
            self.parse([cc_row()], "mp2")

    def test_gfn2_dual_unit_columns_must_agree(self):
        for line in [
            "m rmsd1-opt.out2 atomizationE : 1.0 1.0",
            "m rmsd1-opt.out2 atomizationE : nan 627.51",
        ]:
            with self.assertRaises(ValueError):
                self.parse([line], "gfn2")


def write_geometry(root, symbols=("C", "O"), coordinates=((0., 0., 0.), (1.2, 0., 0.))):
    path = Path(root) / "rmsd1-opt.mol"
    atom_rows = [f"{x:10.4f}{y:10.4f}{z:10.4f} {symbol:<3} 0 0 0 0 0 0"
                 for symbol, (x, y, z) in zip(symbols, coordinates)]
    mol_lines = ["geometry", "test", "", f"{len(symbols):3d}  0  0  0  0  0  0  0  0  0999 V2000",
                 *atom_rows, "M  END"]
    xyz_lines = [str(len(symbols)), "geometry",
                 *[f"{symbol} {x:.5f} {y:.5f} {z:.5f}"
                   for symbol, (x, y, z) in zip(symbols, coordinates)]]
    path.write_text("\n".join(mol_lines) + "\n")
    path.with_suffix(".xyz").write_text("\n".join(xyz_lines) + "\n")
    return path


class GeometryTests(unittest.TestCase):
    def test_matching_ordered_geometry_has_content_hashes_and_composition(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_geometry(tmp)
            identity = geometry_identity(path)
            self.assertEqual(identity["natoms"], 2)
            self.assertEqual(identity["elements"], {"C": 1, "O": 1})
            self.assertEqual(len(identity["geometry_sha256"]), 64)
            self.assertEqual(len(identity["mol_sha256"]), 64)
            self.assertEqual(len(identity["xyz_sha256"]), 64)
            self.assertEqual(identity["mol_xyz_max_coordinate_error_angstrom"], 0.0)

    def test_changed_coordinates_change_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_geometry(tmp)
            first = geometry_identity(path)
            path = write_geometry(tmp, coordinates=((0., 0., 0.), (1.3, 0., 0.)))
            second = geometry_identity(path)
            self.assertNotEqual(first["geometry_sha256"], second["geometry_sha256"])

    def test_coordinate_mismatch_cannot_be_paired(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_geometry(tmp)
            xyz = path.with_suffix(".xyz")
            xyz.write_text(xyz.read_text().replace("1.20000", "1.21000"))
            with self.assertRaisesRegex(ValueError, "coordinate mismatch"):
                geometry_identity(path)

    def test_atom_order_mismatch_cannot_be_paired(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_geometry(tmp)
            xyz = path.with_suffix(".xyz")
            lines = xyz.read_text().splitlines()
            lines[2], lines[3] = lines[3], lines[2]
            xyz.write_text("\n".join(lines))
            with self.assertRaisesRegex(ValueError, "ordered atom mismatch"):
                geometry_identity(path)

    def test_count_mismatch_cannot_be_paired(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_geometry(tmp)
            xyz = path.with_suffix(".xyz")
            lines = xyz.read_text().splitlines()
            lines[0] = "3"
            xyz.write_text("\n".join(lines))
            with self.assertRaisesRegex(ValueError, "atom count mismatch"):
                geometry_identity(path)

    def test_nonfinite_coordinate_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_geometry(tmp)
            xyz = path.with_suffix(".xyz")
            xyz.write_text(xyz.read_text().replace("1.20000", "nan"))
            with self.assertRaisesRegex(ValueError, "Nonfinite"):
                geometry_identity(path)


def synthetic_molecules():
    rows = []
    for group in range(10):
        for item in range(2):
            rows.append({"molecule_id": f"m{group}_{item}", "family_id": f"family{group}",
                         "canonical_smiles": f"structure{group}_{item}",
                         "candidates": [{"candidate_id": "c1", "cheap_kcal": 0.0},
                                        {"candidate_id": "c2", "cheap_kcal": 1.0}],
                         "references": {"c1": -1.0, "c2": 0.0}})
    return rows


class FamilyAndSplitTests(unittest.TestCase):
    def test_generic_scaffold_groups_hetero_and_substitution_analogs(self):
        families = [family_for_smiles(s) for s in ["c1ccccc1", "Cc1ccccc1", "c1ccncc1"]]
        self.assertEqual(len({f[0] for f in families}), 1)
        self.assertEqual(len({f[1] for f in families}), 1)
        self.assertNotEqual(families[0][0], family_for_smiles("c1ccc2ccccc2c1")[0])

    def test_all_acyclic_molecules_are_one_conservative_family(self):
        ethanol = family_for_smiles("CCO")
        amine = family_for_smiles("CCN")
        self.assertEqual(ethanol[0], amine[0])
        self.assertEqual(ethanol[1], "ACYCLIC")
        self.assertEqual(ethanol[3], {"C": 2, "H": 6, "O": 1})

    def test_stereoisomers_cannot_escape_grouping(self):
        one = family_for_smiles("F[C@H](Cl)Br")
        two = family_for_smiles("F[C@@H](Cl)Br")
        self.assertEqual(one[:3], two[:3])

    def test_invalid_smiles_fail_closed(self):
        with self.assertRaises(ValueError):
            family_for_smiles("definitely_not_a_smiles")

    def test_family_assignment_is_complete_and_deterministic_under_row_order(self):
        molecules = synthetic_molecules()
        forward = make_split(molecules)
        reverse = make_split(list(reversed(molecules)))
        self.assertEqual(forward, reverse)
        self.assertEqual(forward["counts"]["development"],
                         {"families": 7, "molecules": 14, "candidates": 28})
        self.assertEqual(forward["counts"]["evaluation"],
                         {"families": 3, "molecules": 6, "candidates": 12})
        groups = {}
        for assignment in forward["assignments"]:
            groups.setdefault(assignment["family_id"], set()).add(assignment["split"])
        self.assertTrue(all(len(parts) == 1 for parts in groups.values()))
        saved_hash = forward.pop("split_sha256")
        self.assertEqual(saved_hash, digest(forward))

    def test_split_is_reference_blind(self):
        one = synthetic_molecules()
        two = deepcopy(one)
        for molecule in two:
            molecule["references"] = {"c1": 123456.0, "c2": -987654.0}
        self.assertEqual(make_split(one), make_split(two))

    def test_split_seed_is_explicit(self):
        self.assertNotEqual(make_split(synthetic_molecules(), seed=1)["assignments"],
                            make_split(synthetic_molecules(), seed=2)["assignments"])

    def test_family_leakage_is_rejected(self):
        manifest = make_split(synthetic_molecules())
        first = manifest["assignments"][0]
        first["split"] = "evaluation" if first["split"] == "development" else "development"
        with self.assertRaisesRegex(ValueError, "family leakage"):
            validate_split(manifest)

    def test_duplicate_molecule_assignment_is_rejected(self):
        manifest = make_split(synthetic_molecules())
        manifest["assignments"].append(dict(manifest["assignments"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate assignment"):
            validate_split(manifest)

    def test_identical_chemical_structures_in_different_families_rejected(self):
        molecules = synthetic_molecules()
        molecules[2]["canonical_smiles"] = molecules[0]["canonical_smiles"]
        with self.assertRaisesRegex(ValueError, "Identical chemical structures"):
            make_split(molecules)

    def test_one_family_cannot_be_split_into_development_and_evaluation(self):
        with self.assertRaisesRegex(ValueError, "two chemical families"):
            make_split(synthetic_molecules()[:2])


class PreparedPoolTests(unittest.TestCase):
    def write_and_load(self, features, references, split="development"):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "development_features.jsonl").write_text(
                "\n".join(json.dumps(row) for row in features) + "\n")
            (root / "development_references.jsonl").write_text(
                "\n".join(json.dumps(row) for row in references) + "\n")
            return load_pools(root, split)

    def fixture(self):
        return ([{"molecule_id": "m1", "family_id": "f1", "candidates": [
                    {"candidate_id": "a", "cheap_kcal": 0.0},
                    {"candidate_id": "b", "cheap_kcal": 2.0}]},
                 {"molecule_id": "m2", "family_id": "f2", "candidates": [
                    {"candidate_id": "a", "cheap_kcal": 1.0},
                    {"candidate_id": "b", "cheap_kcal": 0.0}]}],
                [{"molecule_id": "m2", "references": {"a": -2.0, "b": -3.0}},
                 {"molecule_id": "m1", "references": {"a": -100.0, "b": -102.0}}])

    def test_molecule_reference_join_is_by_id_not_row_number(self):
        features, refs = self.fixture()
        loaded = self.write_and_load(features, refs)
        self.assertEqual(loaded[0]["molecule_id"], "m1")
        self.assertEqual(loaded[0]["references"]["b"], -102.0)
        self.assertEqual(loaded[1]["references"]["b"], -3.0)

    def test_reference_values_cannot_normalize_or_reorder_cheap_features(self):
        features, refs = self.fixture()
        before = self.write_and_load(features, refs)
        refs[0]["references"] = {"a": 1e12, "b": -1e12}
        after = self.write_and_load(features, refs)
        self.assertEqual([r["candidates"] for r in before], [r["candidates"] for r in after])
        self.assertEqual([r["family_id"] for r in before], [r["family_id"] for r in after])

    def test_duplicate_reference_and_feature_molecule_rows_rejected(self):
        features, refs = self.fixture()
        for f, r in [(features + [features[0]], refs), (features, refs + [refs[0]])]:
            with self.assertRaisesRegex(ValueError, "Duplicate prepared molecule"):
                self.write_and_load(f, r)

    def test_missing_molecule_and_candidate_labels_rejected(self):
        features, refs = self.fixture()
        with self.assertRaisesRegex(ValueError, "features/references mismatch"):
            self.write_and_load(features, refs[:1])
        del refs[0]["references"]["a"]
        with self.assertRaisesRegex(ValueError, "Incomplete or duplicate"):
            self.write_and_load(features, refs)

    def test_null_blank_nonfinite_and_boolean_labels_rejected(self):
        for missing in [None, "", " ", math.nan, math.inf, True]:
            features, refs = self.fixture()
            refs[0]["references"]["a"] = missing
            with self.subTest(value=missing), self.assertRaises(ValueError):
                self.write_and_load(features, refs)

    def test_duplicate_candidate_ids_rejected(self):
        features, refs = self.fixture()
        features[0]["candidates"].append(dict(features[0]["candidates"][0]))
        with self.assertRaisesRegex(ValueError, "Incomplete or duplicate"):
            self.write_and_load(features, refs)

    def test_empty_candidate_pool_rejected(self):
        features, refs = self.fixture()
        features[0]["candidates"] = []
        refs[1]["references"] = {}
        with self.assertRaises(ValueError):
            self.write_and_load(features, refs)

    def test_cheap_feature_schema_and_nonfinite_values_rejected(self):
        for value in [None, "", math.nan, math.inf, True]:
            features, refs = self.fixture()
            features[0]["candidates"][0]["cheap_kcal"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.write_and_load(features, refs)
        features, refs = self.fixture()
        features[0]["candidates"][0]["reference_kcal"] = -100.0
        with self.assertRaises(ValueError):
            self.write_and_load(features, refs)

    def test_explicit_split_required(self):
        features, refs = self.fixture()
        with self.assertRaisesRegex(ValueError, "Explicit split"):
            self.write_and_load(features, refs, split="all")


if __name__ == "__main__":
    unittest.main()
