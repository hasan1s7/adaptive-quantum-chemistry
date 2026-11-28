"""Pin a pre-reference oxide cohort; fit uncertainty on separate systems.

No relaxed volume, final symmetry, reference ranking, unique_prototype flag,
band gap, or reference-based geometric displacement is a policy feature.
"""
from __future__ import annotations

import hashlib
import json
import math
import platform
import re
import time
from collections import Counter
from functools import reduce
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import nnls
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "decision_engine"
PROTOCOL = "WBM-PBE-PAW52-MP2020-relaxed-eVatom-20261119-oxide-v1"
SEED = 20261127
VALENCES = {s: v for symbols, v in [
    ("Li Na K Rb Cs", 1), ("Mg Ca Sr Ba", 2),
    ("B Al Ga Sc Y", 3), ("Si Ge Sn Ti Zr Hf", 4),
] for s in symbols.split()}
ELEMENTS = sorted([*VALENCES, "O"])
RAW = {
    "summary": ("2026-11-19-wbm-summary.csv.gz", "71653870", "e63906af07b0408ee3eaa7028aa02d27"),
    "mace_mp0": ("mace_mp0-2026-11-19.csv.gz", "71653786", "3bfe7826a613684a92a7dd28643cac9f"),
    "chgnet": ("chgnet-2026-11-19.csv.gz", "71653801", "3944fdbf7d1b041aae6ea811011008cc"),
    "m3gnet": ("m3gnet-2026-11-19.csv.gz", "71653831", "b9bcef0e065876de910516b9a1f7a777"),
    "mp_support": ("2025-02-01-mp-energies.csv.gz", "52080797", "7eb0c49fc169ba92783f2f6d0d19d741"),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n")


def parse_formula(formula: str) -> dict[str, int]:
    """Only explicit integer flat compositions used by the pinned CSVs."""
    if not isinstance(formula, str) or not formula:
        raise ValueError("missing or non-string formula")
    compact = re.sub(r"\s+", "", formula)
    pairs = re.findall(r"([A-Z][a-z]?)(\d+(?:\.\d+)?)?", compact)
    if "".join(a + b for a, b in pairs) != compact or not pairs:
        raise ValueError(f"unsupported formula syntax: {formula}")
    counts = Counter()
    for atom, count in pairs:
        value = float(count or 1)
        if not value.is_integer() or value <= 0:
            raise ValueError("nonintegral or invalid atom count")
        counts[atom] += int(value)
    return dict(sorted(counts.items()))


def reduced_composition(formula: str) -> dict[str, int]:
    counts = parse_formula(formula)
    denominator = reduce(math.gcd, counts.values())
    return {a: n // denominator for a, n in counts.items()}


def comp_key(counts: dict[str, int]) -> str:
    return "".join(a + str(n) for a, n in sorted(counts.items()))


def eligible(counts: dict[str, int]) -> bool:
    return ("O" in counts and 2 <= len(counts) <= 4
            and set(counts) <= set(ELEMENTS)
            and sum(VALENCES.get(a, 0) * n for a, n in counts.items()) == 2 * counts["O"])


def descriptor(counts: dict[str, int], prototype: str) -> list[float]:
    """Declared pre-query compositional + initial-symmetry support proxy."""
    total = sum(counts.values())
    pieces = prototype.split(":")[0].split("_")
    lattice = pieces[1][:1] if len(pieces) > 1 else "?"
    try:
        spacegroup = int(pieces[2])
    except (IndexError, ValueError):
        spacegroup = 0
    return ([counts.get(a, 0) / total for a in ELEMENTS]
            + [0.10 * math.log1p(total), 0.20 * spacegroup / 230]
            + [0.20 * float(lattice == x) for x in "acthom"])


def assignment(systems: list[str]) -> dict[str, str]:
    shift = [s for s in systems if "Li" in s.split("-")]
    ordinary = sorted((s for s in systems if s not in shift),
                      key=lambda s: hashlib.sha256(f"{SEED}|{s}".encode()).hexdigest())
    n_train = math.floor(0.40 * len(ordinary))
    n_cal = math.floor(0.30 * len(ordinary))
    result = {s: ("train" if i < n_train else "calibration" if i < n_train + n_cal else "test")
              for i, s in enumerate(ordinary)}
    result.update({s: "shift_li" for s in shift})
    return result


def conformal_quantile(scores: list[float], alpha: float) -> float | None:
    """None denotes the honest infinite interval with too few groups."""
    rank = math.ceil((len(scores) + 1) * (1 - alpha))
    if rank > len(scores) or not scores:
        return None
    return sorted(scores)[rank - 1]


def validate_splits(pools: list[dict]) -> dict:
    ownership: dict[str, str] = {}
    candidates: set[str] = set()
    prototypes: set[tuple[str, str]] = set()
    for pool in pools:
        group, split = pool["group_id"], pool["split"]
        if group in ownership and ownership[group] != split:
            raise ValueError("chemical system crosses split")
        ownership[group] = split
        for c in pool["candidates"]:
            if c["candidate_id"] in candidates:
                raise ValueError("candidate duplicate across pools")
            candidates.add(c["candidate_id"])
            key = (pool["composition"], c["initial_prototype"])
            if key in prototypes:
                raise ValueError("same-composition initial prototype duplicate")
            prototypes.add(key)
    return {"passed": True, "chemical_systems": len(ownership), "candidates": len(candidates),
            "same_composition_initial_prototype_duplicates": 0,
            "limits": "Different compositions can share abstract prototypes; chemical-system independence is not established."}


def prepare(out: Path, data_root: Path = DATA) -> dict:
    if out.exists():
        raise FileExistsError(f"refusing to overwrite frozen cohort: {out}")
    t0 = time.perf_counter()
    out.mkdir(parents=True)
    files = {}
    for name, (filename, fid, md5) in RAW.items():
        path = data_root / "raw" / filename
        raw = path.read_bytes()
        if hashlib.md5(raw).hexdigest() != md5:
            raise ValueError(f"source checksum mismatch: {filename}")
        files[name] = {"filename": filename, "figshare_file_id": fid,
                       "url": f"https://ndownloader.figshare.com/files/{fid}",
                       "bytes": len(raw), "md5": md5, "sha256": hashlib.sha256(raw).hexdigest()}

    # Read only feature-eligible columns until cohort and group partitions are written.
    feature_columns = ["material_id", "formula", "protostructure_spglib_initial_structure"]
    feature_df = pd.read_csv(data_root / "raw" / RAW["summary"][0], usecols=feature_columns)
    exclusions = []
    chosen = []
    selection_counts = Counter(total_source_rows=len(feature_df))
    for row in feature_df.to_dict("records"):
        counts = reduced_composition(row["formula"])
        if not eligible(counts):
            selection_counts["outside_declared_oxide_scope"] += 1
            continue
        selection_counts["formula_eligible"] += 1
        proto = row["protostructure_spglib_initial_structure"]
        if not isinstance(proto, str) or not proto:
            exclusions.append({"candidate_id": row["material_id"], "reason": "missing_initial_prototype"})
            continue
        chosen.append({"candidate_id": row["material_id"], "composition": comp_key(counts),
                       "formula_counts": counts, "group_id": "-".join(sorted(counts)),
                       "initial_prototype": proto, "descriptor": descriptor(counts, proto)})
    chosen.sort(key=lambda r: r["candidate_id"])
    seen = set()
    deduped = []
    for row in chosen:
        key = (row["composition"], row["initial_prototype"])
        if key in seen:
            exclusions.append({"candidate_id": row["candidate_id"], "reason": "same_composition_initial_prototype", "key": list(key)})
        else:
            deduped.append(row)
            seen.add(key)
    counts = Counter(r["composition"] for r in deduped)
    retained = []
    for row in deduped:
        if counts[row["composition"]] < 2:
            exclusions.append({"candidate_id": row["candidate_id"], "reason": "singleton_after_prequery_dedup"})
        else:
            retained.append(row)
    splits = assignment(sorted({r["group_id"] for r in retained}))
    config = {
        "schema_version": "erkidu-materials-decision-1", "evidence_kind": "replay",
        "source_git_commit": "58b3bd5b95c1165c5208150203007cea0031c64c",
        "protocol_id": PROTOCOL, "energy_unit": "eV/atom", "seed": SEED,
        "endpoint": "regret of best queried relaxed structure within reduced composition",
        "reference_action": "one full DFT relaxation label; NOT a single-point force job",
        "primary_model": "MACE-MP-0 medium v0.3.5 published predictions",
        "other_models": ["CHGNet v0.3.0", "M3GNet MP-2021.2.8-PES"],
        "tolerance_eV_atom": 0.020, "near_tie_eV_atom": 0.002,
        "primary_budget_per_pool": 2, "budget_grid": [1, 2, 3, 4],
        "calibration_alpha": 0.10, "bootstrap_draws": 5000,
        "oxide_valence_rule": {**VALENCES, "O": -2},
        "split_rule": "whole chemical systems; Li held as shift; nonLi SHA256(seed|system) ordered40/30/30",
        "split_assignments": splits, "split_before_label_access": True,
        "pred_normalization": "each model subtracts its prediction on the lexicographically first candidate in its pool",
        "label_normalization": "none; oracle returns uncentered corrected formation energy eV/atom",
        "forbidden_features": ["reference minimum", "relaxed volume", "final symmetry", "band gap", "unique_prototype", "DFT corrections", "initial-final fingerprint distance"],
        "sigma_fit": "NNLS squared training anchored residual on intercept, disagreement squared, public support distance squared",
        "interval_unit": "maximum anchored residual over every candidate/pool in a chemical system",
        "random_seeds": [SEED + i for i in range(8)], "source_files": files,
        "created_by_code_sha256": digest(Path(__file__)),
        "selection_counts": dict(selection_counts), "prelabel_candidates": len(retained),
        "prelabel_compositions": len({r["composition"] for r in retained}),
    }
    dump(out / "preregistered_protocol.json", config)
    dump(out / "prelabel_cohort.json", retained)
    dump(out / "split_assignments.json", splits)
    dump(out / "prelabel_exclusions.json", exclusions)

    # MP metadata is a public support proxy, not a claim of exact pretrained split membership.
    mp = pd.read_csv(data_root / "raw" / RAW["mp_support"][0], usecols=["formula", "protostructure_spglib"])
    support, support_prototypes = [], set()
    for row in mp.to_dict("records"):
        try:
            counts = reduced_composition(row["formula"])
        except ValueError:
            continue
        proto = row["protostructure_spglib"]
        if isinstance(proto, str) and eligible(counts):
            support.append(descriptor(counts, proto))
            support_prototypes.add(proto)
    if not support:
        raise ValueError("empty MP support proxy")
    tree = cKDTree(np.asarray(support))
    dist, _ = tree.query(np.asarray([r["descriptor"] for r in retained]), k=1)
    for row, d in zip(retained, dist):
        row["support_distance"] = float(d)
        row["initial_prototype_in_mp_proxy"] = row["initial_prototype"] in support_prototypes
    prediction_tables = {}
    for model in ["mace_mp0", "chgnet", "m3gnet"]:
        frame = pd.read_csv(data_root / "raw" / RAW[model][0])
        if frame.material_id.duplicated().any():
            raise ValueError(f"duplicate prediction IDs: {model}")
        prediction_tables[model] = frame.set_index("material_id")["e_form_per_atom"].to_dict()
    pools = []
    for composition in sorted({r["composition"] for r in retained}):
        rows = [r for r in retained if r["composition"] == composition]
        anchor = rows[0]["candidate_id"]
        missing = [r["candidate_id"] for r in rows if any(not math.isfinite(float(prediction_tables[m].get(r["candidate_id"], float("nan")))) for m in prediction_tables)]
        if missing:
            exclusions.append({"composition": composition, "reason": "missing_surrogate_prediction_whole_pool", "candidate_ids": missing})
            continue
        for row in rows:
            cid = row["candidate_id"]
            pred = [float(prediction_tables[m][cid] - prediction_tables[m][anchor]) for m in prediction_tables]
            row["predictions_eV_atom"] = pred
            row["mean_eV_atom"] = pred[0]
        # Pairwise disagreement: common energy offsets of the three models cannot inflate it.
        cheap_anchor = min(rows, key=lambda r: (r["mean_eV_atom"], r["candidate_id"]))
        for row in rows:
            deltas = np.asarray(row["predictions_eV_atom"]) - np.asarray(cheap_anchor["predictions_eV_atom"])
            row["disagreement_eV_atom"] = float(np.std(deltas, ddof=1))
        pools.append({"pool_id": composition, "composition": composition,
                      "group_id": rows[0]["group_id"], "split": splits[rows[0]["group_id"]],
                      "candidate_count": len(rows), "anchor_id": cheap_anchor["candidate_id"],
                      "candidates": rows})
    # Only now read evaluator reference energies and correction-protocol checks.
    reference_df = pd.read_csv(data_root / "raw" / RAW["summary"][0], usecols=[
        "material_id", "e_form_per_atom_mp2020_corrected", "e_correction_per_atom_mp2020"])
    references = reference_df.set_index("material_id")["e_form_per_atom_mp2020_corrected"].to_dict()
    corrections = reference_df.set_index("material_id")["e_correction_per_atom_mp2020"].to_dict()
    missing_refs = []
    for pool in pools:
        vals = [corrections[c["candidate_id"]] for c in pool["candidates"]]
        if max(vals) - min(vals) > 1e-6:
            raise ValueError("prequery oxide rule failed correction-constancy gate; stop entire experiment")
        for c in pool["candidates"]:
            cid = c["candidate_id"]
            if not math.isfinite(float(references.get(cid, float("nan")))):
                missing_refs.append(cid)
    if missing_refs:
        # Keep missing status visible; evaluation decides failure, no successful-label filtering.
        for cid in missing_refs:
            references[cid] = None
    refs = {c["candidate_id"]: references[c["candidate_id"]] for p in pools for c in p["candidates"]}
    split_check = validate_splits(pools)
    dump(out / "pools.json", pools)
    dump(out / "references_private.json", {"protocol_id": PROTOCOL, "unit": "eV/atom", "labels": refs})
    dump(out / "exclusions.json", exclusions)
    summary = {
        "evidence_kind": "replay", "pools": len(pools), "candidates": len(refs),
        "chemical_systems": len({p["group_id"] for p in pools}),
        "split_counts": {s: {"pools": sum(p["split"] == s for p in pools),
                              "candidates": sum(len(p["candidates"]) for p in pools if p["split"] == s),
                              "groups": len({p["group_id"] for p in pools if p["split"] == s})}
                         for s in ["train", "calibration", "test", "shift_li"]},
        "initial_prototype_in_mp_proxy": sum(c["initial_prototype_in_mp_proxy"] for p in pools for c in p["candidates"]),
        "mp_proxy_structures": len(support), "missing_reference_ids": missing_refs,
        "missing_surrogate_pools": sum(e["reason"] == "missing_surrogate_prediction_whole_pool" for e in exclusions),
        "correction_constancy_gate_passed": True, "split_check": split_check,
        "measured_preparation_wall_seconds": time.perf_counter() - t0,
        "python": platform.python_version(),
    }
    dump(out / "cohort_summary.json", summary)
    dump(out / "preparation_seal.json", {p.name: digest(p) for p in sorted(out.iterdir()) if p.is_file()})
    return summary


def fit(prepared: Path, out: Path) -> dict:
    if out.exists():
        raise FileExistsError(f"refusing to overwrite fitted artifact: {out}")
    seal = json.loads((prepared / "preparation_seal.json").read_text())
    required = {"pools.json", "references_private.json", "preregistered_protocol.json"}
    if not isinstance(seal, dict) or not required <= set(seal):
        raise ValueError("preparation seal lacks required fitting inputs")
    for name, expected in seal.items():
        if Path(name).name != name or not isinstance(expected, str):
            raise ValueError("invalid preparation seal entry")
        if digest(prepared / name) != expected:
            raise ValueError(f"preparation seal mismatch: {name}")
    pools = json.loads((prepared / "pools.json").read_text())
    references = json.loads((prepared / "references_private.json").read_text())["labels"]
    unavailable = sorted({c["candidate_id"] for p in pools
                          if p["split"] in {"train", "calibration"}
                          for c in p["candidates"]
                          if isinstance(references.get(c["candidate_id"]), bool)
                          or not isinstance(references.get(c["candidate_id"]), (int, float))
                          or not math.isfinite(references[c["candidate_id"]])})
    if unavailable:
        raise ValueError("unsupported fit: missing or invalid train/calibration reference labels; "
                         "no candidates were silently excluded: " + ", ".join(unavailable))
    out.mkdir(parents=True)
    X, residuals = [], []
    train_dist = []
    for p in pools:
        if p["split"] != "train":
            continue
        anchor = next(c for c in p["candidates"] if c["candidate_id"] == p["anchor_id"])
        for c in p["candidates"]:
            train_dist.append(c["support_distance"])
            if c is anchor:
                continue
            error = ((references[c["candidate_id"]] - references[anchor["candidate_id"]])
                     - (c["mean_eV_atom"] - anchor["mean_eV_atom"]))
            X.append([1, c["disagreement_eV_atom"] ** 2, c["support_distance"] ** 2])
            residuals.append(error)
    x, e = np.asarray(X), np.asarray(residuals)
    if len(e) < 2:
        raise ValueError("insufficient training residuals")
    coefficients = {}
    for name, cols in {"constant": [0], "disagreement": [0, 1], "distance": [0, 2], "combined": [0, 1, 2]}.items():
        beta, _ = nnls(x[:, cols], e ** 2)
        full = np.zeros(3)
        full[cols] = beta
        full[0] = max(float(full[0]), 0.001 ** 2)
        coefficients[name] = full.tolist()
    result = {"schema_version": 1, "evidence_kind": "executed_training_fit",
              "prepared_protocol_sha256": digest(prepared / "preregistered_protocol.json"),
              "training_only": True, "training_residuals": len(e),
              "mean_training_anchored_error_eV_atom": float(e.mean()),
              "coefficients": coefficients, "sigma_floor_eV_atom": 0.001,
              "ood_cutoff": float(np.quantile(train_dist, 0.95)),
              "intervals": {}, "train_groups": sorted({p["group_id"] for p in pools if p["split"] == "train"}),
              "calibration_groups": sorted({p["group_id"] for p in pools if p["split"] == "calibration"}),
              "assumptions": "Group-level split conformal needs exchangeable chemical-system score distributions conditional on the fixed training fit. Shared pretrained data and prototype correlations can violate this; no shifted-family guarantee."}
    for name, beta in coefficients.items():
        scores = {}
        for p in pools:
            if p["split"] != "calibration":
                continue
            anchor = next(c for c in p["candidates"] if c["candidate_id"] == p["anchor_id"])
            for c in p["candidates"]:
                error = ((references[c["candidate_id"]] - references[anchor["candidate_id"]])
                         - (c["mean_eV_atom"] - anchor["mean_eV_atom"]))
                score = abs(error) / sigma(c, beta)
                scores[p["group_id"]] = max(scores.get(p["group_id"], 0), score)
        result["intervals"][name] = {"alpha": 0.10, "n_calibration_groups": len(scores),
                                    "q": conformal_quantile(list(scores.values()), 0.10),
                                    "q_95": conformal_quantile(list(scores.values()), 0.05),
                                    "scores": scores}
    dump(out / "calibration.json", result)
    dump(out / "fit_seal.json", {"calibration.json": digest(out / "calibration.json")})
    return result


def sigma(candidate: dict, coefficients: list[float]) -> float:
    b = coefficients
    return math.sqrt(max(1e-6, b[0] + b[1] * candidate["disagreement_eV_atom"] ** 2
                         + b[2] * candidate["support_distance"] ** 2))
