#!/usr/bin/env python3
"""Inspect retained initial geometry and known near-duplicate split membership."""
from collections import Counter, defaultdict
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]

def check(ok, message):
    if not ok:
        raise ValueError(message)

def run(prepared):
    data = ROOT / "data/decision_engine"
    path = data / "initial_geometries.json.gz"
    expected = json.loads((data / "initial_geometry_audit.json").read_text())
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    check(actual_hash == expected["output_sha256"], "geometry artifact digest mismatch")
    payload = json.load(gzip.open(path, "rt"))
    check(payload["geometry_stage"] == "before_DFT_relaxation", "wrong geometry stage")
    geometries = {g["material_id"]: g for g in payload["structures"]}
    check(len(geometries) == len(payload["structures"]), "duplicate geometry IDs")
    pools = json.loads((prepared / "pools.json").read_text())
    public = {c["candidate_id"]: (p, c) for p in pools for c in p["candidates"]}
    hashes = defaultdict(list)
    for cid, (pool, c) in public.items():
        check(cid in geometries, "missing initial geometry")
        g = geometries[cid]
        check(g["geometry_valid"] and not g["failure_reasons"], "invalid source geometry retained")
        check(g["chemical_system"] == pool["group_id"], "geometry system differs from metadata")
        check(g["composition_key"] == pool["composition"], "geometry composition differs from pool")
        check(dict(sorted(Counter(g["symbols"]).items())) == g["composition_counts"], "atom-count composition mismatch")
        check(g["n_atoms"] == len(g["symbols"]) == len(g["atomic_numbers"]), "atom count mismatch")
        check(g["pbc"] == [True, True, True], "unexpected nonperiodic structure")
        lattice = np.asarray(g["lattice_angstrom"], dtype=float)
        frac = np.asarray(g["fractional_positions"], dtype=float)
        xyz = np.asarray(g["positions_angstrom"], dtype=float)
        check(lattice.shape == (3, 3) and frac.shape == xyz.shape == (g["n_atoms"], 3), "geometry array shape mismatch")
        check(np.isfinite(lattice).all() and np.isfinite(frac).all() and np.isfinite(xyz).all(), "nonfinite geometry")
        volume = abs(float(np.linalg.det(lattice)))
        check(volume > 0 and math.isclose(volume, g["volume_angstrom3"], abs_tol=1e-6, rel_tol=1e-8), "cell volume mismatch")
        check(np.allclose(frac @ lattice, xyz, atol=1e-7, rtol=0), "fractional-to-Cartesian inconsistency")
        hashes[g["canonical_geometry_sha256"]].append(cid)
    retained_exact = [v for v in hashes.values() if len(v) > 1]
    for ids in retained_exact:
        check(len({public[cid][0]["split"] for cid in ids}) == 1, "exact geometry crosses splits")
    pairs = []
    for pair in expected["near_duplicate_candidate_pairs"]:
        row = dict(pair)
        row["membership"] = {cid: {"retained": cid in public,
                            "split": public[cid][0]["split"] if cid in public else None}
                             for cid in (pair["left"], pair["right"])}
        present = [cid for cid in row["membership"] if cid in public]
        check(len({public[cid][0]["split"] for cid in present}) <= 1, "known near duplicate crosses splits")
        pairs.append(row)
    return {
        "schema": "erkidu-independent-geometry-split-audit/v1",
        "status": "passed", "evidence_class": "executed_inspection",
        "geometry_sha256": actual_hash, "retained_structures_checked": len(public),
        "all_retained_geometries_initial_before_DFT": True,
        "retained_exact_duplicate_groups": retained_exact,
        "known_near_pairs_checked": pairs, "cross_split_exact_or_known_near_pairs": 0,
        "near_pair_method": expected["near_duplicate_method"],
        "limits": ["Recorded pair-spectrum screen is not a proof of crystallographic identity or exhaustive near-duplicate detection",
                  "Shared abstract prototypes across distinct compositions remain a source of correlation",
                  "Source charge is not verified charge/spin metadata; formal oxide screening is not an independent electronic-structure audit",
                  "No model relaxation or reference calculation was executed"],
    }

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if args.out.exists():
        raise SystemExit("Refusing to overwrite audit")
    result = run(args.prepared)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "retained_structures_checked", "cross_split_exact_or_known_near_pairs")}))

if __name__ == "__main__":
    main()
