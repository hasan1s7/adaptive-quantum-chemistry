#!/usr/bin/env python3
"""Inspect every saved decision trace without running a policy or reference query.

The audit checks serialized state, accounting, scoring, summaries and seals.
It does not acquire labels, refit a model, or rerun the scientific experiment.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal
from fractions import Fraction
import gzip
import hashlib
import json
import math
from pathlib import Path
import random
import re
import statistics

import numpy as np

PUBLIC_KEYS = {"candidate_id", "mean_eV_atom", "sigma_eV_atom", "disagreement_eV_atom", "support_distance", "descriptor"}
SNAP_KEYS = PUBLIC_KEYS - {"descriptor"}
FIXED = {"fixed_top", "random", "diversity", "uncertainty", "disagreement", "decision_aware"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    def bad(value):
        raise ValueError(f"nonfinite JSON literal: {value}")
    return json.loads(Path(path).read_text(), parse_constant=bad)


def close(a, b, tol=1e-11):
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(close(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b))
    if type(a) is bool or type(b) is bool:
        return type(a) is bool and type(b) is bool and a == b
    if isinstance(a, (float, int)) and isinstance(b, (float, int)):
        return math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=tol, abs_tol=tol)
    return a == b


def percentile(values, p):
    return float(np.quantile(values, p)) if values else None


def audit(run: Path, prepared: Path, fitted_path: Path, out: Path):
    root = Path(__file__).resolve().parents[1]
    counts = Counter()
    errors = []
    notes = []
    def check(name, truth, context=None):
        counts[name] += 1
        if not truth:
            errors.append({"check": name, "context": context})
    pools = {p["pool_id"]: p for p in load(prepared / "pools.json")}
    refs_doc = load(prepared / "references_private.json")
    refs = refs_doc["labels"]
    fitted = load(fitted_path / "calibration.json")
    manifest = load(run / "experiment_manifest.json")
    protocol = manifest["protocol"]["protocol_id"]
    accounting = load(run / "execution_accounting.json")
    check("reference_unit", refs_doc["unit"] == "eV/atom")
    check("reference_protocol", refs_doc["protocol_id"] == protocol)
    check("complete_evaluator_truth", all(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v) for v in refs.values()))
    for filename, expected in load(run / "result_seal.json").items():
        check("result_seal", (run / filename).exists() and sha(run / filename) == expected, filename)
    captured_sources = {}
    for filename, expected in manifest["source_hashes"].items():
        current_source = root / "erkidu_decision" / filename
        captured_source = current_source
        # Presentation can evolve without rewriting a completed experiment.
        # Only the renderer has this explicit archival path; scientific source
        # mismatches remain failures. The frozen seal still fixes expected bytes.
        if filename == "reporting.py" and current_source.exists() and sha(current_source) != expected:
            captured_source = root / "results/decision_engine/source_at_run/reporting.py"
        matched = captured_source.exists() and sha(captured_source) == expected
        check("captured_source_hash", matched, filename)
        captured_sources[filename] = {"path": str(captured_source.relative_to(root)),
                                      "expected_sha256": expected, "matched": matched,
                                      "current_source": captured_source == current_source}
    for filename, expected in load(prepared / "preparation_seal.json").items():
        check("preparation_seal", (prepared / filename).exists() and sha(prepared / filename) == expected, filename)
    check("fit_input_identity", fitted["prepared_protocol_sha256"] == sha(prepared / "preregistered_protocol.json"))
    check("manifest_fit_identity", manifest["fitted_artifact_sha256"] == sha(fitted_path / "calibration.json"))

    file_specs = [
        ("decision_traces.jsonl.gz", "primary", 1320),
        ("random_seed_traces.jsonl.gz", "random_repeats", 280),
        ("synthetic_failure_traces.jsonl.gz", "synthetic_faults", 120),
    ]
    traces, categories, rows_by_category = {}, {}, defaultdict(list)
    trace_files = {}
    interval_events = []
    certificate_failures = []
    query_statuses = Counter()
    all_attempts = 0
    for filename, category, expected_count in file_specs:
        with gzip.open(run / filename, "rt") as stream:
            records = [json.loads(line) for line in stream]
        trace_files[filename] = {"sha256": sha(run / filename), "runs": len(records)}
        check("expected_trace_file_run_count", len(records) == expected_count, filename)
        for trace in records:
            tid = trace["trace_id"]
            check("trace_id_unique", tid not in traces, tid)
            traces[tid], categories[tid] = trace, category
            row, payload, result = trace["evaluation_after_stop"], trace["public_payload"], trace["result"]
            rows_by_category[category].append(row)
            check("trace_id_row_identity", row["trace_id"] == tid, tid)
            expected_tid = hashlib.sha256(f"{row['pool_id']}|{row['arm']}|{row['budget']}|{row['seed']}|{category=='synthetic_faults'}".encode()).hexdigest()[:20]
            check("trace_id_reconstructs", tid == expected_tid, tid)
            pool = pools[row["pool_id"]]
            candidates = {c["candidate_id"]: c for c in payload["candidates"]}
            known = {c["candidate_id"]: c for c in pool["candidates"]}
            check("trace_roster_identity", set(candidates) == set(known), tid)
            check("split_and_group_identity", row["split"] == pool["split"] and row["group_id"] == pool["group_id"], tid)
            check("public_payload_no_references", set(payload) <= {"budget", "candidates", "energy_unit", "gap_threshold_eV_atom", "group_id", "interval_q", "ood_cutoff", "policy", "pool_id", "protocol_id", "seed", "tolerance_eV_atom"}, tid)
            check("trace_unit_protocol", payload["energy_unit"] == result["energy_unit"] == "eV/atom" and payload["protocol_id"] == protocol, tid)
            check("visibility_boundary_record", result.get("visibility_boundary") == "isolated_interpreter_jsonl_public_payload_and_queried_responses", tid)
            check("historical_cost_unit", result["query_cost_unit"] == "historical_reference_relaxation_label_attempt", tid)
            check("payload_row_budget_seed_policy", payload["budget"] == row["budget"] and payload["seed"] == row["seed"] and payload["policy"] == row["policy"], tid)
            model = {"chgnet_only": 1, "m3gnet_only": 2, "ensemble_only": -1}.get(row["arm"], 0)
            kind = "constant" if row["arm"] == "constant_interval" else "combined"
            beta = fitted["coefficients"][kind]
            for cid, candidate in candidates.items():
                origin = known[cid]
                mean = statistics.mean(origin["predictions_eV_atom"]) if model == -1 else origin["predictions_eV_atom"][model]
                scale = math.sqrt(max(1e-6, beta[0]+beta[1]*origin["disagreement_eV_atom"]**2+beta[2]*origin["support_distance"]**2))
                expected = {"candidate_id": cid, "mean_eV_atom": mean, "sigma_eV_atom": scale,
                            "disagreement_eV_atom": origin["disagreement_eV_atom"], "support_distance": origin["support_distance"], "descriptor": origin["descriptor"]}
                check("public_candidate_whitelist", set(candidate) == PUBLIC_KEYS, {"trace": tid, "candidate": cid})
                check("public_candidate_values", close(candidate, expected), {"trace": tid, "candidate": cid})
            check("calibration_artifact_identity", close(payload["interval_q"], fitted["intervals"][kind]["q"]), tid)
            check("support_threshold_identity", close(payload["ood_cutoff"], fitted["ood_cutoff"] if row["arm"] == "conservative_ood" else None), tid)
            order = sorted(candidates, key=lambda cid: (candidates[cid]["mean_eV_atom"], cid))
            limit = len(candidates) if payload["policy"] == "full_ref" else min(payload["budget"], len(candidates))
            attempted, observed, anchor = [], {}, None
            responses = result["queries"]
            streamed = [e for e in result["decision_events"] if e["event"] == "query_decision"]
            check("query_events_match_responses", len(streamed) == len(responses), tid)
            charged = 0
            qindex = 0
            def verify_snapshot(event, location):
                check("availability_attempted_prefix", event["attempted_candidate_ids"] == attempted, location)
                available = [{"candidate_id": cid, "energy_eV_atom": observed[cid]} for cid in sorted(observed)]
                check("availability_observed_prefix", close(event["available_observations"], available), location)
                check("availability_budget", event["remaining_attempt_budget"] == limit-len(attempted), location)
                check("availability_anchor", event["anchor_id"] == anchor, location)
                expected_offset = observed[anchor]-candidates[anchor]["mean_eV_atom"] if anchor else None
                check("availability_anchor_offset", close(event["anchor_offset_eV_atom"], expected_offset), location)
                public = [{k: candidates[cid][k] for k in SNAP_KEYS} for cid in sorted(candidates)]
                check("availability_predictions", close(event["public_predictions"], public), location)
                check("availability_unit", event["energy_unit"] == "eV/atom", location)
            for event in result["decision_events"]:
                location = {"trace": tid, "event": event["event"], "query_prefix": len(attempted)}
                if "attempted_candidate_ids" in event:
                    verify_snapshot(event, location)
                if event["event"] == "interval_check":
                    remaining = [cid for cid in order if cid not in attempted]
                    q = payload["interval_q"]
                    offset = observed[anchor]-candidates[anchor]["mean_eV_atom"]
                    lower = {cid: candidates[cid]["mean_eV_atom"]+offset-q*candidates[cid]["sigma_eV_atom"] for cid in remaining} if q is not None else {}
                    signed = min(observed.values())-min(lower.values()) if lower else None
                    bound = max(0., signed) if signed is not None else None
                    check("interval_lower_bounds", close(event["lower_bounds_eV_atom"], lower), location)
                    check("interval_signed_margin", close(event["signed_unqueried_margin_eV_atom"], signed), location)
                    check("interval_nonnegative_risk_bound", close(event["regret_upper_bound_eV_atom"], bound) and (bound is None or bound >= 0), location)
                    check("interval_certificate_arithmetic", event["certificate"] == (bound is not None and bound <= payload["tolerance_eV_atom"]), location)
                    interval_events.append({"trace_id": tid, "signed_margin": signed, "bound": bound, "certificate": event["certificate"]})
                if event["event"] != "query_decision":
                    continue
                response = responses[qindex]
                check("query_prestate_identity", close(response["pre_query"], event), location)
                cid = response["candidate_id"]
                check("query_candidate_valid", cid in candidates and event["candidate_id"] == cid, location)
                check("query_order", response["order"] == qindex+1 == event["order"], location)
                repeat = cid in attempted
                check("query_cache_accounting", response["cached"] == repeat and response["charged"] == (0 if repeat else 1), location)
                check("query_unit_protocol_kind", response["energy_unit"] == "eV/atom" and response["protocol_id"] == protocol and response["kind"] == "energy", location)
                charged += response["charged"]
                query_statuses[response["status"]] += 1
                fault = category == "synthetic_faults" and int(hashlib.sha256(("failure|"+cid).encode()).hexdigest()[:8],16)%10 == 0
                check("response_fault_contract", response["ok"] == (not fault), location)
                if response["ok"]:
                    check("response_absolute_reference", close(response["energy_eV_atom"], refs[cid]), location)
                    observed[cid] = response["energy_eV_atom"]
                    if anchor is None:
                        anchor = cid
                else:
                    check("failed_job_no_reference_revelation", "energy_eV_atom" not in response and response["error"] == "missing_reference", location)
                attempted.append(cid)
                qindex += 1
            check("trace_ledger_total", result["charged_calls"] == row["charged_calls"] == charged, tid)
            check("trace_observation_map", close(result["observations"], observed), tid)
            check("trace_no_repeated_query", len(attempted) == len(set(attempted)), tid)
            all_attempts += charged
            if payload["policy"] in FIXED:
                check("fixed_budget_exact", charged == limit, tid)
            elif payload["policy"] == "full_ref":
                check("full_reference_all_candidates", charged == len(candidates), tid)
            elif payload["policy"] == "mlip_only":
                check("frozen_model_no_queries", charged == 0 and result["selected_id"] == order[0], tid)
            else:
                check("variable_budget_respected", charged <= limit, tid)
            selected = result["selected_id"]
            if payload["policy"] != "mlip_only" and selected is not None:
                best_seen = min(observed, key=lambda cid: (observed[cid],cid)) if observed else None
                check("terminal_best_queried", selected == best_seen, tid)
            check("row_result_identity", all(close(row[k],result[k]) for k in ("selected_id","status","reason","fallback")),tid)
            truth_min = min(refs[cid] for cid in candidates)
            regret = max(0.,refs[selected]-truth_min) if selected is not None else None
            accepted = selected is not None and result["status"] == "ok"
            succeeded = bool(accepted and regret is not None and regret <= .020+1e-12)
            check("evaluation_regret", close(row["regret_eV_atom"],regret),tid)
            check("evaluation_accept_success", row["accepted"] == accepted and row["success"] == succeeded and row["abstained"] == (selected is None),tid)
            check("evaluation_failed_jobs", row["failed_jobs"] == sum(q["status"]=="failed" for q in responses),tid)
            check("evaluation_label_kind", row["evidence_kind"] == ("synthetic_failure_on_real_replay" if category=="synthetic_faults" else "replay"),tid)
            check("evaluation_ground_truth_complete", row["reference_complete"] is True,tid)
            if result.get("certified") and accepted and regret is not None and regret > .020+1e-12:
                certificate_failures.append({"trace_id":tid,"arm":row["arm"],"pool_id":row["pool_id"],"split":row["split"],"regret_eV_atom":regret,
                                             "note":"Observed failure of the calibrated interval on this pool, not an arithmetic failure of the certificate test."})

    primary, repeated, stressed = (rows_by_category[k] for k in ("primary","random_repeats","synthetic_faults"))
    check("all_runs_expected", len(traces)==1720)
    for category, rkey, qkey in [("primary","primary_policy_pool_runs","primary_offline_reference_attempts"),
                                 ("random_repeats","additional_random_seed_runs","additional_random_seed_attempts"),
                                 ("synthetic_faults","synthetic_failure_stress_runs","synthetic_failure_stress_attempts")]:
        rr=rows_by_category[category]
        check("runtime_run_count", accounting[rkey]==len(rr),category)
        check("runtime_query_count", accounting[qkey]==sum(r["charged_calls"] for r in rr),category)
    check("runtime_failed_count",accounting["synthetic_failed_attempts"]==sum(r["failed_jobs"] for r in stressed))
    check("no_live_compute_claim",accounting["live_dft_jobs"]==accounting["live_mlip_inference"]==accounting["paid_compute_dollars"]==0)

    csv_specs=[("per_pool.csv",primary),
               ("random_seed_repeats.csv",[r for r in primary if r["arm"]=="random" and r["budget"]==2]+repeated),
               ("synthetic_failure_stress.csv",stressed)]
    for filename, rr in csv_specs:
        with (run/filename).open() as stream:
            saved=list(csv.DictReader(stream))
        expected={r["trace_id"]:r for r in rr}
        check("csv_trace_roster",len(saved)==len(rr) and {r["trace_id"] for r in saved}==set(expected),filename)
        for row in saved:
            target=expected[row["trace_id"]]
            check("csv_columns",set(row)==set(target),filename)
            for key,value in target.items():
                if value is None:
                    ok=row[key]==""
                elif isinstance(value,bool):
                    ok=row[key]==str(value)
                elif isinstance(value,(int,float)):
                    ok=close(float(row[key]),value)
                else:
                    ok=row[key]==str(value)
                check("csv_value",ok,{"file":filename,"trace":row["trace_id"],"field":key})

    aggregates=load(run/"aggregates.json")
    groups=defaultdict(list)
    for row in primary:
        groups[(row["split"],row["arm"],row["budget"])].append(row)
    check("aggregate_roster",{(r['split'],r['arm'],r['budget']) for r in aggregates}==set(groups))
    draws=manifest["bootstrap_draws"]
    seed=manifest["seed"]
    for saved in aggregates:
        key=(saved["split"],saved["arm"],saved["budget"])
        rr=groups[key]
        reg=[r["regret_eV_atom"] for r in rr if r["regret_eV_atom"] is not None]
        vals={"n_pools":len(rr),"n_groups":len({r['group_id'] for r in rr}),"successes":sum(r['success'] for r in rr),
              "success_rate":statistics.mean(r['success'] for r in rr),"mean_regret_eV_atom":statistics.mean(reg) if reg else None,
              "p95_regret_eV_atom":percentile(reg,.95),"worst_regret_eV_atom":max(reg) if reg else None,
              "charged_calls":sum(r['charged_calls'] for r in rr),"mean_calls":statistics.mean(r['charged_calls'] for r in rr),
              "fallback_rate":statistics.mean(r['fallback'] for r in rr),"abstention_rate":statistics.mean(r['abstained'] for r in rr),
              "failed_jobs":sum(r['failed_jobs'] for r in rr),"mean_policy_wall_seconds":statistics.mean(r['measured_policy_wall_seconds'] for r in rr)}
        for name,value in vals.items():
            check("aggregate_value",close(saved[name],value),{"key":key,"field":name})
        gg=sorted({r['group_id'] for r in rr})
        totals=np.asarray([[sum(r['success'] for r in rr if r['group_id']==g),sum(r['regret_eV_atom'] for r in rr if r['group_id']==g and r['regret_eV_atom'] is not None),sum(r['regret_eV_atom'] is not None for r in rr if r['group_id']==g),sum(r['charged_calls'] for r in rr if r['group_id']==g),sum(r['group_id']==g for r in rr)] for g in gg],float)
        sampled=totals[np.random.default_rng(seed).integers(len(gg),size=(draws,len(gg)))].sum(axis=1)
        for name, values in {'success_rate':sampled[:,0]/sampled[:,4], 'mean_regret_eV_atom':sampled[:,1]/np.maximum(1,sampled[:,2]), 'mean_calls':sampled[:,3]/sampled[:,4]}.items():
            check("aggregate_bootstrap_interval",close(saved[name+'_ci95'],np.quantile(values,[.025,.975]).tolist()),{"key":key,"field":name})

    pairs=load(run/"paired_results.json")
    for saved in pairs:
        rr=groups[(saved['split'],saved['arm'],saved['budget'])]
        base={r['pool_id']:r for r in groups[(saved['split'],'fixed_top',saved['budget'])]}
        check("paired_exact_reference_budget",all(r['charged_calls']==base[r['pool_id']]['charged_calls'] for r in rr),saved['arm'])
        rescued=sum(r['success'] and not base[r['pool_id']]['success'] for r in rr)
        harmed=sum(not r['success'] and base[r['pool_id']]['success'] for r in rr)
        values={'rescues':rescued,'harms':harmed,'both_success':sum(r['success'] and base[r['pool_id']]['success'] for r in rr),
                'both_fail':sum(not r['success'] and not base[r['pool_id']]['success'] for r in rr),
                'mean_success_delta':statistics.mean(float(r['success'])-float(base[r['pool_id']]['success']) for r in rr),
                'mean_regret_delta_eV_atom':statistics.mean(r['regret_eV_atom']-base[r['pool_id']]['regret_eV_atom'] for r in rr)}
        for key,value in values.items():
            check('paired_value',close(saved[key],value),{'arm':saved['arm'],'field':key,'budget':saved['budget'],'split':saved['split']})
        gg=sorted({r['group_id'] for r in rr})
        totals=np.asarray([[sum(float(r['success'])-float(base[r['pool_id']]['success']) for r in rr if r['group_id']==g),sum(r['regret_eV_atom']-base[r['pool_id']]['regret_eV_atom'] for r in rr if r['group_id']==g),sum(r['group_id']==g for r in rr)] for g in gg],float)
        sampled=totals[np.random.default_rng(seed).integers(len(gg),size=(draws,len(gg)))].sum(axis=1)
        check('paired_bootstrap_success',close(saved['success_delta_ci95'],np.quantile(sampled[:,0]/sampled[:,2],[.025,.975]).tolist()),saved['arm'])
        check('paired_bootstrap_regret',close(saved['regret_delta_ci95_eV_atom'],np.quantile(sampled[:,1]/sampled[:,2],[.025,.975]).tolist()),saved['arm'])

    coverage=load(run/'calibration_coverage.json')
    for saved in coverage:
        beta=fitted['coefficients'][saved['signal']]
        q=fitted['intervals'][saved['signal']]['q']
        bygroup={},
        bygroup={};candidate_hits=[];pool_hits=[];width=[]
        for pool in pools.values():
            if pool['split']!=saved['split']:
                continue
            origin=next(c for c in pool['candidates'] if c['candidate_id']==pool['anchor_id'])
            hit=[]
            for c in pool['candidates']:
                residual=(refs[c['candidate_id']]-refs[origin['candidate_id']])-(c['mean_eV_atom']-origin['mean_eV_atom'])
                scale=math.sqrt(max(1e-6,beta[0]+beta[1]*c['disagreement_eV_atom']**2+beta[2]*c['support_distance']**2))
                half=q*scale if q is not None else None
                covered=half is None or abs(residual)<=half+1e-12
                hit.append(covered);candidate_hits.append(covered)
                if half is not None:width.append(2*half)
            pool_hits.append(all(hit));bygroup[pool['group_id']]=bygroup.get(pool['group_id'],True) and all(hit)
        values={'n_groups':len(bygroup),'covered_groups':sum(bygroup.values()),'group_coverage':statistics.mean(bygroup.values()),
                'pool_coverage':statistics.mean(pool_hits),'candidate_coverage':statistics.mean(candidate_hits),
                'mean_interval_width_eV_atom':statistics.mean(width) if width else None}
        for key,value in values.items():check('calibration_coverage_value',close(saved[key],value),{'signal':saved['signal'],'split':saved['split'],'field':key})

    random_rows=[r for r in primary if r['arm']=='random' and r['budget']==2]+repeated
    for saved in load(run/'random_seed_summary.json'):
        rr=[r for r in random_rows if r['split']==saved['split'] and r['seed']==saved['seed']]
        vals={'n_pools':len(rr),'success_rate':statistics.mean(r['success'] for r in rr),'mean_regret_eV_atom':statistics.mean(r['regret_eV_atom'] for r in rr),'charged_calls':sum(r['charged_calls'] for r in rr)}
        for key,value in vals.items():check('random_seed_summary_value',close(saved[key],value),{'split':saved['split'],'seed':saved['seed'],'field':key})
    check('random_seed_roster',sorted({r['seed'] for r in random_rows})==manifest['protocol']['random_seeds'])
    for point in load(run/'cost_risk_frontier.json'):
        allrows=[r for r in aggregates if r['split']==point['split']]
        row=next(r for r in allrows if r['arm']==point['arm'] and r['budget']==point['budget'])
        dominated=any(r['mean_calls']<=row['mean_calls'] and r['mean_regret_eV_atom']<=row['mean_regret_eV_atom'] and (r['mean_calls']<row['mean_calls'] or r['mean_regret_eV_atom']<row['mean_regret_eV_atom']) for r in allrows)
        check('frontier_value',close(point['mean_calls'],row['mean_calls']) and close(point['mean_regret_eV_atom'],row['mean_regret_eV_atom']) and point['nondominated_mean_regret']==(not dominated),{'arm':point['arm'],'budget':point['budget']})
    for item in load(run/'worst_cases.json'):
        row=item['decision'];check('worst_case_decision_identity',close(row,traces[row['trace_id']]['evaluation_after_stop']),row['trace_id'])
        check('worst_case_truth_identity',close(item['references_evaluator_only'],{c['candidate_id']:refs[c['candidate_id']] for c in item['pool']['candidates']}),row['trace_id'])

    bundle=load(run/'dashboard_bundle.json')
    for key,filename in {'aggregates':'aggregates.json','paired':'paired_results.json','calibration':'calibration_coverage.json','frontier':'cost_risk_frontier.json','cost_accounting':'execution_accounting.json','decision':'decision.json','selective_risk':'selective_risk.json','random_seeds':'random_seed_summary.json'}.items():
        check('dashboard_bundle_source_identity',close(bundle[key],load(run/filename)),key)
    check('dashboard_worst_cases_subset',close(bundle['worst_cases'],load(run/'worst_cases.json')[:10]))
    embedded=re.search(r'<script id="bundle" type="application/json">(.*?)</script>',(run/'dashboard.html').read_text(),re.S)
    check('dashboard_embedded_bundle_identity',embedded is not None and close(json.loads(embedded.group(1)),bundle))
    reporting=load(run/'reporting_manifest.json')
    check('reporting_input_identity',reporting['input_sha256']==sha(run/'dashboard_bundle.json'))
    check('reporting_renderer_identity',reporting['renderer_sha256']==sha(root/'erkidu_decision/reporting.py'))
    if reporting.get('template'):
        template=root/'erkidu_decision'/reporting['template']
        check('reporting_template_identity',template.is_file() and sha(template)==reporting.get('template_sha256'))
    for filename,expected in reporting.get('additional_input_sha256',{}).items():
        source=run/filename
        check('reporting_additional_input_identity',source.is_file() and sha(source)==expected,filename)
    for filename,expected in reporting['files'].items():
        check('reporting_output_hash',sha(run/filename)==expected['sha256'] and (run/filename).stat().st_size==expected['bytes'],filename)
    scenarios=load(run/'cost_sensitivity.json')
    for saved in scenarios['grid']:
        rr=[r for r in aggregates if r['split']==saved['split'] and r['abstention_rate']==0]
        scored=[(r['mean_regret_eV_atom']+saved['lambda_ref']*r['mean_calls']+saved['eta_mlip']*scenarios['model_pass_assumption'].get(r['arm'],3),r) for r in rr]
        best=min(s for s,r in scored)
        winners={(r['arm'],r['budget']) for s,r in scored if abs(s-best)<1e-12}
        check('cost_scenario_objective',close(saved['minimum_objective_eV_atom'],best) and {(r['arm'],r['budget']) for r in saved['tied_winners']}==winners,{'split':saved['split'],'lambda_ref':saved['lambda_ref'],'eta_mlip':saved['eta_mlip']})

    # Exact arithmetic on the decimal reference labels (not floating summaries).
    exact={}
    for arm,budget in [('fixed_top',2),('decision_aware',2),('m3gnet_only',0)]:
        rr=groups[('test',arm,budget)]
        total=Decimal(0)
        for row in rr:
            pool=pools[row['pool_id']]
            values={c['candidate_id']:Decimal(str(refs[c['candidate_id']])) for c in pool['candidates']}
            total+=values[row['selected_id']]-min(values.values())
        exact[arm]={'total_regret_eV_atom':str(total),'n_pools':len(rr),'mean_fraction':str(Fraction(total)/len(rr))}
    reduction_fixed=Fraction(Decimal(exact['fixed_top']['total_regret_eV_atom'])-Decimal(exact['decision_aware']['total_regret_eV_atom']))/30
    reduction_free=Fraction(Decimal(exact['m3gnet_only']['total_regret_eV_atom'])-Decimal(exact['decision_aware']['total_regret_eV_atom']))/30
    exact['break_even']={'EI_vs_fixed_top_two_extra_model_pass_eta':str(reduction_fixed/2),
                         'EI_vs_M3GNet_lambda_plus_eta_threshold':str(reduction_free/2),
                         'unit':'eV/atom regret-equivalent penalty',
                         'scope':'finite test cohort; no measured prices or physical precision guarantee'}
    notes.extend([
        'No policy, oracle, model fit, relaxation, or reference job was rerun. Bootstrap intervals were recomputed as an arithmetic consistency audit of existing rows.',
        'All replay queries are unique; actual replay logs contain no cache hits. Cache success/failure behavior is covered by existing synthetic unit tests, not demonstrated by these unique-query traces.',
        'Complete evaluator truth is required to score this real-data replay. Synthetic operational failures retain evaluator truth; they cannot estimate losses when reference truth itself is missing.',
        'The chemistry split and bootstrap do not establish independent pretrained exposure or independent WBM parent lineage.',
        'A recorded calibrated certificate can fail on a pool even when its arithmetic is correct; observed certificate failures are preserved below rather than reclassified as code failures.',
    ])
    result={'evidence_kind':'executed_saved_trace_and_result_consistency_audit','status':'passed' if not errors else 'failed',
            'experiment_rerun':False,'new_reference_queries':0,'new_model_fits':0,'new_paid_compute':0,
            'auditor_sha256':sha(Path(__file__)),'captured_sources':captured_sources,'trace_files':trace_files,'total_runs':len(traces),'total_query_attempts':all_attempts,
            'query_status_counts':dict(query_statuses),'checks_by_name':dict(counts),'checks_total':sum(counts.values()),
            'failure_count':len(errors),'failures':errors,
            'interval_audit':{'events':len(interval_events),'negative_signed_margins':sum(e['signed_margin'] is not None and e['signed_margin']<0 for e in interval_events),
                              'negative_risk_bounds':sum(e['bound'] is not None and e['bound']<0 for e in interval_events),
                              'true_certificate_events':sum(e['certificate'] for e in interval_events),
                              'observed_certified_threshold_failures':certificate_failures},
            'exact_test_cost_arithmetic':exact,
            'test_coverage_review':{
                'covered_by_existing_named_tests':['unit/protocol rejection','None/nonfinite references charged','cached successes/failures uncharged','unsupported forces','held-out reference perturbation','calibration-vs-training isolation','missing training label fails explicitly','duplicate/group split rejection','ties','fixed budgets and cost accounting','nonnegative interval-bound repair'],
                'not_exercised_by_canonical_traces':['repeat requests/cache hits','unsupported force requests','actual missing evaluator ground truth','actual failed DFT calculations'],
                'gaps':['No direct named test for bool/string malformed reference values (implementation rejects them).','Real missing evaluation labels lack an end-to-end successful reporting path; pilot importer must require complete truth or explicitly mark evaluation unsupported before paired aggregation.','Unit tags cannot detect numerically plausible values supplied under a false physical unit/protocol label; source and physics review remains necessary.']},
            'notes':notes}
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,default=Path('results/decision_engine/oxide_run'))
    parser.add_argument('--prepared',type=Path,default=Path('results/decision_engine/oxide_prepared'))
    parser.add_argument('--fit',type=Path,default=Path('results/decision_engine/oxide_fit'))
    parser.add_argument('--out',type=Path,default=Path('results/decision_engine/full_trace_audit.json'))
    args=parser.parse_args()
    result=audit(args.run,args.prepared,args.fit,args.out)
    print(json.dumps({k:result[k] for k in ['status','total_runs','total_query_attempts','checks_total','failure_count']},indent=2))
    if result['failures']:print(json.dumps(result['failures'][:20],indent=2))
    raise SystemExit(0 if result['status']=='passed' else 1)
