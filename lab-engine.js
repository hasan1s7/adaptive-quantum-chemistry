/* AQC local replay engine. Policies receive cheap candidates and single-query
 * observations only. The evaluator owns labels. This is not an OS sandbox. */
(function (root) {
  'use strict';
  const TOL = 1e-9;
  const clone = value => JSON.parse(JSON.stringify(value));
  function lexical(a, b) {
    const x = Array.from(String(a)), y = Array.from(String(b));
    for (let i = 0; i < Math.min(x.length, y.length); i++) {
      const d = x[i].codePointAt(0) - y[i].codePointAt(0);
      if (d) return d;
    }
    return x.length - y.length;
  }
  function finite(x) { return typeof x === 'number' && Number.isFinite(x); }
  function validateCandidates(rows) {
    if (!Array.isArray(rows) || !rows.length) throw new Error('Empty candidate pool');
    const ids = new Set();
    const clean = rows.map(row => {
      if (!row || Object.keys(row).sort().join(',') !== 'candidate_id,cheap_kcal') {
        throw new Error('Policy features allow only candidate_id and cheap_kcal');
      }
      if (typeof row.candidate_id !== 'string' || !row.candidate_id || ids.has(row.candidate_id)) {
        throw new Error('Invalid or duplicate candidate ID');
      }
      if (!finite(row.cheap_kcal)) throw new Error('Cheap energy must be finite');
      ids.add(row.candidate_id);
      return Object.freeze({candidate_id: row.candidate_id, cheap_kcal: row.cheap_kcal});
    });
    const values = clean.map(row => row.cheap_kcal);
    if (!Number.isFinite(Math.max(...values) - Math.min(...values))) throw new Error('Cheap energy span overflows finite arithmetic');
    return clean;
  }
  function validateConfig(config) {
    const schemas = {
      full: ['kind'], fixed: ['kind', 'k'], adaptive: ['kind', 'k', 'gap', 'cap'],
      sequential: ['kind', 'one_gap', 'one_ratio', 'error_scale', 'slack', 'cap']
    };
    if (!config || !schemas[config.kind] || Object.keys(config).sort().join(',') !== schemas[config.kind].sort().join(',')) {
      throw new Error('Invalid policy configuration schema');
    }
    if (['fixed', 'adaptive'].includes(config.kind) && (!Number.isInteger(config.k) || config.k < 1)) throw new Error('k must be an integer >=1');
    if (config.kind === 'adaptive') {
      if (!Number.isInteger(config.cap) || config.cap < config.k || !finite(config.gap) || config.gap < 0) throw new Error('Invalid adaptive window/cap');
    }
    if (config.kind === 'sequential') {
      if (!Number.isInteger(config.cap) || config.cap < 2) throw new Error('Sequential cap must be an integer >=2');
      for (const key of ['one_gap', 'one_ratio', 'error_scale', 'slack']) if (!finite(config[key])) throw new Error('Sequential parameters must be finite');
      if (config.one_gap < 0 || config.one_ratio < 0 || config.one_ratio > 1 || config.error_scale < 1 || config.slack < 0) throw new Error('Invalid sequential parameters');
    }
    return Object.freeze({...config});
  }
  function bestObserved(observations) {
    const ids = Object.keys(observations);
    return ids.length ? ids.sort((a, b) => observations[a] - observations[b] || lexical(a, b))[0] : null;
  }

  function createEvaluator(record) {
    const candidates = validateCandidates(record.candidates);
    const ids = new Set(candidates.map(c => c.candidate_id));
    const labels = Object.freeze({...record.references});
    if (Object.keys(labels).some(id => !ids.has(id))) throw new Error('Reference ID outside pool');
    const observations = Object.create(null), cache = Object.create(null), queries = [];
    let stopped = false, finalResult = null;
    function snapshot() {
      return {candidates: candidates.map(c => ({...c})), observations: {...observations},
        queries: clone(queries), expensive_calls: queries.reduce((n, q) => n + q.charged, 0),
        best_verified: bestObserved(observations), stopped, evaluation: finalResult ? clone(finalResult) : null};
    }
    function query(id) {
      if (stopped) throw new Error('Trial already stopped; reset to start a new replay');
      const event = {order: queries.length + 1, candidate_id: id, charged: 0};
      if (!ids.has(id)) {
        queries.push({...event, status: 'rejected', error: 'unknown_candidate'});
        throw new Error('Unknown candidate');
      }
      let response;
      if (Object.prototype.hasOwnProperty.call(cache, id)) {
        response = {...cache[id], cached: true};
        event.status = response.ok ? 'cached' : 'cached_failure';
      } else {
        event.charged = 1;
        const value = labels[id];
        response = value == null ? {ok: false, error: 'missing_reference'}
          : typeof value !== 'number' ? {ok: false, error: 'invalid_reference'}
          : !Number.isFinite(value) ? {ok: false, error: 'nonfinite_reference'}
          : {ok: true, reference_kcal: value};
        response = {...response, candidate_id: id, cached: false};
        cache[id] = {...response};
        event.status = response.ok ? 'succeeded' : 'failed';
        if (response.ok) observations[id] = value;
      }
      if (response.ok) event.reference_kcal = response.reference_kcal;
      else event.error = response.error;
      queries.push(event);
      return {...response};
    }
    function finish(selected = bestObserved(observations), reason = 'manual_stop') {
      if (stopped) return clone(finalResult);
      if (!queries.some(q => q.charged)) throw new Error('Make at least one paid query before stopping');
      const expected = bestObserved(observations);
      if (!expected || selected !== expected) throw new Error('Select the best successfully verified queried candidate');
      const complete = candidates.every(c => finite(labels[c.candidate_id]));
      const allIds = candidates.map(c => c.candidate_id);
      const bestPool = complete ? allIds.sort((a, b) => labels[a] - labels[b] || lexical(a, b))[0] : null;
      const regret = complete ? Math.max(0, observations[selected] - labels[bestPool]) : null;
      finalResult = {selected_candidate: selected, selected_reference_kcal: observations[selected],
        best_pool_candidate: bestPool, regret_kcal: regret,
        success_within_1_kcal: regret == null ? null : regret <= 1 + TOL,
        stop_reason: reason, complete_reference_pool: complete};
      stopped = true;
      return clone(finalResult);
    }
    return Object.freeze({query, finish, snapshot});
  }

  function createEvaluatorBank(records) {
    const bank = new Map(records.map(record => [record.molecule_id, clone(record)]));
    if (bank.size !== records.length) throw new Error('Duplicate simulator molecule');
    const catalog = records.map(record => ({molecule_id: record.molecule_id,
      family_id: record.family_id, n_candidates: record.candidates.length,
      candidates: validateCandidates(record.candidates).map(c => ({...c})),
      fold_id: record.fold_id ?? null, is_acyclic: !!record.is_acyclic}));
    return Object.freeze({catalog,
      open(id) { if (!bank.has(id)) throw new Error('Unknown development molecule'); return createEvaluator(bank.get(id)); }});
  }

  function* policyProgram(rawCandidates, rawConfig) {
    const candidates = validateCandidates(rawCandidates).sort((a, b) => a.cheap_kcal - b.cheap_kcal || lexical(a.candidate_id, b.candidate_id));
    const config = validateConfig(rawConfig);
    const observations = Object.create(null), attempted = new Set();
    let fallback = false, failed = false, stopReason;
    function* event(value) { yield {type: 'event', ...value}; }
    function* query(row, reason) {
      const id = row.candidate_id;
      if (attempted.has(id)) return Object.prototype.hasOwnProperty.call(observations, id);
      attempted.add(id);
      yield* event({event: 'query_decision', candidate_id: id, reason});
      const response = yield {type: 'query', candidate_id: id};
      if (!response || response.candidate_id !== id) throw new Error('Unexpected oracle response');
      if (response.ok) { observations[id] = response.reference_kcal; return true; }
      failed = true;
      yield* event({event: 'query_failure', candidate_id: id, reason: response.error});
      return false;
    }
    function* complete(reason) {
      fallback = true;
      yield* event({event: 'fallback', reason, after_attempts: attempted.size});
      for (const row of candidates) yield* query(row, 'full_fallback');
      return 'full_rerank_fallback_' + reason;
    }
    if (config.kind === 'full') {
      for (const row of candidates) yield* query(row, 'full_rerank');
      stopReason = failed ? 'full_rerank_with_failed_outputs' : 'full_rerank_complete';
    } else if (config.kind === 'sequential') {
      if (!(yield* query(candidates[0], 'initial_verification'))) stopReason = yield* complete('failed_output');
      else if (candidates.length === 1) stopReason = 'all_candidates_queried';
      else {
        const cheapFirst = candidates[0].cheap_kcal;
        const gap = candidates[1].cheap_kcal - cheapFirst;
        const span = candidates[candidates.length - 1].cheap_kcal - cheapFirst;
        const ratio = span > 0 ? gap / span : 0;
        const separated = gap > 0 && gap + TOL >= config.one_gap && ratio + TOL >= config.one_ratio;
        yield* event({event: 'cheap_separation', gap12_kcal: gap, cheap_span_kcal: span,
          gap_ratio: ratio, one_gap: config.one_gap, one_ratio: config.one_ratio,
          action: separated ? 'stop' : 'query_next', after_attempts: attempted.size});
        if (separated) stopReason = 'sequential_cheap_separation_heuristic';
        else if (!(yield* query(candidates[1], 'initial_discrepancy'))) stopReason = yield* complete('failed_output');
        else {
          let count = 2;
          while (count < candidates.length) {
            const base = observations[candidates[0].candidate_id];
            let maxError = 0;
            for (const row of candidates.slice(0, count)) {
              maxError = Math.max(maxError, Math.abs((observations[row.candidate_id] - base) - (row.cheap_kcal - cheapFirst)));
            }
            const error = config.error_scale * maxError + config.slack;
            const best = Math.min(...Object.values(observations)) - base;
            const next = candidates[count].cheap_kcal - cheapFirst;
            if (![maxError, error, best, next, next - error + 1].every(Number.isFinite)) throw new Error('Nonfinite empirical-envelope arithmetic');
            const safe = best <= next - error + 1 + TOL;
            const action = safe ? 'stop' : attempted.size >= config.cap ? 'fallback' : 'query_next';
            yield* event({event: 'empirical_envelope', max_observed_discrepancy_kcal: maxError,
              envelope_error_kcal: error, best_observed_relative_kcal: best,
              next_cheap_relative_kcal: next, tolerated_lower_envelope_kcal: next - error + 1,
              regret_tolerance_kcal: 1, numerical_tolerance: TOL, action, after_attempts: attempted.size});
            if (safe) { stopReason = 'sequential_empirical_envelope'; break; }
            if (attempted.size >= config.cap) { stopReason = yield* complete('empirical_unresolved_at_cap'); break; }
            const ok = yield* query(candidates[count], 'empirical_envelope_unresolved');
            count++;
            if (!ok) { stopReason = yield* complete('failed_output'); break; }
          }
          if (!stopReason) stopReason = 'all_candidates_queried';
        }
      }
    } else {
      let count = Math.min(config.k, candidates.length);
      for (const row of candidates.slice(0, count)) yield* query(row, 'initial_top_k');
      if (failed) stopReason = yield* complete('failed_output');
      else if (config.kind === 'fixed') stopReason = count < candidates.length ? 'fixed_k_complete' : 'all_candidates_queried';
      else {
        stopReason = 'cheap_gap_exceeds_threshold';
        while (count < candidates.length) {
          const row = candidates[count], gap = row.cheap_kcal - candidates[0].cheap_kcal;
          if (gap > config.gap) break;
          if (count >= config.cap) { stopReason = yield* complete('crowded_at_cap'); break; }
          yield* event({event: 'escalation', candidate_id: row.candidate_id, cheap_gap_kcal: gap});
          count++;
          if (!(yield* query(row, 'cheap_window'))) { stopReason = yield* complete('failed_output'); break; }
        }
        if (count === candidates.length && !fallback) stopReason = 'all_candidates_queried';
      }
    }
    const selected = bestObserved(observations);
    if (!selected) stopReason = 'no_reference_verified_candidate';
    yield* event({event: 'stop', reason: stopReason, selected_candidate: selected, after_attempts: attempted.size});
    return {selected_candidate: selected, observations: {...observations}, fallback, stop_reason: stopReason};
  }

  function createPolicyRunner(candidates, config, query) {
    if (typeof query !== 'function') throw new Error('An oracle query function is required');
    const program = policyProgram(candidates, config), events = [];
    let pending = null, result = null, done = false;
    function advance(value) {
      let item = value;
      while (!item.done && item.value.type === 'event') {
        events.push({...item.value, event_order: events.length + 1});
        item = program.next();
      }
      if (item.done) { done = true; pending = null; result = {...item.value, policy_events: clone(events)}; }
      else if (item.value.type === 'query') pending = item.value.candidate_id;
      else throw new Error('Invalid policy program event');
    }
    advance(program.next());
    function snapshot() { return {done, pending_candidate: pending, result: result ? clone(result) : null, events: clone(events)}; }
    function step() {
      if (done) return snapshot();
      const response = query(pending);
      advance(program.next(response));
      return snapshot();
    }
    function run() {
      let guard = 0;
      while (!done) {
        if (++guard > candidates.length + 1) throw new Error('Policy exceeded candidate pool');
        step();
      }
      return snapshot();
    }
    return Object.freeze({step, run, snapshot});
  }
  function runPolicy(candidates, references, config) {
    const evaluator = createEvaluator({candidates, references});
    const runner = createPolicyRunner(candidates, config, evaluator.query);
    const state = runner.run(), result = state.result;
    if (!result.selected_candidate) {
      return {...result, ...evaluator.snapshot(), error: 'no_reference_verified_candidate'};
    }
    const evaluation = evaluator.finish(result.selected_candidate, result.stop_reason);
    const account = evaluator.snapshot();
    return {...result, queries: account.queries, expensive_calls: account.expensive_calls,
      observations: account.observations, evaluation};
  }
  function filterExperiments(rows, filters = {}) {
    const q = String(filters.query || '').toLowerCase();
    return rows.filter(row => (!filters.kind || filters.kind === 'all' || row.kind === filters.kind)
      && (!q || [row.config_id, row.policy, row.kind, JSON.stringify(row.config || {})].join(' ').toLowerCase().includes(q))
      && (filters.maxRisk == null || 100 * (1 - row.success_rate) <= filters.maxRisk + TOL)
      && (filters.maxCalls == null || row.mean_calls <= filters.maxCalls + TOL));
  }
  function sortExperiments(rows, field = 'mean_calls', descending = false) {
    return [...rows].sort((a, b) => {
      const x = a[field], y = b[field];
      const diff = typeof x === 'number' && typeof y === 'number' ? x - y : lexical(x ?? '', y ?? '');
      return (descending ? -diff : diff) || lexical(a.config_id || a.policy, b.config_id || b.policy);
    });
  }
  const api = Object.freeze({lexical, validateCandidates, validateConfig, bestObserved,
    createEvaluator, createEvaluatorBank, createPolicyRunner, runPolicy, filterExperiments, sortExperiments});
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.AQCEngine = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
