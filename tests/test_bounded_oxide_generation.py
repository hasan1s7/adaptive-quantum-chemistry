from copy import deepcopy
import unittest

import numpy as np

from tools.bounded_oxide_generation import geometry_hash, near_match, propose, validate_geometry


def record():
    frac = [[.1, .1, .1], [.4, .4, .4], [.8, .8, .8]]
    return {"symbols": ["Si", "O", "O"], "pbc": [True, True, True],
            "lattice_angstrom": [[5., 0., 0.], [0., 5., 0.], [0., 0., 5.]],
            "fractional_positions": frac, "positions_angstrom": (np.asarray(frac) * 5).tolist()}


class BoundedGeometryTests(unittest.TestCase):
    def test_invalid_composition_cell_and_contacts_rejected(self):
        good = record()
        self.assertTrue(validate_geometry(good, {"Si": 1, "O": 2})["geometry_valid"])
        for fault in ("cell", "contact", "composition"):
            bad = deepcopy(good)
            if fault == "cell":
                bad["lattice_angstrom"][0] = [0., 0., 0.]
            elif fault == "contact":
                bad["fractional_positions"][1] = bad["fractional_positions"][0]
            else:
                bad["symbols"][0] = "O"
            with self.subTest(fault=fault):
                self.assertFalse(validate_geometry(bad, {"Si": 1, "O": 2})["geometry_valid"])

    def test_seeded_proposals_repeat_and_near_screen_handles_translation(self):
        first, p1 = propose(record(), np.random.default_rng(20261127))
        second, p2 = propose(record(), np.random.default_rng(20261127))
        self.assertEqual(geometry_hash(first), geometry_hash(second))
        self.assertEqual(p1, p2)
        self.assertNotEqual(geometry_hash(first), geometry_hash(record()))
        shifted = record()
        shifted["fractional_positions"] = ((np.asarray(shifted["fractional_positions"]) + .2) % 1).tolist()
        self.assertIsNotNone(near_match(record(), shifted))


if __name__ == "__main__":
    unittest.main()
