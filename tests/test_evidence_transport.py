"""Lossless repository transport must preserve the scientific seal's bytes."""
from pathlib import Path
import hashlib
import json
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from archive_evidence import DEFAULT_PART_BYTES, pack, restore

ROOT = Path(__file__).resolve().parents[1]
CURRENT_MANIFEST = ROOT / "data/evidence_chunks/lab-ledger/manifest.json"


class EvidenceTransportTests(unittest.TestCase):
    def test_default_parts_fit_the_bounded_base64_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target, folder = root / "evidence.gz", root / "parts"
            with target.open("wb") as stream:
                stream.write(b"a" * DEFAULT_PART_BYTES)
                stream.write(b"tail")
            manifest = pack(target, folder, root)
            self.assertEqual([part["size_bytes"] for part in manifest["parts"]], [10 * 1024 * 1024, 4])
            self.assertTrue(all(4 * ((part["size_bytes"] + 2) // 3) < 16 * 1024 * 1024 for part in manifest["parts"]))

    def test_round_trip_and_idempotence_preserve_exact_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target, folder = root / "evidence.gz", root / "parts"
            original = bytes(range(256)) * 7
            target.write_bytes(original)
            manifest = pack(target, folder, root, part_bytes=113)
            self.assertGreater(len(manifest["parts"]), 1)
            self.assertEqual(restore(folder / "manifest.json", root)["status"], "already_verified")
            target.unlink()
            self.assertEqual(restore(folder / "manifest.json", root)["status"], "restored_verified")
            self.assertEqual(target.read_bytes(), original)

    def test_corrupt_chunk_and_conflicting_existing_file_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target, folder = root / "evidence.gz", root / "parts"
            target.write_bytes(b"ordered paid queries")
            manifest = pack(target, folder, root, part_bytes=6)
            target.write_bytes(b"unrelated")
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                restore(folder / "manifest.json", root)
            target.unlink()
            (root / manifest["parts"][0]["path"]).write_bytes(b"broken")
            with self.assertRaisesRegex(ValueError, "part differs"):
                restore(folder / "manifest.json", root)
            self.assertFalse(target.exists())
            self.assertFalse(target.with_name(target.name + ".restoring").exists())

    @unittest.skipUnless(CURRENT_MANIFEST.exists(), "Bundled transport manifest required")
    def test_bundled_eight_part_transport_restores_the_sealed_ledger(self):
        manifest = json.loads(CURRENT_MANIFEST.read_text())
        seal = json.loads((ROOT / "results/lab/evaluation_seal.json").read_text())
        self.assertEqual(manifest["target_size_bytes"], 75200465)
        self.assertEqual(manifest["target_sha256"], seal["artifact_sha256"]["decision_ledger.jsonl.gz"])
        self.assertEqual(len(manifest["parts"]), 8)
        self.assertEqual([part["size_bytes"] for part in manifest["parts"]], [10485760] * 7 + [1800145])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for part in manifest["parts"]:
                destination = root / part["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / part["path"], destination)
            copied_manifest = root / CURRENT_MANIFEST.relative_to(ROOT)
            copied_manifest.write_bytes(CURRENT_MANIFEST.read_bytes())
            result = restore(copied_manifest, root)
            restored = root / manifest["target_path"]
            self.assertEqual(result["status"], "restored_verified")
            self.assertEqual(result["sha256"], manifest["target_sha256"])
            self.assertEqual(restored.stat().st_size, manifest["target_size_bytes"])
            self.assertEqual(restore(copied_manifest, root)["status"], "already_verified")

    @unittest.skipUnless((ROOT / "releases/v0.2.0/transport-original.json").exists(), "Preserved v0.2 transport manifest required")
    def test_original_four_part_checksums_remain_recoverable_from_same_ledger(self):
        original = json.loads((ROOT / "releases/v0.2.0/transport-original.json").read_text())
        current = json.loads(CURRENT_MANIFEST.read_text())
        self.assertEqual(len(original["parts"]), 4)
        self.assertEqual(original["target_sha256"], current["target_sha256"])
        self.assertEqual(original["target_size_bytes"], current["target_size_bytes"])
        ledger = ROOT / current["target_path"]
        if not ledger.exists():
            self.skipTest("Restore the ledger to verify historical chunk boundaries")
        with ledger.open("rb") as stream:
            for part in original["parts"]:
                content = stream.read(part["size_bytes"])
                self.assertEqual(len(content), part["size_bytes"])
                self.assertEqual(hashlib.sha256(content).hexdigest(), part["sha256"])
            self.assertEqual(stream.read(1), b"")


if __name__ == "__main__":
    unittest.main()
