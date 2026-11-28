#!/usr/bin/env python3
"""Export four SnO2 forensic-review input kits; never invokes DFT or a scheduler.

POSCAR files are complete source geometries. INCAR/KPOINTS remain templates with
reviewer-required settings, and no licensed POTCAR files are supplied.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path


CASES = {
    "wbm-4-25075": "MACE first choice; shared cubic high-energy endpoint",
    "wbm-1-37760": "MACE fixed-top-two second query",
    "wbm-1-37762": "Decision-aware second query; low reference endpoint",
    "wbm-2-33797": "Reference minimum; same final prototype as decision-aware selection",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def poscar(record: dict) -> str:
    elements = sorted(set(record["symbols"]))
    counts = Counter(record["symbols"])
    lines = [f"Erkidu forensic input {record['material_id']} INITIAL geometry", "1.0"]
    lines.extend(" ".join(f"{value:.12f}" for value in row) for row in record["lattice_angstrom"])
    lines.extend([" ".join(elements), " ".join(str(counts[e]) for e in elements), "Direct"])
    for element in elements:
        for symbol, position in zip(record["symbols"], record["fractional_positions"]):
            if symbol == element:
                lines.append(" ".join(f"{value:.12f}" for value in position))
    return "\n".join(lines) + "\n"


def incar(material_id: str, relax: bool) -> str:
    lines = [
        f"SYSTEM = Erkidu {material_id} {'relaxation' if relax else 'single-point'} REVIEW REQUIRED",
        "# Proposed new audit settings; exact historical INCAR has not been recovered.",
        "# Review every placeholder and record VASP/POTCAR versions before use.",
        "GGA = PE", "ENCUT = 520", "PREC = Accurate", "EDIFF = 1E-6",
        "ISPIN = 2", "MAGMOM = __REVIEW_SITE_ORDERED_INITIAL_MAGNETIZATION__",
        "ISYM = __REVIEW_SYMMETRY_HANDLING__", "ISMEAR = 0", "SIGMA = 0.05",
        "LASPH = .TRUE.", "LREAL = .FALSE.", "LDAU = .FALSE.",
        "ALGO = Normal", "NELM = 200", "LWAVE = .FALSE.", "LCHARG = .FALSE.",
        "# No dispersion correction is proposed; this matches the stated PBE target.",
    ]
    if relax:
        lines += ["IBRION = 2", "ISIF = 3", "NSW = 200", "EDIFFG = -0.005"]
    else:
        lines += ["IBRION = -1", "ISIF = 2", "NSW = 0"]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometries", type=Path, default=Path("data/decision_engine/initial_geometries.json.gz"))
    parser.add_argument("--out", type=Path, default=Path("proposed/fresh_sno2_batch"))
    args = parser.parse_args()
    source = json.loads(gzip.decompress(args.geometries.read_bytes()))
    geometries = {record["material_id"]: record for record in source["structures"]}
    missing = sorted(set(CASES) - geometries.keys())
    if missing:
        raise ValueError(f"Missing initial geometries: {missing}")
    args.out.mkdir(parents=True, exist_ok=True)
    records = []
    for material_id, role in CASES.items():
        record = geometries[material_id]
        if record["composition_key"] != "O2Sn1" or record["pbc"] != [True, True, True] or not record["geometry_valid"]:
            raise ValueError(f"Invalid input geometry contract: {material_id}")
        destination = args.out / material_id
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "POSCAR").write_text(poscar(record))
        (destination / "INCAR.relax.template").write_text(incar(material_id, True))
        (destination / "INCAR.single_point.template").write_text(incar(material_id, False))
        (destination / "KPOINTS.template").write_text(
            "Gamma mesh REVIEW REQUIRED: target >=1000 k-points per reciprocal atom; converge energy\n"
            "0\nGamma\n__NX__ __NY__ __NZ__\n0 0 0\n")
        (destination / "POTCAR.spec.json").write_text(json.dumps({
            "element_order": ["O", "Sn"],
            "historical_paw_family": "PBE PAW version 5.2 as stated in WBM paper",
            "selected_potcar_symbols": None,
            "potcar_sha256": None,
            "required_review": "Resolve O and Sn PAW symbols/valence and exact licensed POTCAR versions; do not substitute silently",
            "supplied": False,
        }, indent=2) + "\n")
        records.append({"material_id": material_id, "role": role,
                        "n_atoms": record["n_atoms"], "initial_geometry_sha256": record["canonical_geometry_sha256"],
                        "source_record_sha256": record["source_record_sha256"],
                        "source_charge": record["charge"], "intended_formal_charge": 0,
                        "pbc": record["pbc"],
                        "files": {p.name: sha256(p) for p in sorted(destination.iterdir()) if p.is_file()},
                        "ready_for_submission": False})
    manifest = {
        "schema_version": "erkidu.proposed-fresh-reference-batch.v1",
        "status": "PROPOSED_NOT_RUN_REVIEW_REQUIRED", "dft_jobs_executed": 0,
        "compute_spend_authorized": False, "scheduler_submission": None,
        "purpose": "Forensic reproduction of one examined SnO2 failure; not an independent policy test",
        "input_geometries_sha256": sha256(args.geometries),
        "cases": records,
        "reference_protocol": {
            "functional": "PBE", "u_correction": "none for SnO2", "dispersion": "none proposed",
            "periodic": [True, True, True], "energy_unit": "eV per full cell; divide by actual atom count for comparison",
            "force_unit": "eV/angstrom", "cutoff_eV": 520,
            "spin": "spin-polarized; site initial magnetic moments require Ahmad review",
            "charge": "neutral formal Sn4+/O2- intent; source JSON charge null; confirm before submitting",
            "k_grid": "Gamma centered; choose and pin actual integer mesh, target1000 k-points per reciprocal atom, verify convergence",
            "electronic_tolerance_proposed_eV": 1e-6, "ionic_force_tolerance_eV_angstrom": 0.005,
            "historical_reproduction_limit": "Exact original INCAR, VASP build, POTCAR hashes and initial moments are unavailable",
        },
        "budget": {
            "initial_single_points": 4, "variable_cell_relaxations": 4, "final_static_checks": 4,
            "total_max_reference_jobs_before_review": 12,
            "optional_reruns_authorized": False,
            "resource_planning_only": "Start assessment at8 CPU ranks,16GiB/job,60min wall cap/job; unmeasured estimate, site review required",
            "planned_concurrency": 1, "queue_seconds": None, "runtime_seconds": None,
            "actual_dollars": None, "cpu_rank_hour_cap_if_all_jobs_hit_wall_cap": 96,
        },
        "required_outputs": ["exact VASP version", "all input hashes including POTCAR", "SCF and ionic convergence status",
                             "initial energy and forces", "final geometry and energy", "max force and stress",
                             "wall/CPU time", "queue time", "attempts and failures", "symmetry and basin comparison"],
        "stop_rules": ["Stop a job at the declared wall or ionic-step cap and record failure; no automatic paid retries",
                       "Do not treat a nonconverged relaxation as a reference energy",
                       "Resolve any change of electronic protocol before comparing its energies with historic WBM labels",
                       "Differences below2meV/atom are ties for this forensic comparison unless a tighter convergence study supports more precision"],
    }
    (args.out / "batch_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (args.out / "README.md").write_text(
        "# Proposed SnO2 reference batch\n\n"
        "No DFT was run and no compute purchase or submission is authorized. POSCAR files contain source initial structures. "
        "INCAR and KPOINTS files are templates with mandatory review placeholders; POTCAR is not supplied.\n\n"
        "Before execution, Ahmad must approve the neutral-charge intent, magnetic initialization, symmetry handling, "
        "integer Gamma mesh and exact PAW symbols/versions. Record VASP build and every input hash. The batch manifest "
        "separates four initial single points, four relaxations and four final static checks. These are proposed job counts, "
        "not measured runtime or cost. A new compute approval is needed for external spend.\n\n"
        "This is a forensic replay audit of an examined failure, not a fresh holdout for policy tuning or a material discovery.\n")
    print(json.dumps({"status": manifest["status"], "cases": len(records), "output": str(args.out), "jobs_executed": 0}))


if __name__ == "__main__":
    main()
