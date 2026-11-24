"""Geometry display has its own identity and corruption checks."""
import hashlib
from pathlib import Path
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_viewer_geometry import parse_verified_xyz
from aqc.data import digest


class ViewerGeometryTests(unittest.TestCase):
    def test_coordinates_preserve_order_units_and_identity(self):
        raw = b"2\nverified fixture\nC 0.0 1.25 -2.0\nH 0.0 1.25 -0.9\n"
        expected = {"elements_in_order": ["C", "H"], "xyz_angstrom": [[0.0, 1.25, -2.0], [0.0, 1.25, -.9]]}
        symbols, coordinates = parse_verified_xyz(raw, hashlib.sha256(raw).hexdigest(), digest(expected))
        self.assertEqual(symbols, expected["elements_in_order"])
        self.assertEqual(coordinates, expected["xyz_angstrom"])

    def test_modified_xyz_and_unmatched_geometry_fail_closed(self):
        raw = b"1\nfixture\nC 0 0 0\n"
        expected = digest({"elements_in_order": ["C"], "xyz_angstrom": [[0.0, 0.0, 0.0]]})
        with self.assertRaisesRegex(ValueError, "pinned source"):
            parse_verified_xyz(raw + b"\n", hashlib.sha256(raw).hexdigest(), expected)
        with self.assertRaisesRegex(ValueError, "original audit"):
            parse_verified_xyz(raw, hashlib.sha256(raw).hexdigest(), "0" * 64)

    def test_nonfinite_coordinates_and_extra_records_are_rejected(self):
        for raw in (b"1\nfixture\nC nan 0 0\n", b"1\nfixture\nC 0 0 0\nH 1 0 0\n"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    parse_verified_xyz(raw, hashlib.sha256(raw).hexdigest(), "0" * 64)


if __name__ == "__main__":
    unittest.main()
