"""Descriptive, post-run diagnostics. Never retunes the frozen policies."""
from __future__ import annotations
import csv
import json
from collections import Counter
from pathlib import Path
import sys
import numpy as np
from scipy.stats import spearmanr
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from erkidu_decision.prepare import dump

ROOT = Path(__file__).resolve().parents[1]
base = ROOT / "results/decision_engine"
prepared = base / "oxide_prepared"
run = base / "oxide_run"
pools = json.loads((prepared / "pools.json").read_text())
refs = json.loads((prepared / "references_private.json").read_text())["labels"]
rows = list(csv.DictReader((run / "per_pool.csv").open()))
aggregates = json.loads((run / "aggregates.json").read_text())
exclusions = json.loads((prepared / "exclusions.json").read_text())
correlation = {}
for split in ["train", "calibration", "test", "shift_li"]:
    errors, disagreement, distance = [], [], []
    for p in pools:
        if p["split"] != split:
            continue
        anchor = next(c for c in p["candidates"] if c["candidate_id"] == p["anchor_id"])
        for c in p["candidates"]:
            if c["candidate_id"] == anchor["candidate_id"]:
                continue
            true_gap = refs[c["candidate_id"]] - refs[anchor["candidate_id"]]
            predicted_gap = np.asarray(c["predictions_eV_atom"]) - anchor["predictions_eV_atom"]
            errors.append(predicted_gap - true_gap)
            disagreement.append(c["disagreement_eV_atom"])
            distance.append(c["support_distance"])
    e = np.asarray(errors)
    correlation[split] = {"n_nonanchor_contrasts": len(e), "models": ["MACE-MP0", "CHGNet", "M3GNet"],
                          "error_correlation": np.corrcoef(e.T).tolist(),
                          "spearman_disagreement_abs_mace_error": float(spearmanr(disagreement, np.abs(e[:, 0])).statistic),
                          "spearman_support_distance_abs_mace_error": float(spearmanr(distance, np.abs(e[:, 0])).statistic),
                          "scope": "post-run descriptive; contrasts within pools correlated; no independent-sample p-values"}
failure_rows = list(csv.DictReader((run / "synthetic_failure_stress.csv").open()))
stress = []
for split in ["test", "shift_li"]:
    for arm in ["fixed_top", "decision_aware", "conservative"]:
        rr = [r for r in failure_rows if r["split"] == split and r["arm"] == arm]
        stress.append({"evidence_kind": "synthetic_failure_on_real_replay", "split": split, "arm": arm,
                       "pools": len(rr), "accepted": sum(r["accepted"] == "True" for r in rr),
                       "abstained": sum(r["abstained"] == "True" for r in rr),
                       "incomplete_reference": sum(r["status"] == "incomplete_reference" for r in rr),
                       "failed_attempts": sum(int(r["failed_jobs"]) for r in rr),
                       "attempted_calls": sum(int(r["charged_calls"]) for r in rr),
                       "successful_final_decisions": sum(r["success"] == "True" for r in rr)})

near_ties, nontrivial = {}, []
for split in ["test", "shift_li"]:
    rr = [r for r in rows if r["split"] == split and r["arm"] == "mlip_only"]
    near_ties[split] = {"near_tie_pools_at_2meV": sum(r["near_tie"] == "True" for r in rr), "all_pools": len(rr),
                       "pool_sizes": dict(Counter(int(r["candidate_count"]) for r in rr))}
    for arm in ["fixed_top", "decision_aware", "random", "diversity"]:
        rr = [r for r in rows if r["split"] == split and r["arm"] == arm and r["budget"] == "2" and int(r["candidate_count"]) > 2]
        nontrivial.append({"split": split, "arm": arm, "n_pools_with_more_than_two_candidates": len(rr),
                           "successes": sum(r["success"] == "True" for r in rr),
                           "mean_regret_eV_atom": float(np.mean([float(r["regret_eV_atom"]) for r in rr])) if rr else None})
def lookup(arm, budget, split="test"):
    return next(r for r in aggregates if r["split"] == split and r["arm"] == arm and r["budget"] == budget)
ei, m3, top = lookup("decision_aware", 2), lookup("m3gnet_only", 0), lookup("fixed_top", 2)
break_even = (m3["mean_regret_eV_atom"] - ei["mean_regret_eV_atom"]) / (ei["mean_calls"] - m3["mean_calls"])
interpretation = {
    "evidence_kind": "post_run_development_interpretation", "adaptive_promoted": False,
    "comparison": "one SnO2 rescue versus fixed MACE top-two; all other primary paired regret differences exactly zero",
    "strongest_tolerance_baseline": "prespecified M3GNet-only arm has30/30 tolerance success at0 reference acquisitions",
    "baseline_selection_caveat": "M3GNet was not selected on test for deployment; its arm was prespecified. Choosing it now creates a new policy requiring fresh evaluation.",
    "business_decision": "retain reliability/provenance evaluation layer; do not sell demonstrated adaptive compute savings",
    "mean_loss_break_even_vs_m3_eV_atom_per_extra_reference": break_even,
    "mean_loss_break_even_vs_m3_meV_atom_per_extra_reference": 1000 * break_even,
    "binary_loss_break_even": "both succeed30/30; any positive extra reference cost favors M3GNet-only on observed tolerance loss",
    "physical_precision_warning": "Sub-meV mean differences and0.03meV near ties are below source convergence scale; do not infer physical superiority.",
    "promotion_limits": ["one discordant primary chemical system", "shared pretrained support", "public retrospective labels",
                          "10 shifted groups,8 two-candidate pools", "no live inference/DFT runtime", "missing model convergence logs"],
    "exclusions": dict(Counter(e["reason"] for e in exclusions)),
    "near_ties": near_ties, "nontrivial_pool_results": nontrivial,
    "error_correlation": correlation, "synthetic_failure_summary": stress,
}
dump(base / "post_run_diagnostics.json", interpretation)
print(json.dumps(interpretation, indent=2))
