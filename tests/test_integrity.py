"""Real evidence-corruption regressions and portable serialization checks."""
import csv
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from aqc.data import gzip_text_writer, write_json
from aqc.dashboard import build_dashboard
from aqc.integrity import verify_artifact_seal, write_artifact_seal

FIXTURE = Path(__file__).resolve().parents[1] / "results" / "fixture"


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="aqc-integrity-")
        self.root = Path(self.tmp.name) / "results"
        shutil.copytree(FIXTURE, self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def reseal(self):
        original = json.loads((self.root / "evaluation_seal.json").read_text())
        return write_artifact_seal(self.root, config_sha256=original["config_sha256"],
                                   split_sha256=original["split_sha256"])

    def mutate_csv(self, name, field, value):
        path = self.root / name
        with path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        rows[0][field] = value
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def test_historical_seal_verified_with_scope_warning(self):
        result = verify_artifact_seal(self.root)
        self.assertTrue(result["verified"])
        self.assertEqual(result["seal_schema_version"], 1)
        self.assertGreater(result["primary_rows_verified"], 0)
        self.assertTrue(result["warnings"])

    def test_changed_aggregate_is_rejected_by_dashboard(self):
        self.mutate_csv("aggregate.csv", "success_rate", "0.123456")
        with self.assertRaisesRegex(ValueError, "Sealed artifact changed"):
            build_dashboard(self.root)

    def test_missing_seal_cannot_be_called_verified(self):
        (self.root / "evaluation_seal.json").unlink()
        with self.assertRaisesRegex(ValueError, "missing evidence"):
            build_dashboard(self.root)

    def test_explicit_preview_cannot_bypass_bad_existing_seal(self):
        self.mutate_csv("aggregate.csv", "mean_calls", "999")
        with self.assertRaisesRegex(ValueError, "Sealed artifact changed"):
            build_dashboard(self.root, allow_incomplete=True)

    def test_rehashing_wrong_aggregate_does_not_bypass_consistency(self):
        self.mutate_csv("aggregate.csv", "success_rate", "0.123456")
        with self.assertRaisesRegex(ValueError, "Evidence inconsistency"):
            self.reseal()

    def test_mixed_query_trace_rejected_even_after_hash_update(self):
        path = self.root / "traces.jsonl"
        traces = [json.loads(line) for line in path.read_text().splitlines()]
        paid = next(x for x in traces if x["result"]["expensive_calls"])
        paid["result"]["queries"][0]["charged"] = 0
        path.write_text("\n".join(json.dumps(x) for x in traces) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Evidence inconsistency"):
            self.reseal()

    def test_modified_frozen_config_rejected_even_when_primary_results_match(self):
        path = self.root / "frozen_config.json"
        value = json.loads(path.read_text())
        value["policies"]["adaptive"]["gap"] += 1
        write_json(path, value)
        with self.assertRaisesRegex(ValueError, "Frozen configuration"):
            verify_artifact_seal(self.root)

    def test_unsafe_seal_path_rejected(self):
        path = self.root / "evaluation_seal.json"
        value = json.loads(path.read_text())
        value["artifact_sha256"]["../outside"] = "0" * 64
        write_json(path, value)
        with self.assertRaisesRegex(ValueError, "Unsafe artifact path"):
            verify_artifact_seal(self.root)

    def test_complete_seal_covers_supplementary_evidence(self):
        self.reseal()
        result = verify_artifact_seal(self.root, require_complete=True)
        self.assertEqual(result["seal_schema_version"], 2)
        self.assertEqual(result["unsealed_files"], [])
        self.assertIn("development_frontier.csv", result["sealed_files"])

    def test_complete_seal_rejects_new_unsealed_evidence(self):
        self.reseal()
        (self.root / "another_run.csv").write_text("accidental,mixed,run\n")
        with self.assertRaisesRegex(ValueError, "files are unsealed"):
            verify_artifact_seal(self.root, require_complete=True)

    def test_changed_decision_rejected_after_rehash(self):
        path = self.root / "decision.json"
        value = json.loads(path.read_text())
        value["relative_call_savings"] = .99
        write_json(path, value)
        with self.assertRaisesRegex(ValueError, "decision.relative_call_savings"):
            self.reseal()

    def test_rehashed_false_target_flags_are_rejected(self):
        path = self.root / "decision.json"
        original = json.loads(path.read_text())
        flags = ("observed_95pct_success_met", "frozen_comparator_95pct_success_met",
                 "target_risk_comparison_available", "observed_risk_no_worse_than_frozen_comparator",
                 "observed_30pct_call_savings_met", "observed_joint_target_met", "bootstrap_joint_evidence")
        for flag in flags:
            with self.subTest(flag=flag):
                changed = dict(original)
                changed[flag] = not original[flag]
                write_json(path, changed)
                with self.assertRaisesRegex(ValueError, f"decision.{flag}"):
                    self.reseal()

    def test_rehashed_embedded_pair_disagreement_is_rejected(self):
        path = self.root / "decision.json"
        value = json.loads(path.read_text())
        value["paired_difference"]["relative_call_savings_ci_low"] = .42
        write_json(path, value)
        with self.assertRaisesRegex(ValueError, "decision.paired_difference"):
            self.reseal()

    def test_unknown_primary_policy_cannot_skip_consistency_checks(self):
        path = self.root / "decision.json"
        value = json.loads(path.read_text())
        value["primary_policy"] = "unobserved_policy"
        write_json(path, value)
        with self.assertRaisesRegex(ValueError, "observed paid"):
            self.reseal()


class SerializationTests(unittest.TestCase):
    def test_json_is_utf8_and_lf_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.json"
            write_json(path, {"unit": "Å", "calls": 1})
            raw = path.read_bytes()
            self.assertNotIn(b"\r", raw)
            self.assertTrue(raw.endswith(b"\n"))
            self.assertEqual(json.loads(raw), {"unit": "Å", "calls": 1})

    def test_compressed_logs_independent_of_filename_and_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a.gz", Path(tmp) / "b.gz"
            for path in (a, b):
                with gzip_text_writer(path) as stream:
                    stream.write('{"query":"a","charged":1}\n')
            self.assertEqual(a.read_bytes(), b.read_bytes())
            self.assertEqual(a.read_bytes()[4:8], b"\0\0\0\0")
            self.assertNotIn(b"\r", gzip.decompress(a.read_bytes()))


if __name__ == "__main__":
    unittest.main()
