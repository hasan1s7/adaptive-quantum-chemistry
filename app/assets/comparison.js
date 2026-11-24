/* Independent local replay lanes. No policy formulas or reference-label sharing. */
(function (root) {
  'use strict';
  const C = root.AQCClient || (typeof require === 'function' ? require('./client.js') : null);
  const DEFAULT_ROLES = Object.freeze(['fixed', 'matched_simple', 'sequential', 'full']);
  const LABELS = Object.freeze({fixed: 'Fixed top-2', matched_simple: 'Matched simple · fold-selected',
    sequential: 'Sequential · fold-selected', full: 'Full reference rerank'});
  const MAX_ARCHIVED = 12;
  const copy = value => JSON.parse(JSON.stringify(value));
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const stable = value => JSON.stringify(value, Object.keys(value).sort());
  function freeze(value) {
    if (value && typeof value === 'object' && !Object.isFrozen(value)) {
      Object.values(value).forEach(freeze); Object.freeze(value);
    }
    return value;
  }
  function message(error) { return String(error?.message || error || 'The local comparison request failed.').slice(0, 4096); }
  function unavailableReason(error) {
    if (error instanceof C.APIError && error.status === 410 && error.code === 'session_expired') return 'session_expired';
    if (error instanceof C.APIError && error.status === 404 && error.code === 'unknown_session') return 'unknown_session';
    return null;
  }
  function safeConfig(raw, role) {
    const supplied = raw?.config || raw;
    const schemas = {full: ['kind'], fixed: ['kind', 'k'], adaptive: ['kind', 'k', 'gap', 'cap'],
      sequential: ['kind', 'one_gap', 'one_ratio', 'error_scale', 'slack', 'cap']};
    if (!object(supplied) || !schemas[supplied.kind] || Object.keys(supplied).sort().join(',') !== schemas[supplied.kind].slice().sort().join(',')) {
      throw new Error('The saved ' + role + ' configuration is unavailable or invalid for this molecule.');
    }
    if ((role === 'fixed' && supplied.kind !== 'fixed') || (role === 'full' && supplied.kind !== 'full') ||
        (role === 'sequential' && supplied.kind !== 'sequential') || (role === 'matched_simple' && !['fixed', 'adaptive'].includes(supplied.kind))) {
      throw new Error('The saved configuration does not match its comparison role.');
    }
    const out = Object.fromEntries(schemas[supplied.kind].map(key => [key, supplied[key]]));
    if (Object.entries(out).some(([key, value]) => key !== 'kind' && (typeof value !== 'number' || !Number.isFinite(value)))) throw new Error('Policy parameters must be finite numbers.');
    if (('k' in out && (!Number.isInteger(out.k) || out.k < 1 || out.k > 10000)) ||
        ('cap' in out && (!Number.isInteger(out.cap) || out.cap < (out.kind === 'sequential' ? 2 : out.k) || out.cap > 10000)) ||
        ('gap' in out && out.gap < 0) || ('one_gap' in out && out.one_gap < 0) ||
        ('one_ratio' in out && (out.one_ratio < 0 || out.one_ratio > 1)) ||
        ('error_scale' in out && out.error_scale < 1) || ('slack' in out && out.slack < 0)) throw new Error('Policy parameters are outside their allowed ranges.');
    return freeze(out);
  }
  function poolIdentity(molecule) {
    return molecule.candidates.map(row => ({candidate_id: row.candidate_id,
      geometry_sha256: row.geometry_sha256 || null, xyz_sha256: row.xyz_sha256 || null}));
  }
  function sourceDeclaration(raw) {
    const out = {};
    for (const key of ['source_revision', 'source_split_sha256', 'registry_sha256', 'evidence_seal_sha256', 'geometry_asset_sha256']) {
      const value = raw?.[key];
      if (typeof value === 'string' && value.length <= 128) out[key] = value;
    }
    return out;
  }
  function createComparison(options = {}) {
    if (!C) throw new Error('The local AQC client asset must load before the comparison controller.');
    const api = options.api || C.createClient();
    const onChange = typeof options.onChange === 'function' ? options.onChange : () => {};
    let molecule = null, lanes = [], archived = [], busy = false, disposed = false, generation = 0;
    let warning = null, createdAt = null, source = {}, pendingCleanup = [], operation = 0;
    const token = (root.crypto?.randomUUID ? root.crypto.randomUUID() : Date.now().toString(36) + '-' + Math.random().toString(36).slice(2));
    const charges = records => records.reduce((sum, lane) => sum + (lane.session?.session_expensive_calls || 0), 0);
    const needsRetention = records => charges(records) > 0 || records.some(lane => lane.error || lane.session?.status === 'failed');
    function currentStatus() {
      if (disposed) return 'disposed';
      if (!molecule) return 'empty';
      if (lanes.some(lane => lane.uncertain || lane.session?.status === 'failed')) return 'partial_failure';
      if (lanes.length && lanes.every(lane => lane.session?.status === 'completed')) return 'completed';
      return charges(lanes) ? 'active' : 'ready';
    }
    function snapshot() {
      const unavailable = lanes.filter(lane => lane.unavailable).length;
      return freeze(copy({molecule, lanes, busy, status: currentStatus(), charged_calls: charges(lanes),
        cumulative_charged_calls: charges(lanes) + archived.reduce((sum, run) => sum + run.charged_calls, 0),
        cumulative_accounting_complete: !lanes.some(lane => lane.uncertain) && !archived.some(run => run.lanes.some(lane => lane.uncertain)),
        unavailable_lane_count: unavailable,
        can_archive_unavailable: !disposed && !busy && !!molecule && unavailable > 0 &&
          lanes.every(lane => !lane.uncertain || lane.unavailable) && archived.length < MAX_ARCHIVED,
        completed_lanes: lanes.filter(lane => lane.session?.status === 'completed').length,
        archived_runs: archived, max_archived_runs: MAX_ARCHIVED, warning, pending_cleanup: pendingCleanup,
        scope: 'development_only_offline_replay', fresh_external_holdout: false, created_at: createdAt,
        source_declaration: source}));
    }
    function publish() {
      const state = snapshot();
      // A rendering failure must not cancel a charged request or erase its ledger.
      try { onChange(state); } catch (error) { root.console?.error?.('AQC comparison rendering failed:', error); }
      return state;
    }
    function requireIdle(allowUncertain = false) {
      if (disposed) throw new Error('This comparison has been closed. Its retained report remains exportable.');
      if (busy) throw new Error('A comparison request is in progress. Wait for its recorded state.');
      if (!allowUncertain && lanes.some(lane => lane.uncertain)) throw new Error('Reconcile the uncertain lane before another query or molecule change. A query may already have been charged.');
    }
    function findLane(role) {
      const lane = lanes.find(item => item.role === role);
      if (!lane) throw new Error('Unknown comparison lane.');
      return lane;
    }
    function acceptState(lane, raw, target = molecule, creating = false) {
      const clean = C.makeSavedRun(target, raw, {}).session;
      if (stable(clean.config) !== stable(lane.config)) throw new Error('The returned session configuration differs from this lane.');
      if (clean.reset_count !== 0 || clean.session_expensive_calls !== clean.expensive_calls) throw new Error('Comparison lanes cannot reset or hide previous charges.');
      if (lane.session && (clean.session_id !== lane.session.session_id || clean.expensive_calls < lane.session.expensive_calls ||
          JSON.stringify(clean.queries.slice(0, lane.session.queries.length)) !== JSON.stringify(lane.session.queries))) {
        throw new Error('The returned state would replace this lane identity or erase an already recorded charge.');
      }
      if (lane.session?.stopped && (clean.status !== lane.session.status ||
          JSON.stringify(clean.evaluation) !== JSON.stringify(lane.session.evaluation))) throw new Error('A stopped lane cannot change its recorded outcome.');
      if (Number.isSafeInteger(raw.revision) && raw.revision >= 0) {
        if (lane.session && Number.isSafeInteger(lane.session.revision) && raw.revision < lane.session.revision) throw new Error('A stale session response cannot overwrite a newer ledger.');
        clean.revision = raw.revision;
      }
      lane.session = C.unwrapSession(clean);
      lane.uncertain = false;
      lane.unavailable = null;
      if (creating && (clean.expensive_calls !== 0 || Object.keys(clean.observations).length)) {
        lane.uncertain = true;
        throw new Error('A new comparison lane unexpectedly contains paid queries; its ledger will be retained.');
      }
      return lane.session;
    }
    function retainedRun(reason) {
      return copy({molecule, pool_identity: poolIdentity(molecule), lanes, charged_calls: charges(lanes),
        accounting_complete: !lanes.some(lane => lane.uncertain),
        created_at: createdAt, retained_at: new Date().toISOString(), retained_reason: reason,
        scope: 'development_only_offline_replay', source_declaration: source});
    }
    async function release(records) {
      const released = new Set();
      for (const lane of records) {
        if (!lane.session?.session_id || released.has(lane.session.session_id)) continue;
        released.add(lane.session.session_id);
        try { await api.releaseSession(lane.session.session_id); }
        catch (error) { pendingCleanup.push({session_id: lane.session.session_id, role: lane.role, error: message(error)}); }
      }
      // Each entry is a retained diagnostic about a worker lease, not a paid ledger.
      if (pendingCleanup.length) warning = 'Some local worker sessions could not be released; their recorded charges remain retained. The server expires idle sessions.';
    }
    async function load(rawMolecule, roles = DEFAULT_ROLES) {
      requireIdle();
      if (archived.length >= MAX_ARCHIVED && needsRetention(lanes)) throw new Error('This workbench retains at most ' + MAX_ARCHIVED + ' earlier comparisons. Export the report and open a new workbench before starting another. No paid history was discarded.');
      if (!Array.isArray(roles) || roles.length < 2 || roles.length > 4 || new Set(roles).size !== roles.length || roles.some(role => !DEFAULT_ROLES.includes(role))) throw new Error('Choose two to four distinct comparison roles.');
      const nextMolecule = C.cleanMolecule(rawMolecule);
      nextMolecule.n_candidates = nextMolecule.candidates.length;
      nextMolecule.scope = 'original_development_only';
      const nextLanes = roles.map(role => {
        const config = safeConfig(rawMolecule.policy_configs?.[role] || (role === 'full' ? {kind: 'full'} : null), role);
        return {id: role, role, label: role === 'fixed' ? 'Fixed top-' + config.k : LABELS[role], config,
          session: null, busy: false, uncertain: false, unavailable: null, error: null};
      });
      busy = true; warning = null; const version = ++generation; publish();
      try {
        for (const lane of nextLanes) {
          let raw;
          try { raw = await api.createSession(nextMolecule.molecule_id, copy(lane.config)); }
          catch (error) {
            // Failed worker startup can still return a real, zero-charge session to release.
            if (error.session) acceptState(lane, error.session, nextMolecule, true);
            throw error;
          }
          acceptState(lane, raw, nextMolecule, true);
          if (lane.session.status !== 'active') throw new Error('A comparison worker did not start in the active, zero-charge state.');
          if (nextLanes.some(other => other !== lane && other.session?.session_id === lane.session.session_id) ||
              lanes.some(other => other.session?.session_id === lane.session.session_id)) throw new Error('Comparison lanes must receive distinct server session identities.');
          if (version !== generation) throw new Error('A stale comparison setup was discarded.');
        }
        const previous = lanes;
        if (molecule && needsRetention(lanes)) archived.push(retainedRun('new_comparison'));
        molecule = nextMolecule; lanes = nextLanes; source = sourceDeclaration(rawMolecule.provenance);
        createdAt = new Date().toISOString();
        await release(previous);
      } catch (error) {
        if (charges(nextLanes)) {
          archived.push(copy({molecule: nextMolecule, pool_identity: poolIdentity(nextMolecule), lanes: nextLanes,
            charged_calls: charges(nextLanes), created_at: new Date().toISOString(), retained_at: new Date().toISOString(),
            accounting_complete: !nextLanes.some(lane => lane.uncertain),
            retained_reason: 'failed_setup_with_recorded_charges', scope: 'development_only_offline_replay',
            source_declaration: sourceDeclaration(rawMolecule.provenance)}));
        }
        await release(nextLanes.filter(lane => lane.session && lane.session.expensive_calls === 0 &&
          !lanes.some(old => old.session?.session_id === lane.session.session_id)));
        warning = 'The comparison could not be opened. All recorded paid history is retained. ' + message(error);
        throw error;
      } finally { busy = false; publish(); }
      return snapshot();
    }
    async function readLane(lane) {
      try { acceptState(lane, await api.getSession(lane.session.session_id)); return true; }
      catch (error) {
        if (error.session) {
          try { acceptState(lane, error.session); return true; } catch (_) { /* Keep the original paid ledger. */ }
        }
        lane.uncertain = true;
        lane.unavailable = unavailableReason(error) || lane.unavailable;
        lane.error = 'The recorded state could not be reconciled. ' + message(error);
        return false;
      }
    }
    async function performLane(lane, action, version) {
      if (!lane.session || lane.session.stopped || lane.uncertain) return;
      lane.busy = true; lane.error = null; publish();
      const key = 'aqc-cmp-' + token + '-' + (++operation).toString(36);
      try {
        const raw = await api.action(lane.session.session_id, action, {}, {idempotencyKey: key});
        if (version !== generation) throw new Error('A stale comparison response cannot replace the current pool.');
        acceptState(lane, raw);
      } catch (error) {
        lane.error = message(error); lane.uncertain = true;
        lane.unavailable = unavailableReason(error) || lane.unavailable;
        if (error.session) {
          try { acceptState(lane, error.session); } catch (_) { /* Reconcile without trusting an inconsistent error payload. */ }
        }
        if (lane.uncertain && version === generation) await readLane(lane);
        // Never replay a mutation automatically. GET only reconciles its actual ledger.
      } finally { lane.busy = false; publish(); }
    }
    async function act(action, role) {
      requireIdle();
      if (!molecule) throw new Error('Open a comparison before making a paid query.');
      if (!['step', 'run'].includes(action)) throw new Error('Comparison lanes support step and run actions only.');
      const selected = role == null ? lanes : [findLane(role)];
      busy = true; const version = generation; publish();
      try { await Promise.all(selected.map(lane => performLane(lane, action, version))); }
      finally { busy = false; publish(); }
      return snapshot();
    }
    async function reconcile(role) {
      requireIdle(true);
      if (!molecule) throw new Error('There is no comparison to reconcile.');
      const selected = role == null ? lanes.filter(lane => lane.uncertain) : [findLane(role)];
      busy = true; publish();
      try {
        await Promise.all(selected.map(async lane => {
          if (!lane.session) return;
          lane.busy = true; publish();
          if (await readLane(lane)) lane.error = lane.session.status === 'failed'
            ? 'The server recorded a failed run. Its paid ledger is retained.' : null;
          lane.busy = false; publish();
        }));
      } finally { busy = false; publish(); }
      return snapshot();
    }
    async function archiveUnavailable() {
      requireIdle(true);
      if (!molecule || !lanes.some(lane => lane.unavailable)) throw new Error('Only a confirmed expired or missing server session can be archived with unresolved accounting. Reconcile temporary connection failures first.');
      if (lanes.some(lane => lane.uncertain && !lane.unavailable)) throw new Error('A temporary connection failure still has an unknown outcome. Reconcile that lane before archiving unavailable sessions.');
      if (archived.length >= MAX_ARCHIVED) throw new Error('The retained comparison archive is full. Export this report before opening a new workbench. No history was discarded.');
      busy = true; publish();
      try {
        const previous = lanes;
        // Preserve the complete last-confirmed pool and all lane ledgers first.
        // An expired server record cannot resolve an earlier lost mutation.
        archived.push(retainedRun('unavailable_sessions_with_unresolved_accounting'));
        molecule = null; lanes = []; source = {}; createdAt = null; generation++;
        warning = 'Unavailable sessions were archived with their last confirmed ledgers. Cumulative calls remain a lower bound because an unresolved request may have charged more. You can open a new comparison.';
        publish();
        await release(previous.filter(lane => !lane.unavailable));
      } finally { busy = false; publish(); }
      return snapshot();
    }
    async function dispose() {
      requireIdle(); busy = true; publish();
      try { await release(lanes); disposed = true; generation++; }
      finally { busy = false; publish(); }
      return snapshot();
    }
    function exportReport() {
      if (!molecule && !archived.length) throw new Error('Open a comparison before exporting a report.');
      return freeze(copy({format: 'aqc-policy-comparison', version: 1, exported_at: new Date().toISOString(),
        verification: {status: 'unverified_snapshot', authenticity_verified: false,
          checks: 'Locally checked molecule, configuration, query-ledger and selection consistency; this portable file is not sealed benchmark evidence.'},
        scope: 'development_only_offline_replay', fresh_external_holdout: false,
        label_scope: 'Each lane contains only its own successful paid observations. Evaluator regret appears only after that lane completes.',
        calls_meaning: snapshot().cumulative_accounting_complete
          ? 'Sum of independently charged offline replay lanes, including retained earlier comparisons. No live quantum jobs or wall-clock savings.'
          : 'Last-confirmed lower bound on independent offline replay charges. An unresolved current or archived request may have charged more. No live quantum jobs or wall-clock savings.',
        pool_rule: 'All lanes in a comparison use the same ordered candidate IDs and verified geometry identities; policies receive IDs and cheap energies only.',
        snapshot_in_flight: busy, cumulative_charged_calls: snapshot().cumulative_charged_calls,
        cumulative_accounting_complete: snapshot().cumulative_accounting_complete,
        runs: [...archived, ...(molecule ? [retainedRun(disposed ? 'closed' : 'current')]: [])]}));
    }
    function exportCSV() {
      const report = exportReport(), rows = [];
      report.runs.forEach((run, index) => {
        for (const lane of run.lanes) {
          const session = lane.session;
          rows.push({comparison_index: index + 1, molecule_id: run.molecule.molecule_id, family_id: run.molecule.family_id,
            fold_id: run.molecule.fold_id, n_candidates: run.molecule.candidates.length, role: lane.role, config: JSON.stringify(lane.config),
            status: session?.status || 'not_created', uncertain: lane.uncertain, unavailable: lane.unavailable || '',
            accounting_complete: run.accounting_complete, cumulative_accounting_complete: report.cumulative_accounting_complete,
            charged_calls: session?.expensive_calls || 0,
            selected_candidate: session?.selected_candidate, regret_kcal: session?.evaluation?.regret_kcal,
            success_within_1_kcal: session?.evaluation?.success_within_1_kcal, fallback: session?.fallback,
            stop_reason: session?.stop_reason, error: lane.error || '',
            query_order: JSON.stringify(session?.queries.map(row => row.candidate_id) || []),
            queried_reference_kcal: JSON.stringify(session?.observations || {}),
            pool_identity: JSON.stringify(run.pool_identity), scope: report.scope, verification: 'unverified_snapshot',
            calls_meaning: report.cumulative_accounting_complete ? 'Independent offline replay charges; no live calculations'
              : 'Last-confirmed lower bound; unresolved current or archived charges; no live calculations'});
        }
      });
      return C.csv(rows, ['comparison_index', 'molecule_id', 'family_id', 'fold_id', 'n_candidates', 'role', 'config', 'status',
        'uncertain', 'unavailable', 'accounting_complete', 'cumulative_accounting_complete', 'charged_calls', 'selected_candidate', 'regret_kcal', 'success_within_1_kcal', 'fallback', 'stop_reason', 'error',
        'query_order', 'queried_reference_kcal', 'pool_identity', 'scope', 'verification', 'calls_meaning']);
    }
    return Object.freeze({load, snapshot, stepAll: () => act('step'), runAll: () => act('run'),
      actionLane: (role, action) => act(action, role), reconcile, reconcileLane: role => reconcile(role), archiveUnavailable, dispose,
      exportReport, exportJSON: () => JSON.stringify(exportReport(), null, 2) + '\n', exportCSV});
  }
  const exported = Object.freeze({createComparison, DEFAULT_ROLES, LABELS, MAX_ARCHIVED, poolIdentity});
  root.AQCComparison = exported;
  if (typeof module !== 'undefined' && module.exports) module.exports = exported;
})(typeof window !== 'undefined' ? window : globalThis);
