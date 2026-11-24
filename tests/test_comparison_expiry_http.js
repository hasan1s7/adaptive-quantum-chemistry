'use strict';
/* Reproduce normal server expiry through real HTTP, then recover in-page.
 * This is one additional product-check query, not a scientific experiment.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const C = require('../app/assets/client.js');
const Comparison = require('../app/assets/comparison.js');
const {startServer} = require('../scripts/verify_workbench.js');

(async () => {
  const server = await startServer({sessionTtl: 1});
  let controller;
  try {
    const api = C.createClient((url, options) => fetch(new URL(url, server.url), options));
    controller = Comparison.createComparison({api});
    const molecule = await api.molecule('omegacsd_GIHTUM');
    await controller.load(molecule);
    await controller.actionLane('fixed', 'step');
    assert.equal(controller.snapshot().charged_calls, 1);
    // A real monotonic TTL is the behavior under test; this bounded delay lets
    // the server expire the idle sessions without accessing its internal state.
    await new Promise(resolve => setTimeout(resolve, 1250));
    await controller.actionLane('fixed', 'step');
    let state = controller.snapshot();
    const unavailable = state.lanes.find(lane => lane.role === 'fixed');
    assert(unavailable.unavailable, 'Definitive expiry must have a recoverable unavailable state');
    assert.equal(unavailable.session.expensive_calls, 1, 'Keep the actual confirmed paid ledger');
    assert.equal(unavailable.uncertain, true, 'Do not manufacture a resolved final accounting total');
    assert.equal(state.can_archive_unavailable, true);
    await controller.archiveUnavailable();
    state = controller.snapshot();
    assert.equal(state.archived_runs.length, 1);
    assert.equal(state.cumulative_charged_calls, 1);
    assert.equal(state.cumulative_accounting_complete, false);
    assert.equal(state.molecule, null);
    await controller.load(molecule);
    state = controller.snapshot();
    assert.equal(state.charged_calls, 0);
    assert.equal(state.cumulative_charged_calls, 1);
    assert.equal(state.cumulative_accounting_complete, false);
    const exported = JSON.parse(controller.exportJSON());
    assert.equal(exported.cumulative_accounting_complete, false);
    assert.equal(exported.runs.length, 2);
    assert.equal(exported.runs[0].lanes.find(lane => lane.role === 'fixed').session.expensive_calls, 1);
    const report = {status: 'passed', actual_server: true, python_site_packages_disabled: true,
      expiry_seconds: 1, actual_paid_queries: 1, stale_mutation_rejected: true,
      explicit_archive_recovery: true, retained_confirmed_queries: 1,
      cumulative_accounting_complete: false, fresh_comparison_calls: 0,
      no_mutation_retry: true, scope: 'Product recovery check; no scientific experiment'};
    if (process.argv[2]) fs.writeFileSync(path.resolve(process.argv[2]), JSON.stringify(report, null, 2) + '\n');
    console.log('PASS actual HTTP session expiry: paid ledger retained, explicit archive recovery, fresh zero-call comparison, uncertain cumulative total preserved');
  } finally {
    try { if (controller) await controller.dispose(); } finally { await server.stop(); }
  }
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
