'use strict';
/* Meaningful view contracts; browser layout and real HTTP replay are tested separately. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const UI = require('../app/assets/workbench.js');
let checks = 0;
async function test(name, fn) { await fn(); checks++; console.log('PASS ' + name); }
const copy = value => JSON.parse(JSON.stringify(value));
function row(molecule, policy, calls, regret, family = 'family-one') {
  return {molecule_id: molecule, family_id: family, policy, fold_id: 0, n_candidates: 10,
    expensive_calls: calls, regret_kcal: regret, success_1kcal: regret <= 1 + 1e-9, config_id: policy + '-config', stop_reason: 'completed'};
}
function csv(text) {
  const rows = []; let current = [], field = '', quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (char === '"') { if (quoted && text[i + 1] === '"') { field += '"'; i++; } else quoted = !quoted; }
    else if (char === ',' && !quoted) { current.push(field); field = ''; }
    else if (char === '\n' && !quoted) { current.push(field.replace(/\r$/, '')); rows.push(current); current = []; field = ''; }
    else field += char;
  }
  if (field || current.length) { current.push(field); rows.push(current); }
  const keys = rows.shift();
  return rows.map(values => Object.fromEntries(keys.map((key, index) => [key, values[index]])));
}
function dom() {
  const nodes = new Map();
  class Element {
    constructor(id) { this.id = id; this.innerHTML = ''; this.textContent = ''; this.hidden = false; this.disabled = false;
      this.value = ''; this.checked = false; this.clientWidth = 500; this.events = {}; }
    addEventListener(name, fn) { this.events[name] = fn; }
    querySelectorAll() { return []; }
    fire(name, event = {}) { return this.events[name]?.({target: this, ...event}); }
  }
  const source = fs.readFileSync(path.join(__dirname, '../app/index.html'), 'utf8');
  for (const match of source.matchAll(/id="([^"]+)"/g)) nodes.set(match[1], new Element(match[1]));
  nodes.get('diag-comparator').value = 'matched_simple'; nodes.get('diag-family').value = 'all';
  nodes.get('diag-behavior').value = 'all'; nodes.get('diag-sort').value = 'regret';
  return {nodes, document: {getElementById(id) { assert(nodes.has(id), 'Unknown DOM element: ' + id); return nodes.get(id); }}};
}

(async () => {
  await test('paired outcomes join by molecule and comparator role, independent of row order', () => {
    const rows = [row('b', 'sequential', 1, 2), row('a', 'fixed_top_k', 2, 2), row('b', 'fixed_top_k', 2, .1), row('a', 'sequential', 3, 0)];
    const original = copy(rows), pairs = UI.pairRows(rows, 'fixed_top_k');
    assert.equal(pairs.length, 2); assert.equal(pairs.find(x => x.molecule_id === 'a').rescue, true);
    assert.equal(pairs.find(x => x.molecule_id === 'b').early_stop, true); assert.deepEqual(rows, original);
    assert.equal(UI.pairRows(rows, 'matched_simple').length, 0);
  });
  await test('success threshold and equal-regret tolerance handle boundary ties without invented rescues', () => {
    const rows = [row('tie', 'sequential', 3, 1 + 5e-10), row('tie', 'matched_simple', 2, 1),
      row('fail', 'sequential', 2, 1 + 2e-9), row('fail', 'matched_simple', 2, 1)];
    const [tie, fail] = UI.pairRows(rows);
    assert.equal(tie.rescue, false); assert.equal(tie.waste, true); assert.equal(tie.shared_failure, false);
    assert.equal(fail.rescue, false); assert.equal(fail.early_stop, false); assert.equal(fail.shared_failure, false);
  });
  await test('filtering keeps whole paired molecules and stable family/search/category semantics', () => {
    const rows = UI.pairRows([row('B', 'sequential', 10, 0, 'f1'), row('B', 'matched_simple', 2, 0, 'f1'),
      row('A', 'sequential', 1, 3, 'f2'), row('A', 'matched_simple', 2, 0, 'f2')]);
    assert.deepEqual(UI.filterPairs(rows, {behavior: 'waste'}).map(x => x.molecule_id), ['B']);
    assert.deepEqual(UI.filterPairs(rows, {family: 'f2', search: 'a'}).map(x => x.molecule_id), ['A']);
    assert.equal(UI.filterPairs(rows, {family: 'f1', behavior: 'early_stop'}).length, 0);
    assert.deepEqual(UI.filterPairs(rows, {sort: 'molecule'}).map(x => x.molecule_id), ['A', 'B']);
    assert.deepEqual(rows.map(x => x.molecule_id), ['B', 'A']);
  });
  await test('observed-energy chart uses only own successful paid observations, never evaluator or hidden minima', () => {
    const session = {queries: [{charged: 1, status: 'succeeded', reference_kcal: -100}, {charged: 1, status: 'failed'},
      {charged: 1, status: 'succeeded', reference_kcal: -102}], evaluation: {regret_kcal: 987654321}, hidden_minimum: -9999};
    const output = UI.observedProgress(session, 280);
    assert.match(output, /After 3 calls: -2\.0000/); assert.doesNotMatch(output, /987654321|-9999|-102|-100/);
    assert.match(output, /relative to this lane/);
    assert.doesNotMatch(output, />-0\.0</);
    const empty = UI.observedProgress({queries: [{charged: 1, status: 'failed'}], evaluation: {regret_kcal: 0}});
    assert.match(empty, /No reference revealed/); assert.doesNotMatch(empty, /<svg/);
  });
  await test('paired plot retains sign conventions, handles empty/single pools, and escapes molecule labels', () => {
    assert.match(UI.pairedPlot([], null), /No paired outcomes/);
    const pair = UI.pairRows([row('<script>bad</script>', 'sequential', 1, 3), row('<script>bad</script>', 'matched_simple', 2, 0)])[0];
    const output = UI.pairedPlot([pair], pair.molecule_id, 280);
    assert.match(output, /-1 calls/); assert.match(output, /\+3\.000/); assert.doesNotMatch(output, /<script>/);
    assert.match(output, /&lt;script&gt;/); assert.doesNotMatch(output, /NaN|Infinity/);
  });
  await test('real sealed rows preserve fixed versus matched-simple comparator differences and failure cases', () => {
    const parsed = csv(fs.readFileSync(path.join(__dirname, '../results/lab/per_molecule.csv'), 'utf8'));
    const rows = parsed.map(x => ({...x, expensive_calls: Number(x.expensive_calls), regret_kcal: Number(x.regret_kcal),
      fold_id: Number(x.fold_id), n_candidates: Number(x.n_candidates), success_1kcal: x.success_within_1_kcal === 'True'}));
    const fixed = UI.pairRows(rows, 'fixed_top_k'), matched = UI.pairRows(rows, 'matched_simple');
    assert.equal(fixed.length, 478); assert.equal(new Set(fixed.map(x => x.family_id)).size, 287);
    assert.equal(fixed.filter(x => x.rescue).length, 1); assert.equal(fixed.filter(x => x.waste).length, 10);
    assert.equal(fixed.find(x => x.molecule_id === 'omegacsd_GIHTUM').rescue, true);
    assert.equal(fixed.find(x => x.molecule_id === 'astex_1xoq').waste, true);
    assert.equal(fixed.find(x => x.molecule_id === 'omegapdb_2f4j').early_stop, true);
    assert.equal(fixed.find(x => x.molecule_id === 'omegapdb_2byi').shared_failure, true);
    assert.equal(fixed.find(x => x.molecule_id === 'omegapdb_1yc4').calls_delta, 0);
    assert.equal(matched.find(x => x.molecule_id === 'omegapdb_1yc4').calls_delta, -8);
  });
  await test('comparison DOM keeps each lane reference hidden and suppresses premature evaluator scores', () => {
    const originalCore = global.AQCComparison; let change, snapshot;
    const molecule = {molecule_id: 'm', family_id: 'f', fold_id: 0, candidates: [{candidate_id: 'a', cheap_kcal: 0, geometry_sha256: 'g-a'}, {candidate_id: 'b', cheap_kcal: 1, geometry_sha256: 'g-b'}]};
    const session = () => ({status: 'active', stopped: false, observations: {}, queries: [], expensive_calls: 0, best_verified: null, evaluation: {regret_kcal: 7654321, success_within_1_kcal: false}, pending_reason: 'initial_verification'});
    snapshot = {molecule, lanes: [{role: 'fixed', label: 'Fixed top-2', config: {kind: 'fixed', k: 2}, session: session()},
      {role: 'sequential', label: 'Sequential', config: {kind: 'sequential'}, session: session()}], archived_runs: [], charged_calls: 1, cumulative_charged_calls: 1, completed_lanes: 0};
    snapshot.lanes[0].session.observations = {a: 12345.6789}; snapshot.lanes[0].session.expensive_calls = 1;
    global.AQCComparison = {createComparison(options) { change = options.onChange; return {snapshot: () => copy(snapshot)}; }};
    try {
      const {document, nodes} = dom(); UI.create(document, {api: {}}); change(copy(snapshot));
      assert.equal(nodes.get('cmp-reference').innerHTML, 'Hidden until this lane queries');
      assert.doesNotMatch(nodes.get('comparison-lanes').innerHTML, /7654321/);
      assert.doesNotMatch(nodes.get('cmp-progress').innerHTML, /12345/);
      nodes.get('cmp-lane-select').value = 'fixed'; nodes.get('cmp-lane-select').fire('change');
      assert.match(nodes.get('cmp-reference').innerHTML, /12,345\.6789/);
      nodes.get('cmp-lane-select').value = 'sequential'; nodes.get('cmp-lane-select').fire('change');
      assert.equal(nodes.get('cmp-reference').innerHTML, 'Hidden until this lane queries');
      snapshot.lanes[1].uncertain = true; snapshot.archived_runs = [{}]; snapshot.cumulative_charged_calls = 12; change(copy(snapshot));
      assert.match(nodes.get('cmp-call-label').textContent, /last confirmed/);
      assert.match(nodes.get('comparison-warning').textContent, /no query will be automatically repeated/);
      assert.match(nodes.get('cmp-archive-note').textContent, /last confirmed cumulative/);
    } finally { global.AQCComparison = originalCore; }
  });
  await test('only definitive session expiry enables explicit archiving and incomplete history stays exportable', async () => {
    const originalCore = global.AQCComparison;
    let change, archiveCalls = 0, moleculeFetches = 0;
    const molecule = {molecule_id: 'm', family_id: 'f', fold_id: 0, candidates: [{candidate_id: 'a', cheap_kcal: 0, geometry_sha256: 'g-a'}]};
    let state = {molecule, lanes: [{role: 'sequential', label: 'Sequential', config: {kind: 'sequential'},
      uncertain: true, unavailable: null, session: {status: 'active', stopped: false, observations: {}, queries: [], expensive_calls: 1}}],
      archived_runs: [], charged_calls: 1, cumulative_charged_calls: 1, completed_lanes: 0,
      cumulative_accounting_complete: false, unavailable_lane_count: 0, can_archive_unavailable: false};
    const downloads = [];
    global.AQCComparison = {createComparison(options) {
      change = options.onChange;
      return {snapshot: () => copy(state), exportJSON: () => '{"accounting_complete":false}',
        async archiveUnavailable() {
          archiveCalls++; const archived = copy(state);
          state = {molecule: null, lanes: [], archived_runs: [archived], charged_calls: 0,
            cumulative_charged_calls: 1, completed_lanes: 0, cumulative_accounting_complete: false,
            unavailable_lane_count: 0, can_archive_unavailable: false};
          change(copy(state));
        }};
    }};
    try {
      const {document, nodes} = dom();
      const view = UI.create(document, {api: {molecule: async () => { moleculeFetches++; return molecule; },
        request: async () => ({scope: 'development_family_cv_retrospective', fresh_external_holdout: false, rows: [], cases: []})},
        download: (...args) => downloads.push(args)});
      view.ready({molecules: [{molecule_id: 'm', family_id: 'f', n_candidates: 1}]});
      nodes.get('cmp-molecule').value = 'm'; change(copy(state));
      assert.equal(nodes.get('comparison-recovery').hidden, true);
      assert.equal(nodes.get('cmp-archive-unavailable').disabled, true);
      await nodes.get('cmp-archive-unavailable').fire('click');
      assert.equal(archiveCalls, 0, 'unknown network outcomes cannot be archived');
      state.lanes[0].unavailable = 'session_expired'; state.unavailable_lane_count = 1; state.can_archive_unavailable = true;
      change(copy(state));
      assert.equal(nodes.get('comparison-recovery').hidden, false);
      assert.equal(nodes.get('cmp-archive-unavailable').disabled, false);
      assert.match(nodes.get('comparison-warning').textContent, /expired or unavailable/);
      await nodes.get('cmp-archive-unavailable').fire('click');
      assert.equal(archiveCalls, 1); assert.equal(nodes.get('cmp-current').textContent, 'Choose a molecule');
      assert.equal(nodes.get('cmp-load').disabled, false); assert.equal(nodes.get('cmp-step').disabled, true);
      assert.equal(nodes.get('cmp-json').disabled, false); assert.equal(nodes.get('comparison-inspector').hidden, true);
      assert.match(nodes.get('cmp-archive-note').textContent, /1 last confirmed cumulative/);
      assert.match(nodes.get('comparison-warning').textContent, /lower bound/);
      assert.doesNotMatch(nodes.get('comparison-lanes').innerHTML, /data-policy-lane/);
      view.onView('compare'); await Promise.resolve();
      assert.equal(moleculeFetches, 0, 'archiving does not automatically begin a new comparison');
      await nodes.get('cmp-json').fire('click');
      assert.equal(downloads[0][0], 'aqc-comparison-retained-history.json');
      assert.match(downloads[0][1], /accounting_complete/);
    } finally { global.AQCComparison = originalCore; }
  });
  console.log(`\n${checks} workbench view checks passed. Browser layout and real server replay checks are separate.`);
})().catch(error => { console.error(error); process.exitCode = 1; });
