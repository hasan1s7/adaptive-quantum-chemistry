#!/usr/bin/env python3
"""Independent inspect-only audit of prepared oxide data and calibration.

This does not tune, query an oracle, or execute a policy. Source prediction
columns are checked directly to distinguish model anchoring from reference
minimum normalization. Whole-system partitions and metadata duplicates are
checked independently of the preparation function.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_CANDIDATE_FIELDS = {
    "candidate_id", "composition", "formula_counts", "group_id",
    "initial_prototype", "descriptor", "support_distance",
    "initial_prototype_in_mp_proxy", "predictions_eV_atom", "mean_eV_atom",
    "disagreement_eV_atom",
}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def check(condition, message):
    if not condition:
        raise ValueError(message)

def audit(prepared, fit_dir=None):
    protocol = json.loads((prepared / "preregistered_protocol.json").read_text())
    pools = json.loads((prepared / "pools.json").read_text())
    private = json.loads((prepared / "references_private.json").read_text())
    assignments = json.loads((prepared / "split_assignments.json").read_text())
    for name, expected in json.loads((prepared / "preparation_seal.json").read_text()).items():
        check(sha(prepared / name) == expected, "prepared evidence seal mismatch: " + name)
    check(private["unit"] == protocol["energy_unit"] == "eV/atom", "unit mismatch")
    check(private["protocol_id"] == protocol["protocol_id"], "protocol mismatch")
    check(assignments == protocol["split_assignments"], "frozen assignment mismatch")
    raw = ROOT / "data/decision_engine/raw"
    tables = {}
    for name in ("mace_mp0", "chgnet", "m3gnet"):
        source = raw / protocol["source_files"][name]["filename"]
        check(sha(source) == protocol["source_files"][name]["sha256"], "prediction source hash mismatch")
        frame = pd.read_csv(source, usecols=["material_id", "e_form_per_atom"])
        check(not frame.material_id.duplicated().any(), "duplicate raw prediction IDs")
        tables[name] = frame.set_index("material_id")["e_form_per_atom"].to_dict()
    source = raw / protocol["source_files"]["summary"]["filename"]
    check(sha(source) == protocol["source_files"]["summary"]["sha256"], "reference source hash mismatch")
    label_df = pd.read_csv(source, usecols=["material_id", "e_form_per_atom_mp2020_corrected"])
    source_labels = label_df.set_index("material_id")["e_form_per_atom_mp2020_corrected"].to_dict()
    ownership, composition_owner = {}, {}
    seen_ids, seen_prototypes = set(), set()
    split_counts = Counter()
    for pool in pools:
        group, split, composition = pool["group_id"], pool["split"], pool["composition"]
        check(assignments[group] == split, "assignment drift")
        check(group not in ownership or ownership[group] == split, "group split leakage")
        check(composition not in composition_owner, "composition appears in multiple pools")
        ownership[group], composition_owner[composition] = split, group
        split_counts[split] += 1
        candidates = pool["candidates"]
        first = min(c["candidate_id"] for c in candidates)
        cheap_anchor = min(candidates, key=lambda c: (c["mean_eV_atom"], c["candidate_id"]))
        check(cheap_anchor["candidate_id"] == pool["anchor_id"], "cheap anchor mismatch")
        for c in candidates:
            cid = c["candidate_id"]
            check(set(c) <= PUBLIC_CANDIDATE_FIELDS, "unknown/nonpublic feature field")
            check(cid not in seen_ids, "candidate ID leakage/duplication")
            seen_ids.add(cid)
            check("-".join(sorted(c["formula_counts"])) == group, "chemical-system identity mismatch")
            check(c["composition"] == composition, "candidate composition mismatch")
            check(c["group_id"] == group, "candidate group mismatch")
            key = (composition, c["initial_prototype"])
            check(key not in seen_prototypes, "same-composition prototype duplicate")
            seen_prototypes.add(key)
            pred = [tables[m][cid] - tables[m][first] for m in tables]
            check(np.allclose(pred, c["predictions_eV_atom"], atol=1e-12, rtol=0), "prediction offset is not first-ID model normalization")
            check(abs(pred[0] - c["mean_eV_atom"]) < 1e-12, "primary predictor mismatch")
            offsets = [tables[m][cid] - tables[m][cheap_anchor["candidate_id"]] for m in tables]
            check(abs(float(np.std(offsets, ddof=1)) - c["disagreement_eV_atom"]) < 1e-12, "contrast disagreement mismatch")
            label = private["labels"][cid]
            original = source_labels[cid]
            if not math.isfinite(original):
                check(label is None, "missing label did not retain unavailable status")
            else:
                check(label == original, "reference was altered or reference-minimum centered")
    check(set(private["labels"]) == seen_ids, "private/public candidate universe mismatch")
    check(all(split == "shift_li" for system, split in ownership.items() if "Li" in system.split("-")), "Li escaped shift partition")
    calibration_check = None
    if fit_dir is not None:
        calibration = json.loads((fit_dir / "calibration.json").read_text())
        for name, expected in json.loads((fit_dir / "fit_seal.json").read_text()).items():
            check(sha(fit_dir / name) == expected, "calibration seal mismatch")
        calibration_check = {}
        for method, beta in calibration["coefficients"].items():
            scores = {}
            for p in pools:
                if p["split"] != "calibration":
                    continue
                a = next(c for c in p["candidates"] if c["candidate_id"] == p["anchor_id"])
                for c in p["candidates"]:
                    error = ((private["labels"][c["candidate_id"]] - private["labels"][a["candidate_id"]])
                             - (c["mean_eV_atom"] - a["mean_eV_atom"]))
                    sigma = math.sqrt(max(1e-6, beta[0] + beta[1] * c["disagreement_eV_atom"] ** 2 + beta[2] * c["support_distance"] ** 2))
                    scores[p["group_id"]] = max(scores.get(p["group_id"], 0.), abs(error) / sigma)
            expected = calibration["intervals"][method]
            check(scores == expected["scores"], "scores are not whole-system maxima")
            for alpha, qname in ((.1, "q"), (.05, "q_95")):
                rank = math.ceil((len(scores) + 1) * (1 - alpha))
                q = sorted(scores.values())[rank - 1] if 0 < rank <= len(scores) else None
                check(q == expected[qname], "finite-group conformal quantile mismatch")
            calibration_check[method] = {"groups": len(scores), "q90": expected["q"], "q95": expected["q_95"]}
    return {
        "schema": "erkidu-independent-data-audit/v1", "status": "passed",
        "evidence_class": "executed_inspection", "policy_or_oracle_runs": 0,
        "pools": len(pools), "candidates": len(seen_ids), "chemical_systems": len(ownership),
        "pool_split_counts": dict(split_counts), "calibration_checked": calibration_check,
        "checks": ["source and output seals", "whole chemical-system partitions", "composition uniqueness",
                   "same-composition initial-prototype deduplication", "explicit public feature whitelist",
                   "each model normalized by first lexicographic candidate only", "raw uncentered reference labels",
                   "cheap-anchor contrast disagreement", "Li shift separation"],
        "limitations": ["No full-geometry near-duplicate or trajectory audit is possible from this metadata-only bundle",
                        "Different chemical systems can share abstract prototypes and are not proven independent",
                        "Public MP support is not an exact model-training-membership audit",
                        "Published labels remain retrospective and cannot validate generated structures"],
    }

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--fit", type=Path)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if args.out.exists():
        raise SystemExit("Refusing to overwrite an audit")
    result = audit(args.prepared, args.fit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "pools", "candidates", "chemical_systems")}))

if __name__ == "__main__":
    main()
