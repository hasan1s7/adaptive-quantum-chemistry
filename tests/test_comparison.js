'use strict';
/* Independent comparison orchestration and charged-request fault tests. */
const assert = require('node:assert/strict');
const C = require('../app/assets/client.js');
const Comparison = require('../app/assets/comparison.js');
const copy = value => JSON.parse(JSON.stringify(value));
let checks = 0;
async function test(name, fn) { await fn(); checks++; console.log('PASS ' + name); }
const molecule = {molecule_id: 'fixture_comparison', family_id: 'fixture_family', fold_id: 3,
  policy_configs: {fixed: {kind: 'fixed', k: 2}, matched_simple: {kind: 'adaptive', k: 2, gap: .6, cap: 3},
    sequential: {kind: 'sequential', one_gap: .01, one_ratio: .3, error_scale: 1, slack: .25, cap: 3}, full: {kind: 'full'}},
  provenance: {source_revision: 'a'.repeat(40), evidence_seal_sha256: 'e'.repeat(64), extra_reference_map: {secret: 99}},
  candidates: ['a', 'b', 'c'].map((id, index) => ({candidate_id: id, cheap_kcal: index * .2,
    geometry_sha256: ('abc'[index]).repeat(64), xyz_sha256: ('def'[index]).repeat(64),
    symbols: ['C', 'H'], coordinates_angstrom: [[0, 0, 0], [1, index, 0]], forbidden_reference: 900 + index}))};
function mockAPI() {
  const states = new Map(), actions = [], created = [], released = [], references = {a: 3, b: 0, c: -1};
  let count = 0, createErrorAt = 0, actionHook = null, getHook = null;
  function initial(config, id) {
    return {session_id: id, molecule_id: molecule.molecule_id, config: copy(config), mode: 'policy', status: 'active', stopped: false,
      expensive_calls: 0, session_expensive_calls: 0, reset_count: 0, queries: [], observations: {}, best_verified: null,
      selected_candidate: null, pending_candidate: 'a', pending_reason: 'initial_verification', policy_events: [],
      stop_reason: null, fallback: false, evaluation: null, revision: 0};
  }
  function query(session) {
    const id = session.pending_candidate;
    assert(id && !Object.hasOwn(session.observations, id));
    session.queries.push({order: session.queries.length + 1, candidate_id: id, charged: 1, status: 'succeeded', reference_kcal: references[id]});
    session.observations[id] = references[id]; session.expensive_calls++; session.session_expensive_calls++;
    const best = Object.keys(session.observations).sort((a, b) => references[a] - references[b] || a.localeCompare(b))[0];
    session.best_verified = {candidate_id: best, reference_kcal: references[best]};
    session.pending_candidate = ['a', 'b', 'c'][session.expensive_calls] || null;
    const max = session.config.kind === 'fixed' ? 2 : session.config.kind === 'sequential' ? 1 : 3;
    if (session.expensive_calls === max) {
      session.stopped = true; session.status = 'completed'; session.pending_candidate = null; session.selected_candidate = best;
      session.stop_reason = session.config.kind === 'full' ? 'full_rerank_complete' : 'fixed_k_complete';
      session.evaluation = {regret_kcal: references[best] + 1, success_within_1_kcal: references[best] + 1 <= 1 + 1e-9, selected_reference_kcal: references[best]};
    }
  }
  const api = {
    async createSession(mid, config) {
      assert.equal(mid, molecule.molecule_id); count++;
      if (count === createErrorAt) throw new Error('worker startup failure');
      const id = 'test_session_' + count, state = initial(config, id);
      states.set(id, state); created.push({id, config: copy(config)}); return copy(state);
    },
    async releaseSession(id) { released.push(id); return {closed: true}; },
    async getSession(id) { if (getHook) return getHook(id); return copy(states.get(id)); },
    async action(id, action, data, options) {
      assert.deepEqual(data, {}); assert.match(options.idempotencyKey, /^[A-Za-z0-9_.:-]{1,80}$/);
      assert(!actions.some(row => row.key === options.idempotencyKey), 'each operator request has a fresh idempotency key');
      actions.push({id, action, key: options.idempotencyKey});
      const session = states.get(id);
      query(session); if (action === 'run') while (!session.stopped) query(session);
      session.revision++;
      if (actionHook) return actionHook(id, session);
      return copy(session);
    }
  };
  return {api, states, actions, created, released,
    failCreateAt(value) { createErrorAt = value; }, onAction(fn) { actionHook = fn; }, onGet(fn) { getHook = fn; }};
}
async function fixture(roles) { const mock = mockAPI(), controller = Comparison.createComparison({api: mock.api}); await controller.load(copy(molecule), roles); return {mock, controller}; }

(async () => {
  await test('four lanes start at zero with exact fold choices and identical ordered geometry identities', async () => {
    const {mock, controller} = await fixture(); const state = controller.snapshot();
    assert.equal(state.charged_calls, 0); assert.equal(state.cumulative_charged_calls, 0); assert.equal(state.lanes.length, 4);
    assert.equal(new Set(state.lanes.map(lane => lane.session.session_id)).size, 4);
    assert.deepEqual(state.lanes.find(row => row.role === 'matched_simple').config, molecule.policy_configs.matched_simple);
    assert.notDeepEqual(state.lanes[0].config, state.lanes[1].config);
    assert.deepEqual(Comparison.poolIdentity(state.molecule), Comparison.poolIdentity(molecule));
    assert.equal(mock.actions.length, 0); assert(!JSON.stringify(state).includes('forbidden_reference'));
    assert(!JSON.stringify(state).includes('extra_reference_map'));
    assert(Object.isFrozen(state) && Object.isFrozen(state.lanes[0].config));
  });
  await test('one paid reveal belongs only to its lane; same candidate costs another lane separately', async () => {
    const {controller, mock} = await fixture(); await controller.actionLane('fixed', 'step');
    let state = controller.snapshot(); assert.equal(state.charged_calls, 1);
    assert.deepEqual(state.lanes[0].session.observations, {a: 3});
    for (const lane of state.lanes.slice(1)) { assert.deepEqual(lane.session.observations, {}); assert.equal(lane.session.expensive_calls, 0); assert.equal(lane.session.evaluation, null); }
    await controller.actionLane('full', 'step'); state = controller.snapshot();
    assert.equal(state.charged_calls, 2); assert.deepEqual(state.lanes[3].session.observations, {a: 3});
    assert.equal(mock.actions.length, 2); assert.notEqual(mock.actions[0].id, mock.actions[1].id);
  });
  await test('batch stepping and stopping preserve own selection, score boundary, and total independent charges', async () => {
    const {controller} = await fixture(); await controller.stepAll(); let state = controller.snapshot();
    assert.equal(state.charged_calls, 4); assert.equal(state.completed_lanes, 1);
    for (const lane of state.lanes) assert.equal(lane.session.evaluation !== null, lane.role === 'sequential');
    await controller.runAll(); state = controller.snapshot();
    assert.equal(state.status, 'completed'); assert.equal(state.charged_calls, 9); assert.equal(state.completed_lanes, 4);
    assert.equal(state.lanes[0].session.selected_candidate, 'b'); assert.equal(state.lanes[0].session.evaluation.regret_kcal, 1);
    assert.equal(state.lanes[2].session.selected_candidate, 'a'); assert.equal(state.lanes[2].session.evaluation.regret_kcal, 4);
    assert.equal(state.lanes[3].session.selected_candidate, 'c'); assert.equal(state.lanes[3].session.evaluation.regret_kcal, 0);
    await controller.stepAll(); assert.equal(controller.snapshot().charged_calls, 9);
  });
  await test('a partially created replacement is released without deleting the previous paid comparison', async () => {
    const {controller, mock} = await fixture(); await controller.actionLane('fixed', 'step');
    const prior = controller.snapshot(); mock.failCreateAt(7);
    await assert.rejects(controller.load(copy(molecule)), /startup failure/);
    const after = controller.snapshot(); assert.equal(after.charged_calls, 1); assert.deepEqual(after.lanes, prior.lanes);
    assert.deepEqual(mock.released, ['test_session_5', 'test_session_6']); assert.equal(after.archived_runs.length, 0);
  });
  await test('double taps, molecule changes, and disposal are rejected while a paid request is in flight', async () => {
    const {controller, mock} = await fixture(); let finish;
    mock.onAction((id, state) => new Promise(resolve => { finish = () => resolve(copy(state)); }));
    const request = controller.actionLane('fixed', 'step');
    await assert.rejects(controller.stepAll(), /in progress/); await assert.rejects(controller.load(copy(molecule)), /in progress/);
    await assert.rejects(controller.dispose(), /in progress/); assert.equal(mock.actions.length, 1);
    await assert.rejects(controller.archiveUnavailable(), /in progress/);
    finish(); await request; assert.equal(controller.snapshot().charged_calls, 1);
  });
  await test('a timed-out charged mutation is reconciled by GET without retrying the mutation', async () => {
    const {controller, mock} = await fixture(); mock.onAction(() => { throw new C.APIError('network timeout', 0, 'timeout'); });
    await controller.actionLane('fixed', 'step'); const state = controller.snapshot();
    assert.equal(mock.actions.length, 1); assert.equal(state.charged_calls, 1); assert.equal(state.lanes[0].uncertain, false);
    assert.deepEqual(state.lanes[0].session.observations, {a: 3}); assert.match(state.lanes[0].error, /timeout/);
  });
  await test('unreconciled charged outcomes block all further mutation and survive export until explicitly reconciled', async () => {
    const {controller, mock} = await fixture(); mock.onAction(() => { throw new Error('lost response'); }); mock.onGet(() => { throw new Error('offline'); });
    await controller.actionLane('fixed', 'step'); let state = controller.snapshot();
    assert.equal(state.lanes[0].uncertain, true); assert.equal(state.charged_calls, 0); // Last confirmed total, explicitly uncertain.
    await assert.rejects(controller.runAll(), /Reconcile/); await assert.rejects(controller.load(copy(molecule)), /Reconcile/);
    const report = controller.exportReport(); assert.equal(report.runs[0].lanes[0].uncertain, true);
    mock.onGet(null); await controller.reconcileLane('fixed'); state = controller.snapshot();
    assert.equal(state.lanes[0].uncertain, false); assert.equal(state.charged_calls, 1); assert.equal(mock.actions.length, 1);
  });
  await test('410 expiry and 404 missing sessions can be explicitly archived without losing their last confirmed ledgers', async () => {
    for (const [status, code] of [[410, 'session_expired'], [404, 'unknown_session']]) {
      const {controller, mock} = await fixture(); await controller.actionLane('fixed', 'step');
      const before = controller.snapshot(); mock.onGet(() => { throw new C.APIError('Session unavailable', status, code); });
      await controller.reconcileLane('fixed'); let state = controller.snapshot();
      assert.equal(state.lanes[0].unavailable, code); assert.equal(state.lanes[0].uncertain, true);
      assert.equal(state.unavailable_lane_count, 1); assert.equal(state.can_archive_unavailable, true);
      assert.equal(state.cumulative_accounting_complete, false); assert.equal(state.charged_calls, 1);
      await controller.archiveUnavailable(); state = controller.snapshot();
      assert.equal(state.molecule, null); assert.deepEqual(state.lanes, []); assert.equal(state.charged_calls, 0);
      assert.equal(state.cumulative_charged_calls, 1); assert.equal(state.cumulative_accounting_complete, false);
      assert.equal(state.archived_runs.length, 1); assert.equal(state.archived_runs[0].accounting_complete, false);
      assert.deepEqual(state.archived_runs[0].lanes[0].session.queries, before.lanes[0].session.queries);
      assert.deepEqual(mock.released, ['test_session_2', 'test_session_3', 'test_session_4']);
      const report = controller.exportReport(); assert.equal(report.runs.length, 1);
      assert.equal(report.runs[0].lanes[0].unavailable, code); assert.equal(report.cumulative_accounting_complete, false);
      assert.match(report.calls_meaning, /lower bound/); assert(controller.exportCSV().includes(code));
      mock.onGet(null); await controller.load(copy(molecule)); await controller.runAll();
      assert.equal(controller.snapshot().charged_calls, 9); assert.equal(controller.snapshot().cumulative_charged_calls, 10);
      assert.equal(controller.snapshot().cumulative_accounting_complete, false, 'New complete runs cannot resolve an old missing outcome');
      assert.equal(controller.exportReport().runs.length, 2);
    }
  });
  await test('a charged response lost before expiry remains an explicit lower bound after recovery and new queries', async () => {
    const {controller, mock} = await fixture(); await controller.actionLane('fixed', 'step');
    mock.onAction(() => { throw new C.APIError('Response lost after charging', 0, 'timeout'); });
    mock.onGet(() => { throw new C.APIError('Session has expired', 410, 'session_expired'); });
    await controller.actionLane('fixed', 'step');
    assert.equal(mock.states.get('test_session_1').expensive_calls, 2); // Server charged the missing response.
    assert.equal(controller.snapshot().charged_calls, 1); assert.equal(mock.actions.length, 2);
    await controller.archiveUnavailable();
    const report = controller.exportReport(); assert.equal(report.cumulative_charged_calls, 1); assert.equal(report.cumulative_accounting_complete, false);
    assert.deepEqual(report.runs[0].lanes[0].session.observations, {a: 3});
    assert.equal(report.runs[0].lanes[0].session.selected_candidate, null);
    assert.equal(report.runs[0].lanes[0].uncertain, true); assert.equal(report.runs[0].lanes[0].unavailable, 'session_expired');
    mock.onAction(null); mock.onGet(null); await controller.load(copy(molecule)); await controller.actionLane('full', 'step');
    assert.equal(controller.snapshot().cumulative_charged_calls, 2); assert.equal(controller.snapshot().cumulative_accounting_complete, false);
    assert.equal(mock.actions.length, 3, 'No old paid mutation was automatically replayed');
  });
  await test('temporary unknown outcomes cannot be archived, even alongside a confirmed expired lane', async () => {
    const {controller, mock} = await fixture();
    mock.onGet(id => { throw id === 'test_session_1' ? new C.APIError('Expired', 410, 'session_expired') : new C.APIError('Offline', 0, 'offline'); });
    await controller.reconcileLane('fixed'); await controller.reconcileLane('full');
    assert.equal(controller.snapshot().can_archive_unavailable, false);
    await assert.rejects(controller.archiveUnavailable(), /temporary connection failure/);
    assert.equal(controller.snapshot().archived_runs.length, 0); assert.equal(mock.released.length, 0);
    mock.onGet(null); await controller.reconcileLane('full'); assert.equal(controller.snapshot().can_archive_unavailable, true);
    await controller.reconcileLane('fixed');
    assert.equal(controller.snapshot().lanes[0].unavailable, null); assert.equal(controller.snapshot().cumulative_accounting_complete, true);
    await assert.rejects(controller.archiveUnavailable(), /confirmed expired or missing/);
  });
  await test('mutation errors classify only confirmed unavailable session codes and never replay their action', async () => {
    const {controller, mock} = await fixture(); let attempts = 0;
    mock.api.action = async () => { attempts++; throw new C.APIError('Expired before request', 410, 'session_expired'); };
    mock.onGet(() => { throw new C.APIError('Connection lost', 0, 'offline'); });
    await controller.actionLane('fixed', 'step');
    assert.equal(attempts, 1); assert.equal(controller.snapshot().lanes[0].unavailable, 'session_expired');
    assert.equal(controller.snapshot().can_archive_unavailable, true); assert.equal(controller.snapshot().charged_calls, 0);
    await controller.archiveUnavailable(); await controller.load(copy(molecule));
    mock.api.action = async () => { attempts++; throw new C.APIError('Unknown action', 404, 'unknown_action'); };
    await controller.actionLane('fixed', 'step');
    assert.equal(attempts, 2); assert.equal(controller.snapshot().lanes[0].unavailable, null);
    assert.equal(controller.snapshot().can_archive_unavailable, false);
    await assert.rejects(controller.archiveUnavailable(), /confirmed expired or missing/);
  });
  await test('unavailable recovery checks the archive cap before releasing any worker or discarding a ledger', async () => {
    const {controller, mock} = await fixture(['fixed', 'full']);
    for (let i = 0; i < Comparison.MAX_ARCHIVED; i++) { await controller.actionLane('fixed', 'step'); await controller.load(copy(molecule), ['fixed', 'full']); }
    mock.onGet(() => { throw new C.APIError('No longer available', 404, 'unknown_session'); });
    await controller.reconcileLane('fixed');
    const before = controller.snapshot(), releases = mock.released.length;
    assert.equal(before.can_archive_unavailable, false); await assert.rejects(controller.archiveUnavailable(), /archive is full/);
    assert.deepEqual(controller.snapshot(), before); assert.equal(mock.released.length, releases);
    assert.equal(controller.exportReport().runs.length, Comparison.MAX_ARCHIVED + 1);
  });
  await test('a server failure payload retains the charged query ledger and never exposes an evaluator score', async () => {
    const {controller, mock} = await fixture(); mock.onAction((id, session) => {
      session.status = 'failed'; session.stopped = true; session.pending_candidate = null; session.stop_reason = 'runtime_failure';
      session.failure = {code: 'worker_failure', message: 'worker exited'}; session.evaluation = null;
      const error = new C.APIError('paid worker failure', 502); error.session = copy(session); throw error;
    });
    await controller.actionLane('fixed', 'step'); const state = controller.snapshot();
    assert.equal(state.status, 'partial_failure'); assert.equal(state.charged_calls, 1); assert.equal(state.lanes[0].session.evaluation, null);
    assert.equal(state.lanes[0].session.status, 'failed'); assert.equal(state.lanes[0].uncertain, false);
    assert.deepEqual(state.lanes[1].session.observations, {});
  });
  await test('stale or cross-lane responses cannot erase a paid ledger or replace its identity', async () => {
    const {controller, mock} = await fixture(); const old = copy(mock.states.get('test_session_1'));
    await controller.actionLane('fixed', 'step'); mock.onAction(() => copy(old)); mock.onGet(() => copy(old));
    await controller.actionLane('fixed', 'step'); let state = controller.snapshot();
    assert.equal(state.charged_calls, 1); assert.equal(state.lanes[0].uncertain, true); assert.deepEqual(state.lanes[0].session.observations, {a: 3});
    mock.onGet(() => copy(mock.states.get('test_session_2'))); await controller.reconcile('fixed');
    assert.equal(controller.snapshot().lanes[0].uncertain, true);
    mock.onGet(null); await controller.reconcile('fixed'); state = controller.snapshot(); assert.equal(state.charged_calls, 2);
    assert.equal(state.lanes[0].session.selected_candidate, 'b');
  });
  await test('malformed response with an unqueried reference cannot reach snapshots or reports', async () => {
    const {controller, mock} = await fixture(); mock.onAction((id, session) => ({...copy(session), observations: {a: 3, c: 999}}));
    await controller.actionLane('fixed', 'step'); const state = controller.snapshot();
    assert.deepEqual(state.lanes[0].session.observations, {a: 3}); assert(!controller.exportJSON().includes('999'));
    assert.equal(mock.actions.length, 1); assert.equal(state.lanes[0].uncertain, false);
  });
  await test('exact configuration snapshots cannot be retuned through caller or returned-state mutation', async () => {
    const raw = copy(molecule), mock = mockAPI(), controller = Comparison.createComparison({api: mock.api});
    await controller.load(raw); raw.policy_configs.matched_simple.gap = 99; raw.candidates[0].cheap_kcal = -999;
    assert.equal(controller.snapshot().lanes[1].config.gap, .6); assert.equal(controller.snapshot().molecule.candidates[0].cheap_kcal, 0);
    assert.throws(() => { controller.snapshot().lanes[1].config.gap = 99; }, TypeError);
    const absent = copy(molecule); delete absent.policy_configs.matched_simple;
    await assert.rejects(controller.load(absent), /matched_simple/); assert.equal(mock.created.length, 4);
  });
  await test('earlier paid comparisons remain in cumulative totals and exported JSON/CSV after replacement', async () => {
    const {controller, mock} = await fixture(); await controller.runAll(); await controller.load(copy(molecule));
    let state = controller.snapshot(); assert.equal(state.charged_calls, 0); assert.equal(state.cumulative_charged_calls, 9); assert.equal(state.archived_runs.length, 1);
    assert.equal(mock.released.length, 4); await controller.actionLane('fixed', 'step');
    const report = JSON.parse(controller.exportJSON()); assert.equal(report.runs.length, 2); assert.equal(report.cumulative_charged_calls, 10);
    assert.equal(report.verification.authenticity_verified, false); assert.equal(report.fresh_external_holdout, false);
    assert.equal(report.runs[0].lanes[1].config.gap, .6); assert.equal(report.runs[1].lanes[1].session.expensive_calls, 0);
    assert.deepEqual(report.runs[0].pool_identity, report.runs[1].pool_identity);
    const csv = controller.exportCSV(); assert.equal(csv.split('\r\n').filter(Boolean).length, 9);
    assert(csv.includes('geometry_sha256') && csv.includes('matched_simple') && csv.includes('unverified_snapshot'));
    assert(!csv.includes('forbidden_reference')); assert(!controller.exportJSON().includes('extra_reference_map'));
    await controller.dispose(); state = controller.snapshot(); assert.equal(state.status, 'disposed'); assert.equal(state.cumulative_charged_calls, 10);
    assert.equal(controller.exportReport().cumulative_charged_calls, 10); await assert.rejects(controller.stepAll(), /closed/);
  });
  await test('the bounded comparison archive refuses a new run before creating or releasing any session', async () => {
    const {controller, mock} = await fixture(['fixed', 'full']);
    for (let i = 0; i < Comparison.MAX_ARCHIVED; i++) { await controller.actionLane('fixed', 'step'); await controller.load(copy(molecule), ['fixed', 'full']); }
    await controller.actionLane('fixed', 'step');
    const before = {created: mock.created.length, released: mock.released.length, charges: controller.snapshot().cumulative_charged_calls};
    await assert.rejects(controller.load(copy(molecule)), /No paid history was discarded/);
    assert.equal(mock.created.length, before.created); assert.equal(mock.released.length, before.released);
    assert.equal(controller.snapshot().cumulative_charged_calls, before.charges); assert.equal(before.charges, 13);
  });
  await test('browsing unopened zero-charge pools does not consume the retained paid-history limit', async () => {
    const {controller, mock} = await fixture(['fixed', 'full']);
    for (let i = 0; i < Comparison.MAX_ARCHIVED + 2; i++) await controller.load(copy(molecule), ['fixed', 'full']);
    assert.equal(controller.snapshot().archived_runs.length, 0); assert.equal(controller.snapshot().cumulative_charged_calls, 0);
    assert.equal(mock.released.length, (Comparison.MAX_ARCHIVED + 2) * 2);
  });
  await test('failed zero-charge worker startup is cleaned up and distinct-session collisions are rejected', async () => {
    const mock = mockAPI(), originalCreate = mock.api.createSession;
    mock.api.createSession = async (...args) => {
      const session = await originalCreate(...args); if (mock.created.length === 2) session.session_id = 'test_session_1'; return session;
    };
    const controller = Comparison.createComparison({api: mock.api});
    await assert.rejects(controller.load(copy(molecule)), /distinct server session/);
    assert.equal(controller.snapshot().status, 'empty'); assert.equal(controller.snapshot().charged_calls, 0);
  });
  console.log('\n' + checks + ' comparison orchestration checks passed. Real HTTP replay and browser checks are separate.');
})().catch(error => { console.error(error); process.exitCode = 1; });
