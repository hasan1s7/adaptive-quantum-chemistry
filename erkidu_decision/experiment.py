"""Controlled, isolated policy replay and group-level uncertainty reporting."""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import os
import platform
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from .core import Oracle, run_policy
from .prepare import PROTOCOL, SEED, digest, dump, sigma, validate_splits


def write_csv(path, records):
    if not records:
        return
    with Path(path).open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(records[0]))
        w.writeheader()
        w.writerows(records)


def write_jsonl_gz(path, records):
    with Path(path).open("wb") as handle:
        with gzip.GzipFile(fileobj=handle, mode="wb", mtime=0, filename="") as f:
            for row in records:
                f.write((json.dumps(row, sort_keys=True, allow_nan=False) + "\n").encode())


def public_payload(pool, fitted, policy, budget, seed=SEED, *, model_index=0,
                   sigma_kind="combined", ood=False):
    candidates = []
    for c in pool["candidates"]:
        mean = (float(np.mean(c["predictions_eV_atom"])) if model_index == -1
                else c["predictions_eV_atom"][model_index])
        candidates.append({"candidate_id": c["candidate_id"], "mean_eV_atom": mean,
                           "sigma_eV_atom": sigma(c, fitted["coefficients"][sigma_kind]),
                           "disagreement_eV_atom": c["disagreement_eV_atom"],
                           "support_distance": c["support_distance"], "descriptor": c["descriptor"]})
    return {"candidates": candidates, "policy": policy, "budget": budget, "seed": seed,
            "tolerance_eV_atom": 0.020, "interval_q": fitted["intervals"][sigma_kind]["q"],
            "ood_cutoff": fitted["ood_cutoff"] if ood else None,
            "gap_threshold_eV_atom": 0.05, "pool_id": pool["pool_id"],
            "group_id": pool["group_id"], "protocol_id": PROTOCOL, "energy_unit": "eV/atom"}


def score_one(pool, fitted, references, arm, policy, budget, seed, options=None, failure_ids=()):
    options = options or {}
    payload = public_payload(pool, fitted, policy, budget, seed, **options)
    labels = {c["candidate_id"]: (None if c["candidate_id"] in failure_ids else references[c["candidate_id"]])
              for c in pool["candidates"]}
    oracle = Oracle(list(labels), labels, expected_protocol=PROTOCOL)
    start = time.perf_counter()
    result = run_policy(payload, oracle, isolated=True)
    elapsed = time.perf_counter() - start
    # Evaluator-only fields below never return to the policy.
    truth = {c["candidate_id"]: references[c["candidate_id"]] for c in pool["candidates"]}
    valid_truth = {k: v for k, v in truth.items() if v is not None}
    target_complete = len(valid_truth) == len(truth)
    best = min(valid_truth.values()) if valid_truth else None
    selected = result["selected_id"]
    regret = max(0., truth[selected] - best) if selected is not None and truth.get(selected) is not None and target_complete else None
    accepted = selected is not None and result["status"] == "ok"
    energies = sorted(valid_truth.values())
    near_tie = len(energies) > 1 and energies[1] - energies[0] <= 0.002 + 1e-12
    success = bool(accepted and regret is not None and regret <= 0.020 + 1e-12)
    trace_id = hashlib.sha256(f"{pool['pool_id']}|{arm}|{budget}|{seed}|{bool(failure_ids)}".encode()).hexdigest()[:20]
    row = {"trace_id": trace_id, "evidence_kind": "replay" if not failure_ids else "synthetic_failure_on_real_replay",
           "split": pool["split"], "pool_id": pool["pool_id"], "group_id": pool["group_id"],
           "arm": arm, "policy": policy, "budget": budget, "seed": seed,
           "candidate_count": len(truth), "selected_id": selected, "status": result["status"],
           "accepted": accepted, "success": success, "regret_eV_atom": regret,
           "charged_calls": oracle.charged_calls, "fallback": result["fallback"],
           "abstained": selected is None, "failed_jobs": sum(e["status"] == "failed" for e in oracle.events),
           "near_tie": near_tie, "reference_complete": target_complete,
           "max_support_distance": max(c["support_distance"] for c in pool["candidates"]),
           "mean_disagreement_eV_atom": float(np.mean([c["disagreement_eV_atom"] for c in pool["candidates"]])),
           "measured_policy_wall_seconds": elapsed, "reason": result["reason"]}
    trace = {"trace_id": trace_id, "public_payload": payload, "result": result, "evaluation_after_stop": row}
    return row, trace


def bootstrap(rows, draws=5000, seed=SEED):
    """Resample whole observed systems. Conditional descriptive intervals only."""
    groups = sorted({r["group_id"] for r in rows})
    if not groups:
        return {}
    by_group = [[r for r in rows if r["group_id"] == g] for g in groups]
    sums = np.asarray([[sum(r["success"] for r in rr),
                        sum(r["regret_eV_atom"] for r in rr if r["regret_eV_atom"] is not None),
                        sum(r["regret_eV_atom"] is not None for r in rr),
                        sum(r["charged_calls"] for r in rr), len(rr)] for rr in by_group], float)
    rng = np.random.default_rng(seed)
    sampled = sums[rng.integers(len(groups), size=(draws, len(groups)))].sum(axis=1)
    vals = {"success_rate": sampled[:, 0] / sampled[:, 4],
            "mean_regret_eV_atom": sampled[:, 1] / np.maximum(1, sampled[:, 2]),
            "mean_calls": sampled[:, 3] / sampled[:, 4]}
    return {key + "_ci95": [float(x) for x in np.quantile(value, [0.025, 0.975])]
            for key, value in vals.items()}


def aggregate(rows, draws=5000):
    keys = sorted({(r["split"], r["arm"], r["budget"]) for r in rows})
    result = []
    for split, arm, budget in keys:
        rr = [r for r in rows if (r["split"], r["arm"], r["budget"]) == (split, arm, budget)]
        regrets = [r["regret_eV_atom"] for r in rr if r["regret_eV_atom"] is not None]
        result.append({"split": split, "arm": arm, "budget": budget,
                       "n_pools": len(rr), "n_groups": len({r["group_id"] for r in rr}),
                       "successes": sum(r["success"] for r in rr), "success_rate": float(np.mean([r["success"] for r in rr])),
                       "mean_regret_eV_atom": float(np.mean(regrets)) if regrets else None,
                       "p95_regret_eV_atom": float(np.quantile(regrets, .95)) if regrets else None,
                       "worst_regret_eV_atom": max(regrets) if regrets else None,
                       "charged_calls": sum(r["charged_calls"] for r in rr),
                       "mean_calls": float(np.mean([r["charged_calls"] for r in rr])),
                       "fallback_rate": float(np.mean([r["fallback"] for r in rr])),
                       "abstention_rate": float(np.mean([r["abstained"] for r in rr])),
                       "failed_jobs": sum(r["failed_jobs"] for r in rr),
                       "mean_policy_wall_seconds": float(np.mean([r["measured_policy_wall_seconds"] for r in rr])),
                       **bootstrap(rr, draws)})
    return result


def paired(rows, draws=5000):
    outputs = []
    for split in ["test", "shift_li"]:
        for budget in [1, 2, 3, 4]:
            base = {r["pool_id"]: r for r in rows if r["split"] == split and r["arm"] == "fixed_top" and r["budget"] == budget}
            for arm in ["decision_aware", "random", "diversity", "uncertainty", "disagreement"]:
                challenger = {r["pool_id"]: r for r in rows if r["split"] == split and r["arm"] == arm and r["budget"] == budget}
                ids = sorted(set(base) & set(challenger))
                if not ids:
                    continue
                rr = []
                for i in ids:
                    a, b = challenger[i], base[i]
                    if a["charged_calls"] != b["charged_calls"]:
                        raise AssertionError("equal-budget policy comparison changed attempted costs")
                    rr.append({"group_id": a["group_id"], "success_delta": float(a["success"]) - float(b["success"]),
                               "regret_delta": a["regret_eV_atom"] - b["regret_eV_atom"]})
                groups = sorted({r["group_id"] for r in rr})
                sums = np.asarray([[sum(r["success_delta"] for r in rr if r["group_id"] == g),
                                    sum(r["regret_delta"] for r in rr if r["group_id"] == g),
                                    sum(r["group_id"] == g for r in rr)] for g in groups])
                rng = np.random.default_rng(SEED)
                bs = sums[rng.integers(len(groups), size=(draws, len(groups)))].sum(axis=1)
                outputs.append({"split": split, "arm": arm, "baseline": "fixed_top", "budget": budget,
                                "n_pools": len(ids), "n_groups": len(groups),
                                "rescues": sum(challenger[i]["success"] and not base[i]["success"] for i in ids),
                                "harms": sum(base[i]["success"] and not challenger[i]["success"] for i in ids),
                                "both_success": sum(base[i]["success"] and challenger[i]["success"] for i in ids),
                                "both_fail": sum(not base[i]["success"] and not challenger[i]["success"] for i in ids),
                                "mean_success_delta": float(np.mean([r["success_delta"] for r in rr])),
                                "mean_regret_delta_eV_atom": float(np.mean([r["regret_delta"] for r in rr])),
                                "success_delta_ci95": np.quantile(bs[:, 0] / bs[:, 2], [.025, .975]).tolist(),
                                "regret_delta_ci95_eV_atom": np.quantile(bs[:, 1] / bs[:, 2], [.025, .975]).tolist(),
                                "same_total_budget": True,
                                "interval_scope": "paired chemical-system bootstrap conditional on frozen fit, split and policies"})
    return outputs


def calibration_report(pools, refs, fitted):
    report = []
    errors = []
    for split in ["calibration", "test", "shift_li"]:
        for kind, beta in fitted["coefficients"].items():
            q = fitted["intervals"][kind]["q"]
            groups, structure_hits, widths, per_pool = {}, [], [], []
            for p in pools:
                if p["split"] != split:
                    continue
                anchor = next(c for c in p["candidates"] if c["candidate_id"] == p["anchor_id"])
                hits = []
                for c in p["candidates"]:
                    error = ((refs[c["candidate_id"]] - refs[anchor["candidate_id"]])
                             - (c["mean_eV_atom"] - anchor["mean_eV_atom"]))
                    half = q * sigma(c, beta) if q is not None else None
                    covered = half is None or abs(error) <= half + 1e-12
                    hits.append(covered)
                    structure_hits.append(covered)
                    if half is not None:
                        widths.append(2 * half)
                    if kind == "combined":
                        errors.append({"candidate_id": c["candidate_id"], "pool_id": p["pool_id"], "group_id": p["group_id"],
                                       "split": split, "anchored_residual_eV_atom": error, "interval_halfwidth_eV_atom": half,
                                       "covered": covered, "disagreement_eV_atom": c["disagreement_eV_atom"],
                                       "support_distance": c["support_distance"]})
                covered = all(hits)
                per_pool.append(covered)
                groups[p["group_id"]] = groups.get(p["group_id"], True) and covered
            report.append({"split": split, "signal": kind, "q": q, "nominal_group_coverage": .90,
                           "n_groups": len(groups), "covered_groups": sum(groups.values()),
                           "group_coverage": float(np.mean(list(groups.values()))) if groups else None,
                           "pool_coverage": float(np.mean(per_pool)) if per_pool else None,
                           "candidate_coverage": float(np.mean(structure_hits)) if structure_hits else None,
                           "mean_interval_width_eV_atom": float(np.mean(widths)) if widths else None,
                           "guarantee_applies_under_shift": False})
    return report, errors


def risk_selection(rows, pools):
    by_pool = {p["pool_id"]: p for p in pools}
    result = []
    for split in ["test", "shift_li"]:
        rr = [r for r in rows if r["split"] == split and r["arm"] == "mlip_only"]
        for signal in ["mean_disagreement_eV_atom", "max_support_distance"]:
            ordered = sorted(rr, key=lambda r: (r[signal], r["pool_id"]))
            for fraction in [.25, .5, .75, 1.]:
                n = max(1, math.ceil(fraction * len(ordered)))
                kept = ordered[:n]
                result.append({"split": split, "signal": signal, "nominal_retained_fraction": fraction,
                               "accepted_pools": len(kept), "total_pools": len(rr),
                               "threshold": kept[-1][signal] if kept else None,
                               "selective_failure_rate": float(np.mean([not r["success"] for r in kept])) if kept else None,
                               "mean_regret_eV_atom": float(np.mean([r["regret_eV_atom"] for r in kept])) if kept else None,
                               "note": "retrospective risk-coverage curve, not a test-tuned deployment threshold"})
    return result


def cost_frontier(aggregates):
    output = []
    for split in ["test", "shift_li"]:
        points = [r for r in aggregates if r["split"] == split]
        for row in points:
            dominated = any(other["mean_calls"] <= row["mean_calls"] and other["mean_regret_eV_atom"] <= row["mean_regret_eV_atom"]
                            and (other["mean_calls"] < row["mean_calls"] or other["mean_regret_eV_atom"] < row["mean_regret_eV_atom"])
                            for other in points)
            output.append({"split": split, "arm": row["arm"], "budget": row["budget"],
                           "mean_calls": row["mean_calls"], "mean_regret_eV_atom": row["mean_regret_eV_atom"],
                           "failure_rate": 1 - row["success_rate"], "nondominated_mean_regret": not dominated})
    return output


def run(prepared: Path, fit_path: Path, out: Path, workers=4, bootstrap_draws=5000):
    if out.exists():
        raise FileExistsError(f"refusing to overwrite experiment output: {out}")
    out.mkdir(parents=True)
    start = time.perf_counter()
    cpu0 = os.times()
    pools = json.loads((prepared / "pools.json").read_text())
    refs_doc = json.loads((prepared / "references_private.json").read_text())
    refs = refs_doc["labels"]
    fitted = json.loads((fit_path / "calibration.json").read_text())
    config = json.loads((prepared / "preregistered_protocol.json").read_text())
    if fitted["prepared_protocol_sha256"] != digest(prepared / "preregistered_protocol.json"):
        raise ValueError("fit and protocol mismatch")
    for key, value in json.loads((prepared / "preparation_seal.json").read_text()).items():
        if digest(prepared / key) != value:
            raise ValueError(f"prepared data integrity mismatch: {key}")
    validate_splits(pools)
    evaluation = [p for p in pools if p["split"] in {"test", "shift_li"}]
    tasks = []
    for p in evaluation:
        for arm, model in [("mlip_only", 0), ("chgnet_only", 1), ("m3gnet_only", 2), ("ensemble_only", -1)]:
            tasks.append((p, fitted, refs, arm, "mlip_only", 0, SEED, {"model_index": model}))
        tasks.append((p, fitted, refs, "full_ref", "full_ref", 999, SEED))
        for budget in config["budget_grid"]:
            for arm in ["fixed_top", "random", "diversity", "uncertainty", "disagreement", "decision_aware"]:
                tasks.append((p, fitted, refs, arm, arm, budget, SEED))
        for arm, policy, options in [
            ("gap_threshold", "gap_threshold", {}),
            ("calibrated_interval", "calibrated_interval", {}),
            ("conservative_ood", "calibrated_interval", {"ood": True}),
            ("constant_interval", "calibrated_interval", {"sigma_kind": "constant"}),
        ]:
            tasks.append((p, fitted, refs, arm, policy, 999, SEED, options))
    manifest = {"evidence_kind": "executed_labeled_replay", "protocol_sha256": digest(prepared / "preregistered_protocol.json"),
                "fitted_artifact_sha256": digest(fit_path / "calibration.json"),
                "source_hashes": {p.name: digest(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
                "n_policy_pool_runs": len(tasks), "n_evaluation_pools": len(evaluation),
                "reference_jobs_live": 0, "model_inference_live": False,
                "bootstrap_draws": bootstrap_draws, "seed": SEED,
                "worker_processes_parallel": workers, "split_counts": json.loads((prepared / "cohort_summary.json").read_text())["split_counts"],
                "protocol": config, "evaluator_labels_available_only_parent_process": True}
    dump(out / "experiment_manifest.json", manifest)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda t: score_one(*t), tasks))
    rows, traces = [x[0] for x in results], [x[1] for x in results]
    write_csv(out / "per_pool.csv", rows)
    write_jsonl_gz(out / "decision_traces.jsonl.gz", traces)
    aggregates = aggregate(rows, bootstrap_draws)
    pairs = paired(rows, bootstrap_draws)
    dump(out / "aggregates.json", aggregates)
    write_csv(out / "aggregates.csv", [{k: json.dumps(v) if isinstance(v, list) else v for k, v in r.items()} for r in aggregates])
    dump(out / "paired_results.json", pairs)
    cal, errors = calibration_report(pools, refs, fitted)
    dump(out / "calibration_coverage.json", cal)
    write_csv(out / "calibration_residuals.csv", errors)
    dump(out / "selective_risk.json", risk_selection(rows, pools))
    frontier = cost_frontier(aggregates)
    dump(out / "cost_risk_frontier.json", frontier)
    worst = sorted([r for r in rows if r["arm"] in {"mlip_only", "decision_aware", "fixed_top", "diversity", "disagreement"} and r["budget"] in {0, 2}],
                   key=lambda r: -(r["regret_eV_atom"] or 0))[:30]
    dump(out / "worst_cases.json", [{"decision": r, "pool": next(p for p in pools if p["pool_id"] == r["pool_id"]),
                                   "references_evaluator_only": {c["candidate_id"]: refs[c["candidate_id"]] for c in next(p for p in pools if p["pool_id"] == r["pool_id"])["candidates"]}}
                                  for r in worst])
    # Prespecified seed repeats, one additional charged replay per policy/pool/seed.
    random_tasks = [(p, fitted, refs, "random", "random", 2, seed) for seed in config["random_seeds"][1:] for p in evaluation]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        repeats = list(pool.map(lambda t: score_one(*t), random_tasks))
    random_rows = [r for r in rows if r["arm"] == "random" and r["budget"] == 2] + [x[0] for x in repeats]
    write_csv(out / "random_seed_repeats.csv", random_rows)
    write_jsonl_gz(out / "random_seed_traces.jsonl.gz", [x[1] for x in repeats])
    seed_summary = []
    for split in ["test", "shift_li"]:
        for seed in config["random_seeds"]:
            rr = [r for r in random_rows if r["split"] == split and r["seed"] == seed]
            seed_summary.append({"split": split, "seed": seed, "n_pools": len(rr),
                                 "success_rate": float(np.mean([r["success"] for r in rr])),
                                 "mean_regret_eV_atom": float(np.mean([r["regret_eV_atom"] for r in rr])),
                                 "charged_calls": sum(r["charged_calls"] for r in rr)})
    dump(out / "random_seed_summary.json", seed_summary)
    # Faults are explicitly synthetic on real candidate pools. Lost labels remain evaluator-known for scoring.
    failures = {cid for cid in refs if int(hashlib.sha256(("failure|" + cid).encode()).hexdigest()[:8], 16) % 10 == 0}
    stress_tasks = [(p, fitted, refs, arm, policy, budget if budget != 999 else len(p["candidates"]), SEED, {}, failures)
                    for p in evaluation for arm, policy, budget in [("fixed_top", "fixed_top", 2), ("decision_aware", "decision_aware", 2), ("conservative", "calibrated_interval", 999)]]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        stress = list(pool.map(lambda t: score_one(*t), stress_tasks))
    write_csv(out / "synthetic_failure_stress.csv", [x[0] for x in stress])
    write_jsonl_gz(out / "synthetic_failure_traces.jsonl.gz", [x[1] for x in stress])
    cpu1 = os.times()
    accounting = {"evidence_kind": "measured_local_replay_runtime", "wall_seconds": time.perf_counter() - start,
                  "parent_cpu_seconds": cpu1.user + cpu1.system - cpu0.user - cpu0.system,
                  "child_cpu_seconds": cpu1.children_user + cpu1.children_system - cpu0.children_user - cpu0.children_system,
                  "primary_policy_pool_runs": len(rows), "primary_offline_reference_attempts": sum(r["charged_calls"] for r in rows),
                  "additional_random_seed_runs": len(repeats), "additional_random_seed_attempts": sum(x[0]["charged_calls"] for x in repeats),
                  "synthetic_failure_stress_runs": len(stress), "synthetic_failure_stress_attempts": sum(x[0]["charged_calls"] for x in stress),
                  "synthetic_failed_attempts": sum(x[0]["failed_jobs"] for x in stress),
                  "live_dft_jobs": 0, "live_mlip_inference": 0, "gpu_seconds": None,
                  "reference_job_runtime": None, "mlip_inference_runtime": None,
                  "reference_queue_wait": None, "reference_batch_parallelism": None,
                  "paid_compute_dollars": 0, "dollar_savings_measured": None,
                  "local_replay_parallel_workers": workers, "available_cpu_count": os.cpu_count(),
                  "python": platform.python_version(), "note": "offline label attempts are not DFT runtime or monetary savings"}
    dump(out / "execution_accounting.json", accounting)
    primary = [r for r in pairs if r["arm"] == "decision_aware" and r["budget"] == 2]
    decision = {"evidence_kind": "executed_development_replay", "primary_endpoint": "regret at exactly two references per composition", "primary_pairs": primary,
                "promotion_gate": "retain fixed top-two unless both test and shift show no higher mean regret, no extra threshold harms, and independent fresh validation succeeds",
                "adaptive_promoted": False,
                "reason": "This experiment is a public benchmark replay with small chemistry-disjoint test groups, not independent customer validation.",
                "generation": "blocked pending trustworthy fixed-pool endpoint and compatible fresh reference validation"}
    dump(out / "decision.json", decision)
    bundle = {"schema_version": "erkidu-dashboard-results-1", "claim_type": "executed_labeled_replay",
              "cohort": json.loads((prepared / "cohort_summary.json").read_text()),
              "aggregates": aggregates, "paired": pairs, "calibration": cal,
              "frontier": frontier, "cost_accounting": accounting, "decision": decision,
              "worst_cases": json.loads((out / "worst_cases.json").read_text())[:10],
              "selective_risk": risk_selection(rows, pools), "random_seeds": seed_summary}
    dump(out / "dashboard_bundle.json", bundle)
    dump(out / "result_seal.json", {p.name: digest(p) for p in sorted(out.iterdir()) if p.is_file()})
    return {"primary_pairs": primary, "accounting": accounting}
