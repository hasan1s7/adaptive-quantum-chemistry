"""Interactive workbench contracts, oracle parity, and DOM action wiring.

The Node harness exercises real application actions with a minimal DOM; it is
not a browser rendering test. Browser layout is inspected separately. None of
these tests read historical evaluation reference rows or change saved runs.
"""
from __future__ import annotations

import json
import gzip
import hashlib
from pathlib import Path
import random
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from aqc.data import digest
from aqc.lab import build_lab, _development_pools, _geometry_view
from aqc.oracle import PolicySession

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "results" / "fixture"
ENGINE = ROOT / "aqc" / "web" / "lab-engine.js"
NODE = shutil.which("node")
FIXTURE_AVAILABLE = (FIXTURE / "evaluation_seal.json").exists()
REAL = ROOT / "results" / "real"
GEOMETRY_ASSET = ROOT / "data" / "development_geometry.json.gz"
GEOMETRY_AVAILABLE = GEOMETRY_ASSET.exists() and (REAL / "prepared" / "geometry_manifest.csv").exists()


def payload(path):
    return json.loads(re.search(r'<script id="lab-payload" type="application/json">(.*?)</script>',
                                Path(path).read_text(), flags=re.S).group(1))


def node(code, data=None, *arguments):
    completed = subprocess.run([NODE, "-e", code, str(ENGINE), *map(str, arguments)],
                               input=json.dumps(data), text=True, capture_output=True)
    if completed.returncode:
        raise AssertionError(f"Node exited {completed.returncode}: {completed.stderr}")
    return json.loads(completed.stdout)


BATCH_PARITY = r"""
const E=require(process.argv[1]);
const cases=JSON.parse(require('fs').readFileSync(0,'utf8'));
console.log(JSON.stringify(cases.map(row=>{
  const r=E.runPolicy(row.candidates,row.references,row.config);
  return {selected_candidate:r.selected_candidate,expensive_calls:r.expensive_calls,
    query_order:r.queries.map(q=>q.candidate_id),fallback:r.fallback,stop_reason:r.stop_reason};
})));
"""


DOM_HARNESS = r"""
const fs=require('fs'),vm=require('vm');
const html=fs.readFileSync(process.argv[2],'utf8');
const raw=html.match(/<script id="lab-payload" type="application\/json">([\s\S]*?)<\/script>/)[1];
const data=JSON.parse(raw),nodes=new Map(),downloads=[],timers=new Map();let nextTimer=1,scrollCalls=0;
function element(id){
 if(!nodes.has(id))nodes.set(id,{id,innerHTML:'',textContent:'',value:'',hidden:false,disabled:false,
  dataset:{},style:{},attrs:{},events:{},classList:{toggle(){},add(){}},
  setAttribute(k,v){this.attrs[k]=v},removeAttribute(k){delete this.attrs[k]},
  addEventListener(k,v){this.events[k]=v},remove(){this.removed=true},focus(){},
  click(){if(this.download)downloads.push(this.download);if(this.events.click)this.events.click({target:this})},
  querySelector(s){return element(this.id+'-'+s)},closest(){return null}});
 return nodes.get(id);
}
element('lab-payload').textContent=raw;
element('kind-filter').value='all';element('risk-filter').value='100';
element('simulation-policy').value='sequential';element('failure-filter').value='remaining';
const pages=['explore','simulator','failures','verification'].map(x=>element('page-'+x));
const navs=pages.map((p,i)=>{const e=element('nav-'+i);e.dataset.page=p.id.slice(5);return e});
const scopes=['development','cv','historical'].map(x=>{const e=element('scope-'+x);e.dataset.scope=x;return e});
const sorts=['config_id','success_rate','mean_calls','p95_regret_kcal','fallback_rate'].map(x=>{const e=element('sort-'+x);e.dataset.sort=x;return e});
const document={getElementById:element,body:{appendChild(){}},createElement:()=>element('download'),
 querySelectorAll:s=>s==='.page'?pages:s==='[data-page]'?navs:s==='[data-scope]'||s==='.scope-tabs [role=tab]'?scopes:s==='[data-sort]'?sorts:[],
 querySelector:s=>s.startsWith('[data-scope=')?scopes.find(e=>s.includes(e.dataset.scope)):element(s)};
const context={console,document,Blob,URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},
 setTimeout(fn){const id=nextTimer++;timers.set(id,fn);return id},clearTimeout(id){timers.delete(id)},
 innerWidth:1200,scrollTo(){scrollCalls++}};context.window=context;context.globalThis=context;
vm.createContext(context);
const scripts=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m=>m[1]);
for(const source of scripts)vm.runInContext(source,context);
if(!context.AQCLab)throw new Error(element('fatal-error').textContent||'Application did not initialize');
const app=context.AQCLab,result={initial:app.state(),metrics:element('global-metrics').innerHTML,
 integrity:element('integrity-cards').innerHTML,payloadRemoved:element('lab-payload').removed};
const initialScrolls=scrollCalls;element('geometry-step-policy').click();result.afterStep=app.state();
result.inlinePaidAfterStep=element('geometry-paid-calls').textContent;
element('geometry-run-policy').click();result.afterRun=app.state();result.resultText=element('stop-result').innerHTML;
result.queryDidNotScroll=scrollCalls===initialScrolls;
app.switchPage('explore');result.navigationScrolled=scrollCalls===initialScrolls+1;
app.switchPage('simulator');
const beforeCompare=JSON.stringify(app.state().simulation);app.comparePolicies();
result.comparison=element('simulation-comparison').innerHTML;
result.comparePreservedTrial=beforeCompare===JSON.stringify(app.state().simulation);
element('simulation-policy').value='manual';app.resetTrial();
const ranked=[...app.state().simulation.candidates].sort((a,b)=>a.cheap_kcal-b.cheap_kcal||context.AQCEngine.lexical(a.candidate_id,b.candidate_id));
app.revealCandidate(ranked[0].candidate_id);result.manualOne=app.state();
app.revealCandidate(ranked[0].candidate_id);result.manualCached=app.state();
app.revealCandidate(ranked[1].candidate_id);app.finishManual();result.manualStop=app.state();
element('export-trace').click();result.downloads=[...downloads];
app.switchScope('historical');result.history=app.state();result.historyFiltersDisabled=element('risk-filter').disabled;
result.historyChart=element('risk-chart').innerHTML;
app.switchScope('cv');result.cv=app.state();result.cvFiltersDisabled=element('calls-filter').disabled;
app.switchScope('development');result.devFiltersEnabled=!element('risk-filter').disabled;
element('failure-filter').value='rescued';element('failure-filter').events.change();
result.rescueCount=element('failure-count').textContent;
app.openMolecule(data.simulator_pools[0].molecule_id);result.opened=app.state();
const unchanged=app.state().moleculeId;app.openMolecule('__not_a_development_molecule__');
result.unknownDoesNotOpen=app.state().moleculeId===unchanged;
result.scopeBanner=element('simulator-scope').textContent;
console.log(JSON.stringify(result));
"""


@unittest.skipUnless(NODE, "Node is required for optional browser-engine parity checks")
class LabEngineTests(unittest.TestCase):
    def test_every_paid_registry_config_matches_python_on_feedback_branches(self):
        from aqc.experiments import build_configurations
        configs = [entry["config"] for entry in build_configurations() if entry["kind"] != "diagnostic"]
        candidates = [{"candidate_id": cid, "cheap_kcal": cheap}
                      for cid, cheap in zip("abcd", [0, .25, .5, 4])]
        cases = [{"candidates": candidates, "references": dict(zip("abcd", refs)), "config": config}
                 for refs in ([0, .25, .5, 4], [0, 4, -2, 5]) for config in configs]
        observed = node(BATCH_PARITY, cases)
        self.assertEqual(len(cases), 2038)
        with PolicySession() as session:
            for case, js in zip(cases, observed):
                with self.subTest(config=case["config"], refs=case["references"]):
                    py = session.run(case["candidates"], case["references"], case["config"])
                    wanted = {key: py[key] for key in ["selected_candidate", "expensive_calls", "fallback", "stop_reason"]}
                    wanted["query_order"] = [event["candidate_id"] for event in py["queries"]]
                    self.assertEqual(js, wanted)

    def test_ties_missing_offsets_rank_reversals_and_singletons_match_python(self):
        configs = [{"kind": "full"}, *({"kind": "fixed", "k": k} for k in [1, 2, 8]),
                   {"kind": "adaptive", "k": 1, "gap": 0, "cap": 2},
                   {"kind": "adaptive", "k": 2, "gap": 10, "cap": 2},
                   {"kind": "sequential", "one_gap": 8, "one_ratio": .3, "error_scale": 2, "slack": .25, "cap": 2},
                   {"kind": "sequential", "one_gap": 0, "one_ratio": 0, "error_scale": 1, "slack": 0, "cap": 4}]
        pools = [
            (["a", "Z", "-", "_", "\U0001f600", "\ue000"], [0]*6, [0]*6),
            (["c", "b", "a"], [1, .2, 0], [-2, .1, 3]),
            (["a", "b", "c", "d"], [0, .1, .2, 3], [None, 3, -2, 0]),
            (["a", "b", "c", "d"], [0, .1, .2, 3], [2, None, -2, 0]),
            (["a", "b", "c", "d"], [1000, 1000.25, 1000.5, 1004], [-20000, -19996, -20002, -19995]),
            (["single"], [3], [-5]),
            (["a", "b", "c"], [0, 8-5e-10, 10], [2, 4, -3]),
        ]
        rng = random.Random(1729)
        for _ in range(12):
            n = rng.randint(2, 10)
            pools.append(([f"c{i}" for i in range(n)], [rng.random()*8 for _ in range(n)],
                          [rng.uniform(-3, 7) for _ in range(n)]))
        cases = [{"candidates": [{"candidate_id": cid, "cheap_kcal": cheap} for cid, cheap in zip(ids, cheap)],
                  "references": dict(zip(ids, refs)), "config": config}
                 for ids, cheap, refs in pools for config in configs]
        observed = node(BATCH_PARITY, cases)
        with PolicySession() as session:
            for case, js in zip(cases, observed):
                with self.subTest(case=case):
                    py = session.run(case["candidates"], case["references"], case["config"])
                    wanted = {key: py[key] for key in ["selected_candidate", "expensive_calls", "fallback", "stop_reason"]}
                    wanted["query_order"] = [event["candidate_id"] for event in py["queries"]]
                    self.assertEqual(js, wanted)

    def test_evaluator_hides_labels_until_charged_and_regret_until_stop(self):
        result = node(r"""
const E=require(process.argv[1]),candidates=[{candidate_id:'a',cheap_kcal:0},{candidate_id:'b',cheap_kcal:1},{candidate_id:'c',cheap_kcal:2}];
const bank=E.createEvaluatorBank([{molecule_id:'m',family_id:'f',candidates,references:{a:2,b:0,c:-1}}]);
const e=bank.open('m'),result={catalog:bank.catalog,initial:e.snapshot()};
try{e.finish()}catch(error){result.zeroQueryRejected=true}
e.query('a');result.one=e.snapshot();e.query('a');result.cached=e.snapshot();e.query('b');
try{e.finish('a')}catch(error){result.nonbestRejected=true}
result.finished=e.finish();result.stop=e.snapshot();
try{e.query('c')}catch(error){result.afterStopRejected=true}
result.independent=bank.open('m').snapshot();console.log(JSON.stringify(result));
""")
        self.assertNotIn("references", result["catalog"][0])
        self.assertEqual(result["initial"]["observations"], {})
        self.assertIsNone(result["initial"]["evaluation"])
        self.assertTrue(result["zeroQueryRejected"])
        self.assertEqual(result["one"]["observations"], {"a": 2})
        self.assertIsNone(result["one"]["evaluation"])
        self.assertEqual(result["cached"]["expensive_calls"], 1)
        self.assertEqual(result["cached"]["queries"][-1]["charged"], 0)
        self.assertTrue(result["nonbestRejected"])
        self.assertEqual(result["finished"]["selected_candidate"], "b")
        self.assertEqual(result["finished"]["regret_kcal"], 1)
        self.assertTrue(result["afterStopRejected"])
        self.assertEqual(result["independent"]["expensive_calls"], 0)

    def test_missing_outputs_are_charged_and_block_incomplete_pool_regret(self):
        result = node(r"""
const E=require(process.argv[1]),candidates=[{candidate_id:'a',cheap_kcal:0},{candidate_id:'b',cheap_kcal:1}];
const r=E.runPolicy(candidates,{a:null,b:2},{kind:'fixed',k:1});
console.log(JSON.stringify(r));
""")
        self.assertEqual(result["expensive_calls"], 2)
        self.assertEqual(result["queries"][0]["status"], "failed")
        self.assertEqual(result["queries"][0]["charged"], 1)
        self.assertEqual(result["selected_candidate"], "b")
        self.assertTrue(result["fallback"])
        self.assertIsNone(result["evaluation"]["regret_kcal"])

    def test_strict_candidate_config_schema_and_overflow_guard(self):
        rejected = node(r"""
const E=require(process.argv[1]);let n=0;
const probes=[()=>E.validateCandidates([{candidate_id:'a',cheap_kcal:0,reference_kcal:-1}]),
 ()=>E.validateCandidates([{candidate_id:'a',cheap_kcal:true}]),
 ()=>E.validateCandidates([{candidate_id:'a',cheap_kcal:-1e308},{candidate_id:'b',cheap_kcal:1e308}]),
 ()=>E.validateConfig({kind:'fixed',k:true}),
 ()=>E.validateConfig({kind:'sequential',one_gap:0,one_ratio:0,error_scale:.5,slack:0,cap:2}),
 ()=>E.validateConfig({kind:'full',reference_min:0})];
for(const probe of probes){try{probe()}catch(error){n++}}console.log(JSON.stringify(n));
""")
        self.assertEqual(rejected, 6)

    def test_filter_sort_are_measured_row_operations(self):
        result = node(r"""
const E=require(process.argv[1]);const rows=[
 {config_id:'c',kind:'sequential',success_rate:.95,mean_calls:1.3,config:{slack:.25}},
 {config_id:'a',kind:'fixed',success_rate:.97,mean_calls:2,config:{k:2}},
 {config_id:'b',kind:'fixed',success_rate:.94,mean_calls:1,config:{k:1}}];
const before=JSON.stringify(rows),visible=E.filterExperiments(rows,{maxRisk:5,maxCalls:2});
console.log(JSON.stringify({ids:E.sortExperiments(visible,'mean_calls').map(r=>r.config_id),
 search:E.filterExperiments(rows,{query:'slack',kind:'sequential'}).map(r=>r.config_id),unchanged:before===JSON.stringify(rows)}));
""")
        self.assertEqual(result["ids"], ["c", "a"])
        self.assertEqual(result["search"], ["c"])
        self.assertTrue(result["unchanged"])


@unittest.skipUnless(FIXTURE_AVAILABLE, "saved synthetic fixture artifacts are required")
class LabBuildTests(unittest.TestCase):
    def test_pending_requires_explicit_preview_and_never_invents_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "explicit pending"):
                build_lab(root, FIXTURE, FIXTURE / "prepared", root / "lab.html")
            result = build_lab(root, FIXTURE, FIXTURE / "prepared", root / "lab.html", allow_pending=True)
            saved = payload(result)
            self.assertTrue(saved["meta"]["pending"])
            self.assertEqual(saved["meta"]["dataset_kind"], "synthetic")
            self.assertEqual(saved["experiments"], [])
            self.assertEqual(saved["cv"], {})
            self.assertFalse(saved["verification"]["lab"]["verified"])
            self.assertEqual(saved["historical"]["decision"], json.loads((FIXTURE / "decision.json").read_text()))
            self.assertNotIn("<script src=", result.read_text())
            self.assertNotIn("fetch(", result.read_text())

    def test_only_original_development_pools_enter_simulator(self):
        with tempfile.TemporaryDirectory() as directory:
            result = build_lab(Path(directory), FIXTURE, FIXTURE / "prepared", allow_pending=True)
            saved = payload(result)
            split = json.loads((FIXTURE / "prepared" / "split_manifest.json").read_text())
            development = {row["molecule_id"] for row in split["assignments"] if row["split"] == "development"}
            evaluation = {row["molecule_id"] for row in split["assignments"] if row["split"] == "evaluation"}
            simulator = {row["molecule_id"] for row in saved["simulator_pools"]}
            self.assertEqual(simulator, development)
            self.assertFalse(simulator & evaluation)
            self.assertTrue(all(set(candidate) == {"candidate_id", "cheap_kcal"}
                                for pool in saved["simulator_pools"] for candidate in pool["candidates"]))
            self.assertFalse(any("evaluation_references" in row["name"] for row in saved["verification"]["files"]))

    def test_corrupted_development_input_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(FIXTURE / "prepared", root / "prepared")
            with (root / "prepared" / "development_features.jsonl").open("a") as stream:
                stream.write("\n")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                build_lab(root, FIXTURE, root / "prepared", allow_pending=True)

    def test_registered_but_unsealed_run_is_not_presented_as_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "experiment_registry.json").write_text("{}")
            with self.assertRaises(ValueError):
                build_lab(root, FIXTURE, FIXTURE / "prepared", allow_pending=True)

    def test_payload_escaping_cannot_close_inert_script(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            malicious = {"note": "</script><script>alert('x')</script> & \u2028 \u2029"}
            with patch("aqc.lab._failure_anatomy", return_value=malicious):
                result = build_lab(root, FIXTURE, FIXTURE / "prepared", allow_pending=True)
            self.assertNotIn("</script><script>alert", result.read_text())
            self.assertEqual(payload(result)["failure_analysis"], malicious)

    @unittest.skipUnless(NODE, "Node is required for optional DOM action checks")
    def test_real_application_actions_step_reveal_run_reset_compare_export(self):
        with tempfile.TemporaryDirectory() as directory:
            output = build_lab(Path(directory), FIXTURE, FIXTURE / "prepared", allow_pending=True)
            shown = node(DOM_HARNESS, None, output)
            saved = payload(output)
            self.assertEqual(shown["initial"]["page"], "simulator")
            self.assertEqual(shown["initial"]["simulation"]["expensive_calls"], 0)
            self.assertIsNone(shown["initial"]["simulation"]["evaluation"])
            self.assertTrue(shown["payloadRemoved"])
            self.assertEqual(shown["afterStep"]["simulation"]["expensive_calls"], 1)
            self.assertTrue(shown["inlinePaidAfterStep"].startswith("1 paid call / "))
            self.assertTrue(shown["queryDidNotScroll"])
            self.assertTrue(shown["navigationScrolled"])
            self.assertTrue(shown["afterRun"]["simulation"]["stopped"])
            self.assertIn("AFTER STOP", shown["resultText"])
            self.assertTrue(shown["comparePreservedTrial"])
            self.assertIn("Full rerank", shown["comparison"])
            self.assertEqual(shown["manualOne"]["simulation"]["expensive_calls"], 1)
            self.assertEqual(shown["manualCached"]["simulation"]["expensive_calls"], 1)
            self.assertEqual(shown["manualStop"]["simulation"]["expensive_calls"], 2)
            self.assertTrue(shown["manualStop"]["simulation"]["stopped"])
            self.assertTrue(shown["downloads"][0].endswith(".json"))
            self.assertEqual(shown["history"]["visibleExperiments"], len(saved["historical"]["aggregate"]))
            self.assertTrue(shown["historyFiltersDisabled"])
            self.assertIn("<svg", shown["historyChart"])
            self.assertEqual(shown["cv"]["visibleExperiments"], 0)
            self.assertTrue(shown["cvFiltersDisabled"])
            self.assertTrue(shown["devFiltersEnabled"])
            self.assertEqual(shown["rescueCount"], str(saved["failure_analysis"]["rescued_on_second"]) + " cases")
            self.assertEqual(shown["opened"]["simulation"]["expensive_calls"], 0)
            self.assertTrue(shown["unknownDoesNotOpen"])
            self.assertIn("synthetic engineering fixture", shown["scopeBanner"])


@unittest.skipUnless(GEOMETRY_AVAILABLE, "verified real development display coordinates are required")
class LabGeometryTests(unittest.TestCase):
    def test_viewer_asset_covers_exact_development_identities_and_source_hashes(self):
        prepared = REAL / "prepared"
        pools, audit, split = _development_pools(prepared)
        geometry = _geometry_view(prepared, GEOMETRY_ASSET, pools, audit, split)
        self.assertTrue(geometry["available"])
        self.assertTrue(geometry["display_only"])
        self.assertEqual(geometry["molecule_count"], len(pools))
        self.assertEqual(geometry["candidate_count"], sum(len(pool["candidates"]) for pool in pools))
        self.assertEqual(geometry["compressed_sha256"], hashlib.sha256(GEOMETRY_ASSET.read_bytes()).hexdigest())
        self.assertNotIn("references", json.loads(gzip.decompress(GEOMETRY_ASSET.read_bytes()))["molecules"][0])

    def test_coordinate_tamper_rejected_even_if_asset_manifest_is_rehashed(self):
        prepared = REAL / "prepared"
        pools, audit, split = _development_pools(prepared)
        content = json.loads(gzip.decompress(GEOMETRY_ASSET.read_bytes()))
        content["molecules"][0]["candidates"][0]["coordinates_angstrom"][0][0] += .1
        companion = json.loads((GEOMETRY_ASSET.with_name("development_geometry_manifest.json")).read_text())
        with tempfile.TemporaryDirectory() as directory:
            altered = Path(directory) / GEOMETRY_ASSET.name
            altered.write_bytes(gzip.compress(json.dumps(content).encode()))
            companion["payload_sha256"] = digest(content)
            companion["asset_sha256"] = hashlib.sha256(altered.read_bytes()).hexdigest()
            altered.with_name("development_geometry_manifest.json").write_text(json.dumps(companion))
            with self.assertRaisesRegex(ValueError, "geometry differs"):
                _geometry_view(prepared, altered, pools, audit, split)


if __name__ == "__main__":
    unittest.main()
