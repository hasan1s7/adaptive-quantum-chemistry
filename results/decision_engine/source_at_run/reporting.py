"""Local-only, dependency-free dashboard and exportable scientific frontier.

The input contract is dashboard_bundle.json. No data, labels, or execution state
are fetched by the renderer. All scenario costs are explicitly hypothetical.
"""
from __future__ import annotations

import hashlib
import html
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


_TEMPLATE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><title>Erkidu — reference decisions</title>
<style>
:root{--bg:#f7f7f2;--panel:#fff;--ink:#192a36;--muted:#5b6c76;--line:#dce2df;--accent:#c3572e;--blue:#2766c2;--good:#168b7a;--soft:#eff3ef;--focus:#996700;--shadow:0 8px 30px #132e3b06}
body[data-theme=dark]{--bg:#111a22;--panel:#18242d;--ink:#edf2ed;--muted:#a9b9c2;--line:#33434d;--accent:#ffae83;--blue:#91b8ff;--good:#82d4be;--soft:#202f39;--focus:#f1cf7c;--shadow:0 8px 35px #0002}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}a{color:var(--blue)}button,input,select{font:inherit}button,select{min-height:42px;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:9px;padding:9px 13px}button{cursor:pointer}button:hover{background:var(--soft)}button:focus-visible,select:focus-visible,input:focus-visible,summary:focus-visible,circle:focus-visible{outline:3px solid var(--focus);outline-offset:3px}.wrap{max-width:1240px;margin:auto;padding:28px 34px 52px}.top{display:flex;justify-content:space-between;align-items:center;gap:16px}.brand{font-size:22px;letter-spacing:-.7px;font-weight:650}.brand span{color:var(--muted);font-size:12px;letter-spacing:1.7px;display:block;font-weight:500}.tools{display:flex;gap:9px}.hero{padding:48px 0 27px;max-width:970px}.kicker{font-size:11px;letter-spacing:1.7px;text-transform:uppercase;color:var(--good);font-weight:750}.hero h1{font-size:clamp(32px,4.9vw,59px);line-height:1.08;letter-spacing:-2.2px;font-weight:540;max-width:870px;margin:15px 0 19px}.hero p{font-size:17px;color:var(--muted);max-width:800px;margin:0}.badge{display:inline-flex;border:1px solid var(--line);padding:4px 10px;border-radius:20px;font-size:11px;font-weight:650;color:var(--muted)}.notice{border-left:3px solid var(--accent);background:var(--soft);padding:14px 18px;margin:16px 0 26px;border-radius:0 8px 8px 0}.notice strong{font-weight:650}.notice p{margin:5px 0 0;color:var(--muted);font-size:13px}.controls{display:flex;align-items:end;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:20px}.control-group{display:flex;gap:12px;flex-wrap:wrap}label{display:flex;flex-direction:column;gap:5px;font-size:12px;font-weight:600;color:var(--muted)}select{min-width:165px;font-size:14px}.small{font-size:12px;color:var(--muted)}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:13px;margin:0 0 20px}.metric{padding:18px 19px;background:var(--panel);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow)}.metric .label{font-size:12px;color:var(--muted)}.metric .value{font-size:29px;line-height:1.2;letter-spacing:-.8px;margin:8px 0}.metric .foot{font-size:11px;color:var(--muted)}.panel{min-width:0;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:23px;margin-bottom:20px;box-shadow:var(--shadow)}.panel-head{display:flex;justify-content:space-between;align-items:start;gap:12px;margin-bottom:16px}.panel h2{font-size:20px;line-height:1.25;margin:0 0 6px;font-weight:580;letter-spacing:-.4px}.panel h3{font-size:15px;margin:0 0 10px}.panel-head p,.section-note{font-size:12px;color:var(--muted);margin:0;max-width:760px}.chart-shell{position:relative}.chart-shell svg{width:100%;height:auto;display:block;overflow:visible}.chart-shell .axis{stroke:var(--line)}.chart-shell text{fill:var(--muted);font:11px ui-sans-serif,system-ui,sans-serif}.chart-shell .axis-label{font-size:12px}.chart-shell .point{cursor:pointer;stroke:var(--panel);stroke-width:1.8}.legend{display:flex;gap:9px 18px;flex-wrap:wrap;margin:0 0 10px}.legend span{font-size:11px;display:inline-flex;align-items:center;gap:6px;color:var(--muted)}.dot{width:9px;height:9px;border-radius:50%;display:inline-block}.chart-readout{min-height:48px;padding:11px 14px;border:1px solid var(--line);border-radius:8px;background:var(--soft);font-size:12px;color:var(--muted);margin-top:12px}.table-scroll{overflow:auto}table{width:100%;border-collapse:collapse;text-align:left;font-variant-numeric:tabular-nums;font-size:12px;white-space:nowrap}th{font-size:10px;text-transform:uppercase;letter-spacing:.7px;color:var(--muted);font-weight:650;vertical-align:bottom;padding:11px 12px;border-bottom:1px solid var(--line)}td{padding:12px;border-bottom:1px solid var(--line)}th:first-child,td:first-child{padding-left:0}tbody tr:last-child td{border-bottom:0}tbody tr.highlight{background:var(--soft)}.num{text-align:right}.sub{display:block;font-size:10px;color:var(--muted);margin-top:2px}.pill{display:inline-block;border:1px solid var(--line);padding:1px 6px;border-radius:4px;font-size:10px;color:var(--muted);margin-left:5px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:20px}.grid2 .panel{margin-bottom:20px}.paired-tiles{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:16px 0}.paired-tile{padding:15px;background:var(--soft);border-radius:9px}.paired-tile strong{display:block;font-size:29px;font-weight:550;line-height:1.2}.paired-tile span{font-size:12px;color:var(--muted)}.positive{color:var(--good)}.negative{color:var(--accent)}.line-item{display:flex;justify-content:space-between;gap:16px;border-bottom:1px solid var(--line);padding:10px 0;font-size:12px}.line-item:last-child{border:0}.line-item span{color:var(--muted)}.line-item strong{font-weight:570;text-align:right}.cost-sliders{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin:20px 0 15px}input[type=range]{width:100%;accent-color:var(--accent);min-height:36px}.winner{border:1px solid var(--line);border-radius:9px;background:var(--soft);padding:14px 17px;font-size:14px}.winner strong{display:block;font-size:20px;font-weight:550;letter-spacing:-.3px}.caveat{font-size:11px;color:var(--muted);margin-top:12px;line-height:1.7}.case{border-top:1px solid var(--line)}.case:first-child{border-top:0}.case summary{cursor:pointer;list-style:none;padding:16px 0;display:flex;justify-content:space-between;gap:15px;align-items:center;font-size:13px}.case summary::-webkit-details-marker{display:none}.case summary::after{content:'+';font-size:20px;color:var(--muted)}.case[open] summary::after{content:'−'}.case summary strong{font-weight:600}.case-body{padding:0 0 18px}.case .meta{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:12px}.case .table-scroll{margin:8px 0}.case p{color:var(--muted);font-size:12px}.empty{padding:20px;color:var(--muted)}footer{font-size:11px;color:var(--muted);border-top:1px solid var(--line);padding-top:22px;display:flex;justify-content:space-between;gap:24px;flex-wrap:wrap}footer p{max-width:830px;margin:0}.visually-hidden{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:850px){.wrap{padding:22px}.metrics{grid-template-columns:1fr 1fr}.grid2{grid-template-columns:1fr;gap:0}.hero{padding-top:36px}.hero h1{letter-spacing:-1.2px}.panel{padding:18px}.cost-sliders{grid-template-columns:1fr;gap:10px}}@media(max-width:480px){.wrap{padding:18px 13px}.top{align-items:start}.brand{font-size:19px}.brand span{font-size:9px}.tools{gap:5px}.tools button{font-size:11px;padding:7px 10px}.hero h1{font-size:35px;letter-spacing:-1.2px}.hero p{font-size:15px}.metric{padding:15px}.metric .value{font-size:25px}.control-group{width:100%}.control-group label{flex:1;min-width:130px}select{min-width:0;width:100%}.panel h2{font-size:18px}.panel-head{flex-direction:column}.chart-shell{margin-left:-10px;margin-right:-5px}.case summary{font-size:12px}.case summary .sub{max-width:230px}}
@media(prefers-reduced-motion:no-preference){button,.metric{transition:background .15s,border-color .15s}}@media print{body{--bg:#fff;--panel:#fff;--ink:#111;--muted:#444;--line:#bbb;--soft:#eee}.tools,.controls,.cost-sliders{display:none}.wrap{max-width:none;padding:0}.panel{break-inside:avoid;box-shadow:none}.hero{padding-top:20px}.grid2{display:block}}
</style></head><body><div class="wrap">
<header class="top"><div class="brand">Erkidu<span>REFERENCE DECISIONS</span></div><div class="tools"><button id="download" type="button">Export data</button><button id="theme" type="button" aria-label="Switch color theme">Theme</button></div></header>
<main><section class="hero"><div class="kicker">Executed labeled replay · energy-only · local</div><h1>What did the next reference buy?</h1><p>A frozen pool. A known budget. A decision that can be checked. Compare which structures deserve a reference relaxation, then inspect the mistakes that matter.</p></section>
<div class="notice" role="note"><strong id="conclusion">Loading the executed result.</strong><p>Published WBM relaxed-energy labels are replayed here. No fresh DFT jobs or MLIP inference were run. This evaluates selection within a compatible composition; forces, synthesis and application performance remain untested.</p></div>
<div class="controls"><div class="control-group"><label>Evaluation slice<select id="split"><option value="test">Chemistry-disjoint test</option><option value="shift_li">Lithium-family shift</option></select></label><label>Acquisition budget<select id="budget"><option value="2">Two labels / pool</option><option value="1">One label / pool</option><option value="3">Three labels / pool</option><option value="4">Four labels / pool</option><option value="all">All operating points</option></select></label><label>Chart endpoint<select id="metric"><option value="regret">Mean regret</option><option value="miss">Miss rate &gt; 20 meV/atom</option></select></label></div><div class="small" id="cohort-note"></div></div>
<div class="metrics" id="metrics"></div>
<section class="panel"><div class="panel-head"><div><h2>The reference cost–risk frontier</h2><p>Lower and farther left is better. Lines join fixed-budget operating points; large points show the selected budget. Hover or focus a point for exact values.</p></div><span class="badge">Counts ≠ DFT runtime</span></div><div class="legend" id="legend"></div><div class="chart-shell" id="chart"></div><div class="chart-readout" id="chart-readout" aria-live="polite">Use the table below for every operating point and its uncertainty.</div></section>
<section class="panel"><div class="panel-head"><div><h2>Same evidence, different acquisition rules</h2><p>Success means an accepted choice within 20 meV/atom of the pool’s reference minimum. Brackets show descriptive 95% chemical-system bootstrap intervals. Values below the declared 2 meV/atom near-tie scale should not be interpreted as a physical precision claim.</p></div></div><div class="table-scroll"><table><caption class="visually-hidden">Policy results for the selected slice and acquisition budget.</caption><thead><tr><th>Policy</th><th class="num">Labels</th><th class="num">Success</th><th class="num">Mean regret<span class="sub">meV/atom</span></th><th class="num">Reference attempts</th><th class="num">Fallback</th><th class="num">Abstain</th></tr></thead><tbody id="results"></tbody></table></div></section>
<div class="grid2"><section class="panel"><div class="panel-head"><div><h2>Did adaptation rescue or harm?</h2><p>Decision-aware EI versus fixed top-k, paired on the same pools at the same reference budget.</p></div></div><div id="paired"></div></section><section class="panel"><div class="panel-head"><div><h2>Whole-system interval coverage</h2><p>One maximum-residual score per chemical system. Nominal coverage: 90% under exchangeability assumptions.</p></div></div><div class="table-scroll"><table><caption class="visually-hidden">Calibration coverage by uncertainty signal.</caption><thead><tr><th>Signal</th><th class="num">Systems covered</th><th class="num">Coverage</th><th class="num">Width<span class="sub">meV/atom</span></th></tr></thead><tbody id="calibration"></tbody></table></div><p class="caveat">Observed coverage under shift is a measurement, not a guarantee. Shared model training and WBM prototype lineage can violate independence. Candidate coverage is not interchangeable with whole-system coverage.</p></section></div>
<section class="panel"><div class="panel-head"><div><h2>When would the preferred policy change?</h2><p>Explore a hypothetical scalar objective: mean regret + a penalty for each reference label + a penalty for each required model pass.</p></div><span class="badge">Scenario, not measured prices</span></div><div class="cost-sliders"><label>Reference-label penalty <span id="refvalue"></span><input id="refweight" type="range" min="0" max="50" step="0.1" value="5" aria-label="Regret-equivalent reference-label penalty in meV per atom"></label><label>Model-pass penalty <span id="modelvalue"></span><input id="modelweight" type="range" min="0" max="10" step="0.05" value="0.25" aria-label="Regret-equivalent model-pass penalty in meV per atom"></label></div><div class="winner" id="winner" aria-live="polite"></div><p class="caveat">A pass produces predictions for a candidate pool. Fixed top-k uses one model; combined uncertainty and EI use three. Descriptor, integration and scheduling costs are omitted. Scores use point estimates, including numerical differences below the 2 meV/atom near-tie scale. No price or willingness to pay was measured. M3GNet needs no reference query to meet the declared 20 meV/atom success endpoint in these slices.</p></section>
<div class="grid2"><section class="panel"><div class="panel-head"><div><h2>Measured local execution</h2><p>These timings belong to the replay harness, including worker-process overhead.</p></div></div><div id="runtime"></div></section><section class="panel"><div class="panel-head"><div><h2>What the evidence supports</h2><p>Research-grade decision evaluation with explicit limits.</p></div></div><div class="line-item"><span>Result class</span><strong>Executed public-label replay</strong></div><div class="line-item"><span>Physical target</span><strong>Same-composition relaxed energy</strong></div><div class="line-item"><span>Force support</span><strong>Unsupported in this benchmark</strong></div><div class="line-item"><span>Fresh DFT validation</span><strong>Not run</strong></div><div class="line-item"><span>Independent customer validation</span><strong>Not run</strong></div><div class="line-item"><span>Generation</span><strong>Deferred behind fixed-pool gate</strong></div><p class="caveat">Published model predictions may have related training exposure. The chemistry split alone does not establish independent structural families. No candidate is presented as a new material.</p></section></div>
<section class="panel"><div class="panel-head"><div><h2>Failure records worth opening</h2><p>Largest recorded regrets in the selected slice. Reference columns below are evaluator-only evidence revealed after the policy stopped.</p></div><span class="badge">Inspect the counterexample</span></div><div id="cases"></div></section>
</main><footer><p>This view is generated entirely from <a href="dashboard_bundle.json">dashboard_bundle.json</a>. The companion bundle includes the manifests, acquisition traces, per-pool records, exclusions, calibration and source checksums. The local code and data govern every value shown here.</p><div><a href="cost_risk_frontier.svg">Exportable figure</a> · <a href="cost_sensitivity.json">Cost scenarios</a></div></footer>
</div><script id="bundle" type="application/json">__BUNDLE__</script><script>
'use strict';
const D=JSON.parse(document.getElementById('bundle').textContent), L=__LABELS__, C=__COLORS__, P=__PASSES__;
const $=id=>document.getElementById(id), esc=x=>String(x??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const n=(x,d=1)=>Number.isFinite(x)?Number(x).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d}):'—';
const pct=x=>Number.isFinite(x)?n(100*x,1)+'%':'—', meV=x=>Number.isFinite(x)?n(1000*x,Math.abs(1000*x)>0&&Math.abs(1000*x)<.1?3:2):'—';
const split=()=>$('split').value, budget=()=>$('budget').value, current=()=>D.aggregates.filter(r=>r.split===split());
const primary=arm=>current().find(r=>r.arm===arm&&r.budget===2), color=arm=>C[arm]||'#8995a3';
const ci=(a,scale=1,d=2)=>Array.isArray(a)?'['+a.map(x=>n(x*scale,d)).join(', ')+']':'—';
function setTheme(v){document.body.dataset.theme=v;$('theme').textContent=v==='dark'?'Light':'Dark';try{localStorage.setItem('erkidu-theme',v)}catch(e){}}
let theme;try{theme=localStorage.getItem('erkidu-theme')}catch(e){}setTheme(theme||((window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light'));
$('theme').addEventListener('click',()=>setTheme(document.body.dataset.theme==='dark'?'light':'dark'));
$('download').addEventListener('click',()=>{const u=URL.createObjectURL(new Blob([JSON.stringify(D,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download='erkidu-dashboard-results.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)});
function metricCard(label,value,foot){return '<div class="metric"><div class="label">'+label+'</div><div class="value">'+value+'</div><div class="foot">'+foot+'</div></div>'}
function renderSummary(){const b=primary('fixed_top'), a=primary('decision_aware'), free=current().find(r=>r.arm==='m3gnet_only'), pair=D.paired.find(r=>r.split===split()&&r.arm==='decision_aware'&&r.budget===2);if(!b||!a){$('metrics').innerHTML='';return;}
$('cohort-note').textContent=b.n_pools+' pools · '+b.n_groups+' chemical systems';
$('metrics').innerHTML=metricCard('Frozen M3GNet successes',(free?free.successes+' / '+free.n_pools:'—'),'Zero reference labels · tolerance 20 meV/atom')+metricCard('Fixed top-two successes',b.successes+' / '+b.n_pools,n(b.charged_calls,0)+' reference-label attempts')+metricCard('Decision-aware successes',a.successes+' / '+a.n_pools,n(a.charged_calls,0)+' labels · three-model uncertainty')+metricCard('Paired rescues / harms',(pair?pair.rescues+' / '+pair.harms:'—'),'EI versus fixed top-two · same label budget');
const rescueCount=pair?.rescues??0, rescueText=rescueCount===1?'One rescue':rescueCount===0?'No rescue':rescueCount+' rescues';$('conclusion').textContent=rescueText+'; the business case is unproven. Frozen M3GNet passes '+(free?free.successes+' of '+free.n_pools:'the available')+' pools without a reference query at the declared tolerance.';
}
const chartArms=['fixed_top','decision_aware','random','diversity','uncertainty','disagreement','mlip_only','m3gnet_only','full_ref'];
function renderChart(){const rows=current().filter(r=>chartArms.includes(r.arm));const miss=$('metric').value==='miss', yVal=r=>miss?100*(1-r.success_rate):1000*r.mean_regret_eV_atom;
const w=Math.max(320,Math.min(1040,$('chart').clientWidth||1040)),h=350,m={l:w<600?52:72,r:24,t:18,b:60},pw=w-m.l-m.r,ph=h-m.t-m.b;
const xmax=Math.max(1,...rows.map(r=>r.mean_calls))*1.06,ymax=Math.max(miss?2:1,...rows.map(yVal))*1.16;
const xx=x=>m.l+x/xmax*pw,yy=y=>m.t+ph-y/ymax*ph;
let s='<svg viewBox="0 0 '+w+' '+h+'" role="img" aria-labelledby="chart-title chart-desc"><title id="chart-title">Reference-label cost and selection risk</title><desc id="chart-desc">'+esc(miss?'Miss rate versus mean reference labels per pool.':'Mean regret in millielectronvolts per atom versus mean reference labels per pool.')+' Exact values are also in the results table.</desc>';
for(let i=0;i<=4;i++){const y=ymax*i/4;s+='<line class="axis" x1="'+m.l+'" y1="'+yy(y)+'" x2="'+(w-m.r)+'" y2="'+yy(y)+'"/><text text-anchor="end" x="'+(m.l-12)+'" y="'+(yy(y)+4)+'">'+n(y,ymax<10?1:0)+'</text>';}
for(let i=0;i<=5;i++){const x=xmax*i/5;s+='<text text-anchor="middle" x="'+xx(x)+'" y="'+(h-m.b+23)+'">'+n(x,1)+'</text>';}
s+='<text class="axis-label" text-anchor="middle" x="'+(m.l+pw/2)+'" y="'+(h-8)+'">Historical reference-relaxation labels / pool</text><text class="axis-label" transform="translate(17 '+(m.t+ph/2)+') rotate(-90)" text-anchor="middle">'+(miss?'Miss rate (%)':'Mean regret (meV/atom)')+'</text>';
for(const arm of chartArms){const rr=rows.filter(r=>r.arm===arm).sort((a,b)=>a.budget-b.budget);if(rr.length>1)s+='<polyline fill="none" stroke="'+color(arm)+'" stroke-width="'+(['fixed_top','decision_aware'].includes(arm)?2.8:1.4)+'" opacity=".8" points="'+rr.map(r=>xx(r.mean_calls)+','+yy(yVal(r))).join(' ')+'"/>';
for(const r of rr){const active=budget()==='all'||String(r.budget)===budget()||[0,999].includes(r.budget);const label=(L[r.arm]||r.arm)+'; '+(r.budget===999?'variable/full pool':r.budget+' label cap')+'; mean '+n(r.mean_calls,3)+' labels; regret '+meV(r.mean_regret_eV_atom)+' meV/atom; success '+pct(r.success_rate)+'; regret CI '+ci(r.mean_regret_eV_atom_ci95,1000)+'.';s+='<circle class="point" tabindex="0" data-readout="'+esc(label)+'" aria-label="'+esc(label)+'" cx="'+xx(r.mean_calls)+'" cy="'+yy(yVal(r))+'" r="'+(active?5.7:3)+'" opacity="'+(active?1:.38)+'" fill="'+color(arm)+'"><title>'+esc(label)+'</title></circle>';}}
s+='</svg>';$('chart').innerHTML=s;$('legend').innerHTML=chartArms.map(arm=>'<span><i class="dot" style="background:'+color(arm)+'"></i>'+esc(L[arm])+'</span>').join('');document.querySelectorAll('.point').forEach(el=>{const fn=()=>{$('chart-readout').textContent=el.dataset.readout};el.addEventListener('mouseenter',fn);el.addEventListener('focus',fn);el.addEventListener('click',fn)});}
function renderTable(){const rr=current().filter(r=>budget()==='all'||String(r.budget)===budget()||[0,999].includes(r.budget)).sort((a,b)=>({m3gnet_only:0,fixed_top:1,decision_aware:2,mlip_only:3}[a.arm]??9)-({m3gnet_only:0,fixed_top:1,decision_aware:2,mlip_only:3}[b.arm]??9)||a.mean_calls-b.mean_calls||a.mean_regret_eV_atom-b.mean_regret_eV_atom);
$('results').innerHTML=rr.map(r=>'<tr class="'+(['m3gnet_only','fixed_top','decision_aware'].includes(r.arm)?'highlight':'')+'"><td>'+esc(L[r.arm]||r.arm)+(r.arm==='decision_aware'?'<span class="pill">challenger</span>':'')+'</td><td class="num">'+(r.budget===999?'variable':r.budget)+'</td><td class="num">'+r.successes+'/'+r.n_pools+'<span class="sub">'+pct(r.success_rate)+'</span></td><td class="num">'+meV(r.mean_regret_eV_atom)+'<span class="sub">'+ci(r.mean_regret_eV_atom_ci95,1000)+'</span></td><td class="num">'+n(r.charged_calls,0)+'<span class="sub">'+n(r.mean_calls,3)+' / pool</span></td><td class="num">'+pct(r.fallback_rate)+'</td><td class="num">'+pct(r.abstention_rate)+'</td></tr>').join('');}
function line(label,value){return '<div class="line-item"><span>'+label+'</span><strong>'+value+'</strong></div>'}
function renderPaired(){const k=budget()==='all'?2:Number(budget()), r=D.paired.find(r=>r.split===split()&&r.arm==='decision_aware'&&r.budget===k);if(!r){$('paired').innerHTML='<p class="empty">No matched pair for this operating point.</p>';return;}$('paired').innerHTML='<div class="paired-tiles"><div class="paired-tile"><strong class="positive">'+r.rescues+'</strong><span>rescued pools</span></div><div class="paired-tile"><strong class="negative">'+r.harms+'</strong><span>harmed pools</span></div></div>'+line('Both successful',r.both_success)+line('Both missed',r.both_fail)+line('Mean regret difference',meV(r.mean_regret_delta_eV_atom)+' meV/atom')+line('95% paired interval',ci(r.regret_delta_ci95_eV_atom,1000)+' meV/atom')+line('Matched budget',k+' labels / pool')+'<p class="caveat">Negative regret differences favor EI. Intervals condition on the frozen fit, split and policies; they do not establish independent replication.</p>';}
function renderCalibration(){const names={constant:'Constant scale',disagreement:'Model disagreement',distance:'Support distance',combined:'Combined signals'};$('calibration').innerHTML=D.calibration.filter(r=>r.split===split()).map(r=>'<tr class="'+(r.signal==='combined'?'highlight':'')+'"><td>'+esc(names[r.signal]||r.signal)+'</td><td class="num">'+r.covered_groups+'/'+r.n_groups+'</td><td class="num">'+pct(r.group_coverage)+'</td><td class="num">'+(r.q===null?'∞':meV(r.mean_interval_width_eV_atom))+'</td></tr>').join('');}
function renderCosts(){const ref=Number($('refweight').value),mlip=Number($('modelweight').value);$('refvalue').textContent=n(ref,2)+' meV/atom per label';$('modelvalue').textContent=n(mlip,2)+' meV/atom per pool pass';let rr=current().filter(r=>Number.isFinite(r.mean_regret_eV_atom)&&r.abstention_rate===0).map(r=>({r,score:1000*r.mean_regret_eV_atom+ref*r.mean_calls+mlip*(P[r.arm]??3)}));rr.sort((a,b)=>a.score-b.score||a.r.mean_calls-b.r.mean_calls);if(!rr.length)return;const best=rr[0],ties=rr.filter(x=>Math.abs(x.score-best.score)<1e-9),title=[...new Set(ties.map(x=>(L[x.r.arm]||x.r.arm)+(x.r.budget>0&&x.r.budget<999?' · cap '+x.r.budget:'')))];$('winner').innerHTML='<span class="small">Lowest scenario score across all operating points in this slice</span><strong>'+esc(title.slice(0,3).join(' / '))+(title.length>3?' + '+(title.length-3)+' tied':'')+'</strong><span class="small">'+n(best.score,3)+' meV/atom equivalent · '+n(best.r.mean_calls,3)+' reference labels / pool · '+(P[best.r.arm]??3)+' model passes</span>';}
function renderRuntime(){const a=D.cost_accounting;$('runtime').innerHTML=line('Replay wall time',n(a.wall_seconds,2)+' s')+line('Parent + child CPU',n(a.parent_cpu_seconds+a.child_cpu_seconds,2)+' s')+line('Local worker parallelism',a.local_replay_parallel_workers)+line('Primary policy–pool runs',n(a.primary_policy_pool_runs,0))+line('Primary offline reference attempts',n(a.primary_offline_reference_attempts,0))+line('Live DFT jobs / live MLIP inference',a.live_dft_jobs+' / '+a.live_mlip_inference)+line('New paid compute spend','$'+n(a.paid_compute_dollars,2))+line('Reference queue / job runtime','Not measured')+line('Dollar savings','Not measured');}
function renderCases(){const cases=D.worst_cases.filter(x=>x.decision.split===split());$('cases').innerHTML=cases.length?cases.map(({decision:r,pool,references_evaluator_only:refs})=>'<details class="case"><summary><div><strong>'+esc(r.pool_id)+' · '+esc(L[r.arm]||r.arm)+'</strong><span class="sub">'+esc(r.selected_id||'abstained')+' · '+esc(r.group_id)+'</span></div><span>'+meV(r.regret_eV_atom)+' meV/atom</span></summary><div class="case-body"><div class="meta"><span class="badge">'+r.charged_calls+' reference attempts</span><span class="badge">'+esc(r.status)+'</span><span class="badge">'+esc(r.evidence_kind)+'</span></div><p>Stop reason: '+esc(r.reason)+'. Trace ID: '+esc(r.trace_id)+'. Reference values below are the evaluator’s record, not the policy’s pre-query knowledge.</p><div class="table-scroll"><table><thead><tr><th>Candidate</th><th class="num">Frozen prediction<span class="sub">relative eV/atom</span></th><th class="num">Reference<span class="sub">corrected eV/atom</span></th><th class="num">Disagreement<span class="sub">meV/atom</span></th><th class="num">Support distance</th></tr></thead><tbody>'+pool.candidates.map(c=>'<tr class="'+(c.candidate_id===r.selected_id?'highlight':'')+'"><td>'+esc(c.candidate_id)+(c.candidate_id===r.selected_id?' <span class="pill">selected</span>':'')+'</td><td class="num">'+n(c.mean_eV_atom,6)+'</td><td class="num">'+n(refs[c.candidate_id],6)+'</td><td class="num">'+meV(c.disagreement_eV_atom)+'</td><td class="num">'+n(c.support_distance,5)+'</td></tr>').join('')+'</tbody></table></div><p>Predictions use a fixed pre-query within-pool offset; references use the declared corrected formation-energy convention. Compare rankings within this composition. The two columns do not share an absolute energy zero.</p></div></details>').join(''):'<p class="empty">No record from this slice appears in the bundle’s global worst-case shortlist. See worst_cases.json and per_pool.csv for the full run.</p>';}
function render(){renderSummary();renderChart();renderTable();renderPaired();renderCalibration();renderCosts();renderRuntime();renderCases();}
['split','budget','metric'].forEach(id=>$(id).addEventListener('change',render));['refweight','modelweight'].forEach(id=>$(id).addEventListener('input',renderCosts));if(window.addEventListener)window.addEventListener('resize',renderChart,{passive:true});render();
</script></body></html>'''


def render(run: Path) -> dict:
    run = Path(run)
    source = run / "dashboard_bundle.json"
    raw = source.read_bytes()
    bundle = json.loads(raw)
    required = {"aggregates", "paired", "calibration", "frontier", "cost_accounting", "decision", "worst_cases"}
    if not required <= set(bundle):
        raise ValueError(f"incomplete dashboard bundle: {sorted(required-set(bundle))}")
    data = json.dumps(bundle, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c").replace("&", "\\u0026")
    page = _TEMPLATE.replace("__BUNDLE__", data).replace("__LABELS__", json.dumps(LABELS)).replace("__COLORS__", json.dumps(COLORS)).replace("__PASSES__", json.dumps(PASSES))
    # Fail fast on accidental placeholders, then write only derived local reports.
    if any(x in page for x in ("__BUNDLE__", "__LABELS__", "__COLORS__", "__PASSES__")):
        raise ValueError("unresolved dashboard placeholder")
    (run / "dashboard.html").write_text(page)
    _write_json(run / "cost_sensitivity.json", cost_sensitivity(bundle))
    files = ["dashboard.html", "cost_sensitivity.json", *_plot(bundle, run)]
    manifest = {"evidence_kind": "renderer_of_executed_replay_plus_hypothetical_cost_scenarios",
                "input": source.name, "input_sha256": hashlib.sha256(raw).hexdigest(),
                "renderer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "network_dependencies": [], "files": {name: {"bytes": (run/name).stat().st_size,
                    "sha256": hashlib.sha256((run/name).read_bytes()).hexdigest()} for name in files}}
    _write_json(run / "reporting_manifest.json", manifest)
    return manifest
