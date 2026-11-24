'use strict';
/* Frontend contract and DOM-action tests. These do not substitute for browser layout QA. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const C = require('../app/assets/client.js');
const UI = require('../app/assets/app.js');
const ROOT = path.resolve(__dirname, '..');
let checks = 0;
async function test(name, fn) { await fn(); checks++; console.log('PASS ' + name); }
const copy = value => JSON.parse(JSON.stringify(value));
const response = (data, status = 200) => ({ok: status < 400, status, json: async () => copy(data)});
const molecule = {molecule_id: 'real_pool', family_id: 'scaffold_family', fold_id: 2,
  policy_configs: {sequential: {kind: 'sequential', one_gap: .01, one_ratio: .3, error_scale: 1, slack: .25, cap: 10}},
  candidates: [
    {candidate_id: 'a', cheap_kcal: 0, symbols: ['C', 'H'], coordinates_angstrom: [[0, 0, 0], [1, 0, 0]], geometry_sha256: 'geom-a'},
    {candidate_id: 'b', cheap_kcal: .2, symbols: ['C', 'H'], coordinates_angstrom: [[0, 0, 0], [0, 1, 0]], geometry_sha256: 'geom-b'},
    {candidate_id: 'c', cheap_kcal: .5, symbols: ['C', 'H'], coordinates_angstrom: [[0, 0, 0], [0, 0, 1]], geometry_sha256: 'geom-c'}]};
function initialState(config = {kind: 'fixed', k: 2}) {
  return {session_id: 'local_session', molecule_id: molecule.molecule_id, config, mode: config.kind === 'manual' ? 'manual' : 'policy',
    status: 'active', stopped: false, expensive_calls: 0, session_expensive_calls: 0, reset_count: 0, queries: [], observations: {},
    best_verified: null, pending_candidate: config.kind === 'manual' ? null : 'a', pending_reason: 'initial_verification', policy_events: [],
    selected_candidate: null, stop_reason: null, fallback: false, evaluation: null};
}
function paidState() {
  const state = initialState();
  state.expensive_calls = 1; state.session_expensive_calls = 1;
  state.queries = [{order: 1, candidate_id: 'a', charged: 1, status: 'succeeded', reference_kcal: 3}];
  state.observations = {a: 3}; state.best_verified = {candidate_id: 'a', reference_kcal: 3}; state.pending_candidate = 'b';
  return state;
}
function completedState() {
  const state = paidState(); state.stopped = true; state.status = 'completed'; state.pending_candidate = null;
  state.selected_candidate = 'a'; state.stop_reason = 'manual_complete';
  state.evaluation = {regret_kcal: .4, success_within_1_kcal: true, selected_reference_kcal: 3};
  return state;
}
function serverTrace(session, previous = []) {
  return {schema_version: 1, session: copy(session), previous_runs: copy(previous),
    candidates: molecule.candidates.map(row => ({candidate_id: row.candidate_id, cheap_kcal: row.cheap_kcal})),
    accounting: {runs: previous.length + 1, charged_jobs: previous.reduce((sum, row) => sum + row.expensive_calls, 0) + session.expensive_calls},
    label_scope: 'Queried references only.'};
}
function dom() {
  const html = fs.readFileSync(path.join(ROOT, 'app/index.html'), 'utf8');
  const nodes = new Map();
  class Element {
    constructor(id = '') { this.id = id; this.innerHTML = ''; this.textContent = ''; this.value = ''; this.hidden = false; this.disabled = false;
      this.dataset = {}; this.style = {}; this.attrs = {}; this.events = {}; this.checked = false;
      this.classList = {toggle() {}, add() {}, remove() {}}; }
    setAttribute(key, value) { this.attrs[key] = String(value); if (key === 'hidden') this.hidden = true; }
    removeAttribute(key) { delete this.attrs[key]; }
    hasAttribute(key) { return Object.prototype.hasOwnProperty.call(this.attrs, key); }
    addEventListener(key, fn) { this.events[key] = fn; }
    appendChild() {}
    remove() {}
    querySelector(selector) { return this.children?.[selector] || null; }
    closest(selector) { return selector === 'button' ? this : null; }
    async fire(event = 'click', overrides = {}) { if (!this.disabled && this.events[event]) return this.events[event]({target: this, ...overrides}); }
    click() { return this.fire(); }
  }
  for (const match of html.matchAll(/id="([^"]+)"/g)) nodes.set(match[1], new Element(match[1]));
  nodes.get('startup-panel').children = {h1: new Element('heading'), p: new Element('text'), '.loader': new Element('loader')};
  const navs = ['replay', 'results', 'saved'].map(name => { const node = new Element('nav-' + name); node.dataset.view = name; return node; });
  nodes.get('policy-select').value = 'sequential'; nodes.get('configuration-kind').value = 'all'; nodes.get('configuration-risk').value = 'all'; nodes.get('configuration-sort').value = 'mean_calls';
  const document = {body: new Element('body'), getElementById(id) { assert(nodes.has(id), 'Unknown DOM ID ' + id); return nodes.get(id); },
    querySelectorAll: selector => selector === '[data-view]' ? navs : [], createElement: () => new Element('created')};
  const saved = new Map(), storage = {getItem: key => saved.get(key) || null, setItem: (key, value) => saved.set(key, value)};
  return {document, nodes, navs, storage};
}
function mockAPI() {
  let session, creations = 0, actions = 0, releases = 0;
  const references = {a: 3, b: 0, c: -1};
  function query(id) {
    if (Object.prototype.hasOwnProperty.call(session.observations, id)) return;
    session.queries.push({order: session.queries.length + 1, candidate_id: id, charged: 1, status: 'succeeded', reference_kcal: references[id]});
    session.observations[id] = references[id]; session.expensive_calls++; session.session_expensive_calls++;
    const best = Object.keys(session.observations).sort((a, b) => session.observations[a] - session.observations[b])[0];
    session.best_verified = {candidate_id: best, reference_kcal: session.observations[best]};
    session.pending_candidate = ['a', 'b', 'c'][session.expensive_calls] || null;
  }
  function finish() {
    const best = session.best_verified.candidate_id;
    session.stopped = true; session.status = 'completed'; session.selected_candidate = best; session.pending_candidate = null;
    session.stop_reason = session.config.kind === 'manual' ? 'manual_stop' : 'fixed_k_complete';
    session.evaluation = {regret_kcal: references[best] + 1, selected_reference_kcal: references[best], success_within_1_kcal: references[best] + 1 <= 1};
  }
  const api = {health: async () => ({status: 'ok', provenance: {source_revision: 'pinned'}}),
    catalog: async () => ({molecules: [{molecule_id: molecule.molecule_id, family_id: molecule.family_id, n_candidates: 3}]}),
    molecule: async () => copy(molecule),
    createSession: async (id, config) => { creations++; session = initialState(config); session.session_id = 'session' + creations; return copy(session); },
    releaseSession: async () => { releases++; return {released: true}; },
    getSession: async () => copy(session), exportSession: async () => serverTrace(session),
    action: async (id, name, body) => {
      actions++;
      if (name === 'reset') { const calls = session.session_expensive_calls, resets = session.reset_count + 1, config = session.config; session = initialState(config); session.session_expensive_calls = calls; session.reset_count = resets; }
      else if (name === 'finish') finish();
      else if (name === 'query') query(body.candidate_id);
      else { const max = session.config.kind === 'full' ? 3 : 2; query(session.pending_candidate); if (name === 'run') while (session.expensive_calls < max) query(session.pending_candidate); if (session.expensive_calls >= max) finish(); }
      return copy(session);
    },
    results: async () => {
      function csv(file) {
        const text = fs.readFileSync(path.join(ROOT, 'results/lab', file), 'utf8');
        const rows = []; let row = [], field = '', quoted = false;
        for (let i = 0; i < text.length; i++) {
          const ch = text[i];
          if (ch === '"') { if (quoted && text[i + 1] === '"') { field += '"'; i++; } else quoted = !quoted; }
          else if (ch === ',' && !quoted) { row.push(field); field = ''; }
          else if (ch === '\n' && !quoted) { row.push(field.replace(/\r$/, '')); rows.push(row); row = []; field = ''; }
          else field += ch;
        }
        if (field || row.length) { row.push(field); rows.push(row); }
        const keys = rows.shift();
        return rows.map(values => Object.fromEntries(keys.map((key, index) => [key, values[index]])));
      }
      const decision = JSON.parse(fs.readFileSync(path.join(ROOT, 'results/lab/decision.json')));
      return {aggregate: csv('aggregate.csv'), experiments: csv('experiments.csv'), decision,
        fold_choices: {folds: [0, 1, 2, 3, 4]}, provenance: {source_revision: 'pinned'}};
    },
    counters: () => ({creations, actions, releases})};
  return api;
}

(async () => {
  await test('API uses same-origin JSON and does not retry charged mutations', async () => {
    const calls = [], client = C.createClient(async (url, init) => { calls.push({url, init}); return response({ok: true}); });
    await client.health(); await client.createSession('m', {kind: 'fixed', k: 2}); await client.action('id', 'query', {candidate_id: 'a'});
    assert.equal(calls[0].url, '/api/health'); assert.equal(calls[1].init.method, 'POST');
    assert.deepEqual(JSON.parse(calls[2].init.body), {candidate_id: 'a'}); assert.equal(calls[2].init.credentials, 'same-origin');
    await assert.rejects(client.request('https://outside.example/api/'), /Only the local/);
    let failedCalls = 0;
    const failing = C.createClient(async () => { failedCalls++; throw new Error('connection closed'); });
    await assert.rejects(failing.action('id', 'step'), error => error.code === 'offline');
    assert.equal(failedCalls, 1);
  });
  await test('comparison mutation keys reach the server without entering policy data or retrying', async () => {
    const calls = [], client = C.createClient(async (url, init) => { calls.push({url, init}); return response({ok: true}); });
    await client.action('lane-1', 'step', {}, {idempotencyKey: 'comparison-lane-1-step-1'});
    assert.equal(calls.length, 1);
    assert.equal(calls[0].init.headers['Idempotency-Key'], 'comparison-lane-1-step-1');
    assert.deepEqual(JSON.parse(calls[0].init.body), {});
    await assert.rejects(client.action('lane-1', 'step', {}, {idempotencyKey: 'bad\nkey'}), error => error.code === 'invalid_idempotency_key');
    assert.equal(calls.length, 1);
  });
  await test('paid worker failures carry the server state into the UI error', async () => {
    const session = paidState(); session.status = 'failed';
    const client = C.createClient(async () => response({error: {code: 'worker_failed', message: 'Paid query logged'}, session}, 502));
    await assert.rejects(client.action('id', 'step'), error => error.code === 'worker_failed' && error.session.expensive_calls === 1 && error.session.queries.length === 1);
    const invalid = C.createClient(async () => ({ok: true, status: 200, json: async () => { throw new Error(); }}));
    await assert.rejects(invalid.health(), error => error.code === 'invalid_json');
  });
  await test('session normalization hides early evaluation and handles object selection', () => {
    const state = paidState(); state.evaluation = {regret_kcal: 123};
    const normalized = C.unwrapSession(state);
    assert.equal(normalized.evaluation, null); assert.equal(normalized.best_verified, 'a'); assert.equal(normalized.expensive_calls, 1);
    assert.throws(() => C.unwrapSession({...state, observations: {a: Infinity}}), /finite/);
  });
  await test('portable saved runs preserve geometry and only paid observations', () => {
    const input = copy(molecule); input.references = {a: 3, b: 0, c: -1}; input.candidates[0].reference_kcal = 3;
    const saved = C.makeSavedRun(input, paidState(), {source_revision: 'pinned'});
    assert(!('references' in saved.molecule)); assert(!('reference_kcal' in saved.molecule.candidates[0]));
    assert.deepEqual(saved.session.observations, {a: 3}); assert.equal(saved.session.best_verified, 'a');
    assert.deepEqual(C.validateSavedRun(saved).molecule.candidates[1].coordinates_angstrom, [[0, 0, 0], [0, 1, 0]]);
    assert.throws(() => C.validateSavedRun({format: 'unrelated', version: 1}), /exported/);
    const uncharged = copy(saved); uncharged.session.observations.b = 0;
    assert.throws(() => C.validateSavedRun(uncharged), /successful paid-query history/);
    const wrongCount = copy(saved); wrongCount.session.expensive_calls = 2;
    assert.throws(() => C.validateSavedRun(wrongCount), /charge total/);
    const unverified = copy(saved); unverified.session.best_verified = 'b';
    assert.throws(() => C.validateSavedRun(unverified), /not the best queried/);
    const badCoordinates = copy(saved); badCoordinates.molecule.candidates[0].coordinates_angstrom[0][0] = 'NaN';
    assert.throws(() => C.validateSavedRun(badCoordinates), /coordinates/);
  });
  await test('imports reject molecule and family mismatches even with identical candidate IDs', () => {
    const saved = C.makeSavedRun(molecule, completedState());
    for (const key of ['molecule_id', 'family_id']) {
      const forged = copy(saved); forged.session[key] = 'a_different_' + key;
      assert.throws(() => C.validateSavedRun(forged), /identity differs/);
    }
    const forgedTrace = serverTrace(completedState()); forgedTrace.session.molecule_id = 'another_pool';
    assert.throws(() => C.makeSavedRun(molecule, completedState(), {}, forgedTrace), /identity differs/);
  });
  await test('imports reject duplicate charges, fabricated cached reveals and reference/status contradictions', () => {
    const duplicate = paidState(); duplicate.queries.push({...duplicate.queries[0], order: 2}); duplicate.expensive_calls = 2; duplicate.session_expensive_calls = 2;
    assert.throws(() => C.makeSavedRun(molecule, duplicate), /duplicate charged/);
    const cachedBeforePaid = paidState(); cachedBeforePaid.queries[0].status = 'cached'; cachedBeforePaid.queries[0].charged = 0;
    assert.throws(() => C.makeSavedRun(molecule, cachedBeforePaid), /preceding paid/);
    const wrongCache = paidState(); wrongCache.queries.push({...wrongCache.queries[0], order: 2, charged: 0, status: 'cached', reference_kcal: 1});
    assert.throws(() => C.makeSavedRun(molecule, wrongCache), /Cached reference differs/);
    const failedReveal = paidState(); failedReveal.queries[0].status = 'failed'; failedReveal.queries[0].error = 'missing_reference';
    assert.throws(() => C.makeSavedRun(molecule, failedReveal), /cannot reveal/);
    const unobservedSuccess = paidState(); unobservedSuccess.observations = {}; unobservedSuccess.best_verified = null;
    assert.throws(() => C.makeSavedRun(molecule, unobservedSuccess), /exactly match/);
    const erasedValue = paidState(); delete erasedValue.queries[0].reference_kcal;
    assert.throws(() => C.makeSavedRun(molecule, erasedValue), /finite reference/);
    const falseError = paidState(); falseError.queries[0].error = 'missing_reference';
    assert.throws(() => C.makeSavedRun(molecule, falseError), /no error/);
    const reordered = paidState(); reordered.queries[0].order = 2;
    assert.throws(() => C.makeSavedRun(molecule, reordered), /order or charge/);
    const cached = paidState(); cached.queries.push({...cached.queries[0], order: 2, charged: 0, status: 'cached'});
    assert.equal(C.makeSavedRun(molecule, cached).session.expensive_calls, 1);
    const failed = initialState(); failed.status = 'failed'; failed.stopped = true;
    failed.expensive_calls = failed.session_expensive_calls = 1; failed.pending_candidate = null;
    failed.queries = [{order: 1, candidate_id: 'a', charged: 1, status: 'failed', error: 'missing_reference'},
      {order: 2, candidate_id: 'a', charged: 0, status: 'cached_failure', error: 'missing_reference'}];
    assert.equal(C.makeSavedRun(molecule, failed).session.queries.length, 2);
    failed.queries[1].error = 'different_error';
    assert.throws(() => C.makeSavedRun(molecule, failed), /Cached failure differs/);
  });
  await test('final selections must equal the best queried reference with Python-compatible tie ordering', () => {
    const wrong = completedState(); wrong.selected_candidate = 'b';
    assert.throws(() => C.makeSavedRun(molecule, wrong), /final selected candidate/);
    const tied = completedState();
    tied.queries.push({order: 2, candidate_id: 'b', charged: 1, status: 'succeeded', reference_kcal: 3});
    tied.observations.b = 3; tied.expensive_calls = tied.session_expensive_calls = 2;
    tied.best_verified = 'b'; tied.selected_candidate = 'b';
    assert.throws(() => C.makeSavedRun(molecule, tied), /deterministic ties/);
    tied.best_verified = tied.selected_candidate = 'a';
    assert.equal(C.makeSavedRun(molecule, tied).session.selected_candidate, 'a');
    const unicodeMolecule = {molecule_id: molecule.molecule_id, family_id: molecule.family_id, candidates: [
      {candidate_id: '\ue000', cheap_kcal: 0}, {candidate_id: '\ud83d\ude00', cheap_kcal: 0}]};
    const unicodeState = completedState(); unicodeState.queries = unicodeMolecule.candidates.map((row, index) => ({order: index + 1, candidate_id: row.candidate_id, charged: 1, status: 'succeeded', reference_kcal: 0}));
    unicodeState.expensive_calls = unicodeState.session_expensive_calls = 2; unicodeState.observations = {'\ue000': 0, '\ud83d\ude00': 0};
    unicodeState.best_verified = unicodeState.selected_candidate = '\ue000';
    unicodeState.evaluation = {regret_kcal: 0, selected_reference_kcal: 0, success_within_1_kcal: true};
    assert.equal(C.makeSavedRun(unicodeMolecule, unicodeState).session.selected_candidate, '\ue000');
  });
  await test('evaluation is finite, nonnegative, consistent, and only present after a completed stop', () => {
    for (const value of [-1, NaN, Infinity, '0']) {
      const invalid = completedState(); invalid.evaluation.regret_kcal = value;
      assert.throws(() => C.makeSavedRun(molecule, invalid), /finite, nonnegative/);
    }
    const premature = paidState(); premature.evaluation = completedState().evaluation;
    assert.throws(() => C.makeSavedRun(molecule, premature), /absent before/);
    const wrongFlag = completedState(); wrongFlag.evaluation.success_within_1_kcal = false;
    assert.throws(() => C.makeSavedRun(molecule, wrongFlag), /success flag/);
    const wrongValue = completedState(); wrongValue.evaluation.selected_reference_kcal = 0;
    assert.throws(() => C.makeSavedRun(molecule, wrongValue), /Evaluator selection differs/);
    const noEvaluation = completedState(); noEvaluation.evaluation = null;
    assert.throws(() => C.makeSavedRun(molecule, noEvaluation), /finite, nonnegative/);
    const fullyRevealed = completedState(); fullyRevealed.queries = molecule.candidates.map((row, index) => ({order: index + 1, candidate_id: row.candidate_id, charged: 1, status: 'succeeded', reference_kcal: 3 + index}));
    fullyRevealed.observations = {a: 3, b: 4, c: 5}; fullyRevealed.expensive_calls = fullyRevealed.session_expensive_calls = 3;
    assert.throws(() => C.makeSavedRun(molecule, fullyRevealed), /zero regret/);
    fullyRevealed.evaluation.regret_kcal = 0;
    assert.equal(C.makeSavedRun(molecule, fullyRevealed).session.evaluation.regret_kcal, 0);
  });
  await test('reset histories have bounded counts and independently reconciled cumulative charges', () => {
    const current = paidState(); current.reset_count = 1; current.session_expensive_calls = 2;
    const previous = paidState(); previous.ended_by_reset = true;
    const trace = serverTrace(current, [previous]);
    const saved = C.makeSavedRun(molecule, current, {}, trace);
    assert.equal(C.validateSavedRun(saved).server_trace.accounting.charged_jobs, 2);
    for (const [key, value] of [['reset_count', 10], ['reset_count', 1.5], ['session_expensive_calls', 100000], ['expensive_calls', 4]]) {
      const invalid = paidState(); invalid[key] = value;
      assert.throws(() => C.makeSavedRun(molecule, invalid), /limits/);
    }
    const wrongCount = copy(trace); wrongCount.accounting.runs = 20;
    assert.throws(() => C.makeSavedRun(molecule, current, {}, wrongCount), /accounting/);
    const wrongPrior = copy(trace); wrongPrior.previous_runs[0].molecule_id = 'wrong_pool';
    assert.throws(() => C.makeSavedRun(molecule, current, {}, wrongPrior), /identity/);
    const wrongCharge = copy(trace); wrongCharge.accounting.charged_jobs = 1;
    assert.throws(() => C.makeSavedRun(molecule, current, {}, wrongCharge), /accounting/);
    const excessEvents = paidState(); excessEvents.queries = Array.from({length: 125}, (_, index) => ({...excessEvents.queries[0], order: index + 1}));
    assert.throws(() => C.makeSavedRun(molecule, excessEvents), /trial limits/);
  });
  await test('raw trace/provenance and extra reference maps cannot survive imported snapshot reconstruction', () => {
    const completed = completedState();
    assert.throws(() => C.makeSavedRun(molecule, completed, {}, {references: {a: 3, b: -999}, provenance: {verified: true}}), /arbitrary trace/);
    const trace = serverTrace(completed);
    trace.references = {a: 3, b: -999}; trace.provenance = {verified: true, seal: 'invented'};
    trace.session.references = {b: -999}; trace.session.evaluation.references = {c: -1000};
    trace.session.policy_events = [{event: 'stop', event_order: 1, selected_candidate: 'a', references: {b: -999}, provenance: {verified: true}}];
    completed.policy_events = copy(trace.session.policy_events);
    const saved = C.makeSavedRun(molecule, completed, {dataset_kind: 'real', source_revision: 'declared-only', verified: true, provenance: {sealed: true}}, trace);
    const serialized = JSON.stringify(C.validateSavedRun(saved));
    assert(!serialized.includes('"references"')); assert(!serialized.includes('"provenance"')); assert(!serialized.includes('"verified":true'));
    assert.equal(saved.source.declared_source_revision, 'declared-only'); assert.equal(saved.verification.authenticity_verified, false);
    assert.equal(saved.server_trace.verification.status, 'unverified_snapshot');
    const inventedConfig = paidState(); inventedConfig.config.references = {b: -999};
    assert.throws(() => C.makeSavedRun(molecule, inventedConfig), /configuration/);
  });
  await test('fold-selected configurations are copied; missing sequential choices are not invented', () => {
    const config = UI.resolveConfig(molecule, {}, 'sequential'); config.cap = 999;
    assert.equal(molecule.policy_configs.sequential.cap, 10);
    assert.deepEqual(UI.resolveConfig({}, {}, 'fixed'), {kind: 'fixed', k: 2});
    assert.throws(() => UI.resolveConfig({}, {}, 'sequential'), /unavailable/);
    assert.throws(() => UI.resolveConfig({}, {policies: [{id: 'sequential', config: molecule.policy_configs.sequential}]}, 'sequential'), /unavailable/);
  });
  await test('configuration filtering preserves the original results and includes target ties', () => {
    const rows = [{config_id: 'seq', kind: 'sequential', success_rate: .95, mean_calls: 1.4, p95_regret_kcal: 1},
      {config_id: 'fixed', kind: 'fixed', success_rate: .99, mean_calls: 2, p95_regret_kcal: .2},
      {config_id: 'cheap_only', kind: 'diagnostic', success_rate: .8, mean_calls: 0, p95_regret_kcal: 2}];
    assert.deepEqual(C.filterExperiments(rows, {maxRisk: .05}).map(row => row.config_id), ['seq', 'fixed']);
    assert.deepEqual(C.filterExperiments(rows, {kind: 'sequential', search: 'seq'}).map(row => row.config_id), ['seq']);
    assert.equal(rows[0].config_id, 'seq'); assert.equal(C.policyKind({policy: 'cheap_only'}), 'diagnostic');
    assert.match(C.csv([{name: 'a,"b', value: 2}], ['name', 'value']), /"a,""b"/);
    assert.match(UI.renderPlot(rows, 'registry'), /Pooled development/);
    assert.match(UI.renderPlot(rows, 'registry'), /Unverified diagnostic/);
  });
  await test('main DOM flow keeps labels hidden, charges once per step, and exposes regret only at stop', async () => {
    const h = dom(), api = mockAPI(); const app = UI.createApp(h.document, {api, storage: h.storage});
    await app.start();
    assert.equal(app.state().session.expensive_calls, 0); assert.deepEqual(app.state().session.observations, {});
    assert.equal(h.nodes.get('session-result').hidden, true); assert.match(h.nodes.get('view-reference-energy').innerHTML, /Hidden/);
    assert.equal(h.nodes.get('step-query').disabled, false);
    assert.equal(h.nodes.get('session-status').textContent, 'Ready');
    await app.action('step');
    assert.equal(app.state().session.expensive_calls, 1); assert.equal(app.state().session.best_verified, 'a');
    assert.equal(h.nodes.get('session-status').textContent, 'Ready');
    assert.equal(h.nodes.get('session-result').hidden, true); assert.match(h.nodes.get('query-history').innerHTML, /\+1 charged call/);
    app.selectCandidate('b'); assert.match(h.nodes.get('view-reference-energy').innerHTML, /Hidden/);
    await app.action('run');
    assert.equal(app.state().session.expensive_calls, 2); assert.equal(app.state().session.best_verified, 'b');
    assert.equal(app.state().session.evaluation.regret_kcal, 1); assert.equal(h.nodes.get('session-result').hidden, false);
    assert.match(h.nodes.get('session-result').innerHTML, /WITHIN 1 KCAL\/MOL/); assert.equal(h.nodes.get('query-actions').hidden, true);
    await app.action('reset'); assert.equal(app.state().session.expensive_calls, 0); assert.equal(app.state().session.session_expensive_calls, 2);
    assert.equal(h.nodes.get('session-result').hidden, true);
  });
  await test('manual mode, completed snapshots, local saving and imported read-only views are wired', async () => {
    const h = dom(), api = mockAPI(), app = UI.createApp(h.document, {api, storage: h.storage}); await app.start();
    h.nodes.get('policy-select').value = 'manual'; await app.changePolicy();
    assert.equal(h.nodes.get('finish-manual').hidden, false); assert.equal(h.nodes.get('finish-manual').disabled, true);
    app.selectCandidate('b'); await app.action('query', {candidate_id: 'b'});
    assert.equal(h.nodes.get('step-query').disabled, true); assert.equal(h.nodes.get('finish-manual').disabled, false);
    await app.action('finish'); await h.nodes.get('save-run').fire();
    const saved = JSON.parse(h.storage.getItem('aqc-workbench-saved-runs-v1'));
    assert.equal(saved.length, 1); assert.equal(saved[0].run.session.selected_candidate, 'b');
    const before = api.counters().actions; app.openSaved(saved[0].run);
    assert.equal(app.state().savedMode, true); assert.equal(h.nodes.get('query-actions').hidden, true);
    assert.match(h.nodes.get('coordinate-scope-label').textContent, /UNVERIFIED/);
    assert.match(h.nodes.get('session-result').innerHTML, /not independently re-evaluated/);
    await app.action('query', {candidate_id: 'c'}); assert.equal(api.counters().actions, before);
    assert.match(h.nodes.get('saved-mode-detail').textContent, /without another query/);
    assert(api.counters().releases >= 1, 'switching policy releases abandoned server sessions');
  });
  await test('double taps do not overlap server mutations', async () => {
    const h = dom(), api = mockAPI(), original = api.action; let release, entered = 0;
    api.action = async (...args) => { entered++; await new Promise(resolve => { release = resolve; }); return original(...args); };
    const app = UI.createApp(h.document, {api, storage: h.storage}); await app.start();
    const first = app.action('step'); await app.action('step'); assert.equal(entered, 1);
    assert.equal(h.nodes.get('session-status').textContent, 'Working');
    release(); await first; assert.equal(app.state().session.expensive_calls, 1);
    assert.equal(h.nodes.get('session-status').textContent, 'Ready');
  });
  await test('failed charged response is rendered and unsafe automatic retry is avoided', async () => {
    const h = dom(), api = mockAPI(), app = UI.createApp(h.document, {api, storage: h.storage}); await app.start();
    let calls = 0; api.action = async () => { calls++; const error = new C.APIError('Worker failed', 502, 'worker_failed'); error.session = {...paidState(), status: 'failed'}; throw error; };
    await app.action('step'); assert.equal(calls, 1); assert.equal(app.state().session.expensive_calls, 1);
    assert.match(h.nodes.get('query-history').innerHTML, /3.0000/); assert.equal(h.nodes.get('step-query').disabled, true);
    assert.match(h.nodes.get('global-error').textContent, /Worker failed/);
  });
  await test('real saved registry contains 1020 rows and remains correctly labeled in the UI', async () => {
    const h = dom(), api = mockAPI(), app = UI.createApp(h.document, {api, storage: h.storage}); await app.start();
    app.view('results'); await new Promise(resolve => setImmediate(resolve));
    assert.equal(app.state().results.experiments.length, 1020); assert.equal(app.state().results.aggregate.length, 6);
    assert.match(h.nodes.get('scope-explanation').innerHTML, /not a fresh external holdout/);
    assert.match(h.nodes.get('result-decision').innerHTML, /not met/);
    await h.nodes.get('scope-registry').fire();
    assert.match(h.nodes.get('visible-result-count').textContent, /1,020/);
    h.nodes.get('configuration-kind').value = 'sequential'; await h.nodes.get('configuration-kind').fire('change');
    assert.match(h.nodes.get('visible-result-count').textContent, /816/);
    assert.match(h.nodes.get('scope-explanation').innerHTML, /descriptive pooled/);
  });
  await test('new app uses only local assets and preserves the original viewer byte for byte', () => {
    const html = fs.readFileSync(path.join(ROOT, 'app/index.html'), 'utf8');
    assert(!/<script[^>]+src=["']https?:/i.test(html)); assert(!/<script(?![^>]*src=)[^>]*>/i.test(html));
    assert(html.includes('width=device-width')); assert(html.includes('aria-label="Workbench views"'));
    assert.equal(fs.readFileSync(path.join(ROOT, 'app/assets/molecule-viewer.js'), 'utf8'), fs.readFileSync(path.join(ROOT, 'aqc/web/molecule-viewer.js'), 'utf8'));
  });
  console.log('\n' + checks + ' frontend checks passed. Browser visual/layout checks are separate.');
})().catch(error => { console.error(error); process.exitCode = 1; });
