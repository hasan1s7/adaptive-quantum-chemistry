#!/usr/bin/env python3
"""A bounded geometry-only SiO2 proposal/validation prototype.

No energy model, MLIP relaxation, DFT, or force field is evaluated. The paired
baseline validates the same number of unchanged published initial structures.
Different generated coordinates do not establish a new basin or new material.
"""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
import gzip
import hashlib
import itertools
import json
import math
from pathlib import Path
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261127
LIMIT = 12
CONTACT_FLOOR_ANGSTROM = .9
IMAGES = np.asarray(list(itertools.product(range(-2, 3), repeat=3)), dtype=float)

def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

def sha(value):
    return hashlib.sha256(value).hexdigest()

def geometry_hash(record):
    cell = np.asarray(record["lattice_angstrom"], dtype=float)
    frac = np.asarray(record["fractional_positions"], dtype=float)
    return sha(encode({"cell": np.round(cell, 8).tolist(),
                      "sites": sorted([[symbol, *np.round(position % 1, 8).tolist()]
                                       for symbol, position in zip(record["symbols"], frac)])}))

def validate_geometry(record, expected_counts):
    errors = []
    symbols = record.get("symbols", [])
    cell = np.asarray(record.get("lattice_angstrom", []), dtype=float)
    frac = np.asarray(record.get("fractional_positions", []), dtype=float)
    if dict(Counter(symbols)) != dict(expected_counts):
        errors.append("composition_changed")
    if record.get("pbc") != [True, True, True]:
        errors.append("nonperiodic_or_unknown_boundary")
    if cell.shape != (3, 3) or frac.shape != (len(symbols), 3) or not symbols:
        return {"geometry_valid": False, "failure_reasons": errors + ["invalid_array_shape"],
                "volume_angstrom3": None, "minimum_periodic_distance_angstrom": None}
    if not np.isfinite(cell).all() or not np.isfinite(frac).all():
        return {"geometry_valid": False, "failure_reasons": errors + ["nonfinite_geometry"],
                "volume_angstrom3": None, "minimum_periodic_distance_angstrom": None}
    volume = float(np.linalg.det(cell))
    if volume <= 1e-6:
        errors.append("nonpositive_or_degenerate_cell")
    nonzero_images = IMAGES[np.any(IMAGES != 0, axis=1)]
    minimum = float(np.linalg.norm(nonzero_images @ cell, axis=1).min())
    for i in range(len(frac)):
        for j in range(i):
            distances = np.linalg.norm(((frac[i] - frac[j]) % 1 + IMAGES) @ cell, axis=1)
            minimum = min(minimum, float(distances.min()))
    if minimum < CONTACT_FLOOR_ANGSTROM:
        errors.append("periodic_close_contact_below_engineering_screen")
    return {"geometry_valid": not errors, "failure_reasons": errors,
            "volume_angstrom3": volume, "minimum_periodic_distance_angstrom": minimum}

def pair_spectrum(record):
    cell = np.asarray(record["lattice_angstrom"], dtype=float)
    frac = np.asarray(record["fractional_positions"], dtype=float) % 1
    output = {}
    for i in range(len(frac)):
        for j in range(i):
            kind = "-".join(sorted([record["symbols"][i], record["symbols"][j]]))
            distances = np.linalg.norm((frac[i] - frac[j] + IMAGES) @ cell, axis=1)
            output.setdefault(kind, []).append(float(distances.min()))
    return {key: np.sort(values) for key, values in output.items()}

def near_match(a, b):
    if Counter(a["symbols"]) != Counter(b["symbols"]):
        return None
    va, vb = (abs(float(np.linalg.det(np.asarray(x["lattice_angstrom"])))) for x in (a, b))
    relative_volume = abs(va - vb) / max(va, vb)
    if relative_volume > .001:
        return None
    sa, sb = pair_spectrum(a), pair_spectrum(b)
    if sa.keys() != sb.keys():
        return None
    delta = np.concatenate([sa[k] - sb[k] for k in sorted(sa)])
    rms, largest = float(np.sqrt(np.mean(delta ** 2))), float(np.max(abs(delta)))
    if rms > .01 or largest > .03:
        return None
    return {"relative_volume_difference": relative_volume,
            "pair_spectrum_rms_angstrom": rms, "pair_spectrum_max_abs_angstrom": largest}

def propose(parent, rng):
    # Symmetric small strain has bounded entries, not a statement about relaxed strain.
    raw = rng.uniform(-.002, .002, size=(3, 3))
    strain = (raw + raw.T) / 2
    jitter = rng.uniform(-.002, .002, size=(len(parent["symbols"]), 3))
    cell = np.asarray(parent["lattice_angstrom"], dtype=float) @ (np.eye(3) + strain)
    frac = (np.asarray(parent["fractional_positions"], dtype=float) + jitter) % 1
    result = {"symbols": list(parent["symbols"]), "pbc": [True, True, True],
              "lattice_angstrom": cell.tolist(), "fractional_positions": frac.tolist(),
              "positions_angstrom": (frac @ cell).tolist()}
    return result, {"symmetric_strain_matrix": strain.tolist(), "fractional_jitter": jitter.tolist(),
                    "maximum_entry_strain": .002, "maximum_fractional_jitter": .002}

def run(source, out, seed=SEED, cap=5):
    if out.exists():
        raise FileExistsError("refusing to overwrite a geometry-generation run")
    if not 1 <= cap <= LIMIT:
        raise ValueError("proposal cap must be from1 through12")
    total_wall, total_cpu = time.perf_counter(), time.process_time()
    source_bytes = source.read_bytes()
    payload = json.loads(gzip.decompress(source_bytes))
    if payload.get("geometry_stage") != "before_DFT_relaxation":
        raise ValueError("requires documented initial structures")
    parents = sorted([g for g in payload["structures"]
                      if g["composition_key"] == "O2Si1" and g["geometry_valid"]],
                     key=lambda g: g["material_id"])
    if not parents:
        raise ValueError("no permitted initial SiO2 structures")
    count = min(cap, len(parents))
    out.mkdir(parents=True)
    manifest = {
        "schema": "erkidu-bounded-oxide-generation/v1", "evidence_class": "executed_geometry_only_prototype",
        "seed": seed, "requested_cap": cap, "maximum_cap": LIMIT,
        "actual_proposals": count, "matched_baseline_geometry_attempts": count,
        "source_path": str(source), "source_sha256": sha(source_bytes),
        "upstream_source_url": payload["source_url"], "upstream_source_sha256": payload["source_sha256"],
        "code_sha256": sha(Path(__file__).read_bytes()), "composition": "SiO2",
        "source_selection": "first lexicographic IDs among geometry-valid initial SiO2 inputs; no energies read",
        "parent_ids": [g["material_id"] for g in parents[:count]],
        "available_same_composition_reference_set_size": len(parents),
        "proposal_method": "one seeded symmetric cell strain and independent fractional jitter per parent",
        "maximum_entry_strain": .002, "maximum_fractional_jitter": .002,
        "close_contact_floor_angstrom": CONTACT_FLOOR_ANGSTROM,
        "near_duplicate_rule": {"images_per_axis": [-2, -1, 0, 1, 2],
                                "relative_volume_max": .001, "spectrum_rms_max_angstrom": .01,
                                "spectrum_max_abs_angstrom": .03},
        "mlip_relaxation_budget_executed": 0, "dft_budget_executed": 0,
        "physical_improvement_comparison": "unsupported: no energy or relaxation model evaluated",
        "cost_matching_scope": "same number of geometry-validation attempts only; generation overhead measured separately",
        "novelty_scope": "exact and screened near duplicates relative only to available SiO2 initial inputs; no basin or materials novelty claim",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    rng = np.random.default_rng(seed)
    records, timings = [], []
    for arm in ["non_generative_inputs", "bounded_proposals"]:
        prior = []
        for index, parent in enumerate(parents[:count]):
            wall, cpu = time.perf_counter(), time.process_time()
            if arm == "bounded_proposals":
                geom, parameters = propose(parent, rng)
            else:
                geom = {k: deepcopy(parent[k]) for k in ["symbols", "pbc", "lattice_angstrom",
                                                        "fractional_positions", "positions_angstrom"]}
                parameters = {"unchanged_published_initial_geometry": True}
            generation_wall, generation_cpu = time.perf_counter() - wall, time.process_time() - cpu
            wall, cpu = time.perf_counter(), time.process_time()
            validation = validate_geometry(geom, parent["composition_counts"])
            digest = geometry_hash(geom) if validation["geometry_valid"] else None
            matches = []
            if validation["geometry_valid"]:
                for ref in parents:
                    kind = "exact" if digest == ref["canonical_geometry_sha256"] else "screened_near"
                    metric = {} if kind == "exact" else near_match(geom, ref)
                    if metric is not None:
                        matches.append({"candidate_id": ref["material_id"], "kind": kind, **metric})
            repeated_proposals = [r["candidate_id"] for r in prior if digest is not None and r["geometry_sha256"] == digest]
            reasons = list(validation["failure_reasons"])
            if matches:
                reasons.append("known_initial_reference_duplicate_or_near_duplicate")
            if repeated_proposals:
                reasons.append("duplicate_earlier_proposal")
            cid = f"{arm}-{index:03d}"
            record = {"candidate_id": cid, "arm": arm, "parent_id": parent["material_id"],
                      "parent_source_record_sha256": parent["source_record_sha256"],
                      "parent_geometry_sha256": parent["canonical_geometry_sha256"],
                      "geometry_sha256": digest, "seed": seed, "proposal_index": index,
                      "composition": "SiO2", "parameters": parameters, "geometry": geom,
                      **validation, "reference_set_matches": matches,
                      "duplicate_of_earlier_proposal": repeated_proposals,
                      "queue_status": "rejected_geometry_or_duplicate" if reasons else "awaiting_physical_validation",
                      "queue_rejection_reasons": reasons,
                      "mlip_relaxation": "unsupported_no_runtime_weights_loaded",
                      "dft_validation": "not_run", "reference_forces": "not_available",
                      "physical_validation_failure_reason": "no_MLIP_runtime_weights_or_DFT_reference_calculator_executed",
                      "evidence_class": "executed_geometry_only_prototype"}
            records.append(record)
            prior.append(record)
            timings.append({"candidate_id": cid, "arm": arm,
                            "proposal_or_input_copy_wall_seconds": generation_wall,
                            "proposal_or_input_copy_cpu_seconds": generation_cpu,
                            "geometry_validation_wall_seconds": time.perf_counter() - wall,
                            "geometry_validation_cpu_seconds": time.process_time() - cpu})
    (out / "candidate_records.jsonl").write_bytes(b"".join(encode(r) + b"\n" for r in records))
    summary = {"schema": manifest["schema"], "evidence_class": manifest["evidence_class"],
               "status": "geometry_prototype_executed_physical_validation_blocked", "arms": {},
               "mlip_relaxations": 0, "dft_jobs_attempted": 0, "dft_jobs_completed": 0,
               "energies_or_forces_evaluated": 0, "physical_improvement": None,
               "novel_materials_discovered": None,
               "undefined_reason": "geometry difference does not establish a distinct relaxed basin or a favorable physical property",
               "no_synthesis_or_application_performance_claim": True}
    for arm in ["non_generative_inputs", "bounded_proposals"]:
        rows = [r for r in records if r["arm"] == arm]
        summary["arms"][arm] = {
            "geometry_validation_attempts": len(rows),
            "geometry_valid": sum(r["geometry_valid"] for r in rows),
            "geometry_invalid": sum(not r["geometry_valid"] for r in rows),
            "exact_reference_duplicates": sum(any(m["kind"] == "exact" for m in r["reference_set_matches"]) for r in rows),
            "screened_near_reference_duplicates": sum(any(m["kind"] == "screened_near" for m in r["reference_set_matches"]) for r in rows),
            "duplicate_or_near_duplicate_rate": sum(bool(r["reference_set_matches"]) for r in rows) / len(rows),
            "awaiting_physical_validation": sum(r["queue_status"] == "awaiting_physical_validation" for r in rows),
            "mlip_relaxations": 0, "reference_jobs": 0,
        }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    receipt = {"measured_cost_unit": "local_CPU_and_wall_seconds", "per_candidate": timings,
               "total_wall_seconds": time.perf_counter() - total_wall,
               "total_cpu_seconds": time.process_time() - total_cpu,
               "reference_job_seconds": None, "queue_seconds": None, "dollars": None,
               "note": "Actual local proposal/copy and geometry-screening time; no physical-cost or superiority inference."}
    (out / "runtime_receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    (out / "seal.json").write_text(json.dumps({p.name: sha(p.read_bytes()) for p in out.iterdir() if p.is_file()}, indent=2, sort_keys=True) + "\n")
    return summary

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=ROOT / "data/decision_engine/initial_geometries.json.gz")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument("--cap", type=int, default=5)
    args = p.parse_args()
    print(json.dumps(run(args.source, args.out, args.seed, args.cap), indent=2))

if __name__ == "__main__":
    main()
