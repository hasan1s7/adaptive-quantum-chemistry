/* AQC mobile workbench. All acquisition decisions and hidden labels stay in the local API. */
(function (root) {
  'use strict';
  const C = root.AQCClient || (typeof require === 'function' ? require('./client.js') : null);
  const escape = value => String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[ch]));
  const finite = value => value !== null && value !== '' && value !== undefined && Number.isFinite(Number(value));
  const format = (value, digits = 2) => finite(value) ? Number(value).toLocaleString('en-US', {minimumFractionDigits: digits, maximumFractionDigits: digits}) : '—';
  const integer = value => finite(value) ? Number(value).toLocaleString('en-US', {maximumFractionDigits: 0}) : '—';
  const percent = (value, digits = 1) => finite(value) ? format(Number(value) * 100, digits) + '%' : '—';
  const COLORS = {fixed: '#3279a5', adaptive: '#cc963f', sequential: '#286d58', matched: '#8463a2', full: '#55616d', diagnostic: '#c07871'};
  const LABELS = {fixed: 'Fixed top-k', fixed_top_k: 'Fixed top-k', adaptive: 'Cheap window', sequential: 'Sequential', matched: 'Matched simple', matched_simple: 'Matched simple', full: 'Full rerank', full_rerank: 'Full rerank', diagnostic: 'Cheap-only diagnostic', cheap_only: 'Cheap-only diagnostic', manual: 'Manual queries'};
  const DESCRIPTIONS = {
    sequential: 'The fold-selected rule starts at the cheap minimum, checks the cheap-energy separation, then uses revealed discrepancies to decide whether to continue. Unresolved cases fall back to a full rerank.',
    fixed: 'Query the two cheapest-ranked conformers, then select the best reference energy among those queried.',
    adaptive: 'Query the initial cheap-ranked set, then continue while cheap energies remain inside the saved window. Crowding at the cap triggers a full rerank.',
    full: 'Query every conformer in this fixed pool and select its reference minimum.',
    manual: 'Choose a conformer in the viewer and reveal its reference. Finish only after at least one successful paid query; the best queried conformer is selected.'
  };
  const REASONS = {
    initial_verification: 'Verify the cheap-ranked first conformer.', initial_k: 'Verify the initial cheap-ranked candidates.', initial_top_k: 'Verify the initial cheap-ranked candidates.',
    initial_discrepancy: 'Reveal a second reference to measure the first cheap/reference discrepancy.', cheap_window: 'The next candidate is inside the cheap-energy window.',
    empirical_envelope_unresolved: 'The observed discrepancies do not yet support the heuristic stop.', full_fallback: 'The policy fell back to querying the complete pool.', full_rerank: 'The full rerank queries every candidate.',
    fixed_k_complete: 'The fixed query budget is complete.', cheap_gap_exceeds_threshold: 'The next cheap-energy gap exceeds the saved window.',
    sequential_cheap_separation_heuristic: 'The first cheap-energy gap met the saved separation rule.', sequential_empirical_envelope: 'The observed-error envelope met its heuristic stopping rule.',
    all_candidates_queried: 'Every conformer in the pool has been queried.', full_rerank_complete: 'The complete reference rerank is finished.',
    manual_stop: 'You finished with the best successfully queried reference.', manual_complete: 'You finished with the best successfully queried reference.'
  };
  function reasonText(reason) {
    if (!reason) return '';
    if (REASONS[reason]) return REASONS[reason];
    if (String(reason).startsWith('full_rerank_fallback_')) return 'The policy completed a full rerank fallback (' + String(reason).slice(21).replace(/_/g, ' ') + ').';
    return String(reason).replace(/_/g, ' ');
  }
  function resolveConfig(molecule, catalog, policy) {
    const aliases = {fixed: 'fixed_top_k', full: 'full_rerank'};
    const options = molecule?.policy_configs || {};
    const perMolecule = options[policy] || options[aliases[policy]];
    // A generic catalog preset must never be presented as a fold-selected configuration.
    const supplied = perMolecule || (!['sequential', 'adaptive'].includes(policy)
      ? (catalog?.policies || []).find(row => row.id === policy || row.id === aliases[policy]) : null);
    const config = supplied?.config || (supplied?.kind ? supplied : null);
    if (config) return JSON.parse(JSON.stringify(config));
    if (policy === 'fixed') return {kind: 'fixed', k: 2};
    if (policy === 'full') return {kind: 'full'};
    if (policy === 'manual') return {kind: 'manual'};
    throw new Error('The saved ' + policy + ' configuration is unavailable for this molecule. Choose fixed top-2 or full rerank.');
  }
  function confidence(row, metric, asPercent = false) {
    const lo = row[metric + '_ci_low'], hi = row[metric + '_ci_high'];
    return finite(lo) && finite(hi) ? (asPercent ? percent(lo) + '–' + percent(hi) : format(lo) + '–' + format(hi)) : null;
  }
  function params(row) {
    return ['k', 'gap', 'one_gap', 'one_ratio', 'error_scale', 'slack', 'cap'].filter(key => finite(row[key])).map(key => key.replace(/_/g, ' ') + ' ' + row[key]).join(' · ');
  }
  function renderPlot(rows, scope, viewportWidth = 900) {
    if (!rows.length) return '<div class="empty-state compact">No measured points match these filters.</div>';
    const width = Math.max(280, Math.min(1200, Number(viewportWidth) || 900)), compact = width < 600;
    const height = compact ? 280 : 310, left = compact ? 48 : 64, right = compact ? 14 : 26, top = 22, bottom = 53;
    const valid = rows.filter(row => finite(row.mean_calls) && finite(row.success_rate));
    if (!valid.length) return '<div class="empty-state compact">No finite call/risk measurements are available.</div>';
    const maxX = Math.max(2, Math.ceil(Math.max(...valid.map(row => Number(row.mean_calls_ci_high || row.mean_calls)))));
    const maxRisk = Math.max(.1, Math.max(...valid.map(row => 1 - Number(scope === 'cv' && finite(row.success_rate_ci_low) ? row.success_rate_ci_low : row.success_rate))) * 1.14);
    const yMax = Math.ceil(maxRisk / .025) * .025;
    const x = value => left + Number(value) / maxX * (width - left - right);
    const y = value => top + (1 - Number(value) / yMax) * (height - top - bottom);
    let svg = `<svg viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg" role="img"><title>${scope === 'cv' ? 'Family-blocked development cross-validation' : 'Pooled development configurations'}: risk versus mean charged calls</title><desc>All points are saved observations. The dashed line marks five percent risk. ${scope === 'cv' ? 'Whiskers show marginal family-bootstrap intervals, conditional on the fixed folds and selected policies.' : 'No uncertainty intervals or external validation are implied for the configuration sweep.'}</desc>`;
    for (let i = 0; i <= 4; i++) {
      const tick = yMax * i / 4;
      svg += `<line x1="${left}" y1="${y(tick)}" x2="${width - right}" y2="${y(tick)}" stroke="#e7ede2"/><text x="${left - 11}" y="${y(tick) + 5}" text-anchor="end" font-size="14" fill="#6a7a65">${format(tick * 100, tick === 0 ? 0 : 1)}%</text>`;
    }
    for (let i = 0; i <= 5; i++) {
      const tick = maxX * i / 5;
      svg += `<text x="${x(tick)}" y="${height - bottom + 24}" text-anchor="middle" font-size="14" fill="#6a7a65">${format(tick, tick % 1 ? 1 : 0)}</text>`;
    }
    svg += `<line x1="${left}" y1="${y(.05)}" x2="${width - right}" y2="${y(.05)}" stroke="#b29c6e" stroke-dasharray="5 5"/><text x="${width - right - 3}" y="${y(.05) - 8}" text-anchor="end" font-size="13" fill="#8e794d">5% risk target</text>`;
    for (const row of valid) {
      const kind = C.policyKind(row), color = COLORS[kind] || '#677764', px = x(row.mean_calls), py = y(1 - Number(row.success_rate));
      const title = `${row.config_id || LABELS[row.policy] || row.policy}: ${percent(row.success_rate)} success, ${format(row.mean_calls)} calls per molecule; P95 regret ${format(row.p95_regret_kcal)} kcal/mol${kind === 'diagnostic' ? '. Unverified diagnostic.' : ''}`;
      svg += '<g>';
      if (scope === 'cv' && finite(row.success_rate_ci_low) && finite(row.success_rate_ci_high)) {
        svg += `<line x1="${px}" y1="${y(1 - Number(row.success_rate_ci_high))}" x2="${px}" y2="${y(1 - Number(row.success_rate_ci_low))}" stroke="${color}" opacity=".6" stroke-width="1.6"/>`;
        if (finite(row.mean_calls_ci_low) && finite(row.mean_calls_ci_high)) svg += `<line x1="${x(row.mean_calls_ci_low)}" y1="${py}" x2="${x(row.mean_calls_ci_high)}" y2="${py}" stroke="${color}" opacity=".6" stroke-width="1.6"/>`;
      }
      svg += `<circle cx="${px}" cy="${py}" r="${scope === 'cv' ? 5.2 : 3.3}" fill="${color}" fill-opacity="${scope === 'cv' ? 1 : .38}" stroke="${scope === 'cv' ? '#fff' : color}" stroke-width="${scope === 'cv' ? 1.5 : .3}"><title>${escape(title)}</title></circle></g>`;
    }
    svg += `<text x="${(left + width - right) / 2}" y="${height - 6}" text-anchor="middle" font-size="14" fill="#5f725a">${compact ? 'Mean reference calls / molecule' : 'Mean charged reference calls per molecule'}</text></svg>`;
    return svg;
  }
  function createApp(document, options = {}) {
    const api = options.api || C.createClient();
    let storage = options.storage;
    if (storage === undefined) { try { storage = root.localStorage; } catch (_) { storage = null; } }
    const $ = id => document.getElementById(id);
    const state = {health: null, catalog: null, molecule: null, session: null, config: null,
      view: 'replay', policy: 'sequential', candidateId: null, busy: false, apiReady: false, generation: 0,
      savedMode: false, savedSource: null, results: null, resultScope: 'cv', resultPage: 0, resultsBusy: false, viewer: null};
    const extras = root.AQCExtras?.create(document, {api, download, toast, navigate: view});
    let toastTimer = null;
    const STORAGE_KEY = 'aqc-workbench-saved-runs-v1', MAX_SAVED = 12;
    function setText(id, value) { const node = $(id); if (node) node.textContent = value == null ? '' : String(value); }
    function setHTML(id, value) { const node = $(id); if (node) node.innerHTML = value; }
    function show(id, visible = true) { const node = $(id); if (node) node.hidden = !visible; }
    function listen(id, event, handler) { $(id)?.addEventListener(event, handler); }
    function toast(message) { setText('toast', message); show('toast'); clearTimeout(toastTimer); toastTimer = setTimeout(() => show('toast', false), 4200); }
    function error(message, id = 'global-error') { setText(id, message); show(id, !!message); }
    function connection(online) {
      $('connection-status').className = 'connection ' + (online ? 'ready' : 'offline');
      setHTML('connection-status', '<span class="connection-dot"></span><span>' + (online ? 'Local server connected' : 'Server unavailable') + '</span>');
    }
    function renderSessionStatus() {
      const failed = state.session?.status === 'failed', completed = state.session?.status === 'completed';
      setText('session-status', state.savedMode ? 'Saved run' : failed ? 'Failed · logged' : completed ? 'Completed' : state.busy ? 'Working' : 'Ready');
      $('session-status').className = 'status-chip' + (failed ? ' failure' : completed ? ' complete' : '');
    }
    function busy(value) { state.busy = value; renderSessionStatus(); renderActionState(); }
    function readSaved() {
      try { const data = JSON.parse(storage?.getItem(STORAGE_KEY) || '[]'); return Array.isArray(data) ? data : []; }
      catch (_) { return []; }
    }
    function updateSavedCount() { const count = readSaved().length; setText('saved-count', count); show('saved-count', count > 0); }
    function writeSaved(rows) {
      if (!storage) throw new Error('This browser cannot store runs. Use Download trace to keep a JSON copy.');
      try { storage.setItem(STORAGE_KEY, JSON.stringify(rows)); }
      catch (_) { throw new Error('Browser storage is unavailable or full. Download the run JSON to keep a portable copy.'); }
      updateSavedCount();
    }
    function download(name, text, type = 'application/json') {
      const blob = new Blob([text], {type}), url = root.URL.createObjectURL(blob), anchor = document.createElement('a');
      anchor.href = url; anchor.download = name; anchor.hidden = true; document.body.appendChild(anchor); anchor.click(); anchor.remove();
      setTimeout(() => root.URL.revokeObjectURL(url), 1000);
    }
    function view(name, updateHash = true) {
      if (!['replay', 'results', 'saved', 'compare', 'diagnostics'].includes(name)) name = 'replay';
      state.view = name; document.body.dataset.view = name;
      for (const item of ['replay', 'results', 'saved', 'compare', 'diagnostics']) show('view-' + item, item === name && (item !== 'replay' || !!state.molecule));
      show('startup-panel', name === 'replay' && !state.molecule);
      for (const button of document.querySelectorAll('[data-view]')) {
        const active = button.dataset.view === name; button.classList.toggle('active', active);
        if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
      }
      if (updateHash && root.history?.replaceState) root.history.replaceState(null, '', '#' + name);
      if (name === 'results') loadResults();
      if (name === 'saved') renderSaved();
      if (name === 'replay' && state.viewer) root.requestAnimationFrame?.(() => state.viewer.resize());
      extras?.onView(name);
    }
    function filteredMolecules() {
      const query = ($('molecule-search')?.value || '').trim().toLowerCase();
      return (state.catalog?.molecules || []).filter(row => row.molecule_id.toLowerCase().includes(query));
    }
    function renderMoleculeOptions() {
      const molecules = filteredMolecules();
      setHTML('molecule-select', molecules.length ? molecules.map(row => `<option value="${escape(row.molecule_id)}">${escape(row.molecule_id)} · ${integer(row.n_candidates)} conformers</option>`).join('') : '<option value="">No molecules match</option>');
      if (state.molecule && molecules.some(row => row.molecule_id === state.molecule.molecule_id)) $('molecule-select').value = state.molecule.molecule_id;
      $('molecule-select').disabled = state.busy || state.savedMode || !molecules.length;
      setText('molecule-total', integer(molecules.length) + ' of ' + integer(state.catalog?.molecules?.length));
    }
    function renderPolicyOptions() {
      const choices = state.savedMode ? [[state.policy, 'Saved ' + (LABELS[state.policy] || state.policy) + ' configuration']]
        : [['sequential', 'Sequential · fold-selected'], ['fixed', 'Fixed top-2'], ['adaptive', 'Cheap window · fold-selected'], ['full', 'Full reference rerank'], ['manual', 'Manual queries']];
      setHTML('policy-select', choices.map(([id, label]) => '<option value="' + escape(id) + '">' + escape(label) + '</option>').join(''));
      $('policy-select').value = state.policy;
    }
    function sortedCandidates() {
      return (state.molecule?.candidates || []).slice().sort((a, b) => a.cheap_kcal - b.cheap_kcal || (a.candidate_id < b.candidate_id ? -1 : a.candidate_id > b.candidate_id ? 1 : 0));
    }
    function renderConformers() {
      const rows = sortedCandidates(), min = rows[0]?.cheap_kcal || 0, observations = state.session?.observations || {};
      setHTML('conformer-select', rows.map((row, i) => `<option value="${escape(row.candidate_id)}">${i + 1}. ${escape(row.candidate_id)} · ΔxTB ${format(row.cheap_kcal - min)}${Object.prototype.hasOwnProperty.call(observations, row.candidate_id) ? ' · queried' : ''}</option>`).join(''));
      if (!rows.some(row => row.candidate_id === state.candidateId)) state.candidateId = rows[0]?.candidate_id || null;
      $('conformer-select').value = state.candidateId || ''; $('conformer-select').disabled = !rows.length;
      $('conformer-prev').disabled = rows.length < 2; $('conformer-next').disabled = rows.length < 2;
    }
    function createViewer() {
      if (state.viewer || !root.AQCMoleculeViewer) return state.viewer;
      try {
        state.viewer = root.AQCMoleculeViewer.create($('molecule-viewport'), {background: '#0b1d28',
          onStateChange: next => {
            setText('renderer-label', next.renderer === 'webgl' ? 'WebGL · 3D' : 'Canvas · projected 3D');
            $('viewer-hydrogens').checked = next.hydrogens; $('viewer-spin').checked = next.autoRotate;
            $('viewer-style').value = next.style;
          }});
      } catch (err) { setText('geometry-message', 'The 3D renderer could not start: ' + err.message); show('geometry-message'); }
      return state.viewer;
    }
    function renderGeometry(changeGeometry = true) {
      const candidate = state.molecule?.candidates.find(row => row.candidate_id === state.candidateId);
      if (!candidate) return;
      const min = Math.min(...state.molecule.candidates.map(row => row.cheap_kcal));
      setHTML('view-cheap-energy', format(candidate.cheap_kcal - min, 3) + ' <small>kcal/mol</small>');
      const observations = state.session?.observations || {}, observed = Object.prototype.hasOwnProperty.call(observations, candidate.candidate_id);
      setHTML('view-reference-energy', observed ? '<span class="revealed">' + format(observations[candidate.candidate_id], 4) + ' <small>kcal/mol</small></span>' : 'Hidden until queried');
      if (changeGeometry) {
        const geometry = candidate.geometry || candidate;
        if (!geometry.symbols || !geometry.coordinates_angstrom) {
          state.viewer?.setGeometry(null); setText('geometry-message', 'Verified coordinates are unavailable for this conformer. The energy replay remains usable.'); show('geometry-message');
        } else {
          const viewer = createViewer();
          if (viewer) {
            try { viewer.setGeometry(geometry, {molecule_id: state.molecule.molecule_id, candidate_id: candidate.candidate_id, label: state.molecule.molecule_id + ' / ' + candidate.candidate_id}); viewer.resize(); show('geometry-message', false); }
            catch (err) { setText('geometry-message', 'Unable to display these coordinates: ' + err.message); show('geometry-message'); }
          } else if (!root.AQCMoleculeViewer) { setText('geometry-message', 'The 3D viewer asset did not load. Check that the local server serves /assets/molecule-viewer.js.'); show('geometry-message'); }
        }
        setText('coordinate-detail', candidate.candidate_id + (state.savedMode ? '\nDeclared geometry SHA-256: ' : '\nGeometry SHA-256: ') + (geometry.geometry_sha256 || 'not supplied') + (geometry.xyz_sha256 ? (state.savedMode ? '\nDeclared XYZ SHA-256: ' : '\nXYZ SHA-256: ') + geometry.xyz_sha256 : '') + '\nCoordinates: Å · display bonds: distance heuristic');
      }
      renderActionState();
    }
    function selectCandidate(id) {
      if (!state.molecule?.candidates.some(row => row.candidate_id === id)) return;
      state.candidateId = id; $('conformer-select').value = id; renderGeometry(true);
    }
    function renderPolicyDetails() {
      setText('policy-description', DESCRIPTIONS[state.config?.kind || state.policy] || 'Saved acquisition configuration.');
      const metadata = [ ['Molecule', state.molecule?.molecule_id], ['Chemical family', state.molecule?.family_id], ['CV fold (1–5)', state.molecule?.fold_id == null ? 'not supplied' : Number(state.molecule.fold_id) + 1] ];
      if (state.session?.session_id) metadata.push(['Session', state.session.session_id]);
      if (state.session?.session_expensive_calls > state.session?.expensive_calls) metadata.push(['Calls across resets', state.session.session_expensive_calls]);
      setHTML('policy-metadata', metadata.map(([key, val]) => `<div><dt>${escape(key)}</dt><dd class="mono">${escape(val)}</dd></div>`).join(''));
      setText('policy-config', JSON.stringify(state.config || {}, null, 2));
    }
    function renderActionState() {
      const session = state.session, manual = state.config?.kind === 'manual', active = !!session && !session.stopped && session.status !== 'failed' && !state.savedMode && state.apiReady;
      const observed = session && Object.prototype.hasOwnProperty.call(session.observations || {}, state.candidateId);
      $('step-query').disabled = state.busy || !active || (manual && observed);
      $('run-policy').disabled = state.busy || !active;
      $('finish-manual').disabled = state.busy || !active || !Object.keys(session?.observations || {}).length;
      show('run-policy', !manual); show('finish-manual', manual);
      show('query-actions', !state.savedMode && (!session?.stopped && session?.status !== 'failed'));
      const label = state.busy ? 'Recording…' : manual ? (observed ? 'Already queried' : 'Reveal conformer') : 'Reveal next';
      setHTML('step-query', '<span class="action-symbol" aria-hidden="true">+</span>' + escape(label) + '<span class="button-cost">1 call</span>');
      $('reset-session').disabled = state.busy || !session || state.savedMode || !state.apiReady;
      $('save-run').disabled = state.busy || !session || !session.queries?.length;
      $('download-trace').disabled = state.busy || !session || !session.queries?.length;
      $('policy-select').disabled = state.busy || !state.molecule || state.savedMode || !state.apiReady;
      $('molecule-search').disabled = state.busy || state.savedMode || !state.apiReady;
      $('molecule-select').disabled = state.busy || state.savedMode || !state.apiReady || !filteredMolecules().length;
    }
    function renderSession() {
      const session = state.session;
      setText('replay-scope-label', state.savedMode ? 'SAVED RUN · READ-ONLY SNAPSHOT' : 'REAL MOLECULES · OFFLINE REFERENCE REPLAY');
      setText('replay-scope-pill', state.savedMode ? 'User-supplied snapshot' : 'Original development data');
      setText('coordinate-scope-label', state.savedMode ? 'SUPPLIED COORDINATES · UNVERIFIED' : 'VERIFIED COORDINATES');
      setText('molecule-title', state.molecule?.molecule_id || 'No molecule selected');
      setText('pool-size', state.molecule?.candidates.length || '—');
      setText('paid-count', integer(session?.expensive_calls || 0));
      const isFailure = session?.status === 'failed', isComplete = session?.status === 'completed';
      renderSessionStatus();
      setText('query-title', isFailure ? 'Query failure recorded' : isComplete ? 'Decision recorded' : session?.expensive_calls ? 'Follow the next decision' : 'Start with one reference');
      const best = session?.best_verified;
      setHTML('best-verified', '<span>' + (state.savedMode ? 'Best recorded queried conformer' : 'Best reference-verified conformer') + '</span><strong>' + escape(best || 'None yet') + '</strong><p>' + (best ? format(session.observations[best], 4) + ' kcal/mol · selected only from revealed references' : 'Each query reveals one reference energy.') + '</p>');
      show('session-result', !!session?.evaluation && isComplete);
      if (session?.evaluation && isComplete) {
        const evaluation = session.evaluation, success = evaluation.success_within_1_kcal ?? (finite(evaluation.regret_kcal) ? Number(evaluation.regret_kcal) <= 1 + 1e-9 : null);
        $('session-result').className = 'session-result' + (success === false ? ' unsuccessful' : '');
        const reason = session.stop_reason || evaluation.stop_reason;
        setHTML('session-result', '<div class="result-label">' + (state.savedMode ? 'REPORTED: ' : '') + (success === null ? 'EVALUATION INCOMPLETE' : success ? 'WITHIN 1 KCAL/MOL' : 'ABOVE 1 KCAL/MOL') + '</div><div class="regret-value">' + format(evaluation.regret_kcal, 3) + ' <small>kcal/mol regret</small></div><p>Selected: <strong>' + escape(session.selected_candidate || evaluation.selected_candidate || best) + '</strong>. ' + (state.savedMode ? 'This file reports the evaluator score. Unqueried references are unavailable here, so its regret is not independently re-evaluated.' : 'Regret is measured against the full fixed pool by the evaluator after stopping.') + '</p><p>' + escape(reasonText(reason)) + '</p><p class="mono stop-code">' + escape(reason || 'No stop reason supplied') + (session.fallback ? ' · full fallback used' : '') + '</p>');
      }
      let next;
      if (state.savedMode) next = 'Read-only saved run. Only the reference observations captured at save time are available.';
      else if (isFailure) next = 'The server stopped this session after a failure. Charged calls remain in the query history. Start over to create a fresh replay.';
      else if (isComplete) next = 'The best queried conformer is the final decision. Save or download this trace, or start over.';
      else if (state.config?.kind === 'manual') next = '<strong>' + escape(state.candidateId || '') + '</strong> is selected in the viewer. Reveal it, then finish when you are ready.';
      else next = session?.pending_candidate ? 'Next: <strong>' + escape(session.pending_candidate) + '</strong>. ' + escape(reasonText(session.pending_reason)) : 'Creating a clean session with zero charged calls…';
      setHTML('next-decision', '<span class="step-marker" aria-hidden="true">' + (isComplete ? '✓' : '→') + '</span><p>' + next + '</p>');
      renderTrace(); renderPolicyDetails(); renderConformers(); renderGeometry(false); renderActionState();
    }
    function renderTrace() {
      const queries = state.session?.queries || [];
      setText('trace-count', queries.length ? integer(queries.length) + ' events · ' + integer(state.session.expensive_calls) + ' charged' : 'No queries yet');
      setHTML('query-history', queries.length ? queries.map((query, i) => {
        const succeeded = finite(query.reference_kcal), status = query.status || (succeeded ? 'succeeded' : 'failed');
        return `<li><span class="query-order">${escape(query.order || i + 1)}</span><div class="query-description"><strong>${escape(query.candidate_id)}</strong><p>${query.charged ? '+1 charged call' : 'No new charge'} · ${escape(status)}</p></div><div class="query-energy">${succeeded ? format(query.reference_kcal, 4) : 'Unavailable'}<span>${succeeded ? 'kcal/mol revealed' : escape(query.error || 'reference not revealed')}</span></div></li>`;
      }).join('') : '<li class="empty-state compact">Reference labels stay on the server until a charged query reveals them.</li>');
      const events = state.session?.policy_events || [];
      show('policy-events-details', events.length > 0);
      setHTML('policy-events', events.map(event => '<li><strong>' + escape(reasonText(event.event || event.type || 'decision')) + '</strong>' + (event.reason ? ' · ' + escape(reasonText(event.reason)) : '') + '<pre>' + escape(JSON.stringify(event, null, 2)) + '</pre></li>').join(''));
    }
    async function loadMolecule(id) {
      if (!id || state.busy) return;
      const generation = ++state.generation, previousSessionId = state.session?.session_id;
      error(''); busy(true); state.savedMode = false; renderPolicyOptions(); show('saved-mode-banner', false);
      try {
        const response = await api.molecule(id);
        if (generation !== state.generation) return;
        const molecule = response.molecule || response;
        // Reject accidental API label exposure before it can enter client display state.
        if (molecule.references || molecule.candidates?.some(row => Object.prototype.hasOwnProperty.call(row, 'reference_kcal'))) throw new Error('The molecule API unexpectedly included hidden reference labels. Replay was blocked.');
        C.cleanMolecule(molecule);
        state.molecule = molecule; state.session = null; state.candidateId = null;
        renderMoleculeOptions(); renderConformers();
        show('startup-panel', false); show('view-replay', state.view === 'replay');
        state.config = resolveConfig(molecule, state.catalog, state.policy);
        renderSession(); renderGeometry(true);
        const created = await api.createSession(molecule.molecule_id, state.config);
        if (generation !== state.generation) return;
        state.session = C.unwrapSession(created); renderSession(); connection(true);
        if (previousSessionId && previousSessionId !== state.session.session_id && api.releaseSession) {
          try { await api.releaseSession(previousSessionId); } catch (_) { /* Idle expiration also frees abandoned sessions. */ }
        }
      } catch (err) { error(err.message); if (!state.molecule) startupFailure(err); }
      finally { if (generation === state.generation) busy(false); }
    }
    async function changePolicy() {
      if (state.busy || state.savedMode || !state.molecule) return;
      const previousSessionId = state.session?.session_id;
      state.policy = $('policy-select').value; error(''); busy(true);
      try {
        state.config = resolveConfig(state.molecule, state.catalog, state.policy);
        state.session = null; renderSession();
        state.session = C.unwrapSession(await api.createSession(state.molecule.molecule_id, state.config));
        const first = sortedCandidates()[0]; if (first) selectCandidate(first.candidate_id);
        renderSession(); toast('Fresh session · no references revealed');
        if (previousSessionId && previousSessionId !== state.session.session_id && api.releaseSession) {
          try { await api.releaseSession(previousSessionId); } catch (_) { /* No scientific state is changed by expiration. */ }
        }
      } catch (err) { error(err.message); }
      finally { busy(false); }
    }
    async function action(name, body = {}) {
      if (state.busy || !state.session || state.savedMode || !state.apiReady) return;
      const sessionId = state.session.session_id;
      error(''); busy(true);
      try {
        const result = await api.action(sessionId, name, body);
        state.session = C.unwrapSession(result);
        const last = [...state.session.queries].reverse().find(query => query.charged);
        const selected = state.session.stopped ? state.session.selected_candidate || state.session.best_verified : last?.candidate_id;
        if (selected) selectCandidate(selected);
        if (name === 'reset') { const first = sortedCandidates()[0]; if (first) selectCandidate(first.candidate_id); }
        renderSession(); connection(true);
        if (state.session.stopped) toast('Decision recorded · ' + format(state.session.evaluation?.regret_kcal, 3) + ' kcal/mol regret');
      } catch (err) {
        if (err.session) state.session = C.unwrapSession(err.session);
        else {
          // A POST is never retried. Reconcile a timeout/disconnect by reading the server ledger.
          try { state.session = C.unwrapSession(await api.getSession(sessionId)); }
          catch (_) { state.apiReady = false; connection(false); }
        }
        renderSession(); error(err.message + (err.code === 'timeout' ? ' No query was retried.' : ''));
        if (!state.apiReady) setHTML('global-error', escape(err.message) + '<p>Further queries are paused until the recorded state is recovered. No query was retried.</p><button class="button secondary" data-reconcile-session>Refresh recorded session</button>');
      } finally { busy(false); }
    }
    async function exportCurrent(saveLocal = false) {
      if (state.busy || !state.session?.queries?.length) return;
      try {
        let trace = null;
        if (!state.savedMode && state.apiReady) {
          try { trace = await api.exportSession(state.session.session_id); }
          catch (_) { toast('Server export unavailable; preserving the recorded client snapshot.'); }
        }
        const run = C.makeSavedRun(state.molecule, state.session, state.savedSource || state.health?.provenance || state.health || {}, trace);
        if (saveLocal) {
          const id = run.session.session_id || run.molecule.molecule_id + '_' + run.saved_at;
          const key = id + ':' + run.session.expensive_calls + ':' + Number(run.session.stopped);
          const rows = readSaved().filter(row => row.key !== key);
          rows.unshift({key, run});
          if (rows.length > MAX_SAVED) throw new Error('This browser already has 12 saved runs. Export or remove an older run before saving another.');
          writeSaved(rows); toast('Run saved on this device');
        } else download('aqc-' + run.molecule.molecule_id.replace(/[^A-Za-z0-9_.-]/g, '_') + '-run.json', JSON.stringify(run, null, 2) + '\n');
      } catch (err) { error(err.message); }
    }
    function renderSaved() {
      const rows = readSaved(); updateSavedCount();
      setHTML('saved-runs', rows.length ? rows.map((entry, index) => {
        const run = entry.run, session = run?.session || {}, molecule = run?.molecule || {};
        return `<article class="saved-card"><div class="section-heading"><div><h2>${escape(molecule.molecule_id || 'Unreadable run')}</h2><p class="saved-time">${escape(new Date(run?.saved_at).toLocaleString())}</p></div><span class="status-chip">${session.stopped ? 'Completed' : 'Partial trace'}</span></div><p>${escape(LABELS[session.config?.kind] || session.config?.kind || 'Recorded policy')} · ${integer(session.expensive_calls)} charged calls</p><p>${session.stopped && finite(session.evaluation?.regret_kcal) ? format(session.evaluation.regret_kcal, 3) + ' kcal/mol regret · selected ' + escape(session.selected_candidate || session.best_verified) : 'Only the recorded reference reveals are available.'}</p><div class="saved-actions"><button class="button primary" data-saved-open="${index}">Open run</button><button class="text-button" data-saved-export="${index}">Export JSON</button><button class="text-button delete-run" data-saved-delete="${index}" aria-label="Remove saved run ${escape(molecule.molecule_id)}">Remove</button></div></article>`;
      }).join('') : '<div class="empty-state"><h2>No saved runs yet</h2><p>Reveal a reference, then choose Save run. You can also import a workbench run JSON.</p><button class="button primary" data-start-replay>Replay a molecule</button></div>');
    }
    function openSaved(raw) {
      try {
        const run = C.validateSavedRun(raw); state.generation++; state.savedMode = true;
        state.savedSource = run.source; state.molecule = run.molecule; state.session = C.unwrapSession(run.session);
        state.config = run.session.config; state.policy = run.session.config?.kind || 'manual'; state.candidateId = state.session.best_verified || run.molecule.candidates[0].candidate_id;
        show('saved-mode-banner'); setText('saved-mode-detail', 'Saved ' + new Date(run.saved_at).toLocaleString() + '. Geometry and disclosed references are available without another query.');
        renderPolicyOptions();
        setHTML('molecule-select', '<option value="' + escape(run.molecule.molecule_id) + '">' + escape(run.molecule.molecule_id) + ' · saved run</option>');
        $('molecule-select').value = run.molecule.molecule_id; setText('molecule-total', 'saved run');
        error(''); view('replay'); renderSession(); renderGeometry(true);
      } catch (err) { error(err.message, 'saved-error'); }
    }
    function normalizeResults(raw) {
      const data = raw.results || raw;
      return {...data, aggregate: data.aggregate || data.cross_validation?.aggregate || [], experiments: data.experiments || data.development?.experiments || [], decision: data.decision || {}, provenance: data.provenance || {}};
    }
    async function loadResults() {
      if (state.results) { renderResults(); return; }
      if (state.resultsBusy) return;
      state.resultsBusy = true; show('results-loading'); show('results-content', false); error('', 'results-error');
      try { state.results = normalizeResults(await api.results()); renderResults(); }
      catch (err) { error(err.message + ' Reopen this tab to try again.', 'results-error'); }
      finally { state.resultsBusy = false; show('results-loading', false); }
    }
    function resultRows() {
      if (!state.results) return [];
      if (state.resultScope === 'cv') {
        const order = ['sequential', 'matched_simple', 'fixed_top_k', 'adaptive', 'full_rerank', 'cheap_only'];
        return state.results.aggregate.slice().sort((a, b) => order.indexOf(a.policy) - order.indexOf(b.policy));
      }
      return C.filterExperiments(state.results.experiments, {search: $('configuration-search').value, kind: $('configuration-kind').value,
        maxRisk: $('configuration-risk').value, sort: $('configuration-sort').value});
    }
    function renderDecision() {
      const decision = state.results.decision, aggregate = state.results.aggregate;
      const primary = aggregate.find(row => row.policy === decision.primary_policy), comparator = aggregate.find(row => row.policy === decision.primary_comparator);
      if (!primary || !comparator) { show('result-decision', false); return; }
      show('result-decision', state.resultScope === 'cv');
      const savings = decision.relative_call_savings, pair = decision.paired_difference || {};
      const met = decision.observed_joint_target_met === true;
      const title = met ? 'The observed development target was met' : 'The combined acquisition target was not met';
      const cost = finite(savings) ? (Number(savings) >= 0 ? percent(savings) + ' fewer calls' : percent(-Number(savings)) + ' more calls') : 'no available call-saving estimate';
      setHTML('result-decision', '<div class="decision-mark" aria-hidden="true">' + (met ? '✓' : '↗') + '</div><div><h2>' + title + '</h2><p><strong>' + escape(LABELS[primary.policy] || primary.policy) + '</strong> achieved <strong>' + percent(primary.success_rate) + '</strong> success with ' + cost + ' versus the fold-selected matched simple comparator (' + percent(comparator.success_rate) + ' success). The target is at least 95% success and at least 30% fewer calls at matched risk.</p><p class="comparison-line">' + (confidence(pair, 'relative_call_savings', true) ? 'Paired call-savings interval: ' + confidence(pair, 'relative_call_savings', true) + '. ' : '') + 'Development cross-validation only. These marginal intervals do not establish a joint 95% guarantee. Shape-probe benefit has not been measured.</p></div>');
    }
    function renderResults() {
      if (!state.results) return;
      show('results-content'); show('results-loading', false); const cv = state.resultScope === 'cv', rows = resultRows();
      for (const name of ['cv', 'registry']) { const active = name === state.resultScope; $('scope-' + name).classList.toggle('active', active); $('scope-' + name).setAttribute('aria-pressed', String(active)); }
      const aggregates = state.results.aggregate, first = aggregates[0] || {}, decision = state.results.decision;
      setText('registry-total', integer(state.results.experiments.length));
      setHTML('scope-explanation', cv
        ? '<strong>Five family-blocked folds within the original development set.</strong> Each fold chooses policies using the other four folds. The recorded ' + integer(first.n_molecules || decision.development_molecules) + ' molecules and ' + integer(first.n_families || decision.development_families) + ' families form development cross-validation, not a fresh external holdout.'
        : '<strong>All registered configurations on the original development pools.</strong> These are descriptive pooled measurements. Filtering this table explores the recorded sweep; it does not create a new validated operating point or tune on the historical evaluation set.');
      const summary = [ [integer(first.n_molecules || decision.development_molecules), 'Development molecules', 'Same fixed candidate pools'], [integer(first.n_families || decision.development_families), 'Chemical families', 'Generic-scaffold grouping'], [integer(state.results.experiments.length), 'Registered configurations', 'Measured, including diagnostic'], [cv ? integer(decision.outer_folds || state.results.fold_choices?.folds?.length) : integer(new Set(state.results.experiments.map(row => row.behavior_signature).filter(Boolean)).size), cv ? 'Family-blocked folds' : 'Distinct recorded behaviors', cv ? 'Conditional out-of-fold intervals' : 'Equivalent configurations disclosed'] ];
      setHTML('results-summary', summary.map(([value, label, detail]) => '<div class="summary-stat"><strong>' + value + '</strong><span>' + escape(label) + '</span><span class="stat-sub">' + escape(detail) + '</span></div>').join(''));
      renderDecision();
      setHTML('risk-plot', renderPlot(rows, state.resultScope, $('risk-plot').clientWidth)); setText('plot-count', integer(rows.length) + ' measured points');
      setText('plot-note', cv ? 'Whiskers are marginal 95% family-bootstrap intervals, conditional on the fixed folds and chosen configurations. Selection is not repeated inside the bootstrap. Zero observed failures can yield a degenerate bootstrap interval; this does not prove zero future risk. Calls are offline counts, not elapsed time.' : 'Points may overlap when distinct configurations behave identically. Pooled development outcomes are descriptive; no per-configuration cross-validation claim is made. Calls are offline counts, not elapsed time.');
      show('registry-filters', !cv); setText('result-list-title', cv ? 'Out-of-fold policy results' : 'Registered configuration measurements');
      setText('result-list-description', cv ? 'Success means reference regret ≤1 kcal/mol. Intervals resample chemical families within the recorded folds.' : 'Inspect original and sequential configurations on the same development pools.');
      const pageSize = 20, maxPage = Math.max(0, Math.ceil(rows.length / pageSize) - 1);
      state.resultPage = Math.min(state.resultPage, maxPage); const page = cv ? rows : rows.slice(state.resultPage * pageSize, (state.resultPage + 1) * pageSize);
      setText('visible-result-count', integer(rows.length) + (cv ? ' roles' : ' configurations'));
      setHTML('result-cards', page.length ? page.map(row => {
        const kind = C.policyKind(row), name = cv ? LABELS[row.policy] || row.policy : LABELS[kind] || kind;
        const values = [ ['Success ≤1 kcal/mol', percent(row.success_rate), cv ? confidence(row, 'success_rate', true) : null], ['Calls / molecule', format(row.mean_calls), cv ? confidence(row, 'mean_calls') : null], ['P95 regret · kcal/mol', format(row.p95_regret_kcal, 3), cv ? confidence(row, 'p95_regret_kcal') : null], ['Full fallback', percent(row.fallback_rate), cv ? confidence(row, 'fallback_rate', true) : null] ];
        return '<article class="result-card"><div><div class="result-name"><i class="legend-dot ' + escape(kind) + '"></i><h3>' + escape(name) + '</h3></div>' + (!cv ? '<p class="mono config-id">' + escape(row.config_id) + '</p><p class="result-params">' + escape(params(row)) + '</p>' : '') + (kind === 'diagnostic' ? '<p class="diagnostic-note">No reference verification · not a paid baseline</p>' : '') + '</div><div class="result-values">' + values.map(([label, value, ci]) => '<div class="result-value"><span>' + escape(label) + '</span><strong>' + value + '</strong>' + (ci ? '<small>95% CI ' + ci + '</small>' : '') + '</div>').join('') + '</div>' + (cv && row.uncertainty_warning ? '<p class="uncertainty-note">' + escape(row.uncertainty_warning) + '</p>' : '') + '</article>';
      }).join('') : '<div class="empty-state compact">No configurations match these filters. Try a different family or risk filter.</div>');
      show('result-pagination', !cv && rows.length > pageSize);
      setText('result-page-label', 'Page ' + (state.resultPage + 1) + ' of ' + (maxPage + 1));
      $('result-previous').disabled = state.resultPage <= 0; $('result-next').disabled = state.resultPage >= maxPage;
      $('export-results').disabled = !rows.length;
      const provenance = state.results.provenance, revision = provenance.source_revision || provenance.revision || state.health?.source_revision || 'See the pinned data manifest in the repository.';
      setHTML('evidence-details', '<p><strong>Source:</strong> Folmsbee–Hutchison conformer benchmark. Revision: <code>' + escape(revision) + '</code>.</p><ul><li>Only original development molecules are available for new replay. The historical evaluation remains a previously observed result, not a new test set.</li><li>Family grouping uses generic molecular scaffolds; it is an inferred grouping rather than a supplied chemistry taxonomy.</li><li>Family-bootstrap intervals are conditional on the fixed folds and their selected policies. They do not repeat selection or account for overlapping training sets.</li><li>The 95% success and 30% call-saving targets require both risk and cost to hold. Separate marginal intervals are not a joint confidence guarantee.</li><li>The benchmark buys saved reference labels in offline replay. It does not measure live runtime, quantum compute costs, or shape-probe benefit.</li><li>Interactive replays and imported run files never modify these saved benchmark tables.</li></ul>' + (provenance.verified === false ? '<p>Server provenance reports that this result bundle is not verified. Review its server-side integrity report before relying on it.</p>' : ''));
    }
    function startupFailure(err) {
      connection(false); show('startup-panel'); $('startup-panel')?.querySelector('.loader')?.setAttribute('hidden', '');
      const heading = $('startup-panel')?.querySelector('h1'), text = $('startup-panel')?.querySelector('p');
      if (heading) heading.textContent = 'Connect to the local workbench';
      if (text) text.textContent = root.location?.protocol === 'file:' ? 'A downloaded HTML file cannot reach the local API. Open the HTTP address printed by the AQC app server.' : err.message;
      setText('startup-detail', 'Keep the Python app server running. You can still open an exported run from Saved runs.'); show('retry-startup');
    }
    async function start() {
      error(''); show('retry-startup', false);
      try {
        const [health, catalog] = await Promise.all([api.health(), api.catalog()]);
        if (!Array.isArray(catalog.molecules) || !catalog.molecules.length) throw new Error('No original development molecules are available. Check the server’s data paths.');
        state.health = health; state.catalog = catalog; state.apiReady = true; connection(true); renderMoleculeOptions();
        extras?.ready(catalog);
        await loadMolecule(catalog.default_molecule_id || catalog.molecules[0].molecule_id);
      } catch (err) { state.apiReady = false; startupFailure(err); }
      updateSavedCount();
      const requested = root.location?.hash?.replace('#', '') || 'replay'; view(requested, false);
    }
    for (const button of document.querySelectorAll('[data-view]')) button.addEventListener('click', () => view(button.dataset.view));
    listen('retry-startup', 'click', start);
    listen('global-error', 'click', async event => {
      if (!event.target.closest('[data-reconcile-session]') || !state.session || state.busy) return;
      busy(true);
      try { state.session = C.unwrapSession(await api.getSession(state.session.session_id)); state.apiReady = true; connection(true); error(''); renderSession(); }
      catch (err) { toast(err.message); }
      finally { busy(false); }
    });
    listen('molecule-search', 'input', renderMoleculeOptions);
    listen('molecule-search', 'keydown', event => { if (event.key === 'Enter') loadMolecule($('molecule-select').value); });
    listen('molecule-select', 'change', () => loadMolecule($('molecule-select').value));
    listen('policy-select', 'change', changePolicy);
    listen('conformer-select', 'change', () => selectCandidate($('conformer-select').value));
    for (const [id, delta] of [['conformer-prev', -1], ['conformer-next', 1]]) listen(id, 'click', () => {
      const candidates = sortedCandidates(), index = candidates.findIndex(row => row.candidate_id === state.candidateId);
      if (candidates.length) selectCandidate(candidates[(index + delta + candidates.length) % candidates.length].candidate_id);
    });
    listen('reset-camera', 'click', () => state.viewer?.resetView());
    listen('viewer-style', 'change', () => state.viewer?.setStyle($('viewer-style').value));
    listen('viewer-hydrogens', 'change', () => state.viewer?.setHydrogens($('viewer-hydrogens').checked));
    listen('viewer-spin', 'change', () => state.viewer?.setAutoRotate($('viewer-spin').checked));
    listen('step-query', 'click', () => state.config?.kind === 'manual' ? action('query', {candidate_id: state.candidateId}) : action('step'));
    listen('run-policy', 'click', () => action('run'));
    listen('finish-manual', 'click', () => action('finish'));
    listen('reset-session', 'click', () => action('reset'));
    listen('save-run', 'click', () => exportCurrent(true)); listen('download-trace', 'click', () => exportCurrent(false));
    listen('return-live', 'click', () => {
      state.savedMode = false; state.savedSource = null; state.policy = 'sequential';
      const id = state.catalog?.molecules.some(row => row.molecule_id === state.molecule?.molecule_id) ? state.molecule.molecule_id : state.catalog?.molecules[0]?.molecule_id;
      if (id) loadMolecule(id); else { state.molecule = null; state.session = null; show('saved-mode-banner', false); view('replay'); start(); }
    });
    listen('saved-runs', 'click', event => {
      const button = event.target.closest('button'); if (!button) return;
      if (button.hasAttribute('data-start-replay')) { view('replay'); return; }
      const rows = readSaved();
      if (button.dataset.savedOpen != null) openSaved(rows[Number(button.dataset.savedOpen)]?.run);
      if (button.dataset.savedExport != null) { const run = rows[Number(button.dataset.savedExport)]?.run; if (run) download('aqc-' + String(run.molecule.molecule_id).replace(/[^A-Za-z0-9_.-]/g, '_') + '-run.json', JSON.stringify(run, null, 2) + '\n'); }
      if (button.dataset.savedDelete != null) { try { rows.splice(Number(button.dataset.savedDelete), 1); writeSaved(rows); renderSaved(); toast('Saved copy removed from this device'); } catch (err) { error(err.message, 'saved-error'); } }
    });
    listen('import-run', 'change', async event => {
      const file = event.target.files?.[0]; if (!file) return;
      error('', 'saved-error');
      try {
        if (file.size > 12 * 1024 * 1024) throw new Error('This file is too large for a single saved run (12 MB maximum).');
        const run = C.validateSavedRun(JSON.parse(await file.text())), rows = readSaved();
        if (rows.length >= MAX_SAVED) throw new Error('Remove a saved run before importing another (12 runs maximum).');
        rows.unshift({key: 'import:' + Date.now(), run}); writeSaved(rows); renderSaved(); openSaved(run); toast('Imported read-only run');
      } catch (err) { error('Could not import the run: ' + err.message, 'saved-error'); }
      event.target.value = '';
    });
    for (const name of ['cv', 'registry']) listen('scope-' + name, 'click', () => { state.resultScope = name; state.resultPage = 0; renderResults(); });
    for (const id of ['configuration-search', 'configuration-kind', 'configuration-risk', 'configuration-sort']) listen(id, id.endsWith('search') ? 'input' : 'change', () => { state.resultPage = 0; renderResults(); });
    listen('result-previous', 'click', () => { state.resultPage--; renderResults(); });
    listen('result-next', 'click', () => { state.resultPage++; renderResults(); });
    listen('export-results', 'click', () => download('aqc-' + (state.resultScope === 'cv' ? 'development-cv' : 'development-configurations') + '.csv', C.csv(resultRows(), ['config_id', 'policy', 'kind', 'analysis_scope', 'n_molecules', 'n_families', 'success_rate', 'success_rate_ci_low', 'success_rate_ci_high', 'mean_calls', 'mean_calls_ci_low', 'mean_calls_ci_high', 'p95_regret_kcal', 'fallback_rate', 'total_calls']), 'text/csv;charset=utf-8'));
    let resizeTimer = null;
    root.addEventListener?.('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        if (state.view === 'results' && state.results) setHTML('risk-plot', renderPlot(resultRows(), state.resultScope, $('risk-plot').clientWidth));
      }, 120);
    });
    updateSavedCount(); document.body.dataset.view = 'replay';
    return Object.freeze({start, view, action, loadMolecule, changePolicy, openSaved, renderResults,
      state: () => ({...state, viewer: state.viewer?.getState() || null}), selectCandidate,
      extras: extras || null});
  }
  const exported = {createApp, resolveConfig, reasonText, renderPlot, escape, format, percent, confidence};
  if (typeof module !== 'undefined' && module.exports) module.exports = exported;
  if (typeof document !== 'undefined') {
    root.AQCWorkbench = exported;
    const initialize = () => {
      try { const app = createApp(document); root.AQCWorkbench.app = app; app.start(); }
      catch (err) { const node = document.getElementById('global-error'); if (node) { node.textContent = 'The workbench could not initialize: ' + err.message; node.hidden = false; } }
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize); else initialize();
  }
})(typeof window !== 'undefined' ? window : globalThis);
