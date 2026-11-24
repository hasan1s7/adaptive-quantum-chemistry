"""Build a portable, read-only dashboard from completed benchmark outputs.

No server, CDN, runtime filesystem fetch, network request, or model execution is
needed.  This module only reads evaluator outputs; it never changes a split,
policy, frozen operating point, or benchmark result.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
from typing import Any


OUTPUT_FILES = {
    "aggregate": "aggregate.csv",
    "decision": "decision.json",
    "molecules": "per_molecule.csv",
    "paired": "paired_comparisons.csv",
    "frozen": "frozen_config.json",
    "audit": "audit.json",
    "splits": "split_manifest.json",
    "traces": "traces.jsonl",
    "development": "development_frontier.csv",
    "heldout": "heldout_frontier.csv",
}

_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_TEXT_FIELDS = {
    "policy", "comparator", "selected_candidate", "stop_reason", "query_order",
    "config", "kind", "split", "dataset", "source", "name", "label",
}


def _csv_value(key: str, value: str | None) -> Any:
    if value is None or value == "":
        return None
    if key in _TEXT_FIELDS or key.endswith("_id") or key.endswith("_sha256"):
        return value
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    if value.lower() in ("none", "null", "nan", "inf", "-inf"):
        return None
    if _NUMBER.fullmatch(value):
        numeric = float(value)
        if not math.isfinite(numeric):
            return None
        return int(value) if re.fullmatch(r"[+-]?\d+", value) else numeric
    return value


def _safe_json(value: Any) -> Any:
    """Represent missing/nonfinite optional output fields without invalid JSON."""
    if isinstance(value, dict):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def build_dashboard(results_dir: Path, output_path: Path | None = None) -> Path:
    """Embed saved results in one HTML file, reporting absent optional outputs.

    Existing malformed outputs are rejected, rather than silently replaced by
    illustrative data.  Missing outputs remain explicitly unavailable.
    """
    results_dir = Path(results_dir).resolve()
    if not results_dir.is_dir():
        raise ValueError(f"results directory does not exist: {results_dir}")
    payload: dict[str, Any] = {"source_files": [], "missing_files": []}
    for key, filename in OUTPUT_FILES.items():
        path = results_dir / filename
        if not path.is_file():
            payload[key] = {} if filename.endswith(".json") else []
            payload["missing_files"].append(filename)
            continue
        content = path.read_bytes()
        payload["source_files"].append({
            "name": filename,
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        })
        text = content.decode("utf-8-sig")
        if filename.endswith(".csv"):
            payload[key] = [
                {field: _csv_value(field, value) for field, value in row.items()}
                for row in csv.DictReader(io.StringIO(text))
            ]
        elif filename.endswith(".jsonl"):
            payload[key] = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            payload[key] = json.loads(text)
    payload = _safe_json(payload)
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    # Embedded JSON must not be able to terminate its inert script element.
    encoded = encoded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    encoded = encoded.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    destination = Path(output_path) if output_path is not None else results_dir / "dashboard.html"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(_HTML.replace("__BENCHMARK_JSON__", encoded), encoding="utf-8")
    return destination.resolve()


_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>Adaptive Quantum Chemistry — benchmark dashboard</title>
<style>
:root{--navy:#102438;--navy2:#1d354a;--paper:#f4f6f6;--white:#fff;--ink:#172b3b;--muted:#536778;--line:#dbe3e7;--teal:#006e72;--teal-light:#def2ed;--blue:#2b65a0;--amber:#a86111;--amber-light:#fff0d8;--red:#a63735;--red-light:#fbe5e1;--mono:ui-monospace,SFMono-Regular,Consolas,monospace}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}button,input,select{font:inherit}button,a,input,select{outline-offset:4px}button{cursor:pointer}button:disabled{cursor:default}a{color:var(--teal)}h1,h2,h3,p{margin:0}h1{font-size:clamp(29px,3.5vw,45px);line-height:1.15;font-weight:650;letter-spacing:-1.2px}h2{font-size:23px;font-weight:650;letter-spacing:-.4px}h3{font-size:17px;font-weight:650}.shell{max-width:1440px;margin:auto;padding:0 34px}.hero{background:var(--navy);color:#fff;padding:32px 0 38px}.eyebrow{font-size:14px;text-transform:uppercase;letter-spacing:1.6px;color:#a7c5ce;font-weight:650}.hero-top{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:24px}.hero p{color:#c6d5df;max-width:840px;margin-top:14px;font-size:17px}.pill{display:inline-flex;align-items:center;gap:7px;padding:5px 11px;border-radius:30px;font-size:14px;white-space:nowrap;font-weight:600}.pill-real{background:#d9f2e7;color:#005e4e}.pill-synthetic{background:#ffedc7;color:#7b4c08}.pill-unknown{background:#e7edf1;color:#415363}.pill-success{background:var(--teal-light);color:#075d58}.pill-failure{background:var(--red-light);color:var(--red)}.pill-neutral{background:#eaf0f4;color:#3e576b}.pill-warn{background:var(--amber-light);color:#805211}.hero-meta{font-size:14px;color:#a7c5ce;font-family:var(--mono)}main{padding-top:26px!important;padding-bottom:48px!important}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px}.metric{padding:22px 23px;background:#fff;border:1px solid var(--line);border-radius:12px}.metric .label{color:var(--muted);font-size:14px;font-weight:600}.metric .value{font-size:34px;letter-spacing:-1px;line-height:1.25;font-variant-numeric:tabular-nums;margin:9px 0 8px;font-weight:650}.metric .note{font-size:14px;color:var(--muted);line-height:1.45;min-height:40px}.panel{background:#fff;border:1px solid var(--line);border-radius:14px;margin-bottom:24px;overflow:hidden}.panel-header{padding:22px 24px 18px;display:flex;gap:20px;justify-content:space-between;align-items:flex-start}.panel-header p,.section-note{font-size:16px;color:var(--muted);margin-top:6px}.section-note{padding:0 24px 20px}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}th{text-align:left;white-space:nowrap;font-size:14px;font-weight:600;background:#f2f5f7;color:var(--muted);padding:12px 18px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}td{padding:15px 18px;border-bottom:1px solid #e8edef;font-size:16px;vertical-align:top}tbody tr:last-child td{border-bottom:0}.decision td:first-child{font-weight:600;min-width:205px}.decision tr.focus-row{background:#f3faf7}.sub{font-size:14px;font-weight:400;color:var(--muted);display:block;margin-top:4px}.num{white-space:nowrap}.diagnostic-row{color:#667681}.grid-two{display:grid;grid-template-columns:minmax(0,1.8fr) minmax(300px,1fr);gap:24px}.plot-panel{min-width:0}.tabs{display:inline-flex;border:1px solid var(--line);border-radius:8px;padding:3px;gap:3px;background:#f3f6f7}.tab{border:0;border-radius:6px;padding:7px 13px;font-size:14px;background:transparent;color:var(--muted)}.tab[aria-selected=true]{background:white;color:var(--ink);box-shadow:0 1px 4px #18374b15;font-weight:600}.plot-space{padding:0 17px 8px;min-height:350px}.plot-space svg{width:100%;display:block;overflow:visible}.chart-key{display:flex;flex-wrap:wrap;gap:13px;font-size:14px;padding:0 25px 17px;color:var(--muted)}.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}.scope{padding:23px 24px}.scope h2{margin-bottom:16px}.scope p{font-size:16px;color:var(--muted);margin-bottom:14px}.scope dl{margin:16px 0}.scope dt{font-size:14px;color:var(--muted);margin-top:15px}.scope dd{font-size:16px;margin:3px 0 0;overflow-wrap:anywhere}.scope pre{font:14px/1.55 var(--mono);white-space:pre-wrap;background:#f4f7f8;padding:14px;border-radius:7px;margin:0;overflow:auto;max-height:180px}.rule{height:1px;background:var(--line);margin:19px 0}.toolbar{display:flex;align-items:center;flex-wrap:wrap;gap:12px;padding:0 24px 19px}.control{display:flex;flex-direction:column;gap:4px}.control label{font-size:14px;color:var(--muted);font-weight:600}input[type=search],select{border:1px solid #cbd7de;border-radius:7px;background:white;padding:9px 11px;color:var(--ink);font-size:14px;min-height:40px}input[type=search]{min-width:240px}.filter-check{font-size:14px;display:flex;gap:7px;align-items:center;padding-top:20px}.filter-check input{accent-color:var(--teal);width:16px;height:16px}.quiet-button{border:1px solid #cbd7de;background:#fff;border-radius:7px;padding:8px 13px;color:var(--ink);font-size:14px}.toolbar .quiet-button{margin-top:20px;margin-left:auto}.explorer{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(360px,1fr);border-top:1px solid var(--line)}.molecule-table{max-height:560px;overflow:auto}.molecule-table th{position:sticky;top:0;z-index:1;border-top:0}.molecule-table td,.molecule-table th{padding:11px 13px;font-size:14px}.molecule-table tbody tr{cursor:pointer}.molecule-table tbody tr:hover{background:#f2f8f7}.molecule-table tbody tr.selected{background:#e9f5ef}.molecule-button{border:0;background:transparent;color:var(--teal);font:600 14px var(--mono);text-align:left;padding:0;overflow-wrap:anywhere}.molecule-table .sub{font-size:14px}.trace-panel{padding:22px 24px;border-left:1px solid var(--line);background:#fafcfc;max-height:560px;overflow:auto}.trace-panel h3{font-family:var(--mono);font-size:17px;overflow-wrap:anywhere}.trace-panel p{font-size:14px;color:var(--muted);margin-top:8px}.trace-facts{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:16px 0}.trace-fact{border:1px solid var(--line);background:white;border-radius:8px;padding:10px 12px}.trace-fact .label{font-size:14px;color:var(--muted);display:block}.trace-fact .value{font-size:16px;font-weight:600;overflow-wrap:anywhere;display:block;margin-top:3px}.query-table th,.query-table td{font-size:14px;padding:8px 6px}.query-table td:nth-child(2){font-family:var(--mono);overflow-wrap:anywhere;max-width:140px}.query-table th{white-space:normal}.query-table .chosen{background:#e1f1e8}.stop{font:14px/1.6 var(--mono);background:white;border:1px solid var(--line);border-radius:7px;padding:10px;margin-top:15px;overflow-wrap:anywhere}.empty{padding:38px 25px;text-align:center;color:var(--muted);font-size:16px}.detail-empty{padding:65px 15px}.record-count{font-size:14px;color:var(--muted)}.audit-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;padding:0 24px 24px}details{border:1px solid var(--line);border-radius:8px;padding:12px 14px;background:#fbfcfc}summary{font-size:14px;font-weight:600;cursor:pointer}details pre{font:14px/1.55 var(--mono);white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto;margin-bottom:0}details p{font-size:14px;margin-top:12px;color:var(--muted)}.source-list{padding:0 24px 24px;display:flex;flex-wrap:wrap;gap:8px}.source-file{font:14px var(--mono);border:1px solid var(--line);border-radius:5px;padding:6px 8px;background:#f9fbfc}.missing{padding:0 24px 21px;font-size:14px;color:var(--amber)}.disclaimer{font-size:14px;color:var(--muted);padding:0 2px}.no-script{margin:25px;background:#fff0d8;padding:20px}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}footer{display:flex;justify-content:space-between;gap:22px;padding-top:5px;font-size:14px;color:var(--muted)}.status-line{font-size:14px;color:var(--muted);background:#f2f7f6;padding:14px 24px;border-top:1px solid var(--line)}
@media(max-width:1100px){.shell{padding:0 22px}.metrics{grid-template-columns:repeat(2,1fr)}.grid-two{grid-template-columns:1fr}.explorer{grid-template-columns:1fr}.trace-panel{border-left:0;border-top:1px solid var(--line);max-height:600px}.audit-grid{grid-template-columns:1fr}.trace-facts{grid-template-columns:repeat(4,1fr)}.query-table th,.query-table td{font-size:14px}.scope pre{max-height:220px}.scope dl{display:grid;grid-template-columns:1fr 1fr;gap:0 25px}.panel-header{flex-wrap:wrap}.hero-meta{display:none}}
@media(max-width:600px){.shell{padding:0 15px}.hero{padding-top:24px}.metrics{gap:10px}.metric{padding:16px}.metric .value{font-size:29px}.metric .note{font-size:14px}.hero-top{align-items:flex-start}.eyebrow{font-size:14px}.pill{font-size:14px}.panel-header{padding:19px}.toolbar{padding:0 19px 17px}.control{width:100%}input[type=search],select{width:100%;min-width:0}.filter-check{padding-top:0}.toolbar .quiet-button{margin-top:0}.trace-facts{grid-template-columns:1fr 1fr}.scope dl{display:block}.audit-grid{padding:0 19px 19px}.plot-space{padding:0 7px 8px}.chart-key{font-size:14px}.source-list{padding:0 19px 19px}footer{flex-direction:column;gap:6px}.hero p{font-size:16px}}
@media print{body{background:white}.hero{background:white;color:var(--ink);padding:15px 0}.hero p,.eyebrow{color:var(--muted)}.hero-meta{color:var(--ink)}.shell{max-width:none;padding:0}.panel,.metric{break-inside:avoid}.toolbar,.tabs,.quiet-button{display:none}.grid-two{display:block}.explorer{display:block}.molecule-table,.trace-panel{max-height:none;overflow:visible}.trace-panel{border-left:0}.audit-grid{display:block}details{margin-bottom:10px}.metrics{gap:8px}.metric{padding:12px}.metric .value{font-size:27px}.hero h1{font-size:30px}}
</style>
</head>
<body>
<header class="hero"><div class="shell">
<div class="hero-top"><div class="eyebrow">Fixed-pool conformer acquisition · benchmark 01</div><span id="dataset-badge" class="pill pill-unknown">Dataset status unavailable</span></div>
<h1>Adaptive Quantum Chemistry</h1>
<p>Which conformers deserve a reference calculation? Inspect the measured tradeoff between reference regret and paid single-point queries.</p>
<div id="revision" class="hero-meta" style="margin-top:19px"></div>
</div></header>
<noscript><div class="no-script">This self-contained dashboard uses local JavaScript to display its embedded result tables. No network connection is required.</div></noscript>
<main class="shell">
<section class="metrics" aria-label="Held-out summary" id="metrics"></section>
<section class="panel" aria-labelledby="decision-heading">
<div class="panel-header"><div><h2 id="decision-heading">Held-out decision table</h2><p>Frozen operating points. Reference regret is measured against the best geometry in each identical candidate pool.</p></div><span id="pool-count" class="pill pill-neutral"></span></div>
<div class="table-wrap"><table class="decision"><thead><tr><th>Policy</th><th>Within 1 kcal/mol</th><th>Median / p95 regret</th><th>Mean calls</th><th>Total calls</th><th>Fallback</th></tr></thead><tbody id="decision-body"></tbody></table></div>
<div class="status-line" id="decision-context"></div>
</section>
<div class="grid-two">
<section class="panel plot-panel" aria-labelledby="risk-heading">
<div class="panel-header"><div><h2 id="risk-heading">Risk versus expensive calls</h2><p id="plot-context">Held-out measurements for the frozen policies.</p></div><div class="tabs" role="tablist" aria-label="Plot split"><button class="tab" role="tab" id="heldout-tab" aria-selected="true" data-split="heldout">Held out</button><button class="tab" role="tab" id="development-tab" aria-selected="false" data-split="development">Development</button></div></div>
<div id="risk-plot" class="plot-space" role="tabpanel" aria-labelledby="heldout-tab"></div>
<div class="chart-key"><span><i class="dot" style="background:#177a68"></i>Adaptive</span><span><i class="dot" style="background:#2b65a0"></i>Fixed top-k</span><span><i class="dot" style="background:#293849"></i>Full rerank</span><span><i class="dot" style="background:#88929b"></i>Unverified diagnostic</span></div>
<p class="section-note">Bars show 95% family-cluster bootstrap intervals when recorded. The dashed line is the 5% failure target. Offline calls are not wall-clock savings.</p>
</section>
<aside class="panel scope" aria-labelledby="scope-heading"><h2 id="scope-heading">What was frozen</h2><p>Operating points are chosen on development families. This dashboard only inspects saved results; it cannot tune a policy or run a quantum job.</p><div id="frozen-summary"></div><div class="rule"></div><h3>Paired comparison</h3><div id="paired-summary"></div><p style="margin-top:16px;margin-bottom:0">Bootstrap intervals describe the observed families. Zero observed failures do not establish a population success guarantee.</p></aside>
</div>
<section class="panel" aria-labelledby="molecule-heading">
<div class="panel-header"><div><h2 id="molecule-heading">Follow the decision, molecule by molecule</h2><p>Choose a row to inspect the selected conformer, query order, charged jobs, and stop reason.</p></div><span class="record-count" id="record-count" aria-live="polite"></span></div>
<div class="toolbar">
<div class="control"><label for="search">Molecule or family</label><input id="search" type="search" placeholder="Search IDs…" autocomplete="off"></div>
<div class="control"><label for="policy-filter">Policy</label><select id="policy-filter"></select></div>
<div class="control"><label for="outcome-filter">Outcome</label><select id="outcome-filter"><option value="all">All outcomes</option><option value="failure">Above 1 kcal/mol</option><option value="success">Within 1 kcal/mol</option></select></div>
<div class="control"><label for="sort-filter">Sort</label><select id="sort-filter"><option value="regret">Highest regret</option><option value="calls">Most calls</option><option value="family">Family</option><option value="molecule">Molecule ID</option></select></div>
<label class="filter-check"><input id="fallback-filter" type="checkbox">Fallbacks only</label>
<button class="quiet-button" id="export-csv" type="button">Export visible rows</button>
</div>
<div class="explorer"><div class="molecule-table"><table><thead><tr><th>Molecule / family</th><th>Pool</th><th>Regret</th><th>Calls</th><th>Fallback</th></tr></thead><tbody id="molecule-body"></tbody></table></div><aside class="trace-panel" id="trace-detail" aria-live="polite"><div class="empty detail-empty">Select a molecule to inspect its charged query trace.</div></aside></div>
</section>
<section class="panel" aria-labelledby="audit-heading">
<div class="panel-header"><div><h2 id="audit-heading">Provenance and reproducibility</h2><p>Embedded copies of the saved audit, split manifest, and frozen configuration. All figures above come from these run outputs.</p></div></div>
<div class="audit-grid"><details><summary>Data audit and exclusions</summary><pre id="audit-json"></pre></details><details><summary>Family split manifest</summary><pre id="split-json"></pre></details><details><summary>Frozen configuration</summary><pre id="frozen-json"></pre></details><details><summary>Recorded decision</summary><pre id="decision-json"></pre></details></div>
<div class="source-list" id="source-files"></div><div class="missing" id="missing-files"></div>
</section>
<footer><span>Adaptive Quantum Chemistry · reproducible offline replay</span><span>Read-only · local file · no external assets or live compute</span></footer>
</main>
<script id="benchmark-data" type="application/json">__BENCHMARK_JSON__</script>
<script>
'use strict';
const D=JSON.parse(document.getElementById('benchmark-data').textContent);
const $=id=>document.getElementById(id);
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number=x=>x!==null&&x!==undefined&&x!==''&&Number.isFinite(Number(x))?Number(x):null;
const fmt=(x,d=2)=>number(x)===null?'—':Number(x).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const pct=(x,d=1)=>number(x)===null?'—':fmt(Number(x)*100,d)+'%';
const yes=x=>x===true||x===1||x==='1'||x==='true'||x==='True';
const ci=(row,key,percent=false)=>{const lo=row?.[key+'_ci_low'],hi=row?.[key+'_ci_high'];return number(lo)===null||number(hi)===null?'CI unavailable':(percent?pct(lo)+'–'+pct(hi):fmt(lo)+'–'+fmt(hi));};
const policyLabel=p=>({full_rerank:'Full reference rerank',fixed_top_k:'Fixed top-k · 95% target',fixed_matched:'Fixed top-k · matched development risk',adaptive:'Adaptive cheap-gap',cheap_only:'Cheap-only ranking'}[p]||p||'Unnamed policy');
const aggregate=Array.isArray(D.aggregate)?D.aggregate:[];
const findPolicy=p=>aggregate.find(r=>r.policy===p);
const adaptive=findPolicy('adaptive'),fixed=findPolicy('fixed_top_k'),full=findPolicy('full_rerank');
const primaryName=D.frozen?.primary_comparator??D.decision?.primary_comparator??null;
const comparator=primaryName?findPolicy(primaryName):null;
const comparatorLabel=primaryName?policyLabel(primaryName):'Unrecorded comparator';
const families=adaptive?.n_families??fixed?.n_families??aggregate[0]?.n_families;
const nMolecules=adaptive?.n_molecules??fixed?.n_molecules??aggregate[0]?.n_molecules;
const allMolecules=Array.isArray(D.molecules)?D.molecules:[];
const molecules=allMolecules.filter(r=>!r.split||['evaluation','heldout','held_out','test','final'].includes(String(r.split).toLowerCase()));
const traces=Array.isArray(D.traces)?D.traces:[];
const traceIndex=new Map(traces.filter(r=>!r.split||['evaluation','heldout','held_out','test','final'].includes(String(r.split).toLowerCase())).map(r=>[r.molecule_id+'\0'+r.policy,r]));
const paired=(D.paired||[]).find(r=>r.policy==='adaptive'&&r.comparator===primaryName);

function nestedValues(obj,keyRe,result=[]){if(obj&&typeof obj==='object'){for(const [k,v]of Object.entries(obj)){if(keyRe.test(k)&&(typeof v==='string'||typeof v==='boolean'))result.push(String(v));if(v&&typeof v==='object')nestedValues(v,keyRe,result);}}return result;}
const labels=nestedValues(D.audit,/dataset|source|kind|synthetic|fixture|mode|name|status|label/i).concat(nestedValues(D.frozen,/dataset|source|kind|synthetic|fixture|mode|name|status|label/i));
const rawStatus=labels.join(' ').toLowerCase();
const explicitSynthetic=nestedValues(D.audit,/^synthetic$|^is_synthetic$/i).concat(nestedValues(D.frozen,/^synthetic$|^is_synthetic$/i)).some(x=>x==='true');
const datasetKind=String(D.frozen?.dataset_kind??D.audit?.dataset_kind??D.decision?.dataset_kind??'').toLowerCase();
const isSynthetic=datasetKind==='synthetic'||explicitSynthetic||/synthetic|fixture/.test(rawStatus);
const isReal=!isSynthetic&&(datasetKind==='real'||/folmsbee|hutchison|conformer-benchmark|real_replay|real replay|verified_real/.test(rawStatus));
$('dataset-badge').textContent=isSynthetic?'SYNTHETIC FIXTURE':isReal?'REAL DATA REPLAY':'DATASET STATUS NOT RECORDED';
$('dataset-badge').className='pill '+(isSynthetic?'pill-synthetic':isReal?'pill-real':'pill-unknown');
const revision=nestedValues(D.audit,/revision|commit|source_sha|pinned_sha/i).find(x=>/^[a-f0-9]{40}$/i.test(x));
$('revision').textContent=revision?'Pinned upstream revision '+revision:'Self-contained report · saved evaluator outputs';
const saved=comparator&&adaptive&&number(comparator.total_calls)>0?1-Number(adaptive.total_calls)/Number(comparator.total_calls):null;
function metric(label,value,note){return '<article class="metric"><div class="label">'+esc(label)+'</div><div class="value">'+esc(value)+'</div><div class="note">'+esc(note)+'</div></article>';}
$('metrics').innerHTML=metric('Held-out chemical families',fmt(families,0),fmt(nMolecules,0)+' molecules · grouped before evaluation')+metric('Observed adaptive success',pct(adaptive?.success_rate),adaptive?'Within 1 kcal/mol · 95% CI '+ci(adaptive,'success_rate',true):'Adaptive results unavailable')+metric('Adaptive calls / molecule',fmt(adaptive?.mean_calls),adaptive?'95% CI '+ci(adaptive,'mean_calls'):'Adaptive results unavailable')+metric('Calls saved · frozen comparator',pct(saved),saved===null?'Frozen comparator unavailable':comparatorLabel+' · '+(paired?'95% CI '+ci(paired,'relative_call_savings',true):'CI unavailable; observed risk must also match'));
$('pool-count').textContent=number(nMolecules)===null?'Results unavailable':fmt(nMolecules,0)+' identical held-out pools';
const rank={full_rerank:0,fixed_top_k:1,fixed_matched:2,adaptive:3,cheap_only:4};
$('decision-body').innerHTML=aggregate.length?[...aggregate].sort((a,b)=>(rank[a.policy]??9)-(rank[b.policy]??9)).map(r=>'<tr class="'+(r.policy==='adaptive'?'focus-row':r.policy==='cheap_only'?'diagnostic-row':'')+'"><td>'+esc(policyLabel(r.policy))+(r.policy==='cheap_only'?'<span class="sub">Unverified diagnostic · not a paid baseline</span>':r.policy==='adaptive'?'<span class="sub">Frozen development operating point</span>':'')+'</td><td class="num">'+pct(r.success_rate)+'<span class="sub">95% CI '+ci(r,'success_rate',true)+'</span></td><td class="num">'+fmt(r.median_regret_kcal)+' / '+fmt(r.p95_regret_kcal)+'<span class="sub">kcal/mol · max '+fmt(r.max_regret_kcal)+'</span></td><td class="num">'+fmt(r.mean_calls)+'<span class="sub">95% CI '+ci(r,'mean_calls')+'</span></td><td class="num">'+fmt(r.total_calls,0)+'</td><td class="num">'+pct(r.fallback_rate)+'<span class="sub">95% CI '+ci(r,'fallback_rate',true)+'</span></td></tr>').join(''):'<tr><td colspan="6" class="empty">No aggregate.csv was available. No results have been invented.</td></tr>';
let context='Target: at least 95% within 1 kcal/mol and at least 30% fewer expensive calls than the frozen simple comparator at matched risk.';
if(adaptive&&comparator){context+=' Frozen comparator: '+comparatorLabel+'. Observed success: adaptive '+pct(adaptive.success_rate)+', comparator '+pct(comparator.success_rate)+'. ';context+=Number(comparator.success_rate)<.95?'The frozen comparator misses the 95% target; call savings against it do not establish the target comparison.':Number(adaptive.success_rate)<.95?'The adaptive point misses the 95% target.':Number(adaptive.success_rate)<Number(comparator.success_rate)?'Both meet the target point estimate, but adaptive has higher observed risk; this is not an equal-risk savings claim.':'The paired intervals describe uncertainty; this point estimate alone is not a population guarantee.';}
if(typeof D.decision?.observed_joint_target_met==='boolean')context+=' Recorded observed joint target: '+(D.decision.observed_joint_target_met?'met.':'not met.');
if(isSynthetic)context='Synthetic fixture: validates measurement behavior, not molecular performance. '+context;
$('decision-context').textContent=context;

function configFor(name){return D.frozen?.[name]??D.frozen?.policies?.[name]??D.frozen?.selected?.[name]??null;}
const fixedConfig=configFor('fixed_top_k'),adaptiveConfig=configFor('adaptive'),comparatorConfig=primaryName?configFor(primaryName):null;
$('frozen-summary').innerHTML='<dl><dt>Primary comparator</dt><dd>'+esc(comparatorLabel)+(comparatorConfig?'<pre>'+esc(JSON.stringify(comparatorConfig,null,2))+'</pre>':'<span class="sub">Configuration unavailable</span>')+'</dd><dt>Adaptive rule</dt><dd>'+(adaptiveConfig?'<pre>'+esc(JSON.stringify(adaptiveConfig,null,2))+'</pre>':'Configuration unavailable')+'</dd><dt>Evaluation groups</dt><dd>'+fmt(families,0)+' families · '+fmt(nMolecules,0)+' molecules</dd></dl>';
$('paired-summary').innerHTML=paired?'<dl><dt>Success difference · adaptive − comparator</dt><dd>'+pct(paired.delta_success_rate)+'<span class="sub">95% CI '+ci(paired,'delta_success_rate',true)+'</span></dd><dt>Mean calls difference</dt><dd>'+fmt(paired.delta_mean_calls)+'<span class="sub">95% CI '+ci(paired,'delta_mean_calls')+'</span></dd><dt>Reference regret difference</dt><dd>'+fmt(paired.delta_mean_regret_kcal)+' kcal/mol<span class="sub">95% CI '+ci(paired,'delta_mean_regret_kcal')+'</span></dd></dl>':'<p>No paired result is available for adaptive versus the frozen primary comparator.</p>';


function chartRows(split){let rows=split==='development'?(D.development||[]):[...(D.heldout||[]),...aggregate];const seen=new Set();return rows.filter(r=>{if(number(r.mean_calls)===null||number(r.success_rate)===null)return false;const key=[r.policy??r.kind??r.name,r.mean_calls,r.success_rate].join('|');if(seen.has(key))return false;seen.add(key);return true;});}
function category(r){const name=String(r.policy??r.kind??r.name??'');return /cheap/.test(name)?'cheap_only':/full/.test(name)?'full_rerank':/fixed/.test(name)?'fixed_top_k':/adaptive/.test(name)?'adaptive':'unknown';}
function drawChart(split){const rows=chartRows(split);document.querySelectorAll('.tab').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.split===split)));$('risk-plot').setAttribute('aria-labelledby',split+'-tab');$('plot-context').textContent=split==='development'?'Development sweep only. These groups selected the frozen operating points.':(D.heldout?.length?'Frozen points plus a preregistered, descriptive held-out grid. No test-set retuning.':'Held-out measurements for the frozen policies.');if(!rows.length){$('risk-plot').innerHTML='<div class="empty">'+(split==='development'?'Development frontier unavailable.':'Held-out results unavailable.')+'</div>';return;}
const W=820,H=360,L=75,R=28,T=28,B=66,iw=W-L-R,ih=H-T-B;const xmax=Math.max(1,...rows.map(r=>Number(r.mean_calls)))*1.08;let ymax=Math.max(.08,...rows.map(r=>number(r.success_rate_ci_low)===null?1-Number(r.success_rate):1-Number(r.success_rate_ci_low)))*1.08;ymax=Math.min(1,Math.ceil(ymax*10)/10);const x=v=>L+v/xmax*iw,y=v=>T+ih-v/ymax*ih;const colors={adaptive:'#177a68',fixed_top_k:'#2b65a0',full_rerank:'#293849',cheap_only:'#88929b',unknown:'#8465a3'};let s='<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="Failure risk versus mean expensive calls per molecule, '+esc(split)+' data"><title>Failure risk versus mean expensive calls</title>';
for(let i=0;i<=5;i++){let v=i*xmax/5,xx=x(v);s+='<line x1="'+xx+'" y1="'+T+'" x2="'+xx+'" y2="'+(T+ih)+'" stroke="#e5ebee"/><text x="'+xx+'" y="'+(T+ih+25)+'" text-anchor="middle" fill="#536778" font-size="14">'+fmt(v,v<10?1:0)+'</text>';}
for(let i=0;i<=5;i++){let v=i*ymax/5,yy=y(v);s+='<line x1="'+L+'" y1="'+yy+'" x2="'+(W-R)+'" y2="'+yy+'" stroke="#e5ebee"/><text x="'+(L-13)+'" y="'+(yy+5)+'" text-anchor="end" fill="#536778" font-size="14">'+fmt(v*100,v*100<10?1:0)+'%</text>';}
s+='<line x1="'+L+'" y1="'+y(.05)+'" x2="'+(W-R)+'" y2="'+y(.05)+'" stroke="#a63735" stroke-dasharray="6 5" stroke-width="1.6"/><text x="'+(W-R)+'" y="'+(y(.05)-7)+'" text-anchor="end" fill="#a63735" font-size="14">5% target</text>';
for(const r of rows){const px=x(Number(r.mean_calls)),py=y(1-Number(r.success_rate)),color=colors[category(r)],frozen=aggregate.some(a=>a.policy===r.policy&&a.mean_calls===r.mean_calls&&a.success_rate===r.success_rate),size=frozen?6.8:4;const tooltip=policyLabel(r.policy??r.kind??r.name)+'\nSuccess: '+pct(r.success_rate)+'\nMean calls: '+fmt(r.mean_calls)+'\np95 regret: '+fmt(r.p95_regret_kcal)+' kcal/mol';s+='<g><title>'+esc(tooltip)+'</title>';if(number(r.success_rate_ci_low)!==null&&number(r.success_rate_ci_high)!==null)s+='<line x1="'+px+'" y1="'+y(1-Number(r.success_rate_ci_high))+'" x2="'+px+'" y2="'+y(1-Number(r.success_rate_ci_low))+'" stroke="'+color+'" stroke-width="1.5" opacity=".5"/>';if(number(r.mean_calls_ci_low)!==null&&number(r.mean_calls_ci_high)!==null)s+='<line x1="'+x(Number(r.mean_calls_ci_low))+'" y1="'+py+'" x2="'+x(Number(r.mean_calls_ci_high))+'" y2="'+py+'" stroke="'+color+'" stroke-width="1.5" opacity=".5"/>';s+='<circle cx="'+px+'" cy="'+py+'" r="'+size+'" fill="'+color+'" opacity="'+(frozen?1:.5)+'" stroke="white" stroke-width="1.5"/></g>';}
s+='<text x="'+(L+iw/2)+'" y="'+(H-13)+'" text-anchor="middle" fill="#172b3b" font-size="16">Mean expensive calls per molecule</text><text transform="translate(18 '+(T+ih/2)+') rotate(-90)" text-anchor="middle" fill="#172b3b" font-size="16">Above 1 kcal/mol regret</text></svg>';$('risk-plot').innerHTML=s;}
document.querySelectorAll('.tab').forEach(b=>b.addEventListener('click',()=>drawChart(b.dataset.split)));drawChart('heldout');

const policyNames=[...new Set(molecules.map(r=>r.policy))].sort((a,b)=>(rank[a]??9)-(rank[b]??9));$('policy-filter').innerHTML=policyNames.map(p=>'<option value="'+esc(p)+'">'+esc(policyLabel(p))+'</option>').join('');if(policyNames.includes('adaptive'))$('policy-filter').value='adaptive';
let visibleRows=[],selectedKey=null;
const rowKey=r=>r.molecule_id+'\0'+r.policy;
function renderMolecules(){const query=$('search').value.toLowerCase().trim(),policy=$('policy-filter').value,outcome=$('outcome-filter').value,fallback=$('fallback-filter').checked,sort=$('sort-filter').value;visibleRows=molecules.filter(r=>(!policy||r.policy===policy)&&(!query||(String(r.molecule_id)+' '+String(r.family_id)).toLowerCase().includes(query))&&(!fallback||yes(r.fallback))&&(outcome==='all'||(outcome==='success'?Number(r.regret_kcal)<=1+1e-9:Number(r.regret_kcal)>1+1e-9)));visibleRows.sort((a,b)=>sort==='regret'?Number(b.regret_kcal)-Number(a.regret_kcal)||String(a.molecule_id).localeCompare(String(b.molecule_id)):sort==='calls'?Number(b.expensive_calls)-Number(a.expensive_calls)||String(a.molecule_id).localeCompare(String(b.molecule_id)):String(sort==='family'?a.family_id:a.molecule_id).localeCompare(String(sort==='family'?b.family_id:b.molecule_id)));$('record-count').textContent=fmt(visibleRows.length,0)+' matching molecules';$('molecule-body').innerHTML=visibleRows.length?visibleRows.map((r,i)=>'<tr data-row="'+i+'" class="'+(rowKey(r)===selectedKey?'selected':'')+'"><td><button type="button" class="molecule-button" data-row="'+i+'">'+esc(r.molecule_id)+'</button><span class="sub">'+esc(r.family_id)+'</span></td><td>'+fmt(r.n_candidates,0)+'</td><td><span class="pill '+(Number(r.regret_kcal)<=1+1e-9?'pill-success':'pill-failure')+'">'+fmt(r.regret_kcal)+'</span></td><td>'+fmt(r.expensive_calls,0)+'</td><td>'+(yes(r.fallback)?'<span class="pill pill-warn">Yes</span>':'—')+'</td></tr>').join(''):'<tr><td colspan="5" class="empty">No saved molecules match these filters.</td></tr>';if(selectedKey&&!visibleRows.some(r=>rowKey(r)===selectedKey)){selectedKey=null;$('trace-detail').innerHTML='<div class="empty detail-empty">Select a molecule to inspect its charged query trace.</div>';}}
for(const id of ['search','policy-filter','outcome-filter','sort-filter','fallback-filter'])$(id).addEventListener(id==='search'?'input':'change',renderMolecules);
function traceFact(label,value){return '<div class="trace-fact"><span class="label">'+esc(label)+'</span><span class="value">'+esc(value)+'</span></div>';}
function showTrace(index){const r=visibleRows[index];if(!r)return;selectedKey=rowKey(r);const trace=traceIndex.get(selectedKey),result=trace?.result??trace??{},queries=Array.isArray(result.queries)?result.queries:[],selected=result.selected_candidate??r.selected_candidate,diagnostic=r.policy==='cheap_only';let html='<h3>'+esc(r.molecule_id)+'</h3><p>'+esc(policyLabel(r.policy))+' · '+esc(r.family_id)+'</p><div class="trace-facts">'+traceFact(diagnostic?'Unverified choice':'Best queried conformer',selected??'Not recorded')+traceFact('Reference regret',fmt(r.regret_kcal)+' kcal/mol')+traceFact('Charged jobs',fmt(result.expensive_calls??r.expensive_calls,0)+' / '+fmt(r.n_candidates,0))+traceFact('Fallback',yes(result.fallback??r.fallback)?'Yes':'No')+'</div>';
if(diagnostic)html+='<p>This zero-call diagnostic selects by cheap energy. It has no reference-verified decision and is excluded from paid-policy comparisons.</p>';else if(queries.length){html+='<h3 style="font-family:inherit;font-size:16px;margin:20px 0 8px">Reference reveal log</h3><p style="margin:0 0 12px">Reference values became available only after their logged query. Highlighted row is the selected conformer.</p><div class="table-wrap"><table class="query-table"><thead><tr><th>Order</th><th>Candidate</th><th>Charged</th><th>Reference<br>kcal/mol</th><th>Status</th></tr></thead><tbody>'+queries.map((q,i)=>'<tr class="'+(q.candidate_id===selected?'chosen':'')+'"><td>'+esc(q.order??i+1)+'</td><td>'+esc(q.candidate_id)+'</td><td>'+(yes(q.charged)?'1':'0')+'</td><td class="num">'+fmt(q.reference_kcal,6)+'</td><td>'+esc(q.status??q.error??'Not recorded')+(q.error?'<span class="sub">'+esc(q.error)+'</span>':'')+'</td></tr>').join('')+'</tbody></table></div>';}else{html+='<p>The charged query trace is unavailable for this row.</p>';if(r.query_order)html+='<div class="stop">Saved query order: '+esc(r.query_order)+'</div>';}
const cheapPool=Array.isArray(trace?.cheap_candidates)?trace.cheap_candidates:[];
if(cheapPool.length){const finiteCheap=cheapPool.map(c=>number(c.cheap_kcal)).filter(x=>x!==null),minimum=finiteCheap.length?Math.min(...finiteCheap):null,observations=result.observations??{};html+='<details style="margin-top:15px"><summary>Cheap pool and revealed evidence</summary><p>Every candidate was visible through its cheap score. Reference cells remain unqueried unless an oracle response revealed them.</p><div class="table-wrap"><table class="query-table"><thead><tr><th>Candidate</th><th>Cheap gap<br>kcal/mol</th><th>Reference revealed<br>kcal/mol</th></tr></thead><tbody>'+cheapPool.map(c=>'<tr class="'+(c.candidate_id===selected?'chosen':'')+'"><td>'+esc(c.candidate_id)+'</td><td>'+fmt(number(c.cheap_kcal)===null||minimum===null?null:Number(c.cheap_kcal)-minimum,6)+'</td><td>'+(Object.prototype.hasOwnProperty.call(observations,c.candidate_id)?fmt(observations[c.candidate_id],6):'Unqueried')+'</td></tr>').join('')+'</tbody></table></div></details>';}
html+='<div class="stop"><strong>Stop reason</strong><br>'+esc(result.stop_reason??r.stop_reason??'Not recorded')+'</div>';if(Array.isArray(result.policy_events)&&result.policy_events.length)html+='<details style="margin-top:13px"><summary>Escalations, fallbacks, and failures</summary><pre>'+esc(JSON.stringify(result.policy_events,null,2))+'</pre></details>';$('trace-detail').innerHTML=html;document.querySelectorAll('#molecule-body tr').forEach(el=>el.classList.toggle('selected',Number(el.dataset.row)===index));}
$('molecule-body').addEventListener('click',event=>{const row=event.target.closest('[data-row]');if(row)showTrace(Number(row.dataset.row));});
$('export-csv').addEventListener('click',()=>{if(!visibleRows.length)return;const keys=Object.keys(visibleRows[0]),cell=x=>'"'+String(x??'').replace(/"/g,'""')+'"';const text=[keys.map(cell).join(','),...visibleRows.map(r=>keys.map(k=>cell(r[k])).join(','))].join('\r\n');const url=URL.createObjectURL(new Blob([text],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='aqc-visible-molecules.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
renderMolecules();if(visibleRows.length)showTrace(0);
$('audit-json').textContent=Object.keys(D.audit||{}).length?JSON.stringify(D.audit,null,2):'audit.json unavailable';$('split-json').textContent=Object.keys(D.splits||{}).length?JSON.stringify(D.splits,null,2):'split_manifest.json unavailable';$('frozen-json').textContent=Object.keys(D.frozen||{}).length?JSON.stringify(D.frozen,null,2):'frozen_config.json unavailable';$('decision-json').textContent=Object.keys(D.decision||{}).length?JSON.stringify(D.decision,null,2):'decision.json unavailable';$('source-files').innerHTML=(D.source_files||[]).map(f=>'<span class="source-file" title="SHA-256: '+esc(f.sha256)+'">'+esc(f.name)+' · '+fmt(f.bytes/1024,1)+' KB</span>').join('');$('missing-files').textContent=D.missing_files?.length?'Unavailable outputs: '+D.missing_files.join(', '):'';
</script>
</body>
</html>
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_dir", type=Path, help="Directory with saved benchmark outputs")
    parser.add_argument("--output", type=Path, help="HTML destination; defaults to results_dir/dashboard.html")
    args = parser.parse_args()
    print(build_dashboard(args.results_dir, args.output))


if __name__ == "__main__":
    main()
