#!/usr/bin/env python3
"""Extract a pinned initial-geometry subset using only composition eligibility.

No reference energies or final structures are read by this preparation step.
Near-duplicate candidates are a conservative diagnostic, not proof of equivalence.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import itertools
import json
import math
from pathlib import Path
import urllib.request

import numpy as np

URL = "https://ndownloader.figshare.com/files/53161835"
EXPECTED_MD5 = "b809f101dd42a745ec2baabe7eb16f11"
EXPECTED_SHA256 = "98d545172c1ea9060f03f40cace6f8173a4ac06f1ee875ccd963765211519b58"
VALENCES = {"Li": 1, "Na": 1, "K": 1, "Rb": 1, "Cs": 1,
            "Mg": 2, "Ca": 2, "Sr": 2, "Ba": 2,
            "Al": 3, "Ga": 3, "Sc": 3, "Y": 3, "B": 3,
            "Si": 4, "Ge": 4, "Sn": 4, "Ti": 4, "Zr": 4, "Hf": 4, "O": -2}
ATOMIC_NUMBERS = {"Li": 3, "Na": 11, "K": 19, "Rb": 37, "Cs": 55,
                  "Mg": 12, "Ca": 20, "Sr": 38, "Ba": 56,
                  "Al": 13, "Ga": 31, "Sc": 21, "Y": 39, "B": 5,
                  "Si": 14, "Ge": 32, "Sn": 50, "Ti": 22, "Zr": 40, "Hf": 72, "O": 8}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def reduced_formula(counts: dict[str, int]) -> str:
    divisor = math.gcd(*counts.values())
    return "".join(f"{element}{counts[element] // divisor}" for element in sorted(counts))


def eligible(counts: dict[str, int]) -> bool:
    return ("O" in counts and len(counts) > 1 and set(counts) <= set(VALENCES)
            and sum(VALENCES[e] * n for e, n in counts.items()) == 0)


def pair_spectrum(record: dict, radius: int = 2) -> dict[str, np.ndarray]:
    """Species-labelled periodic pair-distance spectrum for conservative screening.

    The fixed image search is documented; it is not a crystallographic matcher.
    A pair is only compared between equal atom counts and nearly equal volumes.
    """
    frac = np.asarray(record["fractional_positions"], dtype=float) % 1.0
    cell = np.asarray(record["lattice_angstrom"], dtype=float)
    images = np.asarray(list(itertools.product(range(-radius, radius + 1), repeat=3)))
    distances = defaultdict(list)
    for i in range(len(frac)):
        for j in range(i):
            key = "-".join(sorted((record["symbols"][i], record["symbols"][j])))
            displacements = (frac[i] - frac[j] + images) @ cell
            distance = float(np.sqrt(np.min(np.sum(displacements ** 2, axis=1))))
            distances[key].append(distance)
    return {key: np.sort(values) for key, values in distances.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("data/decision_engine/initial_geometries.json.gz"))
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    if not args.archive.exists():
        if not args.download:
            parser.error("Archive is absent; pass --download to retrieve the public pinned file")
        args.archive.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.archive.with_suffix(args.archive.suffix + ".partial")
        with urllib.request.urlopen(URL, timeout=60) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        temporary.replace(args.archive)
    raw = args.archive.read_bytes()
    if hashlib.md5(raw).hexdigest() != EXPECTED_MD5 or digest(raw) != EXPECTED_SHA256:
        raise ValueError("Initial geometry archive checksum mismatch")

    records, invalid = [], []
    source_count = 0
    with gzip.open(args.archive, "rt", encoding="utf-8") as source:
        for line in source:
            source_count += 1
            original = json.loads(line)
            structure = original["initial_structure"]
            symbols = []
            disordered = False
            for site in structure["sites"]:
                species = site["species"]
                if len(species) != 1 or abs(species[0]["occu"] - 1.0) > 1e-12:
                    disordered = True
                    break
                symbols.append(species[0]["element"])
            if disordered:
                invalid.append({"material_id": original["material_id"], "reason": "partial_or_disordered_occupancy"})
                continue
            counts = Counter(symbols)
            if not eligible(counts):
                continue
            cell = np.asarray(structure["lattice"]["matrix"], dtype=float)
            frac = np.asarray([site["abc"] for site in structure["sites"]], dtype=float)
            xyz = np.asarray([site["xyz"] for site in structure["sites"]], dtype=float)
            errors = []
            if not np.isfinite(cell).all() or not np.isfinite(frac).all() or not np.isfinite(xyz).all():
                errors.append("nonfinite_geometry")
            volume = float(abs(np.linalg.det(cell)))
            if volume <= 1e-6:
                errors.append("degenerate_cell")
            if not np.allclose(frac @ cell, xyz, atol=2e-7, rtol=1e-8):
                errors.append("fractional_cartesian_mismatch")
            canonical = {"cell": np.round(cell, 8).tolist(),
                         "sites": sorted([[symbol, *np.round(position % 1.0, 8).tolist()]
                                          for symbol, position in zip(symbols, frac)])}
            record = {"material_id": original["material_id"],
                      "composition_key": reduced_formula(counts),
                      "chemical_system": "-".join(sorted(counts)),
                      "composition_counts": dict(sorted(counts.items())),
                      "n_atoms": len(symbols), "symbols": symbols,
                      "atomic_numbers": [ATOMIC_NUMBERS[symbol] for symbol in symbols],
                      "positions_angstrom": xyz.tolist(), "fractional_positions": frac.tolist(),
                      "lattice_angstrom": cell.tolist(), "pbc": [True, True, True],
                      "volume_angstrom3": volume,
                      "charge": structure.get("charge"),
                      "charge_status": "source_null" if structure.get("charge") is None else "source_declared",
                      "initial_structure": structure,
                      "source_record_sha256": digest(json_bytes(original)),
                      "canonical_geometry_sha256": digest(json_bytes(canonical)),
                      "geometry_valid": not errors, "failure_reasons": errors}
            if errors:
                invalid.append({"material_id": original["material_id"], "reason": errors})
            records.append(record)
    records.sort(key=lambda item: item["material_id"])
    groups = defaultdict(list)
    hashes = defaultdict(list)
    for record in records:
        groups[record["composition_key"]].append(record)
        hashes[record["canonical_geometry_sha256"]].append(record["material_id"])
    exact = [values for values in hashes.values() if len(values) > 1]
    spectra = {}
    near = []
    for group in groups.values():
        for left, right in itertools.combinations(group, 2):
            if left["n_atoms"] != right["n_atoms"]:
                continue
            rel_volume = abs(left["volume_angstrom3"] - right["volume_angstrom3"]) / max(left["volume_angstrom3"], right["volume_angstrom3"])
            if rel_volume > 0.001:
                continue
            for item in (left, right):
                spectra.setdefault(item["material_id"], pair_spectrum(item))
            a, b = spectra[left["material_id"]], spectra[right["material_id"]]
            if a.keys() != b.keys() or any(a[key].shape != b[key].shape for key in a):
                continue
            distances = np.concatenate([a[key] - b[key] for key in sorted(a)])
            rms = float(np.sqrt(np.mean(distances ** 2)))
            max_error = float(np.max(np.abs(distances)))
            if rms <= 0.01 and max_error <= 0.03:
                near.append({"left": left["material_id"], "right": right["material_id"],
                             "composition_key": left["composition_key"],
                             "pair_spectrum_rms_angstrom": rms,
                             "pair_spectrum_max_abs_angstrom": max_error,
                             "relative_volume_difference": rel_volume})
    payload = {"schema_version": "erkidu.initial-geometries.v1",
               "evidence_kind": "replay_input_geometry",
               "geometry_stage": "before_DFT_relaxation",
               "source_url": URL, "source_md5": EXPECTED_MD5, "source_sha256": EXPECTED_SHA256,
               "selection": {"type": "prequery_formal_oxide_charge", "valences": VALENCES},
               "structures": records}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("wb") as raw_output:
        with gzip.GzipFile(filename="", fileobj=raw_output, mode="wb", mtime=0) as output:
            output.write(json_bytes(payload))
    manifest = {"schema_version": "erkidu.initial-geometry-audit.v1", "source_url": URL,
                "source_md5": EXPECTED_MD5, "source_sha256": EXPECTED_SHA256,
                "source_size_bytes": len(raw), "source_rows": source_count,
                "selection_uses_reference_labels": False, "eligible_rows": len(records),
                "eligible_compositions": len(groups), "invalid_records": invalid,
                "exact_duplicate_groups": exact, "near_duplicate_candidate_pairs": near,
                "near_duplicate_method": "Species-pair periodic distance spectra; equal atom counts; relative volume<=0.001; RMS<=0.01A,max<=0.03A; images[-2,2]^3; screening diagnostic, not crystallographic identity proof",
                "near_duplicate_policy": "Keep every same-composition candidate in one split; audit pair co-membership before execution",
                "output_sha256": digest(args.out.read_bytes())}
    audit_path = args.out.with_name("initial_geometry_audit.json")
    audit_path.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"geometry_file": str(args.out), "audit_file": str(audit_path),
                      "eligible": len(records), "invalid": len(invalid),
                      "exact_duplicate_groups": len(exact), "near_duplicate_candidate_pairs": len(near)}))


if __name__ == "__main__":
    main()
