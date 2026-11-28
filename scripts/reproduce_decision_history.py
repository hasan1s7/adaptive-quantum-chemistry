#!/usr/bin/env python3
"""Reproduce the archived two-call development replay without retuning.

The original byte-identical policy source is in scripts/historical. This command
does NOT run the separate 669-call allocation experiment. It reproduces only
the historical two-query-per-pool comparison and checks four output hashes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "sealed_prelabel_plan.jsonl": "2e13675081a5305a8b43c94cd75ce04e7566ac81357dd412d74e5c2cf6bf323e",
    "results.json": "aa8d1f4d7b5dd160003709eaef04a14d439a3089896b4093e4685b9d4d7d610e",
    "per_pool.csv": "46679771aea9daebc93d50c72e7fb385128f0373f1fb5806a05835766f53228c",
    "rank4_rescue_harm.json": "501bec2c1ebac068c9efd4f53967bedfdb844b49e2e2ec8681b3794dd07939c5",
}
INPUTS = {
    "development_features.jsonl": "results/real/prepared/development_features.jsonl",
    "development_references.jsonl": "results/real/prepared/development_references.jsonl",
    "development_geometry.json.gz": "data/development_geometry.json.gz",
    "folds.json": "results/lab/folds.json",
}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    out = args.out.resolve()
    code = ROOT / "scripts/historical/erkidu_two_call.py"
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="erkidu-history-inputs-") as td:
        inp = Path(td)
        for name, location in INPUTS.items():
            (inp / name).symlink_to(ROOT / location)
        for stage in ("plan", "score"):
            subprocess.run([sys.executable, str(code), stage,
                            "--inputs", str(inp), "--out", str(out)],
                           env=env, check=True)
    actual = {name: hashlib.sha256((out / name).read_bytes()).hexdigest()
              for name in EXPECTED}
    mismatches = [name for name in EXPECTED if actual[name] != EXPECTED[name]]
    receipt = {
        "schema": "erkidu-historical-reproduction/v1",
        "status": "passed" if not mismatches else "failed",
        "evidence_class": "executed_historical_development_replay",
        "expected_sha256": EXPECTED, "actual_sha256": actual,
        "mismatches": mismatches,
        "wall_seconds_this_reproduction": time.perf_counter() - started,
        "live_reference_jobs": 0,
        "new_policy_fitting": False,
        "reran_669_call_experiment": False,
        "timing_note": "Local replay only; excludes original reference computations and queueing.",
    }
    (out / "reproduction_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if mismatches:
        raise SystemExit("Historical output hash mismatch: " + ", ".join(mismatches))
    print("PASS: all four archived scientific output hashes reproduced exactly")

if __name__ == "__main__":
    main()
