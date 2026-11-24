"""Retrospective metrics stay scoped, sealed, and separate from paid sessions."""
import copy
import csv
import http.client
import io
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from aqc_app.data import (DataIntegrityError, DevelopmentStore, DIAGNOSTIC_FIELDS,
                          DIAGNOSTIC_ROLES, _csv, _diagnostic_rows, _fold_metadata)
from aqc_app.server import LocalHTTPServer


ROOT = Path(__file__).resolve().parents[1]


class DiagnosticDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = DevelopmentStore(ROOT)
        cls.raw_rows = _csv((ROOT / "results/lab/per_molecule.csv").read_bytes())
        cls.aggregate = _csv((ROOT / "results/lab/aggregate.csv").read_bytes())
        cls.folds = json.loads((ROOT / "results/lab/folds.json").read_text())
        cls.selected = json.loads((ROOT / "results/lab/fold_choices.json").read_text())
        cls.registry = json.loads((ROOT / "results/lab/experiment_registry.json").read_text())

    def project(self, rows, aggregates=None):
        return _diagnostic_rows(rows, self.store._pools, self.store._fold_by_molecule,
                                self.store._fold_choices, self.aggregate if aggregates is None else aggregates)

    def test_exact_scope_coverage_and_metrics_only_projection(self):
        record = self.store.public_diagnostics()
        self.assertEqual(record["scope"], "development_family_cv_retrospective")
        self.assertFalse(record["fresh_external_holdout"])
        self.assertEqual(record["counts"], {"molecules": 478, "families": 287, "candidates": 4761,
                                           "folds": 5, "rows": 2868, "roles": 6})
        self.assertEqual(record["roles"], list(DIAGNOSTIC_ROLES))
        self.assertEqual(len({(r["molecule_id"], r["policy"]) for r in record["rows"]}), 2868)
        for row in record["rows"]:
            self.assertEqual(set(row), set(DIAGNOSTIC_FIELDS))
            self.assertIs(type(row["success_1kcal"]), bool)
            self.assertIs(type(row["fallback"]), bool)
        self.assertFalse(record["provenance"]["candidate_labels_included"])
        self.assertIn("Retrospectively", record["provenance"]["case_selection"])

    def test_unknown_source_columns_and_truth_identifiers_are_never_copied(self):
        rows = copy.deepcopy(self.raw_rows)
        for row in rows:
            row["best_pool_candidate"] = "UNQUERIED_OPTIMUM_SECRET"
            row["selected_candidate"] = "UNQUERIED_SELECTION_SECRET"
            row["query_order"] = "UNQUERIED_TRACE_SECRET"
            row["trace_annotations"] = "UNQUERIED_ANNOTATION_SECRET"
            row["unqueried_references"] = {"UNQUERIED_MAP_SECRET": -12345}
            row["reference_kcal"] = -12345
        projected = json.dumps(self.project(rows))
        self.assertNotIn("UNQUERIED_", projected)
        for forbidden in ("best_pool_candidate", "selected_candidate", "query_order", "trace_annotations",
                          "reference_kcal", "unqueried_references"):
            self.assertNotIn(forbidden, projected)

    def test_changed_per_molecule_bytes_fail_startup_against_the_seal(self):
        original = Path.read_bytes
        target = ROOT / "results/lab/per_molecule.csv"
        def corrupted(path):
            raw = original(path)
            return raw + b"\n" if path == target else raw
        with patch.object(Path, "read_bytes", corrupted):
            with self.assertRaisesRegex(DataIntegrityError, "evidence differs: per_molecule.csv"):
                DevelopmentStore(ROOT)

    def test_duplicate_missing_and_unknown_pool_roles_fail(self):
        duplicate = self.raw_rows + [dict(self.raw_rows[0])]
        unknown = [dict(row) for row in self.raw_rows]
        unknown[0]["molecule_id"] = "historical_or_unknown_molecule"
        wrong_role = [dict(row) for row in self.raw_rows]
        wrong_role[0]["policy"] = "invented_role"
        for rows in (duplicate, self.raw_rows[1:], unknown, wrong_role):
            with self.subTest(rows=len(rows)):
                with self.assertRaisesRegex(DataIntegrityError, "coverage"):
                    self.project(rows)

    def test_identity_scope_and_frozen_configuration_mismatches_fail(self):
        changes = {"family_id": "different_family", "fold_id": 99, "n_candidates": 11,
                   "config_id": "fixed_k_09", "split": "evaluation",
                   "analysis_scope": "fresh_external_holdout"}
        for field, value in changes.items():
            with self.subTest(field=field):
                rows = [dict(row) for row in self.raw_rows]
                rows[0][field] = value
                with self.assertRaisesRegex(DataIntegrityError, "scope, identity, or selected"):
                    self.project(rows)

    def test_numeric_boolean_and_stop_reason_corruption_fails(self):
        changes = [("expensive_calls", True), ("expensive_calls", -1), ("expensive_calls", 1000),
                   ("regret_kcal", float("nan")), ("regret_kcal", float("inf")),
                   ("regret_kcal", -0.01), ("regret_kcal", True),
                   ("success_within_1_kcal", "True"), ("success_within_1_kcal", False),
                   ("fallback", 0), ("stop_reason", "rmsd_hidden_candidate")]
        for field, value in changes:
            with self.subTest(field=field, value=value):
                rows = [dict(row) for row in self.raw_rows]
                rows[0][field] = value
                with self.assertRaisesRegex(DataIntegrityError, "outcome or accounting"):
                    self.project(rows)

    def test_paid_diagnostic_and_full_rerank_accounting_cannot_be_confused(self):
        changes = [("adaptive", "expensive_calls", 0),
                   ("adaptive", "verified_selection", False),
                   ("adaptive", "fallback", True),
                   ("cheap_only", "expensive_calls", 1),
                   ("cheap_only", "verified_selection", True),
                   ("full_rerank", "expensive_calls", 1),
                   ("full_rerank", "regret_kcal", 0.5)]
        for role, field, value in changes:
            with self.subTest(role=role, field=field):
                rows = [dict(row) for row in self.raw_rows]
                next(row for row in rows if row["policy"] == role)[field] = value
                with self.assertRaisesRegex(DataIntegrityError, "accounting differs"):
                    self.project(rows)

    def test_projected_rows_must_reproduce_the_saved_aggregate(self):
        for field, value in (("total_calls", 0), ("success_rate", 1.0), ("n_families", 478)):
            with self.subTest(field=field):
                aggregate = copy.deepcopy(self.aggregate)
                aggregate[0][field] = value
                with self.assertRaisesRegex(DataIntegrityError, "aggregate metrics"):
                    self.project(self.raw_rows, aggregate)

    def test_family_cannot_cross_folds_or_enter_its_training_partition(self):
        folds = copy.deepcopy(self.folds)
        family = next(row["family_id"] for row in folds["assignments"]
                      if sum(other["family_id"] == row["family_id"] for other in folds["assignments"]) > 1)
        row = next(row for row in folds["assignments"] if row["family_id"] == family)
        row["fold_id"] = (row["fold_id"] + 1) % folds["n_folds"]
        with self.assertRaisesRegex(DataIntegrityError, "crosses diagnostic folds"):
            _fold_metadata(self.store._pools, folds, self.selected, self.registry)
        selected = copy.deepcopy(self.selected)
        selected["folds"][0]["training_family_ids"][0] = selected["folds"][0]["validation_family_ids"][0]
        with self.assertRaisesRegex(DataIntegrityError, "family boundaries differ"):
            _fold_metadata(self.store._pools, self.folds, selected, self.registry)

    def test_fold_choices_must_cover_roles_and_match_registered_configurations(self):
        selected = copy.deepcopy(self.selected)
        del selected["folds"][0]["choices"]["matched_simple"]
        with self.assertRaisesRegex(DataIntegrityError, "policy roles"):
            _fold_metadata(self.store._pools, self.folds, selected, self.registry)
        selected = copy.deepcopy(self.selected)
        selected["folds"][0]["choices"]["matched_simple"]["config"] = {"kind": "fixed", "k": 9}
        with self.assertRaisesRegex(DataIntegrityError, "configuration differs"):
            _fold_metadata(self.store._pools, self.folds, selected, self.registry)

    def test_matched_simple_is_exact_for_each_molecule_and_is_not_a_fixed_alias(self):
        kinds = set()
        for mid, fold in self.store._fold_by_molecule.items():
            actual = self.store.public_molecule(mid)["policy_configs"]["matched_simple"]
            expected = self.store._fold_choices[fold]["matched_simple"]["config"]
            self.assertEqual(actual, expected)
            kinds.add(actual["kind"])
            actual["kind"] = "mutated_copy"
            self.assertEqual(self.store.public_molecule(mid)["policy_configs"]["matched_simple"], expected)
        self.assertEqual(kinds, {"fixed", "adaptive"})

    def test_retrospective_cases_match_the_actual_frozen_outcomes(self):
        record = self.store.public_diagnostics()
        rows = {(row["molecule_id"], row["policy"]): row for row in record["rows"]}
        cases = {row["id"]: row["molecule_id"] for row in record["cases"]}
        rescue = rows[cases["rescue"], "sequential"]
        self.assertEqual(rescue["expensive_calls"], 3)
        self.assertTrue(rescue["success_1kcal"])
        self.assertFalse(rows[cases["rescue"], "fixed_top_k"]["success_1kcal"])
        waste = rows[cases["waste"], "sequential"]
        self.assertEqual(waste["expensive_calls"], waste["n_candidates"])
        self.assertEqual(waste["regret_kcal"], rows[cases["waste"], "fixed_top_k"]["regret_kcal"])
        self.assertFalse(rows[cases["early_stop"], "sequential"]["success_1kcal"])
        self.assertTrue(rows[cases["early_stop"], "fixed_top_k"]["success_1kcal"])
        for role in ("sequential", "fixed_top_k"):
            self.assertFalse(rows[cases["shared_failure"], role]["success_1kcal"])
        self.assertEqual(rows[cases["shared_failure"], "full_rerank"]["regret_kcal"], 0)

    def test_comparator_fallback_case_uses_the_exact_frozen_window_policy(self):
        record = self.store.public_diagnostics()
        case = next(row for row in record["cases"] if row["id"] == "comparator_fallback")
        self.assertEqual(case["molecule_id"], "omegapdb_1yc4")
        rows = {row["policy"]: row for row in record["rows"]
                if row["molecule_id"] == case["molecule_id"]}
        comparator = rows["matched_simple"]
        self.assertEqual(comparator["fold_id"], 3)
        self.assertEqual(comparator["config_id"], "adaptive_k02_gap0_cap02")
        self.assertEqual(comparator["expensive_calls"], 10)
        self.assertTrue(comparator["fallback"])
        self.assertEqual(comparator["stop_reason"], "full_rerank_fallback_crowded_at_cap")
        for role in ("fixed_top_k", "sequential"):
            self.assertEqual(rows[role]["expensive_calls"], 2)
            self.assertEqual(rows[role]["regret_kcal"], comparator["regret_kcal"])
        self.assertEqual(comparator["regret_kcal"], 0)
        config = self.store.public_molecule(case["molecule_id"])["policy_configs"]["matched_simple"]
        self.assertEqual(config, {"kind": "adaptive", "k": 2, "gap": 0.0, "cap": 2})

    def test_returned_diagnostics_cannot_mutate_the_stored_results(self):
        copy_record = self.store.public_diagnostics()
        copy_record["rows"][0]["expensive_calls"] = 999
        copy_record["cases"][0]["molecule_id"] = "mutated_copy"
        copy_record["provenance"]["candidate_labels_included"] = True
        original = self.store.public_diagnostics()
        self.assertNotEqual(original["rows"][0]["expensive_calls"], 999)
        self.assertNotEqual(original["cases"][0]["molecule_id"], "mutated_copy")
        self.assertFalse(original["provenance"]["candidate_labels_included"])


class DiagnosticHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = DevelopmentStore(ROOT)

    def setUp(self):
        self.server = LocalHTTPServer(store=self.store, port=0, quiet=True)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        connection.request("POST" if payload is not None else "GET", path,
                           body=json.dumps(payload).encode() if payload is not None else None, headers=headers)
        response = connection.getresponse()
        status, raw, response_headers = response.status, response.read(), dict(response.getheaders())
        connection.close()
        if response_headers.get("Content-Type", "").startswith("application/json"):
            return status, json.loads(raw), response_headers
        return status, raw, response_headers

    def test_json_and_csv_match_and_raw_evaluator_file_is_not_served(self):
        status, record, _ = self.request("/api/diagnostics")
        self.assertEqual(status, 200)
        status, raw, headers = self.request("/api/diagnostics.csv")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        reader = csv.DictReader(io.StringIO(raw.decode()))
        rows = list(reader)
        self.assertEqual(reader.fieldnames, list(DIAGNOSTIC_FIELDS))
        self.assertEqual(len(rows), len(record["rows"]))
        for saved, exported in zip(record["rows"], rows):
            self.assertEqual(exported, {key: str(saved[key]) for key in DIAGNOSTIC_FIELDS})
        for forbidden in ("best_pool_candidate", "selected_candidate", "reference_kcal", "query_order", "trace_annotations"):
            self.assertNotIn(forbidden, json.dumps(record))
            self.assertNotIn(forbidden.encode(), raw)
        for path in ("/api/results/per_molecule.csv", "/results/lab/per_molecule.csv",
                     "/api/diagnostics/per_molecule.csv"):
            self.assertEqual(self.request(path)[0], 404)

    def test_retrospective_reads_do_not_reveal_or_charge_active_lanes(self):
        mid = "omegacsd_GIHTUM"
        configs = self.store.public_molecule(mid)["policy_configs"]
        lanes = []
        for role in ("sequential", "matched_simple"):
            status, state, _ = self.request("/api/sessions", {"molecule_id": mid, "config": configs[role]})
            self.assertEqual(status, 201)
            lanes.append(state)
        self.assertEqual(self.request("/api/diagnostics")[0], 200)
        self.assertEqual(self.request("/api/diagnostics.csv")[0], 200)
        for lane in lanes:
            _, current, _ = self.request("/api/sessions/" + lane["session_id"])
            self.assertEqual(current["observations"], {})
            self.assertEqual(current["expensive_calls"], 0)
            self.assertIsNone(current["evaluation"])
        _, first, _ = self.request("/api/sessions/" + lanes[0]["session_id"] + "/step", {})
        _, second, _ = self.request("/api/sessions/" + lanes[1]["session_id"])
        self.assertEqual(first["expensive_calls"], 1)
        self.assertEqual(second["observations"], {})
        _, second, _ = self.request("/api/sessions/" + lanes[1]["session_id"] + "/step", {})
        self.assertEqual(second["expensive_calls"], 1)
        self.assertEqual(set(first["observations"]), set(second["observations"]))
        self.assertEqual(first["expensive_calls"] + second["expensive_calls"], 2)


if __name__ == "__main__":
    unittest.main()
