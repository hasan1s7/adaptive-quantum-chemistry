/* UI contract checks over saved evidence. No policy or experiment execution. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const vm = require('node:vm');
const run = path.resolve(process.argv[2] || 'results/decision_engine/oxide_run');
const html = fs.readFileSync(path.join(run, 'dashboard.html'), 'utf8');
const parseBlock = id => {
  const match = html.match(new RegExp('<script id="' + id + '" type="application/json">([\\s\\S]*?)<\\/script>'));
  assert.ok(match, 'missing embedded block: ' + id);
  return JSON.parse(match[1]);
};
const data = parseBlock('bundle'), presentation = parseBlock('presentation-data'), assets = parseBlock('embedded-files');
const code = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
new vm.Script(code);
let assertions = 0;
const check = (condition, name) => {assert.ok(condition, name); assertions++;};
const equal = (actual, expected, name) => {assert.equal(actual, expected, name); assertions++;};
check(JSON.stringify(data) === JSON.stringify(JSON.parse(fs.readFileSync(path.join(run, 'dashboard_bundle.json'), 'utf8'))), 'scientific bundle remains unchanged');
const values = {split:'test', budget:'2', metric:'miss', refweight:'5', modelweight:'.25'};
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    value:values[id] || '', textContent:({bundle:JSON.stringify(data),'presentation-data':JSON.stringify(presentation),'embedded-files':JSON.stringify(assets)})[id] || '',
    innerHTML:'', clientWidth:id==='chart'?320:0, checked:false, disabled:false, open:false, dataset:{}, attributes:{}, listeners:{},
    setAttribute(key, value){this.attributes[key]=value;}, addEventListener(type, fn){this.listeners[type]=fn;}, focus(){this.focused=true;}
  });
  return elements.get(id);
}
const steps = [0,1,2,3].map(i=>{const el=element('step'+i);el.dataset.step=String(i);return el;});
const context = {
  document:{getElementById:element, body:{dataset:{}}, querySelectorAll:selector=>selector==='[data-step]'?steps:[], querySelector:selector=>{const m=selector.match(/data-step="(\d)"/);return m?steps[Number(m[1])]:null;}},
  localStorage:{getItem:()=>null,setItem:()=>{}},window:{addEventListener:()=>{}},console,Blob,URL,setTimeout,atob
};
vm.createContext(context);vm.runInContext(code,context);
const view=context.window.ErkiduView;
check(!!view, 'pure view model exposed for contract checks');
const initial=view.deriveComparison(data,'test',2);
equal(initial.free.successes,30,'strongest zero-query comparator succeeds30/30');
equal(initial.free.charged_calls,0,'zero references is explicit');
equal(initial.fixed.successes,29,'fixed top-two result');
equal(initial.adaptive.successes,30,'adaptive result');
equal(initial.fixed.charged_calls,60,'fixed reference count');
equal(initial.adaptive.charged_calls,60,'adaptive reference count');
equal(initial.pair.rescues,1,'one paired rescue');
equal(initial.pair.harms,0,'no paired harms');
check(element('comparison').innerHTML.includes('data-arm="m3gnet_only"'),'free baseline is in the primary comparison');
check(element('headline').textContent.includes('reference labels'),'headline does not call all compute free');
equal(element('metric').value,'miss','default chart endpoint is tolerance miss rate');
for (const split of ['test','shift_li']) for (const cap of [1,2,3,4]) {
  element('split').value=split;element('split').listeners.change();
  element('budget').value=String(cap);element('budget').listeners.change();
  const expected=view.deriveComparison(data,split,cap);
  check(element('comparison').innerHTML.includes('data-arm="fixed_top" data-cap="'+cap+'"'),'summary follows cap '+split+'/'+cap);
  check(element('comparison').innerHTML.includes('data-arm="decision_aware" data-cap="'+cap+'"'),'adaptive follows cap '+split+'/'+cap);
  check(element('paired').innerHTML.includes(cap+' per pool · '+expected.fixed.charged_calls+' labels per arm'),'paired panel matches cap and total '+split+'/'+cap);
  check(element('verdict').innerHTML.includes(expected.pair.rescues+' rescue'),'paired rescue count follows controls '+split+'/'+cap);
}
const c=presentation.case;
equal(c.status,'available','actual saved SnO2 traces available');
equal(c.traces.fixed_top.result.queries[1].candidate_id,'wbm-1-37760','fixed second query is real B record');
equal(c.traces.decision_aware.result.queries[1].candidate_id,'wbm-1-37762','EI second query is real D record');
const before=view.caseState(c,0), first=view.caseState(c,1), diverged=view.caseState(c,2), evaluated=view.caseState(c,3);
check(before.candidates.every(r=>r.observed_reference_eV_atom===null&&r.reference_gap_meV===null),'prediction stage does not reveal reference values or hidden minimum');
equal(first.candidates.filter(r=>r.observed_reference_eV_atom!==null).length,1,'first stage reveals exactly one query');
check(first.candidates.every(r=>r.reference_gap_meV===null),'first reference does not reveal the hidden optimum gap');
check(!JSON.stringify(first).includes('-2.049227'),'unqueried optimum value absent before second query');
check(diverged.branches.every(b=>b.ids.length===2),'comparison contains two separate two-query histories');
check(!JSON.stringify(diverged).includes('-2.049227'),'unqueried optimum remains absent from branch histories');
equal(evaluated.outcomes.find(r=>r.arm==='m3gnet_only').queries,0,'case preserves zero-query M3GNet result');
equal(evaluated.outcomes.find(r=>r.arm==='decision_aware').selected_id,evaluated.outcomes.find(r=>r.arm==='m3gnet_only').selected_id,'EI and free model select same candidate');
check(evaluated.candidates.every(r=>r.observed_reference_eV_atom!==null),'full truth appears only at final evaluation');
steps[2].listeners.click();equal(element('case-position').textContent,'Stage 3 of 4 · fixed test case','walkthrough scope remains explicit');
steps[2].listeners.keydown({key:'ArrowRight',preventDefault(){}});check(steps[3].focused,'walkthrough supports arrow-key focus');
check(element('case-next').disabled,'next button stops at final stage');
equal(presentation.generation.evidence_class,'executed_geometry_only_prototype','generation reads executed receipt');
check(element('generation').innerHTML.includes('5 bounded proposals'),'executed generation status visible');
check(!html.includes('Deferred behind fixed-pool gate'),'stale generation status removed from presentation');
for (const match of html.matchAll(/<a\b[^>]*\bhref="([^"]+)"/g)) check(match[1].startsWith('#'),'standalone page has no broken relative file link');
const names=new Set();
for (const file of assets) {
  check(!names.has(file.name),'unique embedded download name');names.add(file.name);
  const bytes=Buffer.from(file.base64,'base64');equal(bytes.length,file.bytes,'embedded byte count '+file.name);
  equal(crypto.createHash('sha256').update(bytes).digest('hex'),file.sha256,'embedded checksum '+file.name);
}
for (const name of ['dashboard_bundle.json','per_pool.csv','decision_traces.jsonl.gz','random_seed_traces.jsonl.gz','synthetic_failure_traces.jsonl.gz','cost_risk_frontier.svg']) check(names.has(name),'complete evidence download '+name);
check(element('chart').innerHTML.includes('viewBox="0 0 320 340"'),'chart responds to narrow viewport width');
element('metric').value='regret';element('metric').listeners.change();check(element('chart').innerHTML.includes('Mean regret (meV/atom)'),'mean-regret detail remains available');
element('all-budgets').checked=true;element('all-budgets').listeners.change();check(element('table-scope').textContent.includes('all saved query caps'),'table-only all-budget control is explicit');
check(html.includes('per-job convergence flags'),'source convergence caveat remains accessible');
const manifest=JSON.parse(fs.readFileSync(path.join(run,'reporting_manifest.json'),'utf8'));
equal(manifest.template_sha256,crypto.createHash('sha256').update(fs.readFileSync(path.resolve('erkidu_decision/dashboard_template.html'))).digest('hex'),'template version pinned');
console.log(JSON.stringify({status:'passed',assertions,scientific_experiment_rerun:false,checks:'control coherence; actual-case visibility; generation receipt; exact embedded downloads; narrow viewport SVG; keyboard state',visual_browser_qa:'not performed: browser executable unavailable'},null,2));
