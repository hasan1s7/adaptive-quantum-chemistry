"""Run `python -m erkidu_decision --help` from the existing Erkidu checkout."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import tempfile
import time
import urllib.request
from pathlib import Path

from .core import Oracle, run_policy
from .prepare import DATA, PROTOCOL, RAW, ROOT, SEED, digest, dump, prepare, fit


def fetch(data_root):
    target = data_root / "raw"
    target.mkdir(parents=True, exist_ok=True)
    receipts = []
    for name, (filename, file_id, md5) in RAW.items():
        path = target / filename
        if path.exists() and hashlib.md5(path.read_bytes()).hexdigest() == md5:
            receipts.append({"name": name, "status": "cached_verified", "sha256": digest(path)})
            continue
        with tempfile.NamedTemporaryFile(dir=target, delete=False) as tmp:
            temp = Path(tmp.name)
            try:
                with urllib.request.urlopen(f"https://ndownloader.figshare.com/files/{file_id}", timeout=60) as response:
                    while chunk := response.read(1024 * 1024):
                        tmp.write(chunk)
                tmp.close()
                if hashlib.md5(temp.read_bytes()).hexdigest() != md5:
                    raise ValueError(f"download checksum mismatch: {filename}")
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)
        receipts.append({"name": name, "status": "downloaded_verified", "sha256": digest(path)})
    return receipts


def fixture(out):
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    candidates = [
        {"candidate_id": "A", "mean_eV_atom": 0., "sigma_eV_atom": .02,
         "disagreement_eV_atom": .01, "support_distance": .01, "descriptor": [0., 0.]},
        {"candidate_id": "B", "mean_eV_atom": .01, "sigma_eV_atom": .02,
         "disagreement_eV_atom": .02, "support_distance": .1, "descriptor": [1., 0.]},
        {"candidate_id": "C", "mean_eV_atom": 1., "sigma_eV_atom": .15,
         "disagreement_eV_atom": .15, "support_distance": .5, "descriptor": [0., 2.]},
    ]
    cases = {"rescue": {"A": -5., "B": -5.04, "C": -4.},
             "shared_blind_spot": {"A": -5., "B": -5.01, "C": -5.20},
             "failed_reference": {"A": -5., "B": None, "C": -4.},
             "ties": {"A": -5., "B": -5., "C": -4.}}
    runs = []
    for name, labels in cases.items():
        for policy in ["mlip_only", "fixed_top", "random", "diversity", "uncertainty", "decision_aware", "calibrated_interval", "full_ref"]:
            payload = {"candidates": candidates, "policy": policy,
                       "budget": 3 if policy in {"calibrated_interval", "full_ref"} else 2,
                       "interval_q": 3., "ood_cutoff": .3,
                       "tolerance_eV_atom": .02, "seed": SEED,
                       "energy_unit": "eV/atom", "protocol_id": "synthetic-compatible-energy-v1"}
            oracle = Oracle(list(labels), labels, "synthetic-compatible-energy-v1")
            runs.append({"evidence_kind": "synthetic", "case": name, "policy": policy,
                         "public_payload": payload, "result": run_policy(payload, oracle)})
    force = Oracle(["A"], {"A": -5.}, "synthetic-compatible-energy-v1").query("A", kind="forces")
    dump(out / "fixture_results.json", {"claim_type": "executed_synthetic_fixture", "runs": runs,
                                        "force_request": force, "physical_validation": False})
    return {"evidence_kind": "synthetic", "executed_runs": len(runs),
            "offline_attempts": sum(x["result"]["charged_calls"] for x in runs),
            "force_request_status": force["status"], "output": str(out)}


def verify(run):
    seal = json.loads((run / "result_seal.json").read_text())
    for name, expected in seal.items():
        if digest(run / name) != expected:
            raise ValueError(f"result checksum mismatch: {name}")
    import csv
    import gzip
    rows = list(csv.DictReader((run / "per_pool.csv").open()))
    with gzip.open(run / "decision_traces.jsonl.gz", "rt") as f:
        traces = [json.loads(line) for line in f]
    rowmap = {r["trace_id"]: r for r in rows}
    charged = 0
    for t in traces:
        visible = {}
        attempts = []
        for q in t["result"]["queries"]:
            pre = q["pre_query"]
            shown = {r["candidate_id"]: r["energy_eV_atom"] for r in pre["available_observations"]}
            if shown != visible or pre["attempted_candidate_ids"] != attempts:
                raise ValueError("trace availability mismatch")
            if q["candidate_id"] in attempts:
                raise ValueError("unexpected duplicate policy query")
            attempts.append(q["candidate_id"])
            if q["ok"]:
                visible[q["candidate_id"]] = q["energy_eV_atom"]
            charged += q["charged"]
        if sum(q["charged"] for q in t["result"]["queries"]) != int(rowmap[t["trace_id"]]["charged_calls"]):
            raise ValueError("trace charge mismatch")
    expected = json.loads((run / "execution_accounting.json").read_text())["primary_offline_reference_attempts"]
    if charged != expected:
        raise ValueError("aggregate charge mismatch")
    return {"verified": True, "sealed_files": len(seal), "traces": len(traces),
            "offline_reference_attempts": charged, "visibility_snapshots_verified": True}


def main():
    parser = argparse.ArgumentParser(description="Erkidu local MLIP/DFT decision replay (energy-only whole-relaxation labels)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("fetch"); p.add_argument("--data-dir", type=Path, default=DATA)
    p = sub.add_parser("prepare"); p.add_argument("--out", type=Path, required=True); p.add_argument("--data-dir", type=Path, default=DATA)
    p = sub.add_parser("fit"); p.add_argument("--prepared", type=Path, required=True); p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("run"); p.add_argument("--prepared", type=Path, required=True); p.add_argument("--fit", type=Path, required=True); p.add_argument("--out", type=Path, required=True); p.add_argument("--workers", type=int, default=4)
    p = sub.add_parser("fixture"); p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("report"); p.add_argument("--run", type=Path, required=True)
    p = sub.add_parser("verify"); p.add_argument("--run", type=Path, required=True)
    p = sub.add_parser("real"); p.add_argument("--out", type=Path, required=True); p.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.command == "fetch":
        result = fetch(args.data_dir)
    elif args.command == "prepare":
        result = prepare(args.out, args.data_dir)
    elif args.command == "fit":
        result = fit(args.prepared, args.out)
    elif args.command == "run":
        from .experiment import run
        result = run(args.prepared, args.fit, args.out, args.workers)
    elif args.command == "fixture":
        result = fixture(args.out)
    elif args.command == "verify":
        result = verify(args.run)
    elif args.command == "report":
        from .reporting import render
        result = render(args.run)
    elif args.command == "real":
        from .experiment import run
        from .reporting import render
        if args.out.exists():
            raise FileExistsError(args.out)
        fetch(DATA)
        prepare(args.out / "prepared")
        fit(args.out / "prepared", args.out / "fit")
        result = run(args.out / "prepared", args.out / "fit", args.out / "run", args.workers)
        result["report"] = render(args.out / "run")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
