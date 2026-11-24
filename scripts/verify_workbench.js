#!/usr/bin/env node
'use strict';
/* Exercise the browser's comparison controller against the actual local HTTP API.
 * This repeats five retrospectively chosen development cases. It is product
 * verification, not a new experiment, independent sample, or policy selection.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');
const C = require('../app/assets/client.js');
const Comparison = require('../app/assets/comparison.js');
const ROOT = path.resolve(__dirname, '..');
const IDS = ['omegacsd_GIHTUM', 'astex_1xoq', 'omegapdb_2f4j', 'omegapdb_2byi', 'omegapdb_1yc4'];
const ROLES = {fixed: 'fixed_top_k', matched_simple: 'matched_simple', sequential: 'sequential', full: 'full_rerank'};

async function startServer({sessionTtl = 900} = {}) {
  if (!Number.isFinite(sessionTtl) || sessionTtl <= 0) throw new Error('The test server needs a positive session TTL.');
  const source = [
    'from aqc_app.server import LocalHTTPServer',
    'import signal, sys',
    'def stop(*args): raise KeyboardInterrupt()',
    'signal.signal(signal.SIGTERM, stop)',
    'server = LocalHTTPServer(port=0, quiet=True, session_ttl=float(sys.argv[1]))',
    'print(server.url, flush=True)',
    'try: server.serve_forever(poll_interval=0.1)',
    'except KeyboardInterrupt: pass',
    'finally: server.server_close()'
  ].join('\n');
  const child = spawn(process.env.AQC_TEST_PYTHON || 'python3', ['-S', '-u', '-c', source, String(sessionTtl)],
    {cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe']});
  let output = '', errors = '';
  child.stderr.on('data', chunk => { errors = (errors + chunk.toString()).slice(-8192); });
  const url = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { child.kill(); reject(new Error('Local test server startup timed out: ' + errors)); }, 20000);
    child.once('error', error => { clearTimeout(timer); reject(error); });
    child.once('exit', code => { clearTimeout(timer); reject(new Error('Local test server exited before readiness (' + code + '): ' + errors)); });
    child.stdout.on('data', chunk => {
      output += chunk.toString();
      const match = output.match(/^http:\/\/127\.0\.0\.1:\d+\/$/m);
      if (match) { clearTimeout(timer); resolve(match[0]); }
    });
  });
  return {child, url, stop: () => new Promise(resolve => {
    if (child.exitCode !== null) return resolve();
    const timer = setTimeout(() => { child.kill('SIGKILL'); resolve(); }, 5000);
    child.once('exit', () => { clearTimeout(timer); resolve(); });
    child.kill('SIGTERM');
  })};
}

async function main() {
  const args = process.argv.slice(2);
  if (args.length !== 0 && (args.length !== 2 || args[0] !== '--out')) throw new Error('Usage: node scripts/verify_workbench.js [--out report.json]');
  const server = await startServer();
  const api = C.createClient((url, options) => fetch(new URL(url, server.url), options));
  const report = {schema_version: 1, purpose: 'Product integration verification of frozen development replay',
    scope: 'retrospectively_selected_original_development_cases', fresh_external_holdout: false,
    new_scientific_experiments: 0, server_python_site_packages_disabled: true,
    measured_source: 'Sealed per-molecule development CV table via sanitized /api/diagnostics',
    expected_pools: IDS.length, expected_lanes_per_pool: 4, cases: []};
  try {
    const diagnostics = await api.request('/api/diagnostics');
    assert.equal(diagnostics.fresh_external_holdout, false);
    assert.equal(diagnostics.counts.molecules, 478);
    assert.equal(diagnostics.counts.families, 287);
    for (const row of diagnostics.rows) {
      for (const forbidden of ['best_pool_candidate', 'selected_candidate', 'query_order', 'trace_annotations', 'references', 'reference_kcal']) {
        assert.equal(Object.hasOwn(row, forbidden), false, 'Retrospective metrics must not publish candidate-level reference hints');
      }
    }
    for (const moleculeId of IDS) {
      const molecule = await api.molecule(moleculeId);
      const controller = Comparison.createComparison({api});
      try {
        await controller.load(molecule);
        let state = controller.snapshot();
        assert.equal(state.lanes.length, 4);
        assert.equal(new Set(state.lanes.map(lane => lane.session.session_id)).size, 4);
        for (const lane of state.lanes) {
          assert.equal(lane.session.expensive_calls, 0);
          assert.deepEqual(lane.session.observations, {});
          assert.equal(lane.session.evaluation, null);
          assert.deepEqual(lane.config, molecule.policy_configs[lane.role]);
        }
        await controller.actionLane('fixed', 'step');
        state = controller.snapshot();
        for (const lane of state.lanes) {
          assert.equal(lane.session.expensive_calls, lane.role === 'fixed' ? 1 : 0);
          if (lane.role !== 'fixed') assert.deepEqual(lane.session.observations, {}, 'Sibling reference observations must remain hidden');
          assert.equal(lane.session.evaluation, null);
        }
        await controller.runAll();
        state = controller.snapshot();
        const item = {molecule_id: moleculeId, family_id: molecule.family_id, fold_id: molecule.fold_id,
          geometry_identities: molecule.candidates.map(row => ({candidate_id: row.candidate_id, geometry_sha256: row.geometry_sha256})), lanes: []};
        for (const lane of state.lanes) {
          const expected = diagnostics.rows.find(row => row.molecule_id === moleculeId && row.policy === ROLES[lane.role]);
          assert(expected, 'Missing sealed comparison row');
          assert.equal(lane.session.status, 'completed');
          assert.equal(lane.session.expensive_calls, expected.expensive_calls);
          assert(Math.abs(lane.session.evaluation.regret_kcal - expected.regret_kcal) < 1e-9);
          assert.equal(lane.session.fallback, expected.fallback);
          assert.equal(lane.session.stop_reason, expected.stop_reason);
          assert.equal(lane.session.evaluation.success_within_1_kcal, expected.success_1kcal);
          const successful = lane.session.queries.filter(row => row.status === 'succeeded');
          assert.equal(successful.length, lane.session.expensive_calls);
          const best = successful.slice().sort((a, b) => a.reference_kcal - b.reference_kcal || (a.candidate_id < b.candidate_id ? -1 : a.candidate_id > b.candidate_id ? 1 : 0))[0];
          assert.equal(lane.session.selected_candidate, best.candidate_id);
          item.lanes.push({role: lane.role, config: lane.config, expensive_calls: lane.session.expensive_calls,
            regret_kcal: lane.session.evaluation.regret_kcal, fallback: lane.session.fallback,
            selected_candidate: lane.session.selected_candidate, stop_reason: lane.session.stop_reason,
            matches_sealed_result: true});
        }
        assert.equal(state.charged_calls, item.lanes.reduce((total, lane) => total + lane.expensive_calls, 0));
        const exported = controller.exportJSON();
        JSON.parse(exported);
        assert(!exported.includes('best_pool_candidate'));
        assert(controller.exportCSV().includes(moleculeId));
        item.charged_calls = state.charged_calls;
        report.cases.push(item);
        console.log('PASS ' + moleculeId + ': four independent lanes; ' + item.charged_calls + ' offline calls; exact sealed-result parity');
      } finally { await controller.dispose(); }
    }
    report.completed_replays = report.cases.reduce((total, item) => total + item.lanes.length, 0);
    report.offline_charged_calls = report.cases.reduce((total, item) => total + item.charged_calls, 0);
    assert.equal(report.completed_replays, 20);
    assert.equal(report.offline_charged_calls, 96);
    report.status = 'passed';
    if (args[1]) fs.writeFileSync(path.resolve(args[1]), JSON.stringify(report, null, 2) + '\n');
    console.log('PASS 20 real HTTP replays / 96 offline charges. No new quantum calculations or fresh statistical evidence.');
  } finally { await server.stop(); }
}
module.exports = {startServer};
if (require.main === module) main().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
