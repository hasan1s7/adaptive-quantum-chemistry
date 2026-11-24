"""Development-only selection, frozen holdout evaluation and traceable artifacts."""
from __future__ import annotations

import gzip
import importlib.metadata
import json
import platform
import shutil
from pathlib import Path

from .data import canonical_json, digest, load_pools, sha256_file, validate_split, write_csv, write_json, gzip_text_writer
from .oracle import PolicySession, PolicyExecutionError
from .statistics import paired_comparisons, plot_risk_calls, summarize
from .integrity import write_artifact_seal

TARGET_SUCCESS = .95
TARGET_SAVINGS = .30
# Prespecified before opening any final evaluation labels.
GAPS = [0.0, .1, .25, .5, 1.0, 2.0, 4.0, 8.0]
CAPS = [2, 4, 6, 8, 10]
INITIAL_K = [1, 2, 3, 4, 6, 8, 10]


def evaluate_pool(pool, policy, config, session, split):
    refs = pool["references"]
    if policy == "cheap_only":
        chosen = min(pool["candidates"], key=lambda c: (c["cheap_kcal"], c["candidate_id"]))["candidate_id"]
        result = {"selected_candidate": chosen, "queries": [], "observations": {}, "expensive_calls": 0,
                  "fallback": False, "stop_reason": "unverified_cheap_only_diagnostic", "policy_events": []}
    else:
        result = session.run(pool["candidates"], refs, config)
    chosen = result["selected_candidate"]
    best = min(refs, key=lambda cid: (refs[cid], cid))
    regret = max(0.0, refs[chosen] - refs[best])
    row = {"molecule_id": pool["molecule_id"], "family_id": pool["family_id"], "split": split,
           "policy": policy, "n_candidates": len(pool["candidates"]), "selected_candidate": chosen,
           "best_pool_candidate": best, "regret_kcal": regret, "success_within_1_kcal": regret <= 1 + 1e-9,
           "expensive_calls": result["expensive_calls"], "fallback": result["fallback"],
           "stop_reason": result["stop_reason"], "query_order": canonical_json([q["candidate_id"] for q in result["queries"]]),
           "verified_selection": policy != "cheap_only"}
    trace = {"molecule_id": pool["molecule_id"], "family_id": pool["family_id"], "split": split,
             "policy": policy, "config": config, "cheap_candidates": pool["candidates"], "result": result}
    return row, trace


def verify_prepared(prepared: Path):
    audit = json.loads((prepared / "audit.json").read_text())
    split = json.loads((prepared / "split_manifest.json").read_text())
    validate_split(split)
    saved_hash = split.pop("split_sha256")
    if digest(split) != saved_hash:
        raise ValueError("Split manifest content changed")
    split["split_sha256"] = saved_hash
    expected_files = {f"{part}_{table}.jsonl" for part in ("development", "evaluation") for table in ("features", "references")}
    if set(audit["prepared_files_sha256"]) != expected_files:
        raise ValueError("Prepared checksum manifest must cover both feature and reference tables in both splits")
    for name, sha in audit["prepared_files_sha256"].items():
        if sha256_file(prepared / name) != sha:
            raise ValueError(f"Prepared dataset changed: {name}")
    assignments = {a["molecule_id"]: a for a in split["assignments"]}
    seen = set()
    for part in ("development", "evaluation"):
        for line in (prepared / f"{part}_features.jsonl").read_text().splitlines():
            m = json.loads(line)
            a = assignments.get(m["molecule_id"])
            if not a or m["molecule_id"] in seen or a["split"] != part or a["family_id"] != m["family_id"] or a["n_candidates"] != len(m["candidates"]):
                raise ValueError("Prepared feature tables do not match split manifest")
            seen.add(m["molecule_id"])
    if seen != set(assignments):
        raise ValueError("Split assignments are missing feature pools")
    return audit, split


def evaluate_logged(pool, policy, config, session, split, stream):
    """A failed replay still leaves all charged jobs in the trace before aborting."""
    try:
        row, trace = evaluate_pool(pool, policy, config, session, split)
    except PolicyExecutionError as error:
        trace = {"molecule_id": pool["molecule_id"], "family_id": pool["family_id"], "split": split,
                 "policy": policy, "config": config,
                 "result": {"selected_candidate": None, "queries": error.queries,
                            "expensive_calls": error.expensive_calls, "stop_reason": "policy_execution_failure",
                            "error": str(error)}}
        for name in ("failure_stage", "cause_type", "cleanup_errors", "worker_stderr", "policy_events", "observations"):
            if hasattr(error, name):
                trace["result"][name] = getattr(error, name)
        stream.write(canonical_json(trace) + "\n")
        stream.flush()
        raise
    stream.write(canonical_json(trace) + "\n")
    return row


def select_operating_point(frontier: list[dict], minimum_success: float) -> dict | None:
    feasible = [r for r in frontier if r["success_rate"] + 1e-12 >= minimum_success]
    if not feasible:
        return None
    return min(feasible, key=lambda r: (r["total_calls"], r["p95_regret_kcal"], -r["success_rate"], r["policy"]))


def tune(prepared: Path, out: Path) -> dict:
    """Only this function chooses configs; it never loads evaluation reference rows."""
    out.mkdir(parents=True, exist_ok=True)
    frozen_path = out / "frozen_config.json"
    if frozen_path.exists():
        raise ValueError("Frozen config already exists; use a new output directory, not holdout-driven retuning")
    audit, split = verify_prepared(prepared)
    pools = load_pools(prepared, "development")
    max_n = max(len(p["candidates"]) for p in pools)
    configs = {f"fixed_k_{k:02}": {"kind": "fixed", "k": k} for k in range(1, max_n+1)}
    for k in INITIAL_K:
        if k > max_n:
            continue
        for cap in CAPS:
            if cap < k:
                continue
            for gap in GAPS:
                name = f"adaptive_k{k:02}_gap{gap:g}_cap{cap:02}"
                configs[name] = {"kind": "adaptive", "k": k, "gap": gap, "cap": cap}
    configs["full_rerank"] = {"kind": "full"}
    configs["cheap_only"] = {"kind": "diagnostic"}
    all_rows = []
    # Gzip captures every hypothetical paid job even in the methods-development grid.
    with PolicySession() as session, gzip_text_writer(out / "development_traces.jsonl.gz") as traces:
        for i, (name, config) in enumerate(configs.items()):
            for pool in pools:
                row = evaluate_logged(pool, name, config, session, "development", traces)
                all_rows.append(row)
            if (i+1) % 25 == 0:
                print(f"development: {i+1}/{len(configs)} configurations", flush=True)
    frontier = summarize(all_rows, bootstrap=0)
    write_csv(out / "development_frontier.csv", frontier)
    # Keep all actual decisions in compressed form, not merely aggregate performance.
    with gzip_text_writer(out / "development_per_molecule.jsonl.gz") as f:
        for row in all_rows:
            f.write(canonical_json(row) + "\n")
    fixed_points = [r for r in frontier if r["policy"].startswith("fixed_k_")]
    adaptive_points = [r for r in frontier if r["policy"].startswith("adaptive_k")]
    fixed = select_operating_point(fixed_points, TARGET_SUCCESS)
    adaptive = select_operating_point(adaptive_points, TARGET_SUCCESS)
    ceiling = next(r for r in frontier if r["policy"] == "full_rerank")
    fixed_config = configs[fixed["policy"]] if fixed else {"kind": "full"}
    adaptive_config = configs[adaptive["policy"]] if adaptive else {"kind": "full"}
    # Matching occurs on development risk only. Heldout risk may differ and must be reported.
    matched_target = max(TARGET_SUCCESS, adaptive["success_rate"] if adaptive else 1.0)
    matched = select_operating_point(fixed_points, matched_target)
    matched_config = configs[matched["policy"]] if matched else {"kind": "full"}
    selected_configs = {"full_rerank": {"kind": "full"}, "fixed_top_k": fixed_config,
                        "adaptive": adaptive_config, "cheap_only": {"kind": "diagnostic"}}
    comparator = "fixed_top_k"
    if matched_config != fixed_config:
        selected_configs["fixed_matched"] = matched_config
        comparator = "fixed_matched"
    # Pre-register a small descriptive holdout frontier: every fixed k, plus min-cost
    # adaptive points at predetermined development success thresholds. No holdout tuning.
    curve_configs = {name: cfg for name, cfg in configs.items() if name.startswith("fixed_k_")}
    for target in [.80, .90, .95, .975, 1.0]:
        point = select_operating_point(adaptive_points, target)
        if point:
            curve_configs[point["policy"]] = configs[point["policy"]]
    frozen = {"schema_version": 1, "dataset_kind": audit["dataset_kind"],
              "split_sha256": split["split_sha256"], "audit_sha256": sha256_file(prepared / "audit.json"),
              "prepared_files_sha256": audit["prepared_files_sha256"],
              "target_success": TARGET_SUCCESS, "target_call_savings": TARGET_SAVINGS,
              "matching_rule": "Least-cost fixed k with development success >= selected adaptive development success and >=95%; freeze before holdout labels",
              "selection_rule": "Among points >=95% development success, minimize total calls, then p95 regret, then maximize success, then lexical config name",
              "success_tolerance_kcal": 1e-9, "primary_comparator": comparator, "policies": selected_configs,
              "development_choices": {"fixed_top_k": fixed, "adaptive": adaptive, "matched_comparator": matched},
              "reduced_call_fixed_meets_dev_target": bool(fixed and fixed["total_calls"] < ceiling["total_calls"]),
              "reduced_call_adaptive_meets_dev_target": bool(adaptive and adaptive["total_calls"] < ceiling["total_calls"]),
              "holdout_curve_configs": curve_configs,
              "search_grid": {"fixed_k": list(range(1, max_n+1)), "initial_k": INITIAL_K, "gaps_kcal": GAPS, "caps": CAPS,
                              "config_count": len(configs)},
              "source_code_sha256": {p.name: sha256_file(p) for p in sorted(Path(__file__).parent.glob("*.py"))
                                     if p.name not in {"dashboard.py", "lab.py"}},
              "limitations": ["Development selection is empirical and optimistically biased by grid search; final evaluation uses held-out families.",
                              "A >=95% observed success rate is not a population guarantee."]}
    frozen["config_sha256"] = digest(frozen)
    write_json(frozen_path, frozen)
    print("Frozen development choices: " + canonical_json(selected_configs), flush=True)
    return frozen


def validate_frozen(prepared: Path, frozen: dict) -> None:
    audit, split = verify_prepared(prepared)
    copy = dict(frozen)
    saved = copy.pop("config_sha256")
    if digest(copy) != saved:
        raise ValueError("Frozen config content changed")
    if split["split_sha256"] != frozen["split_sha256"] or audit["prepared_files_sha256"] != frozen["prepared_files_sha256"]:
        raise ValueError("Frozen config does not match this data/split")
    if audit["dataset_kind"] != frozen["dataset_kind"] or sha256_file(prepared / "audit.json") != frozen["audit_sha256"]:
        raise ValueError("Dataset provenance changed after freeze")
    current_modules = {p.name for p in Path(__file__).parent.glob("*.py") if p.name not in {"dashboard.py", "lab.py"}}
    if current_modules != set(frozen["source_code_sha256"]):
        raise ValueError("Benchmark module set changed after freeze")
    for filename, sha in frozen["source_code_sha256"].items():
        if sha256_file(Path(__file__).parent / filename) != sha:
            raise ValueError(f"Benchmark code changed after freeze: {filename}; preserve the existing holdout record")


def evaluate(prepared: Path, out: Path, bootstrap: int = 5000, seed: int = 1729) -> dict:
    if type(bootstrap) is not int or bootstrap < 100:
        raise ValueError("Final evaluation requires at least 100 family bootstrap draws")
    frozen = json.loads((out / "frozen_config.json").read_text())
    validate_frozen(prepared, frozen)
    if (out / "evaluation_seal.json").exists():
        raise ValueError("Evaluation is sealed. Use 'reproduce' to verify without changing its choices.")
    # The first evaluation-label load happens AFTER the config has been written and verified.
    pools = load_pools(prepared, "evaluation")
    rows, curve_rows = [], []
    with PolicySession() as session, (out / "traces.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for name, config in frozen["policies"].items():
            for pool in pools:
                row = evaluate_logged(pool, name, config, session, "evaluation", f)
                rows.append(row)
    # A fresh session for the frozen descriptive curve, all jobs charged independently.
    with PolicySession() as session, gzip_text_writer(out / "heldout_frontier_traces.jsonl.gz") as f:
        for name, config in frozen["holdout_curve_configs"].items():
            for pool in pools:
                row = evaluate_logged(pool, name, config, session, "evaluation", f)
                curve_rows.append(row)
    aggregate = summarize(rows, bootstrap, seed)
    frontier = summarize(curve_rows, bootstrap, seed)
    comparisons = paired_comparisons(rows, bootstrap, seed)
    if frozen["primary_comparator"] == "fixed_matched":
        pair_rows = [dict(r, policy="fixed_top_k" if r["policy"] == "fixed_matched" else r["policy"])
                     for r in rows if r["policy"] in {"adaptive", "fixed_matched"}]
        for comparison in paired_comparisons(pair_rows, bootstrap, seed):
            if comparison["policy"] == "adaptive":
                comparison["comparator"] = "fixed_matched"
                comparisons.append(comparison)
    write_csv(out / "per_molecule.csv", rows)
    write_csv(out / "aggregate.csv", aggregate)
    write_csv(out / "paired_comparisons.csv", comparisons)
    write_csv(out / "heldout_frontier.csv", frontier)
    for name in ("audit.json", "split_manifest.json", "families.csv", "excluded_molecules.csv", "unmatched_rows.csv"):
        if (prepared / name).exists():
            shutil.copy2(prepared / name, out / name)
    audit, split = verify_prepared(prepared)
    table = {r["policy"]: r for r in aggregate}
    adaptive, comparator = table["adaptive"], table[frozen["primary_comparator"]]
    pair = next(r for r in comparisons if r["policy"] == "adaptive" and r["comparator"] == frozen["primary_comparator"])
    observed_risk_ok = adaptive["success_rate"] >= TARGET_SUCCESS
    comparator_risk_ok = comparator["success_rate"] >= TARGET_SUCCESS
    observed_match = adaptive["success_rate"] + 1e-12 >= comparator["success_rate"]
    observed_saving = pair["relative_call_savings"] >= TARGET_SAVINGS
    decision = {"dataset_kind": audit["dataset_kind"], "evaluation_families": adaptive["n_families"],
                "evaluation_molecules": adaptive["n_molecules"], "primary_comparator": frozen["primary_comparator"],
                "adaptive_success_rate": adaptive["success_rate"], "baseline_success_rate": comparator["success_rate"],
                "relative_call_savings": pair["relative_call_savings"],
                "observed_95pct_success_met": observed_risk_ok,
                "frozen_comparator_95pct_success_met": comparator_risk_ok,
                "target_risk_comparison_available": observed_risk_ok and comparator_risk_ok,
                "observed_risk_no_worse_than_frozen_comparator": observed_match,
                "observed_30pct_call_savings_met": observed_saving,
                "observed_joint_target_met": observed_risk_ok and comparator_risk_ok and observed_match and observed_saving,
                "all_marginal_interval_checks_pass": bool(adaptive["success_rate_ci_low"] is not None
                    and adaptive["success_rate_ci_low"] >= TARGET_SUCCESS
                    and comparator["success_rate_ci_low"] >= TARGET_SUCCESS
                    and pair["delta_success_rate_ci_low"] >= 0
                    and pair["relative_call_savings_ci_low"] >= TARGET_SAVINGS),
                "paired_difference": pair,
                "interpretation": "Offline fixed-pool selection replay. No wall-clock, live quantum, or shape-probe benefit measured.",
                "next_sprint_rule": "If simple cheap-energy policy does not achieve matched risk and 30% savings, shape acquisition remains a testable hypothesis; freeze a new evaluation set before tuning future probes. If it does, require incremental value over this simple baseline."}
    write_json(out / "decision.json", decision)
    plot_risk_calls(frontier + aggregate, out / "risk_vs_calls.png",
                    f"{'SYNTHETIC FIXTURE' if audit['dataset_kind']=='synthetic' else 'Folmsbee–Hutchison real replay'} · frozen holdout", adaptive["n_families"])
    environment = {"python": platform.python_version(), "platform": platform.platform(),
                   "packages": {p: importlib.metadata.version(p) for p in ["numpy", "matplotlib", "rdkit", "pillow"]},
                   "bootstrap": bootstrap, "bootstrap_seed": seed,
                   "bootstrap_unit": "chemical family; paired, all molecules retained; molecule-weighted metrics; 95% percentile CIs"}
    write_json(out / "environment.json", environment)
    report = report_markdown(audit, split, frozen, aggregate, decision, environment)
    (out / "REPORT.md").write_text(report, encoding="utf-8", newline="\n")
    if audit["dataset_kind"] == "synthetic":
        fixture_checks(prepared, out)
    write_artifact_seal(out, config_sha256=frozen["config_sha256"], split_sha256=split["split_sha256"])
    print(canonical_json(decision), flush=True)
    return decision


def fixture_checks(prepared, out):
    pools = load_pools(prepared, "development")
    results = []
    with PolicySession() as session:
        for name in ("escalation_helps", "escalation_wastes"):
            pool = next(p for p in pools if p["molecule_id"].endswith(name))
            for policy, cfg in [("fixed_top_k", {"kind": "fixed", "k": 1}),
                                ("adaptive", {"kind": "adaptive", "k": 1, "gap": .5, "cap": 2})]:
                row, trace = evaluate_pool(pool, policy, cfg, session, "development")
                results.append({"scenario": name, "row": row, "trace": trace})
    help_rows = [r["row"] for r in results if r["scenario"] == "escalation_helps"]
    waste_rows = [r["row"] for r in results if r["scenario"] == "escalation_wastes"]
    assert help_rows[1]["regret_kcal"] < help_rows[0]["regret_kcal"]
    assert waste_rows[1]["regret_kcal"] == waste_rows[0]["regret_kcal"] and waste_rows[1]["expensive_calls"] > waste_rows[0]["expensive_calls"]
    write_json(out / "fixture_case_checks.json", results)


def report_markdown(audit, split, frozen, aggregate, decision, environment):
    def pct(v): return f"{v*100:.2f}%"
    lines = ["# Adaptive Quantum Chemistry — executed benchmark", "",
             f"**Dataset: {audit['dataset_kind'].upper()}.** Offline fixed-pool replay; no quantum jobs, wall-clock savings, or shape-probe claims.", "",
             f"Held out **{decision['evaluation_molecules']} molecules in {decision['evaluation_families']} families** after freezing choices on development data.", "",
             "| Policy | Success ≤1 kcal/mol (95% family CI) | Median regret | P95 regret | Max regret | Calls / molecule | Total calls | Fallback |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in aggregate:
        ci = f"{pct(r['success_rate_ci_low'])}–{pct(r['success_rate_ci_high'])}"
        lines.append(f"| {r['policy']} | {pct(r['success_rate'])} ({ci}) | {r['median_regret_kcal']:.4f} | {r['p95_regret_kcal']:.4f} | {r['max_regret_kcal']:.4f} | {r['mean_calls']:.3f} | {r['total_calls']} | {pct(r['fallback_rate'])} |")
    pair = decision["paired_difference"]
    lines += ["", "All regrets are kcal/mol. Cheap-only has **zero verification**, so it is a diagnostic and excluded from paid comparisons.", "",
              "## Decision", "", f"Frozen matched-risk comparator: **{decision['primary_comparator']}**.", "",
              f"Adaptive call savings: **{pct(decision['relative_call_savings'])}**, 95% paired-family CI {pct(pair['relative_call_savings_ci_low'])} to {pct(pair['relative_call_savings_ci_high'])}.", "",
              f"Adaptive minus comparator success: {100*pair['delta_success_rate']:.2f} percentage points (95% CI {100*pair['delta_success_rate_ci_low']:.2f} to {100*pair['delta_success_rate_ci_high']:.2f}).",
              f"Observed joint target met: **{decision['observed_joint_target_met']}**. All marginal interval checks pass: **{decision['all_marginal_interval_checks_pass']}**. This is not a simultaneous 95% confidence statement or a calibrated risk guarantee.", "",
              f"Both frozen policies meet the observed 95% target: **{decision['target_risk_comparison_available']}**. If false, call differences are descriptive and do not establish savings at the target risk.", "",
              "Risk matching is selected on development data. A holdout risk mismatch is reported, never repaired by choosing a different test-set point.", "",
              f"A reduced-call fixed baseline met the development 95% target: **{frozen['reduced_call_fixed_meets_dev_target']}**.", "",
              "## Frozen policies", "", "```json", json.dumps(frozen["policies"], indent=2), "```", "",
              "## Data and split", "", "```json", json.dumps(split["counts"], indent=2), "```", "",
              f"Split hash: `{split['split_sha256']}`. Config hash: `{frozen['config_sha256']}`.", "",
              f"Uncertainty: {environment['bootstrap']} paired family-cluster bootstrap resamples, seed {environment['bootstrap_seed']}. Point estimates weight each molecule equally. Intervals do not account for new-data selection bias or certify a population risk bound; all-success cells can yield degenerate empirical intervals.", "",
              "## Scope and limitations", ""]
    lines += [f"- {x}" for x in audit.get("source_limits", [])]
    lines += ["- The heldout frontier is descriptive: its finite configurations were frozen using development data before evaluation. No holdout result changes the primary choices.",
              "- This evaluation set is now observed. Future shape probes require new held-out groups or an explicitly exploratory comparison; do not reuse this result for tuning and call it untouched.", "",
              "## Reproduction artifacts", "",
              "`per_molecule.csv`, `aggregate.csv`, `paired_comparisons.csv`, `traces.jsonl`, `development_traces.jsonl.gz`, `frozen_config.json`, `split_manifest.json`, `evaluation_seal.json`, `risk_vs_calls.png`, and the local `dashboard.html`.", ""]
    return "\n".join(lines)
