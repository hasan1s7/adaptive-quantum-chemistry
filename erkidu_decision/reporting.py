"""Local-only, dependency-free dashboard and exportable scientific frontier.

The frozen dashboard bundle remains unchanged. Saved traces and generation
receipts supply an explanatory layer; embedded downloads work without sibling
files or a network. All cost scenarios remain explicitly hypothetical.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import math
from pathlib import Path

LABELS = {
    "mlip_only": "Frozen MACE-MP-0", "chgnet_only": "Frozen CHGNet",
    "m3gnet_only": "Frozen M3GNet", "ensemble_only": "Three-model mean",
    "full_ref": "Full reference", "fixed_top": "Fixed top-k",
    "random": "Random acquisition", "diversity": "Descriptor diversity",
    "uncertainty": "Predicted error scale", "disagreement": "Model disagreement",
    "decision_aware": "Decision-aware EI", "gap_threshold": "Energy-gap fallback",
    "calibrated_interval": "Calibrated interval", "conservative_ood": "Interval + support fallback",
    "constant_interval": "Constant-scale interval",
}
COLORS = {
    "mlip_only": "#168b7a", "m3gnet_only": "#249bb3", "full_ref": "#748391", "fixed_top": "#2766c2",
    "random": "#83909d", "diversity": "#8d62b1", "uncertainty": "#b98b23",
    "disagreement": "#b95585", "decision_aware": "#da6435",
    "calibrated_interval": "#458a9d", "conservative_ood": "#42694d",
}
PASSES = {
    "mlip_only": 1, "chgnet_only": 1, "m3gnet_only": 1, "ensemble_only": 3,
    "full_ref": 0, "fixed_top": 1, "random": 0, "diversity": 1,
    "uncertainty": 3, "disagreement": 3, "decision_aware": 3,
    "gap_threshold": 1, "calibrated_interval": 3, "conservative_ood": 3,
    "constant_interval": 1,
}
SPLIT_LABELS = {"test": "Chemistry-disjoint test", "shift_li": "Lithium-family shift"}


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def cost_sensitivity(bundle: dict) -> dict:
    """Scenario frontier: eV/atom regret + query and inference-pass penalties."""
    result = {
        "evidence_kind": "hypothetical_cost_scenarios_on_executed_replay",
        "objective": "mean_regret_eV_atom + lambda_ref*mean_reference_label_attempts + eta_mlip*model_passes",
        "lambda_ref_unit": "eV/atom regret-equivalent penalty per reference-relaxation label attempt",
        "eta_mlip_unit": "eV/atom regret-equivalent penalty per model inference pass per pool",
        "model_pass_assumption": PASSES,
        "limits": [
            "No live DFT or MLIP runtime was measured; weights are not prices or demonstrated savings.",
            "One model pass means producing predictions for a complete candidate pool, not one atom or structure.",
            "Descriptor, calibration, integration, and batch scheduling costs are omitted from this scenario.",
            "Abstaining arms are excluded from scalar risk comparison because no abstention penalty was specified.",
            "Results use point estimates; uncertainty does not disappear at a scenario break-even.",
        ],
        "grid": [], "comparisons_to_fixed_top_two": [], "decision_aware_vs_frozen_m3gnet": [],
    }
    for split in ("test", "shift_li"):
        rows = [r for r in bundle.get("aggregates", []) if r.get("split") == split
                and _finite(r.get("mean_regret_eV_atom")) and r.get("abstention_rate", 0) == 0]
        base = next((r for r in rows if r["arm"] == "fixed_top" and r["budget"] == 2), None)
        for lam in (0., 1e-5, 1e-4, 1e-3, 1e-2, 1e-1):
            for eta in (0., 1e-6, 1e-4, 1e-3, 1e-2):
                scored = [(r["mean_regret_eV_atom"] + lam*r["mean_calls"] + eta*PASSES.get(r["arm"], 3), r)
                          for r in rows]
                if not scored:
                    continue
                best = min(x[0] for x in scored)
                winners = [{"arm": r["arm"], "budget": r["budget"], "mean_calls": r["mean_calls"],
                            "mean_regret_eV_atom": r["mean_regret_eV_atom"]}
                           for score, r in scored if abs(score - best) < 1e-12]
                result["grid"].append({"split": split, "lambda_ref": lam, "eta_mlip": eta,
                                       "minimum_objective_eV_atom": best, "tied_winners": winners})
        free = next((r for r in rows if r["arm"] == "m3gnet_only"), None)
        adaptive = next((r for r in rows if r["arm"] == "decision_aware" and r["budget"] == 2), None)
        if free is not None and adaptive is not None:
            dr_free = adaptive["mean_regret_eV_atom"] - free["mean_regret_eV_atom"]
            dq_free = adaptive["mean_calls"] - free["mean_calls"]
            result["decision_aware_vs_frozen_m3gnet"].append({
                "split": split, "adaptive_successes": adaptive["successes"],
                "frozen_m3gnet_successes": free["successes"], "n_pools": free["n_pools"],
                "tolerance_eV_atom": 0.020, "delta_mean_regret_eV_atom": dr_free,
                "extra_mean_reference_labels": dq_free, "extra_model_passes": 2,
                "lambda_break_even_at_zero_model_overhead": (-dr_free / dq_free if dq_free else None),
                "condition": "EI favors the mean-regret objective only if lambda_ref*extra_labels + eta_mlip*2 < -delta_regret",
                "qualification": "No extra threshold successes; sub-near-tie numerical differences do not establish physical or commercial value."
            })
        if base is None:
            continue
        for row in rows:
            dr = row["mean_regret_eV_atom"] - base["mean_regret_eV_atom"]
            dq = row["mean_calls"] - base["mean_calls"]
            dp = PASSES.get(row["arm"], 3) - PASSES["fixed_top"]
            if abs(dq) < 1e-12:
                lam_star = None
                condition = "reference price cancels at equal label count"
            else:
                lam_star = -dr / dq
                condition = "lambda_ref above threshold" if dq < 0 else "lambda_ref below threshold"
            result["comparisons_to_fixed_top_two"].append({
                "split": split, "arm": row["arm"], "budget": row["budget"],
                "reference_arm": "fixed_top", "reference_budget": 2,
                "delta_mean_regret_eV_atom": dr, "delta_mean_calls": dq,
                "delta_model_passes": dp,
                "lambda_break_even_at_zero_mlip_penalty": lam_star,
                "candidate_favored_when": condition,
                "eta_break_even_at_equal_reference_count": (-dr / dp if abs(dq) < 1e-12 and dp else None),
                "dominated_for_all_nonnegative_cost_weights": dr >= 0 and dq >= 0 and dp >= 0
                    and (dr > 0 or dq > 0 or dp > 0),
                "comparison_rule": "candidate favored iff delta_regret + lambda_ref*delta_calls + eta_mlip*delta_passes < 0",
            })
    return result


def _plot(bundle: dict, run: Path) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.labelcolor": "#253344", "text.color": "#253344",
                         "xtick.color": "#526171", "ytick.color": "#526171",
                         "svg.fonttype": "none", "svg.hashsalt": "erkidu-decision-frontier-v1"})
    fig, axes = plt.subplots(1, 2, figsize=(13.6, 6.2), constrained_layout=False)
    fig.patch.set_facecolor("#fcfcfa")
    curve_arms = ["fixed_top", "decision_aware", "random", "diversity", "uncertainty", "disagreement"]
    for ax, split in zip(axes, ("test", "shift_li")):
        ax.set_facecolor("#fcfcfa")
        rows = [r for r in bundle.get("aggregates", []) if r.get("split") == split]
        for arm in curve_arms:
            rr = sorted([r for r in rows if r["arm"] == arm], key=lambda r: r["budget"])
            if not rr:
                continue
            xx = [r["mean_calls"] for r in rr]
            yy = [1000*r["mean_regret_eV_atom"] for r in rr]
            ax.plot(xx, yy, color=COLORS[arm], linewidth=2.3 if arm in {"fixed_top", "decision_aware"} else 1.3,
                    marker="o", markersize=4, label=LABELS[arm], alpha=1 if arm in {"fixed_top", "decision_aware"} else .8)
            primary = next((r for r in rr if r["budget"] == 2), None)
            if primary:
                bounds = primary.get("mean_regret_eV_atom_ci95")
                if bounds and all(_finite(x) for x in bounds):
                    center = 1000*primary["mean_regret_eV_atom"]
                    error = [[max(0, center - 1000*bounds[0])], [max(0, 1000*bounds[1] - center)]]
                    ax.errorbar([primary["mean_calls"]], [center], yerr=error, fmt="none", ecolor=COLORS[arm],
                                capsize=2, alpha=.6, linewidth=1.1)
                ax.scatter(primary["mean_calls"], 1000*primary["mean_regret_eV_atom"], s=47,
                           facecolor=COLORS[arm], edgecolor="white", linewidth=1, zorder=5)
        for arm, marker in [("mlip_only", "D"), ("m3gnet_only", "P"), ("full_ref", "s")]:
            rr = next((r for r in rows if r["arm"] == arm), None)
            if rr:
                ax.scatter(rr["mean_calls"], 1000*rr["mean_regret_eV_atom"], marker=marker,
                           s=56, color=COLORS[arm], label=LABELS[arm], zorder=6)
        frontier = [r for r in bundle.get("frontier", []) if r.get("split") == split and r.get("nondominated_mean_regret")]
        frontier = sorted({(r["mean_calls"], 1000*r["mean_regret_eV_atom"]) for r in frontier})
        if frontier:
            ax.plot([r[0] for r in frontier], [r[1] for r in frontier], color="#253344", linestyle=":", linewidth=1,
                    alpha=.6, zorder=1)
        count = next((r for r in rows if r["arm"] == "fixed_top" and r["budget"] == 2), None)
        subtitle = f"{count['n_pools']} pools · {count['n_groups']} chemical systems" if count else "No evaluated pools"
        ax.set_title(SPLIT_LABELS[split] + "\n" + subtitle, loc="left", fontsize=12, fontweight="medium", pad=13)
        ax.set_xlabel("Historical reference-relaxation labels / pool", labelpad=11)
        ax.set_ylabel("Mean selection regret (meV/atom)", labelpad=10)
        ax.set_xlim(left=-.15)
        ax.set_ylim(bottom=-.8)
        ax.grid(axis="y", color="#dde2e6", linewidth=.6)
        ax.set_axisbelow(True)
    handles, names = axes[0].get_legend_handles_labels()
    handles.append(Line2D([0], [0], color="#253344", ls=":", lw=1))
    names.append("Observed mean-regret frontier")
    fig.legend(handles, names, loc="lower center", bbox_to_anchor=(.5, .105), ncol=3, frameon=False, fontsize=9)
    fig.suptitle("Erkidu · the cost–risk question", x=.065, y=.98, ha="left", fontsize=19, fontweight="medium")
    fig.text(.065, .926, "Executed WBM relaxed-energy replay. Larger markers and error bars: two-label operating point.", fontsize=10, color="#526171")
    fig.text(.065, .032, "95% intervals resample chemical systems; unresolved shared lineage limits independence. Counts are not DFT time or dollars.\n"
             "Same-composition energy only. Sub-2 meV/atom differences are within the declared near-tie scale; no fresh DFT or force validation.",
             fontsize=8.5, color="#526171", linespacing=1.5)
    fig.subplots_adjust(left=.075, right=.985, top=.80, bottom=.34, wspace=.24)
    output = []
    for extension in ("png", "svg"):
        path = run / f"cost_risk_frontier.{extension}"
        fig.savefig(path, dpi=220, facecolor=fig.get_facecolor(), metadata={"Title": "Erkidu reference-label cost–risk frontier", "Date": None, "Creator": "Erkidu reporting.py"} if extension == "svg" else None)
        output.append(path.name)
    plt.close(fig)
    return output


TEMPLATE_PATH = Path(__file__).with_name("dashboard_template.html")


def _json_script(value) -> str:
    return json.dumps(value, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c").replace("&", "\\u0026")


def _presentation_data(bundle: dict, run: Path) -> tuple[dict, dict]:
    """Read existing evidence for explanations; never recalculate a policy."""
    inputs = {}
    source_case = next((entry for entry in bundle["worst_cases"] if entry["pool"]["pool_id"] == "O2Sn1"), None)
    case = {"status": "unavailable", "reason": "The saved SnO2 case is unavailable in this result bundle."}
    trace_path = run / "decision_traces.jsonl.gz"
    if source_case is not None and trace_path.exists():
        selected = {}
        wanted = {("m3gnet_only", 0), ("fixed_top", 2), ("decision_aware", 2), ("constant_interval", 999)}
        with gzip.open(trace_path, "rt") as stream:
            for line in stream:
                record = json.loads(line)
                row = record["evaluation_after_stop"]
                if row["pool_id"] == "O2Sn1" and (row["arm"], row["budget"]) in wanted:
                    selected[row["arm"]] = record
        if set(selected) == {arm for arm, _ in wanted}:
            case = {"status": "available", "title": "SnO₂", "scope": "Fixed test case; two-query histories, independent of the overview controls.",
                    "pool": source_case["pool"], "references_evaluator_only": source_case["references_evaluator_only"],
                    "traces": selected, "reference_unit": "eV/atom", "comparison_unit": "meV/atom",
                    "tolerance_eV_atom": 0.020, "near_tie_eV_atom": 0.002}
        else:
            case["reason"] = "The saved case does not contain all required policy traces."
        inputs["decision_traces.jsonl.gz"] = hashlib.sha256(trace_path.read_bytes()).hexdigest()
    generation_path = run.parent / "generation" / "summary.json"
    generation = {"status": "not_in_this_bundle", "note": "No generation receipt was supplied to this renderer."}
    if generation_path.exists():
        generation = json.loads(generation_path.read_text())
        inputs["../generation/summary.json"] = hashlib.sha256(generation_path.read_bytes()).hexdigest()
    return {"schema_version": "erkidu-decision-view-2", "case": case, "generation": generation,
            "scope": "Explanations of saved results; no new model, query, or scientific evaluation.",
            "source_inputs": dict(inputs)}, inputs


def _embedded_files(run: Path) -> tuple[list[dict], dict]:
    """Preserve exact downloadable bytes, with no relative-URL dependency."""
    specs = [
        ("dashboard_bundle.json", "Result bundle", "application/json"),
        ("per_pool.csv", "Every primary policy decision", "text/csv"),
        ("decision_traces.jsonl.gz", "Primary decision traces", "application/gzip"),
        ("random_seed_traces.jsonl.gz", "Additional random-seed traces", "application/gzip"),
        ("synthetic_failure_traces.jsonl.gz", "Synthetic-failure traces", "application/gzip"),
        ("cost_sensitivity.json", "Hypothetical cost scenarios", "application/json"),
        ("cost_risk_frontier.svg", "Scientific mean-regret figure", "image/svg+xml"),
        ("../generation/candidate_records.jsonl", "Geometry-proposal records", "application/x-ndjson"),
    ]
    result, inputs = [], {}
    for relative, title, mime in specs:
        path = run / relative
        if not path.exists():
            continue
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        result.append({"name": path.name, "title": title, "mime": mime, "bytes": len(raw),
                       "sha256": digest, "base64": base64.b64encode(raw).decode("ascii")})
        # The cost and plot exports are newly derived reporting outputs, not source evidence.
        if relative not in {"cost_sensitivity.json", "cost_risk_frontier.svg"}:
            inputs[relative] = digest
    return result, inputs


def view_contract(bundle: dict, presentation: dict) -> dict:
    """A compact data contract for the decision-first UI and its checks."""
    comparisons = []
    for split in ("test", "shift_li"):
        for budget in (1, 2, 3, 4):
            rows = []
            for arm, cap in (("m3gnet_only", 0), ("fixed_top", budget), ("decision_aware", budget)):
                row = next((r for r in bundle["aggregates"] if r["split"] == split and r["arm"] == arm and r["budget"] == cap), None)
                if row is None:
                    raise ValueError(f"missing primary comparison: {split}/{arm}/{cap}")
                rows.append({k: row[k] for k in ("arm", "budget", "n_pools", "successes", "charged_calls", "mean_calls")})
            pair = next((r for r in bundle["paired"] if r["split"] == split and r["arm"] == "decision_aware" and r["budget"] == budget), None)
            if pair is None:
                raise ValueError(f"missing paired comparison: {split}/{budget}")
            comparisons.append({"split": split, "budget": budget, "arms": rows, "rescues": pair["rescues"], "harms": pair["harms"]})
    case = presentation["case"]
    return {"schema_version": "erkidu-ui-contract-2", "default_split": "test", "default_budget": 2,
            "default_endpoint": "tolerance_miss_rate", "tolerance_eV_atom": .020,
            "global_control_scope": "Split and paid-query cap update all three summary cards and the paired comparison.",
            "walkthrough_scope": "The SnO2 walkthrough is explicitly a fixed two-query test case.",
            "comparisons": comparisons,
            "case_query_ids": ({arm: [q["candidate_id"] for q in record["result"]["queries"]] for arm, record in case["traces"].items()} if case["status"] == "available" else {}),
            "generation_status": presentation["generation"].get("status"),
            "reference_revelation_stages": ["none", "first queried reference", "two separate queried histories", "evaluator-only full labels after stopping"],
            "external_dependencies": [], "relative_download_links": False}


def render(run: Path) -> dict:
    run = Path(run)
    source = run / "dashboard_bundle.json"
    raw = source.read_bytes()
    bundle = json.loads(raw)
    required = {"aggregates", "paired", "calibration", "frontier", "cost_accounting", "decision", "worst_cases"}
    if not required <= set(bundle):
        raise ValueError(f"incomplete dashboard bundle: {sorted(required-set(bundle))}")
    scenario = cost_sensitivity(bundle)
    _write_json(run / "cost_sensitivity.json", scenario)
    plots = _plot(bundle, run)
    presentation, inputs = _presentation_data(bundle, run)
    assets, file_inputs = _embedded_files(run)
    inputs.update(file_inputs)
    contract = view_contract(bundle, presentation)
    _write_json(run / "ui_contract.json", contract)
    template = TEMPLATE_PATH.read_text()
    replacements = {"__BUNDLE__": _json_script(bundle), "__PRESENTATION__": _json_script(presentation),
                    "__ASSETS__": _json_script(assets), "__LABELS__": _json_script(LABELS),
                    "__COLORS__": _json_script(COLORS), "__PASSES__": _json_script(PASSES)}
    page = template
    for marker, value in replacements.items():
        if marker not in template:
            raise ValueError(f"missing dashboard template marker: {marker}")
        page = page.replace(marker, value)
    if any(marker in page for marker in replacements):
        raise ValueError("unresolved dashboard template marker")
    (run / "dashboard.html").write_text(page)
    files = ["dashboard.html", "ui_contract.json", "cost_sensitivity.json", *plots]
    manifest = {"evidence_kind": "renderer_of_executed_replay_plus_hypothetical_cost_scenarios",
                "input": source.name, "input_sha256": hashlib.sha256(raw).hexdigest(),
                "additional_input_sha256": inputs,
                "renderer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "template": TEMPLATE_PATH.name, "template_sha256": hashlib.sha256(TEMPLATE_PATH.read_bytes()).hexdigest(),
                "network_dependencies": [], "scientific_results_modified": False,
                "files": {name: {"bytes": (run/name).stat().st_size, "sha256": hashlib.sha256((run/name).read_bytes()).hexdigest()} for name in files}}
    _write_json(run / "reporting_manifest.json", manifest)
    return manifest
