#!/usr/bin/env python3
"""Inspect saved 669-call records, without rerunning acquisition or tuning."""
from __future__ import annotations
import argparse
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def inspect(saved_dir: Path):
    saved = json.loads((saved_dir / "results.json").read_text())
    with (saved_dir / "per_molecule.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    refs = {r["molecule_id"]: r["references"] for r in map(json.loads,
        (ROOT / "results/real/prepared/development_references.jsonl").read_text().splitlines())}
    features = {r["molecule_id"]: r for r in map(json.loads,
        (ROOT / "results/real/prepared/development_features.jsonl").read_text().splitlines())}
    grouped = defaultdict(dict)
    for row in rows:
        mid, policy = row["molecule"], row["policy"]
        if policy in grouped[mid]:
            raise ValueError("Duplicate policy-molecule record")
        grouped[mid][policy] = row
        q = [row["query_1"]] + ([row["query_2"]] if row["query_2"] else [])
        if len(q) != len(set(q)) or len(q) != int(row["calls"]):
            raise ValueError("Saved query accounting mismatch")
        if row["best_queried"] not in q:
            raise ValueError("Saved selection was not queried")
        y = refs[mid]
        regret = min(y[c] for c in q) - min(y.values())
        if abs(regret - float(row["regret_kcal"])) > 1e-9:
            raise ValueError("Saved regret does not match original references")
        if int(row["within_1"]) != int(regret <= 1):
            raise ValueError("Saved threshold outcome mismatch")
        if features[mid]["family_id"] != row["family"]:
            raise ValueError("Saved family mismatch")
    if len(grouped) != 478 or len(rows) != 1912:
        raise ValueError("Unexpected saved record count")
    summary = {}
    for policy, old in saved["summary"].items():
        selected = [r for r in rows if r["policy"] == policy]
        result = {"calls": sum(int(r["calls"]) for r in selected),
                  "success": sum(int(r["within_1"]) for r in selected),
                  "molecules": len(selected)}
        if any(result[k] != old[k] for k in result):
            raise ValueError("Saved aggregate mismatch")
        summary[policy] = result
    paired = {}
    for policy in ("1_gap_gate", "2_rmsd_rerank", "3_gyration_probe"):
        result = {
            "gains": sum(int(d[policy]["within_1"]) > int(d["fixed_top_two"]["within_1"]) for d in grouped.values()),
            "losses": sum(int(d[policy]["within_1"]) < int(d["fixed_top_two"]["within_1"]) for d in grouped.values()),
        }
        key = policy + "_vs_fixed_top_two"
        if result != saved["paired_changes"][key]:
            raise ValueError("Saved paired counts mismatch")
        paired[key] = result
    paths = {
        "development_features.jsonl": "results/real/prepared/development_features.jsonl",
        "development_references.jsonl": "results/real/prepared/development_references.jsonl",
        "development_geometry.json.gz": "data/development_geometry.json.gz",
        "folds.json": "results/lab/folds.json",
    }
    digests = {name: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for name, path in paths.items()}
    if digests != saved["input_sha256"]:
        raise ValueError("Original input hashes mismatch")
    return {
        "schema": "erkidu-saved-669-ledger-inspection/v1",
        "evidence_class": "executed_integrity_inspection_of_prior_replay",
        "reran_669_policy": False, "live_reference_jobs": 0,
        "new_label_queries": 0, "rows_inspected": len(rows),
        "summary": summary, "paired_vs_top2": paired,
        "reference_regret_records_verified": len(rows),
        "original_input_hashes_verified": digests,
        "files_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in saved_dir.iterdir() if p.is_file()},
        "limitations": "Checks saved query identities, accounting, outcomes and source bytes. No policy execution, new labels, or independent scientific validation.",
    }

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--saved", type=Path, default=ROOT / "results/decision_engine/recovery/saved_669")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if args.out.exists():
        raise SystemExit("Refusing to overwrite an existing inspection")
    result = inspect(args.saved)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print("PASS: inspected 1,912 saved rows; no 669-call policy was rerun")

if __name__ == "__main__":
    main()
