"""Lossless repository transport must preserve the scientific seal's bytes."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from archive_evidence import pack, restore


class EvidenceTransportTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
