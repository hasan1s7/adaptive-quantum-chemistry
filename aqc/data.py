"""Audited source preparation. Reference values never enter policy features."""
from __future__ import annotations

import csv
from contextlib import contextmanager
import gzip
import hashlib
import io
import json
import math
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

REVISION = "0109c8ec7cff3c10d3617ed65392fffc81492755"
UPSTREAM = "https://github.com/ghutchis/conformer-benchmark.git"
HARTREE_TO_KCAL = 627.509469  # Exactly the published compilation convention.
SPLIT_SEED = 1729
FAMILY_RULE = "RDKit 2025.9.6 generic Bemis-Murcko scaffold; all acyclic molecules one family; stereochemistry ignored"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        if not rows and not fields:
            return
        writer = csv.DictWriter(f, fieldnames=fields or list(rows[0]), extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


@contextmanager
def gzip_text_writer(path: Path):
    """Canonical UTF-8/LF gzip output with no clock or path in its header."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            with io.TextIOWrapper(zipped, encoding="utf-8", newline="\n") as stream:
                yield stream


def to_kcal(value: float, unit: str, *, atomization: bool = False) -> float:
    if not math.isfinite(value):
        raise ValueError("Non-finite energy")
    factors = {"kcal/mol": 1.0, "hartree": HARTREE_TO_KCAL, "kJ/mol": 1 / 4.184}
    if unit not in factors:
        raise ValueError(f"Unsupported energy unit: {unit}")
    return value * factors[unit] * (-1 if atomization else 1)


def parse_energies(path: Path, method: str) -> tuple[dict, list[dict], dict]:
    """Joinable keys retain geometry suffix; malformed/nonfinite/duplicate rows fail closed."""
    if method not in {"gfn2", "ccsdt"}:
        raise ValueError(f"Unsupported method: {method}")
    energies, excluded = {}, []
    n_rows = 0
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        n_rows += 1
        tokens = line.split()
        expected = 6 if method == "gfn2" else 7
        if len(tokens) != expected:
            raise ValueError(f"Malformed {method} line {line_number}")
        molecule, filename = tokens[:2]
        stem = filename.split(".", 1)[0]
        if method == "gfn2" and tokens[2:4] != ["atomizationE", ":"]:
            raise ValueError(f"Unsupported GFN2 energy type at {line_number}")
        if method == "ccsdt" and tokens[2:6] != ["FINAL", "SINGLE", "POINT", "ENERGY"]:
            raise ValueError(f"Unsupported CC energy type at {line_number}")
        value = float(tokens[5] if method == "gfn2" else tokens[6])
        if not math.isfinite(value):
            raise ValueError(f"Nonfinite {method} energy at {line_number}")
        if method == "gfn2":
            hartree_value = float(tokens[4])
            if not math.isfinite(hartree_value) or abs(hartree_value * HARTREE_TO_KCAL - value) > .01:
                raise ValueError(f"Inconsistent GFN2 Hartree/kcal fields at {line_number}")
        if not re.fullmatch(r"rmsd\d+-opt", stem):
            excluded.append({"method": method, "molecule_id": molecule, "conformer_id": stem,
                             "source_line": line_number, "reason": "not_published_opt_geometry"})
            continue
        key = (molecule, stem)
        if key in energies:
            raise ValueError(f"Duplicate {method} key: {key}")
        energies[key] = {"value": value, "line": line_number, "filename": filename}
    return energies, excluded, {"raw_rows": n_rows, "opt_rows": len(energies),
                                 "non_opt_rows": len(excluded)}


def geometry_identity(mol_path: Path) -> dict:
    """Exact ordered geometry identity, not a relaxed/RMSD-matched substitute."""
    xyz_path = mol_path.with_suffix(".xyz")
    mol = mol_path.read_text().splitlines()
    xyz = xyz_path.read_text().splitlines()
    if len(mol) < 4 or "V2000" not in mol[3]:
        raise ValueError(f"Unsupported MOL encoding: {mol_path}")
    natoms = int(mol[3][:3])
    if int(xyz[0]) != natoms or len(xyz) < natoms + 2:
        raise ValueError(f"MOL/XYZ atom count mismatch: {mol_path}")
    symbols, coords = [], []
    max_error = 0.0
    for i in range(natoms):
        m, x = mol[4+i].split(), xyz[2+i].split()
        if m[3] != x[0] or len(x) != 4:
            raise ValueError(f"MOL/XYZ ordered atom mismatch: {mol_path}")
        a, b = list(map(float, m[:3])), list(map(float, x[1:]))
        if not all(math.isfinite(v) for v in a+b):
            raise ValueError("Nonfinite coordinate")
        error = max(abs(v-w) for v, w in zip(a, b))
        max_error = max(max_error, error)
        if error > 5.1e-5:
            raise ValueError(f"MOL/XYZ coordinate mismatch: {mol_path}")
        symbols.append(x[0])
        coords.append(b)
    return {"natoms": natoms, "elements": dict(sorted(Counter(symbols).items())),
            "geometry_sha256": digest({"elements_in_order": symbols, "xyz_angstrom": coords}),
            "mol_sha256": sha256_file(mol_path), "xyz_sha256": sha256_file(xyz_path),
            "mol_xyz_max_coordinate_error_angstrom": max_error}


def family_for_smiles(smiles: str) -> tuple[str, str, str, dict]:
    from rdkit import Chem, rdBase
    from rdkit.Chem.Scaffolds import MurckoScaffold
    if rdBase.rdkitVersion != "2025.09.6":
        raise ValueError(f"Family reproducibility requires RDKit 2025.09.6, found {rdBase.rdkitVersion}")
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid source SMILES: {smiles}")
    canonical = Chem.MolToSmiles(mol, isomericSmiles=False)
    core = MurckoScaffold.GetScaffoldForMol(mol)
    scaffold = (Chem.MolToSmiles(MurckoScaffold.MakeScaffoldGeneric(core), isomericSmiles=False)
                if core.GetNumAtoms() else "ACYCLIC")
    family = "family_" + hashlib.sha256(scaffold.encode()).hexdigest()[:16]
    composition = dict(sorted(Counter(a.GetSymbol() for a in Chem.AddHs(mol).GetAtoms()).items()))
    return family, scaffold, canonical, composition


def make_split(molecules: list[dict], seed: int = SPLIT_SEED) -> dict:
    """Reference-free, once-only split: 70% of hash-ordered entire families for development."""
    groups = defaultdict(list)
    identity_families = {}
    for m in molecules:
        groups[m["family_id"]].append(m["molecule_id"])
        identity = m.get("canonical_smiles", m["molecule_id"])
        if identity in identity_families and identity_families[identity] != m["family_id"]:
            raise ValueError("Identical chemical structures assigned to different families")
        identity_families[identity] = m["family_id"]
    if len(groups) < 2:
        raise ValueError("At least two chemical families required")
    ordered = sorted(groups, key=lambda f: hashlib.sha256(f"{seed}|{f}".encode()).hexdigest())
    ndev = min(len(ordered)-1, max(1, int(len(ordered) * .7)))
    dev = set(ordered[:ndev])
    assignments = [{"molecule_id": m["molecule_id"], "family_id": m["family_id"],
                    "split": "development" if m["family_id"] in dev else "evaluation",
                    "n_candidates": len(m["candidates"])}
                   for m in sorted(molecules, key=lambda x: x["molecule_id"])]
    manifest = {"seed": seed, "rule": "sort families by SHA256(seed|family_id); first floor(0.70*n_families) development",
                "family_rule": FAMILY_RULE, "assignments": assignments,
                "families": [{"family_id": f, "split": "development" if f in dev else "evaluation",
                              "molecule_count": len(groups[f]), "molecule_ids": sorted(groups[f])}
                             for f in sorted(groups)],
                "counts": {s: {"families": sum(1 for f in groups if (f in dev) == (s == "development")),
                               "molecules": sum(a["split"] == s for a in assignments),
                               "candidates": sum(a["n_candidates"] for a in assignments if a["split"] == s)}
                           for s in ["development", "evaluation"]}}
    validate_split(manifest)
    manifest["split_sha256"] = digest(manifest)
    return manifest


def validate_split(manifest: dict) -> None:
    ids, family_split = set(), {}
    for a in manifest["assignments"]:
        if a["molecule_id"] in ids:
            raise ValueError("Molecule split leakage / duplicate assignment")
        ids.add(a["molecule_id"])
        if a["split"] not in {"development", "evaluation"}:
            raise ValueError("Unknown split")
        previous = family_split.setdefault(a["family_id"], a["split"])
        if previous != a["split"]:
            raise ValueError("Chemical family leakage")
    if set(family_split.values()) != {"development", "evaluation"}:
        raise ValueError("Both development and evaluation splits required")


def prepare_real(source: Path, out: Path) -> dict:
    """Verify source integrity, geometry-key alignment and chemistry before making pools."""
    source, out = source.resolve(), out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if (source / ".git").exists():
        revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"], text=True)
        if revision != REVISION or dirty:
            raise ValueError("Source checkout must be clean and exactly the pinned revision")
    else:
        # An included content-addressed snapshot has the same upstream Git blob identities.
        lock_path = Path(__file__).resolve().parent.parent / "data" / "upstream_lock.json"
        lock = json.loads(lock_path.read_text())
        if lock["revision"] != REVISION:
            raise ValueError("Wrong snapshot revision")
        for item in lock["files"]:
            path = source / item["path"]
            if sha256_file(path) != item["sha256"]:
                raise ValueError(f"Snapshot content mismatch: {item['path']}")
    cheap, excluded_raw, cheap_counts = parse_energies(source / "energies/gfn2.txt", "gfn2")
    refs, excluded_cc, ref_counts = parse_energies(source / "energies/ccsdt.txt", "ccsdt")
    smiles = {}
    for line in (source / "SMILES/molecules.smi").read_text().splitlines():
        smi, name = line.split()
        if name in smiles:
            raise ValueError("Duplicate molecular SMILES ID")
        smiles[name] = smi
    compiled = {}
    with (source / "data-final.csv").open() as f:
        for row in csv.DictReader(f):
            key = (row["name"], Path(row["geom"]).stem)
            if key in compiled:
                raise ValueError("Duplicate published geometry key")
            compiled[key] = row
    geometries, by_molecule, geom_rows = {}, defaultdict(list), []
    for path in sorted((source / "geometries").glob("*_jobs/*/*-opt.mol")):
        key = (path.parent.name, path.stem)
        if key in geometries:
            raise ValueError(f"Ambiguous geometry key across charge directories: {key}")
        identity = geometry_identity(path)
        identity.update(molecule_id=key[0], conformer_id=key[1], mol_path=str(path.relative_to(source)),
                        xyz_path=str(path.with_suffix(".xyz").relative_to(source)))
        geometries[key] = identity
        by_molecule[key[0]].append(key)
        geom_rows.append({k: canonical_json(v) if isinstance(v, dict) else v for k, v in identity.items()})
    if set(compiled) != set(geometries):
        raise ValueError("Published CSV and geometry inventory do not identify the same pools")
    if not set(refs) <= set(geometries) or not set(cheap) <= set(geometries):
        raise ValueError("Energy key has no geometry")
    mismatches = []
    for key, row in compiled.items():
        if key not in cheap or float(row["gfn2"]) != cheap[key]["value"]:
            raise ValueError(f"Published/raw GFN2 mismatch: {key}")
        has_label = row["dlpno"].strip() not in {"", "nan", "NaN"}
        if has_label != (key in refs):
            raise ValueError(f"Published/raw CC missingness mismatch: {key}")
        if not has_label:
            mismatches.append({"molecule_id": key[0], "conformer_id": key[1], "reason": "missing_ccsdt_output"})
    molecules, excluded_molecules, excluded_candidates, family_rows = [], [], [], []
    duplicate_geometry_ids = []
    for name, keys in sorted(by_molecule.items()):
        # Cross-check physical relative energies without exposing them to policy/tuning features.
        labelled = [key for key in keys if key in refs]
        if labelled:
            base = labelled[0]
            for key in labelled:
                delta = (refs[key]["value"] - refs[base]["value"]) * HARTREE_TO_KCAL
                compiled_delta = float(compiled[base]["dlpno"]) - float(compiled[key]["dlpno"])
                if abs(delta - compiled_delta) > 1e-6:
                    raise ValueError(f"Raw/published reference relative energy disagreement: {key}")
        missing_cheap = [k[1] for k in keys if k not in cheap]
        missing_refs = [k[1] for k in keys if k not in refs]
        reasons = []
        if missing_cheap:
            reasons.append("incomplete_cheap_pool")
        if missing_refs:
            reasons.append("no_reference_labels" if len(missing_refs) == len(keys) else "incomplete_reference_pool")
        if len(keys) < 2:
            reasons.append("singleton_no_ranking_decision")
        if name not in smiles:
            reasons.append("missing_chemical_identity")
        family, scaffold, canonical, composition = family_for_smiles(smiles[name]) if name in smiles else (None, None, None, None)
        if len({canonical_json(geometries[k]["elements"]) for k in keys}) != 1:
            reasons.append("inconsistent_element_composition_across_conformers")
        # MOL bonding is not trusted; SMILES is the author's chemical grouping source.
        composition_matches = all(geometries[k]["elements"] == composition for k in keys)
        if not composition_matches:
            reasons.append("geometry_smiles_element_composition_mismatch")
        hashes = defaultdict(list)
        for key in keys:
            hashes[geometries[key]["geometry_sha256"]].append(key[1])
        for h, ids in hashes.items():
            if len(ids) > 1:
                duplicate_geometry_ids.append({"molecule_id": name, "geometry_sha256": h, "conformer_ids": ids})
        family_rows.append({"molecule_id": name, "family_id": family, "generic_scaffold": scaffold,
                            "canonical_smiles": canonical, "source_smiles": smiles.get(name),
                            "composition_verified": composition_matches})
        if reasons:
            excluded_molecules.append({"molecule_id": name, "n_candidates": len(keys), "n_missing_reference": len(missing_refs),
                                       "n_missing_cheap": len(missing_cheap), "reasons": ";".join(reasons)})
            for key in keys:
                excluded_candidates.append({"molecule_id": name, "conformer_id": key[1],
                                            "has_cheap": key in cheap, "has_reference": key in refs,
                                            "reason": ";".join(reasons)})
            continue
        # Cheap normalization uses cheap values only. Ref absolute energies stay in evaluator files.
        cheap_physical = {key: to_kcal(cheap[key]["value"], "kcal/mol", atomization=True) for key in keys}
        cheap_min = min(cheap_physical.values())
        candidates = [{"candidate_id": key[1], "cheap_kcal": round(cheap_physical[key] - cheap_min, 8)} for key in keys]
        references = {key[1]: to_kcal(refs[key]["value"], "hartree") for key in keys}
        molecules.append({"molecule_id": name, "family_id": family, "canonical_smiles": canonical,
                          "candidates": candidates, "references": references})
    split = make_split(molecules)
    assignments = {a["molecule_id"]: a["split"] for a in split["assignments"]}
    # Physical separation makes it possible to load development labels without reading test labels.
    for part in ("development", "evaluation"):
        selected = [m for m in molecules if assignments[m["molecule_id"]] == part]
        with (out / f"{part}_features.jsonl").open("w", encoding="utf-8", newline="\n") as f, (out / f"{part}_references.jsonl").open("w", encoding="utf-8", newline="\n") as r:
            for m in selected:
                f.write(canonical_json({k: m[k] for k in ("molecule_id", "family_id", "candidates")}) + "\n")
                r.write(canonical_json({"molecule_id": m["molecule_id"], "references": m["references"]}) + "\n")
    write_csv(out / "geometry_manifest.csv", geom_rows)
    write_csv(out / "families.csv", family_rows)
    write_csv(out / "excluded_molecules.csv", excluded_molecules)
    write_csv(out / "excluded_candidates.csv", excluded_candidates)
    write_csv(out / "unmatched_rows.csv", mismatches)
    write_csv(out / "excluded_raw_rows.csv", excluded_raw + excluded_cc)
    write_json(out / "split_manifest.json", split)
    required = ["LICENSE", "README.md", "compile-conformer-data.py", "atomization.py", "data-final.csv",
                "SMILES/molecules.smi", "energies/gfn2.txt", "energies/ccsdt.txt", "geometries/CHG-charges.txt"]
    file_entries = [{"path": x, "sha256": sha256_file(source / x)} for x in required]
    audit = {"dataset_kind": "real", "source_url": UPSTREAM, "revision": REVISION,
             "license": "MIT; Copyright (c) 2020 Geoff Hutchison; upstream license retained",
             "gfn2": cheap_counts, "ccsdt": ref_counts, "source_geometry_count": len(geometries),
             "source_molecule_count": len(by_molecule), "paired_candidate_count": len(set(cheap) & set(refs)),
             "missing_reference_count": len(set(geometries) - set(refs)),
             "missing_cheap_count": len(set(geometries) - set(cheap)),
             "unmatched_ccsdt_count": len(set(refs)-set(cheap)), "included_molecules": len(molecules),
             "included_candidates": sum(len(m["candidates"]) for m in molecules),
             "excluded_molecules": len(excluded_molecules), "excluded_candidates": len(excluded_candidates),
             "exclusion_reason_counts": dict(Counter(reason for m in excluded_molecules for reason in m["reasons"].split(";"))),
             "duplicate_geometry_ids": duplicate_geometry_ids,
             "geometry_pairing": "Exact molecule + full rmsdN-opt stem; all MOL/XYZ ordered atoms and coordinates checked",
             "geometry_optimization": "B3LYP-D3BJ/def2-SVP",
             "cheap_method": "GFN2-xTB, xTB 6.2, published atomization kcal/mol negated; 0.01 kcal/mol source rounding",
             "reference_method": "DLPNO-CCSD(T)/cc-pVTZ, TightPNO, ORCA 4.0.1; raw total Hartree",
             "hartree_to_kcal": HARTREE_TO_KCAL, "family_rule": FAMILY_RULE,
             "source_files": file_entries, "split_counts": split["counts"],
             "source_limits": ["Published energy extracts and author method/geometry mapping; full job inputs, SCF/convergence logs, and per-method geometry checksums absent.",
                               "No solvent, thermal, zero-point or experimental-population inference.",
                               "Whole incomplete pools excluded; results conditional on complete-case coverage.",
                               "Generic scaffold families are an operational inference, not supplied labels; analogs with different scaffolds can remain related.",
                               "No original per-job quantum calculations repeated; offline replay call counts are not wall-clock savings."]}
    audit["prepared_files_sha256"] = {p.name: sha256_file(p) for p in sorted(out.glob("*.jsonl"))}
    write_json(out / "audit.json", audit)
    return audit


def load_pools(prepared: Path, split: str) -> list[dict]:
    if split not in {"development", "evaluation"}:
        raise ValueError("Explicit split required")
    features = [json.loads(line) for line in (prepared / f"{split}_features.jsonl").read_text().splitlines()]
    reference_rows = [json.loads(line) for line in (prepared / f"{split}_references.jsonl").read_text().splitlines()]
    references = {r["molecule_id"]: r["references"] for r in reference_rows}
    if len(references) != len(reference_rows) or len({f["molecule_id"] for f in features}) != len(features):
        raise ValueError("Duplicate prepared molecule")
    if {f["molecule_id"] for f in features} != set(references):
        raise ValueError("Prepared features/references mismatch")
    for pool in features:
        pool["references"] = references[pool["molecule_id"]]
        ids = [c["candidate_id"] for c in pool["candidates"]]
        if not ids or len(ids) != len(set(ids)) or set(ids) != set(pool["references"]):
            raise ValueError("Incomplete or duplicate prepared candidate pool")
        from .oracle import policy_payload
        policy_payload(pool["candidates"], {"kind": "full"})
        if not all(type(x) in (int, float) and math.isfinite(x) for x in pool["references"].values()):
            raise ValueError("Missing or nonfinite prepared reference")
    return features
