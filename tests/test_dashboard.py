"""Dashboard data wiring, using saved fixture results rather than UI demo data.

Node checks exercise DOM-independent display logic; they are not a browser
rendering test and skip on systems without Node.  The benchmark itself needs
only the pinned Python dependencies.
"""

import csv
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from aqc.dashboard import build_dashboard


FIXTURE = Path(__file__).resolve().parents[1] / "results" / "fixture"
FIXTURE_AVAILABLE = (FIXTURE / "aggregate.csv").exists()
NODE = shutil.which("node")

DOM_HARNESS = r"""
const fs=require('fs'),vm=require('vm');
const html=fs.readFileSync(process.argv[2],'utf8');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const data=JSON.parse(html.match(/<script id="benchmark-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
if(input.useFullAsMatched){
  // Reuse the actual full-rerank fixture outcome: fixed k=pool size is identical.
  const full=data.aggregate.find(r=>r.policy==='full_rerank');
  data.aggregate.push({...full,policy:'fixed_matched'});
  const pair=data.paired.find(r=>r.policy==='adaptive'&&r.comparator==='full_rerank');
  data.paired.push({...pair,comparator:'fixed_matched'});
  data.frozen.primary_comparator='fixed_matched';
  data.frozen.policies.fixed_matched={kind:'fixed',k:data.molecules[0].n_candidates};
  data.decision.primary_comparator='fixed_matched';
}
const nodes=new Map();
function element(id){
  if(!nodes.has(id))nodes.set(id,{id,innerHTML:'',textContent:'',value:'',checked:false,
    dataset:{},attrs:{},events:{},classList:{toggle(){}},
    setAttribute(k,v){this.attrs[k]=v},addEventListener(k,v){this.events[k]=v},click(){}});
  return nodes.get(id);
}
element('benchmark-data').textContent=JSON.stringify(data);
element('outcome-filter').value='all';
element('sort-filter').value='regret';
const tabs=['heldout','development'].map(x=>{const e=element(x+'-tab');e.dataset.split=x;return e});
const context={console,URL,Blob,setTimeout,document:{getElementById:element,
  querySelectorAll:s=>s==='.tab'?tabs:[],createElement:()=>element('download-anchor')}};
vm.createContext(context);
const source=html.split('<script>')[1].split('</script>')[0];
vm.runInContext(source,context);
const result=vm.runInContext('({primaryName,saved,policyNames,selectedKey,displayed:visibleRows.length})',context);
for(const id of ['dataset-badge','metrics','decision-body','decision-context','frozen-summary','paired-summary','trace-detail','record-count']){
  result[id]=element(id).innerHTML||element(id).textContent;
}
context.drawChart('development');
result.developmentChart=element('risk-plot').innerHTML;
element('policy-filter').value='cheap_only';
element('outcome-filter').value='failure';
context.renderMolecules();
result.filteredFailures=vm.runInContext('visibleRows.length',context);
console.log(JSON.stringify(result));
"""


def embedded_payload(path):
    html = Path(path).read_text()
    return json.loads(re.search(
        r'<script id="benchmark-data" type="application/json">(.*?)</script>',
        html, flags=re.S,
    ).group(1))


def run_display_logic(path, use_full_as_matched=False):
    # The script and its stdin are separate: do not interpolate result content.
    with tempfile.TemporaryDirectory() as directory:
        script = Path(directory) / "dashboard-check.js"
        script.write_text(DOM_HARNESS)
        completed = subprocess.run(
            [NODE, str(script), str(path)],
            input=json.dumps({"useFullAsMatched": use_full_as_matched}),
            text=True, capture_output=True, check=True,
        )
        return json.loads(completed.stdout)


class DashboardTests(unittest.TestCase):
    def test_missing_outputs_remain_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            output = build_dashboard(Path(directory))
            payload = embedded_payload(output)
            self.assertEqual(payload["aggregate"], [])
            self.assertEqual(payload["molecules"], [])
            self.assertIn("aggregate.csv", payload["missing_files"])
            self.assertEqual(payload["source_files"], [])
            html = output.read_text()
            self.assertNotIn("fetch(", html)
            self.assertNotIn("<script src=", html)
            self.assertNotIn("https://", html)

    def test_inert_payload_cannot_terminate_script_element(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = {"dataset_kind": "synthetic", "note": "</script><script>alert(1)</script>"}
            (root / "audit.json").write_text(json.dumps(content))
            output = build_dashboard(root)
            self.assertNotIn("</script><script>alert", output.read_text())
            self.assertEqual(embedded_payload(output)["audit"], content)

    def test_malformed_saved_outputs_fail_instead_of_becoming_demo_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "audit.json").write_text("not valid JSON")
            with self.assertRaises(json.JSONDecodeError):
                build_dashboard(root)

    @unittest.skipUnless(FIXTURE_AVAILABLE, "run the fixture command to create saved dashboard inputs")
    def test_actual_fixture_is_embedded_without_changing_results(self):
        with tempfile.TemporaryDirectory() as directory:
            output = build_dashboard(FIXTURE, Path(directory) / "dashboard.html")
            payload = embedded_payload(output)
            self.assertEqual(payload["frozen"], json.loads((FIXTURE / "frozen_config.json").read_text()))
            self.assertEqual(payload["decision"], json.loads((FIXTURE / "decision.json").read_text()))
            self.assertEqual(payload["audit"]["dataset_kind"], "synthetic")
            self.assertEqual(len(payload["molecules"]), sum(1 for _ in csv.DictReader(io.StringIO((FIXTURE / "per_molecule.csv").read_text()))))
            trace = payload["traces"][0]
            self.assertIn("cheap_candidates", trace)
            self.assertEqual(sum(q["charged"] for q in trace["result"]["queries"]), trace["result"]["expensive_calls"])

    @unittest.skipUnless(FIXTURE_AVAILABLE and NODE, "saved fixture and Node needed for optional dashboard logic checks")
    def test_actual_fixture_display_filters_and_query_reveals(self):
        with tempfile.TemporaryDirectory() as directory:
            output = build_dashboard(FIXTURE, Path(directory) / "dashboard.html")
            payload = embedded_payload(output)
            display = run_display_logic(output)
            self.assertEqual(display["dataset-badge"], "SYNTHETIC FIXTURE")
            self.assertEqual(display["primaryName"], payload["frozen"]["primary_comparator"])
            adaptive = next(r for r in payload["aggregate"] if r["policy"] == "adaptive")
            self.assertEqual(display["displayed"], adaptive["n_molecules"])
            self.assertIn("Observed adaptive success", display["metrics"])
            self.assertIn("Reference reveal log", display["trace-detail"])
            self.assertIn("Cheap pool and revealed evidence", display["trace-detail"])
            self.assertIn("Unqueried", display["trace-detail"])
            self.assertIn("<svg", display["developmentChart"])
            expected = sum(r["policy"] == "cheap_only" and r["regret_kcal"] > 1 + 1e-9 for r in payload["molecules"])
            self.assertEqual(display["filteredFailures"], expected)

    @unittest.skipUnless(FIXTURE_AVAILABLE and NODE, "saved fixture and Node needed for optional dashboard logic checks")
    def test_fifth_policy_primary_comparator_controls_savings(self):
        with tempfile.TemporaryDirectory() as directory:
            output = build_dashboard(FIXTURE, Path(directory) / "dashboard.html")
            payload = embedded_payload(output)
            display = run_display_logic(output, use_full_as_matched=True)
            adaptive = next(r for r in payload["aggregate"] if r["policy"] == "adaptive")
            full = next(r for r in payload["aggregate"] if r["policy"] == "full_rerank")
            self.assertEqual(display["primaryName"], "fixed_matched")
            self.assertAlmostEqual(display["saved"], 1 - adaptive["total_calls"] / full["total_calls"])
            self.assertIn("Fixed top-k · matched development risk", display["frozen-summary"])
            self.assertIn("Fixed top-k · matched development risk", display["decision-body"])
            self.assertIn("Fixed top-k · matched development risk", display["metrics"])
            self.assertNotIn("No paired result", display["paired-summary"])


if __name__ == "__main__":
    unittest.main()
