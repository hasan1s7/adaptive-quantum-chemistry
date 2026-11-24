/* Same-origin API and portable read-only run files. No scientific policy code. */
(function (root) {
  'use strict';
  class APIError extends Error {
    constructor(message, status = 0, code = 'request_failed') {
      super(message); this.name = 'APIError'; this.status = status; this.code = code;
    }
  }
  const own = (object, key) => Object.prototype.hasOwnProperty.call(object || {}, key);
  const number = value => typeof value === 'number' && Number.isFinite(value);
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const SNAPSHOT_LIMITS = Object.freeze({candidates: 100, resets: 9, atoms: 3000});
  const UNVERIFIED = Object.freeze({status: 'unverified_snapshot', authenticity_verified: false,
    checks: 'Internal molecule, query-ledger, selection, and count consistency only; no source authentication or unqueried reference verification.'});
  function boundedText(value, name, max = 256) {
    if (typeof value !== 'string' || !value.length || value.length > max) throw new Error(name + ' must be a bounded nonempty string.');
    return value;
  }
  function integerIn(value, low, high, name) {
    if (!Number.isSafeInteger(value) || value < low || value > high) throw new Error(name + ' is outside the saved-run limits.');
    return value;
  }
  function lexical(a, b) {
    const x = Array.from(a), y = Array.from(b);
    for (let i = 0; i < Math.min(x.length, y.length); i++) {
      const delta = x[i].codePointAt(0) - y[i].codePointAt(0);
      if (delta) return delta;
    }
    return x.length - y.length;
  }
  function createClient(fetcher, options = {}) {
    const requestFetch = fetcher || root.fetch?.bind(root);
    if (!requestFetch) throw new APIError('This browser does not support local API requests.');
    const timeout = options.timeout ?? 30000;
    async function request(path, method = 'GET', body) {
      if (!path.startsWith('/api/')) throw new APIError('Only the local AQC API can be requested.');
      const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
      const timer = controller ? setTimeout(() => controller.abort(), timeout) : null;
      try {
        const response = await requestFetch(path, {method, credentials: 'same-origin',
          headers: {'Accept': 'application/json', ...(body !== undefined ? {'Content-Type': 'application/json'} : {})},
          ...(body !== undefined ? {body: JSON.stringify(body)} : {}), ...(controller ? {signal: controller.signal} : {})});
        let data;
        try { data = await response.json(); }
        catch (_) { throw new APIError('The local server returned an unreadable response. Check the server log and reload.', response.status, 'invalid_json'); }
        if (!data || typeof data !== 'object') throw new APIError('The local server returned an invalid JSON response.', response.status, 'invalid_json');
        if (!response.ok) {
          const detail = typeof data.error === 'string' ? data.error : data.error?.message || data.message;
          const error = new APIError(detail || `The local server rejected the request (${response.status}).`, response.status, data.code || data.error?.code);
          if (data.session) error.session = data.session;
          throw error;
        }
        return data;
      } catch (error) {
        if (error instanceof APIError) throw error;
        if (error.name === 'AbortError') throw new APIError(method === 'GET'
          ? 'The local server took too long to respond. Check that it is still running.'
          : 'The request timed out; a query may have been charged. Refreshing the session will reconcile its recorded state.', 0, 'timeout');
        throw new APIError('Cannot reach the local AQC server. Keep the server running and check this device’s connection.', 0, 'offline');
      } finally { if (timer) clearTimeout(timer); }
    }
    const sessionPath = id => '/api/sessions/' + encodeURIComponent(id);
    return Object.freeze({request,
      health: () => request('/api/health'), catalog: () => request('/api/catalog'),
      molecule: id => request('/api/molecules/' + encodeURIComponent(id)),
      results: () => request('/api/results'),
      createSession: (molecule_id, config) => request('/api/sessions', 'POST', {molecule_id, config}),
      getSession: id => request(sessionPath(id)),
      releaseSession: id => request(sessionPath(id), 'DELETE'),
      action: (id, action, data = {}) => {
        if (!['step', 'run', 'query', 'finish', 'reset'].includes(action)) return Promise.reject(new APIError('Unknown session action.'));
        return request(sessionPath(id) + '/' + action, 'POST', data);
      },
      exportSession: id => request(sessionPath(id) + '/export.json')
    });
  }
  function unwrapSession(value) {
    if (!value || typeof value !== 'object') throw new Error('The API returned no session state.');
    const raw = value.state && typeof value.state === 'object' ? {...value.state, session_id: value.session_id || value.state.session_id} : value;
    const observations = {...(raw.observations || raw.revealed_observations || {})};
    for (const value of Object.values(observations)) if (!number(value)) throw new Error('A revealed reference observation is not a finite number.');
    const queries = Array.isArray(raw.queries) ? raw.queries : [];
    const calls = raw.expensive_calls ?? raw.charged_calls ?? queries.reduce((sum, query) => sum + Number(query.charged || 0), 0);
    if (!Number.isInteger(calls) || calls < 0) throw new Error('Invalid query accounting in the API response.');
    const stopped = !!(raw.stopped ?? raw.done ?? raw.status === 'stopped');
    // Never surface an evaluator score before the server marks this session stopped.
    const evaluation = stopped ? (raw.evaluation || raw.final_evaluation || null) : null;
    const best = raw.best_verified && typeof raw.best_verified === 'object' ? raw.best_verified.candidate_id : raw.best_verified;
    return {...raw, observations, queries, expensive_calls: calls, stopped, evaluation,
      best_verified: best || raw.best_verified_candidate || raw.selected_candidate || null,
      pending_candidate: raw.pending_candidate || raw.next_candidate || null,
      policy_events: raw.policy_events || raw.events || []};
  }
  function cleanMolecule(raw) {
    if (!object(raw) || !Array.isArray(raw.candidates) || !raw.candidates.length || raw.candidates.length > SNAPSHOT_LIMITS.candidates) throw new Error('A saved run needs a bounded molecule candidate pool.');
    boundedText(raw.molecule_id, 'Molecule ID');
    const family = raw.family_id == null || raw.family_id === '' ? '' : boundedText(raw.family_id, 'Chemical family ID');
    const fold = raw.fold_id == null ? null : integerIn(raw.fold_id, 0, 4, 'Development fold');
    const ids = new Set();
    const candidates = raw.candidates.map(row => {
      if (!object(row) || typeof row.candidate_id !== 'string' || !row.candidate_id || row.candidate_id.length > 256 || ids.has(row.candidate_id) || !number(row.cheap_kcal)) throw new Error('Invalid or duplicate candidate in the run.');
      ids.add(row.candidate_id);
      const out = {candidate_id: row.candidate_id, cheap_kcal: row.cheap_kcal};
      const geometry = object(row.geometry) && !row.symbols ? row.geometry : row;
      for (const key of ['symbols', 'coordinates_angstrom']) if (own(geometry, key)) out[key] = geometry[key];
      for (const key of ['geometry_sha256', 'xyz_sha256']) if (own(geometry, key)) out[key] = boundedText(geometry[key], 'Declared coordinate hash', 128);
      if (own(out, 'symbols') || own(out, 'coordinates_angstrom')) {
        if (!Array.isArray(out.symbols) || !Array.isArray(out.coordinates_angstrom) || !out.symbols.length || out.symbols.length !== out.coordinates_angstrom.length || out.symbols.length > SNAPSHOT_LIMITS.atoms ||
            out.symbols.some(symbol => typeof symbol !== 'string' || !/^[A-Za-z]{1,2}$/.test(symbol)) ||
            out.coordinates_angstrom.some(xyz => !Array.isArray(xyz) || xyz.length !== 3 || !xyz.every(number))) throw new Error('Saved coordinates are invalid.');
        out.symbols = out.symbols.slice(); out.coordinates_angstrom = out.coordinates_angstrom.map(xyz => xyz.slice());
      }
      return out;
    });
    return {molecule_id: raw.molecule_id, family_id: family, fold_id: fold, candidates};
  }
  function cleanConfig(raw) {
    const schemas = {manual: ['kind'], full: ['kind'], fixed: ['kind', 'k'], adaptive: ['kind', 'k', 'gap', 'cap'], sequential: ['kind', 'one_gap', 'one_ratio', 'error_scale', 'slack', 'cap']};
    if (!object(raw) || !schemas[raw.kind] || Object.keys(raw).sort().join(',') !== schemas[raw.kind].slice().sort().join(',')) throw new Error('Saved policy configuration has an invalid schema.');
    const clean = Object.fromEntries(schemas[raw.kind].map(key => [key, raw[key]]));
    for (const [key, value] of Object.entries(clean)) if (key !== 'kind' && !number(value)) throw new Error('Saved policy parameters must be finite numbers.');
    if (own(clean, 'k')) integerIn(clean.k, 1, 10000, 'Policy k');
    if (own(clean, 'cap')) integerIn(clean.cap, clean.kind === 'sequential' ? 2 : clean.k, 10000, 'Policy cap');
    if ((own(clean, 'gap') && clean.gap < 0) || (own(clean, 'one_gap') && clean.one_gap < 0) ||
        (own(clean, 'one_ratio') && (clean.one_ratio < 0 || clean.one_ratio > 1)) ||
        (own(clean, 'error_scale') && clean.error_scale < 1) || (own(clean, 'slack') && clean.slack < 0)) throw new Error('Saved policy parameter is outside its allowed range.');
    return clean;
  }
  function cleanEvents(raw, maxEvents, candidateIds) {
    if (!Array.isArray(raw) || raw.length > maxEvents) throw new Error('Saved policy-event count is outside the trial limits.');
    const eventNames = new Set(['query_decision', 'query_failure', 'fallback', 'cheap_separation', 'empirical_envelope', 'cheap_window', 'escalation', 'stop']);
    const strings = ['event', 'type', 'candidate_id', 'selected_candidate', 'reason', 'action'];
    const numbers = ['event_order', 'after_attempts', 'gap12_kcal', 'cheap_span_kcal', 'gap_ratio', 'one_gap', 'one_ratio', 'numerical_tolerance',
      'max_observed_discrepancy_kcal', 'envelope_error_kcal', 'best_observed_relative_kcal', 'next_cheap_relative_kcal', 'tolerated_lower_envelope_kcal',
      'regret_tolerance_kcal', 'cheap_gap_kcal', 'threshold_kcal', 'cap'];
    return raw.map((event, index) => {
      if (!object(event)) throw new Error('Invalid saved policy event.');
      const out = {};
      for (const key of strings) if (own(event, key)) {
        if (event[key] === null && key === 'selected_candidate') out[key] = null;
        else out[key] = boundedText(event[key], 'Policy event ' + key, 1024);
        if (['candidate_id', 'selected_candidate'].includes(key) && out[key] !== null && !candidateIds.has(out[key])) throw new Error('Policy event refers to a candidate outside the saved molecule.');
      }
      for (const key of numbers) if (own(event, key)) {
        if (!number(event[key])) throw new Error('Saved policy-event numbers must be finite.');
        out[key] = event[key];
      }
      if (!eventNames.has(out.event) || (own(out, 'event_order') && out.event_order !== index + 1)) throw new Error('Saved policy-event name or order is inconsistent.');
      if (own(out, 'after_attempts')) integerIn(out.after_attempts, 0, candidateIds.size, 'Policy-event attempt count');
      return out;
    });
  }
  function cleanFailure(raw) {
    if (raw == null) return null;
    if (!object(raw)) throw new Error('Invalid saved failure record.');
    const out = {};
    for (const key of ['code', 'message', 'failure_stage', 'cause_type', 'worker_stderr']) if (raw[key] != null && raw[key] !== '') out[key] = boundedText(raw[key], 'Failure ' + key, key === 'worker_stderr' ? 16384 : 4096);
    if (raw.cleanup_errors != null) {
      if (!Array.isArray(raw.cleanup_errors) || raw.cleanup_errors.length > 32) throw new Error('Too many saved cleanup errors.');
      out.cleanup_errors = raw.cleanup_errors.map(row => {
        if (!object(row)) throw new Error('Invalid saved cleanup error.');
        return Object.fromEntries(['operation', 'cause_type', 'message'].filter(key => row[key] != null).map(key => [key, boundedText(row[key], 'Cleanup ' + key, 4096)]));
      });
    }
    return out;
  }
  function cleanSession(molecule, raw) {
    if (!object(raw) || raw.molecule_id !== molecule.molecule_id) throw new Error('Saved session molecule identity differs from the supplied molecule.');
    if (own(raw, 'family_id') && raw.family_id !== molecule.family_id) throw new Error('Saved session family identity differs from the supplied molecule.');
    if (!['active', 'completed', 'failed'].includes(raw.status) || typeof raw.stopped !== 'boolean' || raw.stopped !== (raw.status !== 'active')) throw new Error('Saved stopped/status fields are inconsistent.');
    // Inspect the raw value before unwrapSession can hide a premature evaluator score.
    if (raw.status !== 'completed' && (raw.evaluation != null || raw.final_evaluation != null)) throw new Error('Evaluation must be absent before a completed stop.');
    const config = cleanConfig(raw.config), mode = config.kind === 'manual' ? 'manual' : 'policy';
    if (raw.mode != null && raw.mode !== mode) throw new Error('Saved mode differs from its policy configuration.');
    const n = molecule.candidates.length, maxEvents = 20 * n + 64;
    const candidateIds = new Set(molecule.candidates.map(row => row.candidate_id));
    if (!Array.isArray(raw.queries) || raw.queries.length > maxEvents || !object(raw.observations)) throw new Error('Saved query/observation records exceed the trial limits or are invalid.');
    const paid = new Map(), revealed = new Map();
    const queries = raw.queries.map((query, index) => {
      if (!object(query) || query.order !== index + 1 || ![0, 1].includes(query.charged)) throw new Error('Saved query order or charge is invalid.');
      const id = query.candidate_id, status = query.status, hasReference = own(query, 'reference_kcal');
      const allowed = candidateIds.has(id), prior = paid.get(id);
      if (!['succeeded', 'failed', 'cached', 'cached_failure', 'rejected', 'pending'].includes(status)) throw new Error('Unknown saved query status.');
      if (status === 'rejected') {
        if (query.charged !== 0 || hasReference || (id !== null && (typeof id !== 'string' || id.length > 256)) || allowed) throw new Error('Rejected query has a reference, a charge, or a valid candidate.');
      } else {
        if (!allowed) throw new Error('Saved query references a candidate outside the molecule.');
        if (query.charged === 1) {
          if (prior) throw new Error('A candidate has a duplicate charged query in one trial.');
          if (!['succeeded', 'failed', 'pending'].includes(status)) throw new Error('A cached query cannot create a new charge.');
          paid.set(id, query);
        } else if (!prior || !['cached', 'cached_failure'].includes(status)) throw new Error('An uncharged reveal requires a preceding paid query.');
      }
      if (status === 'succeeded' || status === 'cached') {
        if (!hasReference || !number(query.reference_kcal) || own(query, 'error')) throw new Error('Successful query status requires a finite reference and no error.');
        if (status === 'cached' && (prior.status !== 'succeeded' || prior.reference_kcal !== query.reference_kcal)) throw new Error('Cached reference differs from its preceding paid success.');
        revealed.set(id, query.reference_kcal);
      } else {
        if (hasReference) throw new Error('A failed, rejected, or pending query cannot reveal a reference.');
        if (status === 'pending') {
          if (raw.status !== 'failed' || query.charged !== 1) throw new Error('A pending paid job is only valid in a recorded failed run.');
        } else boundedText(query.error, 'Query failure reason', 1024);
        if (status === 'cached_failure' && (prior.status !== 'failed' || prior.error !== query.error)) throw new Error('Cached failure differs from its preceding paid failure.');
      }
      const out = {order: index + 1, candidate_id: id, charged: query.charged, status};
      if (hasReference) out.reference_kcal = query.reference_kcal;
      for (const key of ['error', 'cause_type', 'received_type']) if (own(query, key)) out[key] = boundedText(query[key], 'Query ' + key, 1024);
      return out;
    });
    const calls = integerIn(raw.expensive_calls, 0, n, 'Trial charged calls');
    if (calls !== paid.size) throw new Error('The saved charge total does not match its query history.');
    const observedKeys = Object.keys(raw.observations);
    if (observedKeys.length !== revealed.size || observedKeys.some(id => !revealed.has(id) || !number(raw.observations[id]) || raw.observations[id] !== revealed.get(id))) throw new Error('Saved observations must exactly match successful paid-query history.');
    const observations = Object.fromEntries(revealed);
    const best = [...revealed.keys()].sort((a, b) => revealed.get(a) - revealed.get(b) || lexical(a, b))[0] || null;
    const claimedBest = object(raw.best_verified) ? raw.best_verified.candidate_id : raw.best_verified;
    if ((claimedBest ?? null) !== best) throw new Error('The saved selection is not the best queried reference, including deterministic ties.');
    if (object(raw.best_verified) && raw.best_verified.reference_kcal !== revealed.get(best)) throw new Error('Best-verified reference differs from the query history.');
    const selected = raw.selected_candidate ?? null;
    if (selected !== null && (selected !== best || raw.status === 'active')) throw new Error('The final selected candidate must equal the best successfully queried reference.');
    if (raw.status === 'completed' && (!best || selected !== best || calls < 1)) throw new Error('A completed run must select the best successfully queried reference after a paid call.');
    let evaluation = null;
    if (raw.status === 'completed') {
      const score = raw.evaluation;
      if (!object(score) || !number(score.regret_kcal) || score.regret_kcal < 0 || !number(score.selected_reference_kcal)) throw new Error('Completed evaluation must have finite, nonnegative regret and a finite selected reference.');
      if (score.selected_reference_kcal !== observations[selected] || (own(score, 'selected_candidate') && score.selected_candidate !== selected)) throw new Error('Evaluator selection differs from the best queried reference.');
      if (typeof score.success_within_1_kcal !== 'boolean' || score.success_within_1_kcal !== (score.regret_kcal <= 1 + 1e-9)) throw new Error('Evaluator success flag is inconsistent with regret.');
      if (revealed.size === n && score.regret_kcal !== 0) throw new Error('A fully revealed pool with its best candidate selected must have zero regret.');
      evaluation = {regret_kcal: score.regret_kcal, success_within_1_kcal: score.success_within_1_kcal, selected_reference_kcal: score.selected_reference_kcal};
    }
    const resets = integerIn(raw.reset_count ?? 0, 0, SNAPSHOT_LIMITS.resets, 'Trial reset count');
    const cumulative = integerIn(raw.session_expensive_calls ?? calls, calls, calls + resets * n, 'Cumulative charged calls');
    if (own(raw, 'previous_run_count') && raw.previous_run_count !== resets) throw new Error('Previous-run count differs from the reset count.');
    const pending = raw.pending_candidate ?? null;
    if (pending !== null && (!candidateIds.has(pending) || raw.stopped || mode === 'manual')) throw new Error('Saved pending candidate is inconsistent with the trial state.');
    if (raw.fallback != null && typeof raw.fallback !== 'boolean') throw new Error('Fallback must be a boolean.');
    const out = {session_id: boundedText(raw.session_id, 'Session ID', 128), molecule_id: molecule.molecule_id, family_id: molecule.family_id,
      config, mode, status: raw.status, stopped: raw.stopped, expensive_calls: calls, session_expensive_calls: cumulative, reset_count: resets,
      previous_run_count: resets, queries, observations, best_verified: best, selected_candidate: selected,
      pending_candidate: pending, pending_reason: raw.pending_reason == null ? null : boundedText(raw.pending_reason, 'Pending reason', 1024),
      stop_reason: raw.stop_reason == null ? null : boundedText(raw.stop_reason, 'Stop reason', 1024), fallback: !!raw.fallback, evaluation,
      policy_events: cleanEvents(raw.policy_events ?? [], maxEvents, candidateIds), failure: cleanFailure(raw.failure)};
    if (own(raw, 'ended_by_reset')) {
      if (typeof raw.ended_by_reset !== 'boolean' || raw.ended_by_reset !== (raw.status === 'active')) throw new Error('Reset termination flag is inconsistent.');
      out.ended_by_reset = raw.ended_by_reset;
    }
    if (raw.reset_cleanup_errors != null) out.reset_cleanup_errors = cleanFailure({cleanup_errors: raw.reset_cleanup_errors}).cleanup_errors;
    return out;
  }
  function cleanServerTrace(molecule, session, raw) {
    if (!object(raw) || raw.schema_version !== 1 || !Array.isArray(raw.previous_runs) || !Array.isArray(raw.candidates) || !object(raw.accounting)) throw new Error('Invalid server trace schema; arbitrary trace payloads are not preserved.');
    if (raw.previous_runs.length > SNAPSHOT_LIMITS.resets || raw.previous_runs.length !== session.reset_count) throw new Error('Server trace trial count differs from the reset history.');
    const current = cleanSession(molecule, raw.session);
    if (JSON.stringify(current) !== JSON.stringify(session)) throw new Error('Server trace current state differs from the saved session.');
    const actualCandidates = new Map(molecule.candidates.map(row => [row.candidate_id, row.cheap_kcal]));
    const seen = new Set();
    for (const row of raw.candidates) {
      if (!object(row) || seen.has(row.candidate_id) || !actualCandidates.has(row.candidate_id) || row.cheap_kcal !== actualCandidates.get(row.candidate_id)) throw new Error('Server trace candidate pool differs from the saved molecule.');
      seen.add(row.candidate_id);
    }
    if (seen.size !== actualCandidates.size) throw new Error('Server trace candidate coverage is incomplete.');
    let charges = 0, queryEvents = 0;
    const history = raw.previous_runs.map((row, index) => {
      const run = cleanSession(molecule, row); charges += run.expensive_calls; queryEvents += run.queries.length;
      if (run.session_id !== session.session_id || run.reset_count !== index || run.session_expensive_calls !== charges || JSON.stringify(run.config) !== JSON.stringify(session.config)) throw new Error('Previous-run identity, configuration, or cumulative accounting is inconsistent.');
      return run;
    });
    charges += current.expensive_calls; queryEvents += current.queries.length;
    if (current.session_expensive_calls !== charges || raw.accounting.charged_jobs !== charges || raw.accounting.runs !== history.length + 1 || queryEvents > 20 * molecule.candidates.length + 64) throw new Error('Server trace cumulative trial accounting is inconsistent or exceeds its bounds.');
    return {schema_version: 1, session: current, previous_runs: history,
      candidates: molecule.candidates.map(row => ({candidate_id: row.candidate_id, cheap_kcal: row.cheap_kcal})),
      accounting: {runs: history.length + 1, charged_jobs: charges, meaning: 'Offline charged queries across the supplied reset history.'},
      label_scope: 'Successful queried references only; evaluator scores are unverified claims after completed runs.', verification: {...UNVERIFIED}};
  }
  function makeSavedRun(molecule, session, source = {}, trace = null) {
    const clean = cleanMolecule(molecule), state = cleanSession(clean, session);
    if (!object(source)) throw new Error('Invalid declared saved-run source.');
    const revision = source.declared_source_revision ?? source.source_revision ?? source.revision ?? null;
    const declaredRevision = revision == null ? null : boundedText(revision, 'Declared source revision', 128);
    const provenance = {dataset_kind: ['real', 'synthetic'].includes(source.dataset_kind) ? source.dataset_kind : 'unspecified',
      analysis_scope: 'saved_run_snapshot', declared_source_revision: declaredRevision, verification: {...UNVERIFIED}};
    const saved = {format: 'aqc-workbench-run', version: 1, saved_at: new Date().toISOString(),
      verification: {...UNVERIFIED}, molecule: clean, session: state, source: provenance};
    if (trace != null) saved.server_trace = cleanServerTrace(clean, state, trace);
    return saved;
  }
  function validateSavedRun(raw) {
    if (!object(raw) || raw.format !== 'aqc-workbench-run' || raw.version !== 1) throw new Error('Choose a run JSON exported by this AQC workbench.');
    if (raw.source != null && !object(raw.source)) throw new Error('Invalid declared saved-run source.');
    const validated = makeSavedRun(raw.molecule, raw.session, raw.source || {}, raw.server_trace ?? null);
    if (own(raw, 'saved_at')) {
      if (typeof raw.saved_at !== 'string' || raw.saved_at.length > 64 || Number.isNaN(Date.parse(raw.saved_at))) throw new Error('Saved timestamp is invalid.');
      validated.saved_at = raw.saved_at;
    }
    return validated;
  }
  function policyKind(row) {
    const value = row.kind || row.config?.kind || row.policy || '';
    if (value === 'cheap_only' || value === 'diagnostic') return 'diagnostic';
    if (value === 'fixed_top_k' || value.startsWith('fixed')) return 'fixed';
    if (value === 'full_rerank' || value === 'full') return 'full';
    if (value === 'matched_simple') return 'matched';
    if (value.startsWith('sequential')) return 'sequential';
    if (value.startsWith('adaptive')) return 'adaptive';
    return value;
  }
  function filterExperiments(rows, filters = {}) {
    const search = String(filters.search || '').trim().toLowerCase(), kind = filters.kind || 'all';
    const maxRisk = filters.maxRisk == null || filters.maxRisk === 'all' ? null : Number(filters.maxRisk);
    const sort = filters.sort || 'mean_calls';
    return rows.filter(row => (kind === 'all' || policyKind(row) === kind) &&
      (maxRisk === null || 1 - Number(row.success_rate) <= maxRisk + 1e-9) &&
      (!search || [row.config_id, row.kind, row.k, row.gap, row.cap, row.one_gap, row.one_ratio, row.error_scale, row.slack].join(' ').toLowerCase().includes(search)))
      .slice().sort((a, b) => {
        if (sort === 'config_id') return String(a.config_id).localeCompare(String(b.config_id));
        const delta = Number(a[sort]) - Number(b[sort]);
        return (sort === 'success_rate' ? -delta : delta) || String(a.config_id).localeCompare(String(b.config_id));
      });
  }
  function csv(rows, columns) {
    const escape = value => '"' + String(value == null ? '' : value).replace(/"/g, '""') + '"';
    return [columns.map(escape).join(','), ...rows.map(row => columns.map(key => escape(row[key])).join(','))].join('\r\n') + '\r\n';
  }
  const api = {APIError, createClient, unwrapSession, cleanMolecule, makeSavedRun, validateSavedRun, filterExperiments, policyKind, csv};
  root.AQCClient = Object.freeze(api);
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
