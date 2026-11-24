/* Comparison and retrospective diagnostics. No acquisition logic or hidden labels. */
(function (root) {
  'use strict';
  const C = root.AQCClient || (typeof require === 'function' ? require('./client.js') : null);
  const escape = value => String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[ch]));
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const format = (value, digits = 2) => finite(value) ? (Math.abs(value) < .5 * 10 ** -digits ? 0 : value).toLocaleString('en-US', {minimumFractionDigits: digits, maximumFractionDigits: digits}) : '—';
  const signed = (value, digits = 2) => finite(value) ? (value > 1e-8 ? '+' : '') + format(Math.abs(value) < 1e-8 ? 0 : value, digits) : '—';
  const LABELS = {fixed: 'Fixed top-2', fixed_top_k: 'Fixed top-2', matched_simple: 'Matched simple', sequential: 'Sequential', full: 'Full rerank', full_rerank: 'Full rerank'};
  const COLORS = {fixed: '#488fb9', matched_simple: '#9872c2', sequential: '#39a47f', full: '#8c9ca8'};
  const SUCCESS_TOLERANCE = 1e-9, EQUAL_REGRET_TOLERANCE = 1e-8;
  function pairRows(rows, comparator = 'matched_simple') {
    const molecules = new Map();
    for (const row of rows || []) {
      if (!molecules.has(row.molecule_id)) molecules.set(row.molecule_id, {});
      molecules.get(row.molecule_id)[row.policy] = row;
    }
    return [...molecules.entries()].flatMap(([molecule_id, roles]) => {
      const sequential = roles.sequential, baseline = roles[comparator];
      if (!sequential || !baseline) return [];
      const calls_delta = sequential.expensive_calls - baseline.expensive_calls;
      const regret_delta = sequential.regret_kcal - baseline.regret_kcal;
      const success = sequential.regret_kcal <= 1 + SUCCESS_TOLERANCE;
      const baselineSuccess = baseline.regret_kcal <= 1 + SUCCESS_TOLERANCE;
      return [{molecule_id, family_id: sequential.family_id, fold_id: sequential.fold_id,
        n_candidates: sequential.n_candidates, sequential, baseline, calls_delta, regret_delta,
        rescue: success && !baselineSuccess,
        waste: calls_delta > 0 && Math.abs(regret_delta) <= EQUAL_REGRET_TOLERANCE,
        early_stop: calls_delta < 0 && !success && baselineSuccess,
        shared_failure: !success && !baselineSuccess, fewer_calls: calls_delta < 0,
        worse_regret: regret_delta > EQUAL_REGRET_TOLERANCE}];
    });
  }
  function filterPairs(rows, filters = {}) {
    const query = String(filters.search || '').toLowerCase().trim();
    return rows.filter(row => (!query || row.molecule_id.toLowerCase().includes(query)) &&
      (!filters.family || filters.family === 'all' || row.family_id === filters.family) &&
      (!filters.behavior || filters.behavior === 'all' || row[filters.behavior] === true))
      .sort((a, b) => {
        const order = filters.sort === 'molecule' ? 0 : filters.sort === 'calls_delta' ? b.calls_delta - a.calls_delta :
          filters.sort === 'regret_delta' ? b.regret_delta - a.regret_delta : b.sequential.regret_kcal - a.sequential.regret_kcal;
        return order || (a.molecule_id < b.molecule_id ? -1 : a.molecule_id > b.molecule_id ? 1 : 0);
      });
  }
  function behaviorLabels(row) {
    const flags = [['rescue', 'Success rescued'], ['waste', 'Extra calls · same regret'], ['early_stop', 'Early stop lost success'], ['shared_failure', 'Both outside target']];
    return flags.filter(([key]) => row[key]).map(([, label]) => label);
  }
  function observedProgress(session, width = 500) {
    const queries = session?.queries || [], points = [];
    let first = null, best = Infinity, calls = 0;
    for (const query of queries) {
      calls += Number(query.charged || 0);
      if (finite(query.reference_kcal)) {
        if (first === null) first = query.reference_kcal;
        best = Math.min(best, query.reference_kcal);
        points.push({calls, value: best - first});
      }
    }
    if (!points.length) return '<div class="observed-empty"><span class="empty-orbit" aria-hidden="true">○</span><strong>No reference revealed in this lane.</strong><p>Query a conformer to begin the observed-energy trail.</p></div>';
    width = Math.max(260, Math.min(900, width || 500));
    const height = 195, left = 48, right = 18, top = 24, bottom = 39;
    const low = Math.min(-.2, ...points.map(point => point.value)) * 1.1, span = height - top - bottom;
    const x = value => left + (value - 1) / Math.max(1, calls - 1) * (width - left - right);
    const y = value => top + value / low * span;
    let svg = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Best verified energy change relative to this lane's first paid observation"><title>Observed energy improvement; no unqueried references</title>`;
    for (let i = 0; i <= 2; i++) {
      const value = low * i / 2;
      svg += `<line x1="${left}" y1="${y(value)}" x2="${width - right}" y2="${y(value)}" stroke="#e1e9e3"/><text x="${left - 9}" y="${y(value) + 4}" text-anchor="end">${format(value, 1)}</text>`;
    }
    svg += `<path d="${points.map((point, i) => (i ? 'L' : 'M') + x(point.calls) + ',' + y(point.value)).join(' ')}" fill="none" stroke="#238567" stroke-width="2.5"/>`;
    for (const point of points) svg += `<circle cx="${x(point.calls)}" cy="${y(point.value)}" r="4.5" fill="#238567" stroke="white" stroke-width="2"><title>After ${point.calls} calls: ${format(point.value, 4)} kcal/mol from first observation</title></circle>`;
    svg += `<text x="${left}" y="${height - 15}">1 call</text><text x="${width - right}" y="${height - 15}" text-anchor="end">${calls} charged ${calls === 1 ? 'call' : 'calls'}</text><text x="${left}" y="14">Δ best observed · kcal/mol</text></svg>`;
    return svg;
  }
  function pairedPlot(rows, selected, width = 600) {
    if (!rows.length) return '<div class="empty-state compact">No paired outcomes match these filters.</div>';
    width = Math.max(260, Math.min(1100, width || 600));
    const height = 280, left = 48, right = 19, top = 24, bottom = 49;
    const minX = Math.min(-1, ...rows.map(row => row.calls_delta)), maxX = Math.max(1, ...rows.map(row => row.calls_delta));
    const lowX = minX - .4, highX = maxX + .4;
    const minY = Math.min(-.5, ...rows.map(row => row.regret_delta)) * 1.15, maxY = Math.max(.5, ...rows.map(row => row.regret_delta)) * 1.15;
    const x = value => left + (value - lowX) / (highX - lowX) * (width - left - right);
    const y = value => top + (maxY - value) / (maxY - minY) * (height - top - bottom);
    let svg = `<svg viewBox="0 0 ${width} ${height}" role="group" aria-label="Paired call and regret differences, sequential minus selected comparator"><title>Negative differences favor sequential acquisition</title>`;
    for (let i = 0; i <= 4; i++) {
      const value = minY + (maxY - minY) * i / 4;
      svg += `<line x1="${left}" y1="${y(value)}" x2="${width - right}" y2="${y(value)}" stroke="#e8ede8"/><text x="${left - 8}" y="${y(value) + 4}" text-anchor="end">${format(value, 1)}</text>`;
    }
    svg += `<line x1="${x(0)}" y1="${top}" x2="${x(0)}" y2="${height - bottom}" stroke="#a4b5b1" stroke-dasharray="4 4"/><line x1="${left}" y1="${y(0)}" x2="${width - right}" y2="${y(0)}" stroke="#a4b5b1" stroke-dasharray="4 4"/>`;
    for (const value of [...new Set([minX, 0, maxX])]) svg += `<text x="${x(value)}" y="${height - bottom + 21}" text-anchor="middle">${signed(value, 0)}</text>`;
    for (const row of rows.slice().sort((a, b) => Number(a.molecule_id === selected) - Number(b.molecule_id === selected))) {
      const isSelected = row.molecule_id === selected, color = row.regret_delta > EQUAL_REGRET_TOLERANCE ? '#bc6350' : row.regret_delta < -EQUAL_REGRET_TOLERANCE ? '#238567' : '#7996a4';
      svg += `<circle class="diagnostic-point" data-diagnostic-inspect="${escape(row.molecule_id)}" cx="${x(row.calls_delta)}" cy="${y(row.regret_delta)}" r="${isSelected ? 7 : 4.6}" fill="${color}" fill-opacity="${isSelected ? 1 : .55}" stroke="${isSelected ? '#172c30' : 'white'}" stroke-width="${isSelected ? 2 : 1}" tabindex="0" role="button" aria-label="Inspect ${escape(row.molecule_id)}: ${signed(row.calls_delta, 0)} calls, ${signed(row.regret_delta, 3)} kcal per mole"><title>${escape(row.molecule_id)} · ${signed(row.calls_delta, 0)} calls · ${signed(row.regret_delta, 3)} kcal/mol</title></circle>`;
    }
    return svg + `<text x="${left}" y="14">Δ regret · kcal/mol</text><text x="${(width + left - right) / 2}" y="${height - 5}" text-anchor="middle">Δ charged calls</text></svg>`;
  }
  function create(document, options = {}) {
    const $ = id => document.getElementById(id), api = options.api || C.createClient();
    const text = (id, value) => { if ($(id)) $(id).textContent = value == null ? '' : String(value); };
    const html = (id, value) => { if ($(id)) $(id).innerHTML = value; };
    const show = (id, visible = true) => { if ($(id)) $(id).hidden = !visible; };
    const disable = (id, value) => { if ($(id)) $(id).disabled = !!value; };
    const listen = (id, type, handler) => $(id)?.addEventListener(type, handler);
    const reason = value => root.AQCWorkbench?.reasonText(value) || String(value || '').replace(/_/g, ' ');
    const ui = {catalog: null, diagnostics: null, diagnosticsPromise: null, comparison: null,
      fetching: false, opening: false, view: 'replay', selectedLane: 'sequential', candidateId: null,
      viewer: null, geometryKey: null, page: 0, selectedMolecule: null, diagramWidth: null, awaitingFreshStart: false};
    let controller = null;
    if (root.AQCComparison) controller = root.AQCComparison.createComparison({api, onChange: next => { ui.comparison = next; renderComparison(); }});
    const snapshot = () => ui.comparison || controller?.snapshot() || {lanes: [], archived_runs: [], charged_calls: 0, cumulative_charged_calls: 0, completed_lanes: 0};
    const reportError = error => { text('comparison-error', error?.message || error); show('comparison-error', true); };
    async function guard(action) {
      show('comparison-error', false);
      try { await action(); } catch (error) { reportError(error); }
    }
    function download(name, content, type = 'application/json') {
      if (options.download) options.download(name, content, type);
    }
    function setMoleculeOptions() {
      const query = ($('cmp-search')?.value || '').trim().toLowerCase();
      const previous = $('cmp-molecule')?.value, current = snapshot().molecule?.molecule_id;
      const rows = (ui.catalog?.molecules || []).filter(row => (row.molecule_id + ' ' + row.family_id).toLowerCase().includes(query));
      html('cmp-molecule', rows.length ? rows.map(row => `<option value="${escape(row.molecule_id)}">${escape(row.molecule_id)} · ${row.n_candidates} conformers</option>`).join('') : '<option value="">No matching molecules</option>');
      if (rows.some(row => row.molecule_id === previous)) $('cmp-molecule').value = previous;
      else if (rows.some(row => row.molecule_id === current)) $('cmp-molecule').value = current;
      renderControlState();
    }
    function renderControlState() {
      const state = snapshot(), blocked = ui.fetching || state.busy || state.lanes.some(lane => lane.uncertain), active = state.lanes.some(lane => lane.session && !lane.session.stopped && !lane.uncertain);
      disable('cmp-load', blocked || !$('cmp-molecule')?.value || !controller);
      disable('cmp-molecule', blocked || !ui.catalog); disable('cmp-search', blocked || !ui.catalog);
      disable('cmp-step', blocked || !active); disable('cmp-run', blocked || !active);
      const hasReport = !!state.molecule || !!state.archived_runs?.length;
      disable('cmp-json', state.busy || !hasReport); disable('cmp-csv', state.busy || !hasReport);
      disable('cmp-archive-unavailable', ui.fetching || !state.can_archive_unavailable);
      for (const button of $('comparison-cases')?.querySelectorAll('button') || []) button.disabled = blocked || !controller;
      for (const button of $('comparison-lanes')?.querySelectorAll('[data-lane-action]') || []) {
        const lane = state.lanes.find(item => item.role === button.dataset.lane);
        button.disabled = blocked || !lane?.session || lane.session.stopped;
      }
      for (const button of $('comparison-lanes')?.querySelectorAll('[data-reconcile-lane]') || []) button.disabled = ui.fetching || state.busy;
    }
    function renderCases() {
      const cases = ui.diagnostics?.cases || [];
      html('comparison-cases', cases.length ? cases.map((item, i) => `<button class="case-card" data-comparison-case="${escape(item.molecule_id)}"><span class="case-number">0${i + 1}</span><strong>${escape(item.title)}</strong><span class="case-molecule mono">${escape(item.molecule_id)}</span><span class="case-description">${escape(item.description)}</span><span class="case-open">Open comparison <span aria-hidden="true">↗</span></span></button>`).join('') : '<p class="muted">Measured cases are unavailable. You can still compare any development molecule.</p>');
      renderControlState();
    }
    async function loadMolecule(id) {
      if (!controller) throw new Error('The comparison script did not load. Keep the local server running and reload the page.');
      if (!id) return;
      if (ui.fetching || snapshot().busy || snapshot().lanes.some(lane => lane.uncertain)) throw new Error('Finish or reconcile the current request before changing the comparison.');
      ui.fetching = true; renderControlState();
      try {
        const response = await api.molecule(id), molecule = response.molecule || response;
        if (molecule.references || molecule.candidates?.some(row => Object.prototype.hasOwnProperty.call(row, 'reference_kcal'))) throw new Error('Unexpected hidden labels in the molecule API. Comparison was blocked.');
        C.cleanMolecule(molecule);
        await controller.load(molecule);
        ui.awaitingFreshStart = false;
        ui.candidateId = null; ui.geometryKey = null; ui.selectedLane = 'sequential';
        renderComparison();
      } finally { ui.fetching = false; renderControlState(); }
    }
    async function openComparison(id) {
      ui.opening = true;
      try {
        if ($('cmp-search')) $('cmp-search').value = '';
        setMoleculeOptions(); if ($('cmp-molecule')) $('cmp-molecule').value = id;
        options.navigate?.('compare');
        await loadMolecule(id);
        $('compare-title')?.scrollIntoView?.({behavior: 'smooth', block: 'start'});
      } finally { ui.opening = false; }
    }
    function renderComparison() {
      const state = snapshot(), molecule = state.molecule;
      const uncertain = state.lanes.some(lane => lane.uncertain);
      const unavailable = state.unavailable_lane_count || state.lanes.filter(lane => lane.unavailable).length;
      const incomplete = state.cumulative_accounting_complete === false || uncertain;
      text('cmp-calls', state.charged_calls || 0); text('cmp-finished', `${state.completed_lanes || 0} / ${state.lanes.length || 4}`);
      text('cmp-call-label', uncertain ? 'last confirmed calls · reconciliation needed' : 'calls across these lanes');
      const warning = unavailable ? 'The local server reports an expired or unavailable session, for example after idle expiry or a server restart. Its last confirmed charges are retained; the total may be incomplete. No query will be automatically repeated.' : uncertain ? 'A request may have charged a reference before the response was lost. Counts show the last confirmed state. Reconcile the affected lane before continuing; no query will be automatically repeated.' : incomplete ? 'An archived comparison has unavailable accounting. Its last confirmed charges remain in the cumulative total, which is a lower bound. New comparison counts do not resolve the missing history.' : state.warning;
      text('comparison-warning', warning || ''); show('comparison-warning', !!warning);
      show('comparison-recovery', unavailable > 0);
      text('cmp-recovery-detail', state.can_archive_unavailable ? 'Archive the entire current comparison with its last confirmed counts. This preserves the incomplete record and releases the remaining local sessions so you can explicitly start fresh.' : 'Archiving remains blocked while another request is in progress, a network outcome still needs reconciliation, or the retained-history limit is reached. Export the recorded history before leaving this page.');
      if (molecule) {
        text('cmp-current', molecule.molecule_id);
        text('cmp-pool-detail', `${molecule.candidates.length} identical candidates · ${state.lanes.length} independent sessions · development fold ${molecule.fold_id + 1}`);
        text('cmp-current', molecule.molecule_id);
      } else {
        text('cmp-current', 'Choose a molecule');
        text('cmp-pool-detail', 'Start a fresh comparison when ready. Retained history remains exportable.');
      }
      const archived = state.archived_runs?.length || 0;
      show('cmp-archive-note', archived > 0);
      text('cmp-archive-note', `${archived} earlier comparison${archived === 1 ? '' : 's'} retained in this page session. ${state.cumulative_charged_calls || 0} ${incomplete ? 'last confirmed cumulative' : 'cumulative'} charged calls including the current lanes.${incomplete ? ' This is a lower bound because an uncertain or unavailable record may contain additional charges.' : ''} JSON and CSV exports include the retained comparisons. Switching workbench views keeps this history; leaving this page or reloading clears it.`);
      if (state.lanes.length) html('comparison-lanes', state.lanes.map(lane => {
        const session = lane.session, completed = session?.status === 'completed', failed = session?.status === 'failed';
        const status = lane.unavailable ? 'Session unavailable' : lane.uncertain ? 'Needs reconciliation' : lane.busy ? 'Query in progress' : completed ? 'Stopped' : failed ? 'Failed · ledger retained' : session?.expensive_calls ? 'Active' : 'Ready · labels hidden';
        const evaluation = session?.stopped ? session.evaluation : null;
        const candidates = molecule?.candidates || [], observed = session?.observations || {};
        const chips = candidates.map((candidate, index) => {
          const paid = Object.prototype.hasOwnProperty.call(observed, candidate.candidate_id), pending = session?.pending_candidate === candidate.candidate_id;
          return `<button class="candidate-chip ${paid ? 'queried' : pending ? 'pending' : ''}" data-inspect-lane="${escape(lane.role)}" data-inspect-candidate="${escape(candidate.candidate_id)}" aria-label="Inspect ${escape(candidate.candidate_id)} in ${escape(lane.label)}: ${paid ? 'reference queried' : 'reference hidden'}" title="${escape(candidate.candidate_id)} · ${paid ? 'queried in this lane' : 'hidden in this lane'}">${index + 1}</button>`;
        }).join('');
        return `<article class="comparison-lane ${ui.selectedLane === lane.role ? 'selected' : ''} ${failed || lane.uncertain ? 'has-error' : ''}" data-policy-lane="${escape(lane.role)}"><div class="lane-accent ${escape(lane.role)}"></div><div class="lane-heading"><h2><button class="lane-select" data-select-lane="${escape(lane.role)}" aria-pressed="${ui.selectedLane === lane.role}"><span class="lane-dot ${escape(lane.role)}"></span><span>${escape(lane.label || LABELS[lane.role] || lane.role)}</span></button></h2><span class="lane-state ${completed ? 'stopped' : ''}">${escape(status)}</span></div><div class="lane-main-metrics"><div><strong>${session?.expensive_calls || 0}<small> / ${candidates.length}</small></strong><span>${lane.uncertain ? 'last confirmed calls' : 'charged calls'}</span></div><div class="lane-regret ${evaluation && !evaluation.success_within_1_kcal ? 'outside-target' : ''}"><strong>${evaluation ? format(evaluation.regret_kcal, 3) : '—'}</strong><span>${evaluation ? 'regret · kcal/mol' : 'regret after stop'}</span></div></div><div class="lane-best"><span>Best verified in this lane</span><strong>${escape(session?.best_verified || 'None queried')}</strong></div><div class="candidate-chip-row" aria-label="Candidates in cheap-energy order">${chips}</div><p class="lane-next">${escape(reason(session?.stopped ? session.stop_reason : session?.pending_reason) || 'Waiting for a session.')}</p>${lane.error ? `<p class="lane-error" role="alert">${escape(lane.error.message || lane.error)}</p>` : ''}${lane.uncertain ? `<button class="button secondary" data-reconcile-lane="${escape(lane.role)}">Reconcile ${escape(lane.label)}</button>` : `<div class="lane-actions"><button class="button secondary" data-lane="${escape(lane.role)}" data-lane-action="step">Next query</button><button class="text-button" data-lane="${escape(lane.role)}" data-lane-action="run">Run to stop</button></div>`}${evaluation ? `<p class="lane-outcome ${evaluation.success_within_1_kcal ? 'within' : 'outside'}">${evaluation.success_within_1_kcal ? 'Within 1 kcal/mol' : 'Outside 1 kcal/mol'}${session.fallback ? ' · full-rerank fallback' : ''}</p>` : ''}</article>`;
      }).join(''));
      else html('comparison-lanes', '<div class="panel empty-state">Start a fresh comparison to create independent replay sessions. Earlier confirmed charges remain in retained history.</div>');
      show('comparison-inspector', !!molecule);
      if (molecule) {
        if (!state.lanes.some(lane => lane.role === ui.selectedLane)) ui.selectedLane = state.lanes[0]?.role;
        html('cmp-lane-select', state.lanes.map(lane => `<option value="${escape(lane.role)}">${escape(lane.label)}</option>`).join(''));
        $('cmp-lane-select').value = ui.selectedLane;
        renderInspector();
      }
      renderControlState();
    }
    function renderInspector() {
      const state = snapshot(), molecule = state.molecule, lane = state.lanes.find(item => item.role === ui.selectedLane);
      if (!molecule || !lane) return;
      const session = lane.session, observations = session?.observations || {};
      if (!molecule.candidates.some(row => row.candidate_id === ui.candidateId)) ui.candidateId = molecule.candidates[0]?.candidate_id;
      const candidate = molecule.candidates.find(row => row.candidate_id === ui.candidateId), cheapMin = Math.min(...molecule.candidates.map(row => row.cheap_kcal));
      html('cmp-conformer-select', molecule.candidates.map((row, index) => `<option value="${escape(row.candidate_id)}">${index + 1}. ${escape(row.candidate_id)}${Object.prototype.hasOwnProperty.call(observations, row.candidate_id) ? ' · queried' : ''}</option>`).join(''));
      $('cmp-conformer-select').value = ui.candidateId;
      text('cmp-geometry-title', candidate.candidate_id);
      html('cmp-cheap', format(candidate.cheap_kcal - cheapMin, 3) + ' <small>kcal/mol</small>');
      text('cmp-reference-label', lane.label + ' · paid reference');
      html('cmp-reference', Object.prototype.hasOwnProperty.call(observations, candidate.candidate_id) ? `<span class="revealed">${format(observations[candidate.candidate_id], 4)} <small>kcal/mol</small></span>` : 'Hidden until this lane queries');
      const key = molecule.molecule_id + ':' + candidate.candidate_id;
      if (ui.geometryKey !== key && ui.view === 'compare') {
        try {
          if (!root.AQCMoleculeViewer) throw new Error('The local 3D viewer asset is unavailable.');
          if (!ui.viewer) ui.viewer = root.AQCMoleculeViewer.create($('cmp-viewport'), {background: '#0b1d28', onStateChange: state => {
            text('cmp-renderer', state.renderer === 'webgl' ? 'WebGL · 3D' : 'Canvas · projected 3D');
            if ($('cmp-hydrogens')) $('cmp-hydrogens').checked = state.hydrogens;
            if ($('cmp-spin')) $('cmp-spin').checked = state.autoRotate;
            if ($('cmp-style')) $('cmp-style').value = state.style;
          }});
          ui.viewer.setGeometry(candidate, {molecule_id: molecule.molecule_id, candidate_id: candidate.candidate_id, label: molecule.molecule_id + ' / ' + candidate.candidate_id});
          ui.viewer.resize(); ui.geometryKey = key; show('cmp-geometry-message', false);
        } catch (error) { text('cmp-geometry-message', 'Geometry display unavailable: ' + error.message); show('cmp-geometry-message'); }
      }
      text('cmp-coordinate-detail', `Geometry SHA-256: ${candidate.geometry_sha256 || 'not supplied'}\nXYZ SHA-256: ${candidate.xyz_sha256 || 'not supplied'}\nCoordinates: Å · identical fixed pool in every lane`);
      text('cmp-trace-title', (lane.label || LABELS[lane.role]) + ' decision trail');
      text('cmp-trace-count', `${session?.expensive_calls || 0} paid calls`);
      html('cmp-progress', observedProgress(session, $('cmp-progress')?.clientWidth));
      html('cmp-history', session?.queries?.length ? session.queries.map((query, index) => `<li><span class="query-order">${index + 1}</span><button class="trace-candidate" data-trace-candidate="${escape(query.candidate_id)}"><strong>${escape(query.candidate_id)}</strong><span>${query.charged ? '+1 charged call' : 'No new charge'} · ${escape(query.status || (finite(query.reference_kcal) ? 'succeeded' : 'failed'))}</span></button><span class="trace-energy">${finite(query.reference_kcal) ? format(query.reference_kcal, 4) : 'Unavailable'}<small>${finite(query.reference_kcal) ? 'kcal/mol revealed' : 'failure retained'}</small></span></li>`).join('') : '<li class="empty-state compact">No queries in this lane. Another lane’s observations stay out of this view.</li>');
      text('cmp-config', JSON.stringify(lane.config, null, 2));
      text('cmp-stop-detail', session?.stopped ? reason(session.stop_reason) : 'Policy still active. The evaluator scores the final verified selection only after this lane stops.');
    }
    function chooseLane(role, candidateId) {
      ui.selectedLane = role;
      if (candidateId) ui.candidateId = candidateId;
      renderComparison();
    }
    async function loadDiagnostics() {
      if (ui.diagnostics) return ui.diagnostics;
      if (ui.diagnosticsPromise) return ui.diagnosticsPromise;
      show('diagnostics-loading'); show('diagnostics-error', false); show('diag-retry', false);
      ui.diagnosticsPromise = (async () => {
        try {
          const result = await api.request('/api/diagnostics');
          if (result.scope !== 'development_family_cv_retrospective' || result.fresh_external_holdout !== false || !Array.isArray(result.rows)) throw new Error('The diagnostics API returned an unexpected evidence scope.');
          ui.diagnostics = result;
          const families = [...new Set(result.rows.map(row => row.family_id))].sort();
          html('diag-family', '<option value="all">All chemical families</option>' + families.map(family => `<option value="${escape(family)}">${escape(family)}</option>`).join(''));
          text('diag-provenance', `Source revision: ${result.provenance?.source_revision || 'See the pinned manifest'}\nEvidence seal: ${result.provenance?.evidence_seal_sha256 || 'Verified by the local server'}`);
          show('diagnostics-content'); renderDiagnostics(); renderCases();
          return result;
        } catch (error) {
          text('diagnostics-error', error.message); show('diagnostics-error'); show('diag-retry');
          html('comparison-cases', '<p class="muted">The measured case list could not be loaded. Compare any molecule above, or retry from Failure explorer.</p>');
          return null;
        } finally { show('diagnostics-loading', false); ui.diagnosticsPromise = null; }
      })();
      return ui.diagnosticsPromise;
    }
    function comparator() { return $('diag-comparator')?.value || 'matched_simple'; }
    function filteredPairs() {
      return filterPairs(pairRows(ui.diagnostics?.rows, comparator()), {search: $('diag-search')?.value,
        family: $('diag-family')?.value, behavior: $('diag-behavior')?.value, sort: $('diag-sort')?.value});
    }
    function renderDiagnostics() {
      if (!ui.diagnostics) return;
      const rows = filteredPairs(), families = new Set(rows.map(row => row.family_id)), all = pairRows(ui.diagnostics.rows, comparator());
      const successes = rows.filter(row => row.sequential.regret_kcal <= 1 + SUCCESS_TOLERANCE).length;
      const rescues = rows.filter(row => row.rescue).length, losses = rows.filter(row => !row.sequential.success_1kcal && row.baseline.success_1kcal).length;
      html('diagnostic-summary', `<div><strong>${rows.length}<small> / ${all.length}</small></strong><span>molecules in this filter</span></div><div><strong>${families.size}</strong><span>chemical families represented</span></div><div><strong>${successes}<small> / ${rows.length}</small></strong><span>sequential within 1 kcal/mol</span></div><div><strong>${rescues}<small> rescued · ${losses} lost</small></strong><span>success changes vs ${escape(LABELS[comparator()])}</span></div>`);
      text('diag-plot-count', rows.length + ' paired molecules');
      if (!rows.some(row => row.molecule_id === ui.selectedMolecule)) ui.selectedMolecule = rows[0]?.molecule_id || null;
      html('diagnostic-plot', pairedPlot(rows, ui.selectedMolecule, $('diagnostic-plot')?.clientWidth));
      renderDiagnosticDetail(rows.find(row => row.molecule_id === ui.selectedMolecule));
      const pages = Math.max(1, Math.ceil(rows.length / 12)); ui.page = Math.max(0, Math.min(ui.page, pages - 1));
      const visible = rows.slice(ui.page * 12, (ui.page + 1) * 12);
      text('diag-table-description', `Sequential versus ${LABELS[comparator()]}. Differences use sequential minus comparator.`);
      text('diag-visible-count', `${visible.length} shown · ${rows.length} match`);
      html('diagnostic-rows', visible.length ? visible.map(row => `<button class="diagnostic-row ${ui.selectedMolecule === row.molecule_id ? 'selected' : ''}" data-diagnostic-inspect="${escape(row.molecule_id)}" aria-pressed="${ui.selectedMolecule === row.molecule_id}"><span class="diagnostic-identity"><strong>${escape(row.molecule_id)}</strong><small>Fold ${row.fold_id + 1} · ${row.n_candidates} conformers${behaviorLabels(row).length ? ' · ' + escape(behaviorLabels(row).join(' / ')) : ''}</small></span><span class="diagnostic-value"><span>Seq. / comparator calls</span><strong>${row.sequential.expensive_calls} / ${row.baseline.expensive_calls}</strong></span><span class="diagnostic-value"><span>Δ calls</span><strong class="${row.calls_delta > 0 ? 'difference-bad' : row.calls_delta < 0 ? 'difference-good' : ''}">${signed(row.calls_delta, 0)}</strong></span><span class="diagnostic-value"><span>Seq. regret · kcal/mol</span><strong class="${row.sequential.regret_kcal > 1 + SUCCESS_TOLERANCE ? 'difference-bad' : ''}">${format(row.sequential.regret_kcal, 3)}</strong></span><span class="diagnostic-value"><span>Δ regret · kcal/mol</span><strong class="${row.regret_delta > EQUAL_REGRET_TOLERANCE ? 'difference-bad' : row.regret_delta < -EQUAL_REGRET_TOLERANCE ? 'difference-good' : ''}">${signed(row.regret_delta, 3)}</strong></span></button>`).join('') : '<div class="empty-state"><h3>No molecules match these filters.</h3><p>Clear a filter to return to the full measured development pool.</p></div>');
      text('diag-page', `Page ${ui.page + 1} of ${pages}`); disable('diag-prev', ui.page === 0); disable('diag-next', ui.page >= pages - 1); disable('diag-export', !rows.length);
    }
    function renderDiagnosticDetail(row) {
      if (!row) { html('diagnostic-detail', '<div class="empty-state"><h2>No case selected</h2><p>Choose a molecule after changing the filters.</p></div>'); return; }
      const labels = behaviorLabels(row);
      html('diagnostic-detail', `<p class="eyebrow">MOLECULE UNDER THE MICROSCOPE</p><h2>${escape(row.molecule_id)}</h2><p class="diagnostic-family mono">${escape(row.family_id)}</p><p class="small muted">Development fold ${row.fold_id + 1} · ${row.n_candidates} conformers</p>${labels.length ? `<div class="behavior-tags">${labels.map(label => `<span>${escape(label)}</span>`).join('')}</div>` : '<p class="small muted">A paired measured outcome from the selected filter.</p>'}<dl class="diagnostic-metrics"><div><dt>Sequential</dt><dd>${row.sequential.expensive_calls} calls · ${format(row.sequential.regret_kcal, 3)} kcal/mol regret</dd></div><div><dt>${escape(LABELS[comparator()])}</dt><dd>${row.baseline.expensive_calls} calls · ${format(row.baseline.regret_kcal, 3)} kcal/mol regret</dd></div><div><dt>Difference</dt><dd>${signed(row.calls_delta, 0)} calls · ${signed(row.regret_delta, 3)} kcal/mol</dd></div></dl><div class="diagnostic-stop"><span>Sequential stop</span><p>${escape(reason(row.sequential.stop_reason))}</p></div><button class="button primary" data-open-comparison="${escape(row.molecule_id)}">Replay these policies</button><p class="chart-note">Creates fresh, independently charged replay sessions. The recorded outcome above is retrospective evidence.</p>`);
    }
    function inspectDiagnostic(id) { ui.selectedMolecule = id; renderDiagnostics(); }
    function exportDiagnostics() {
      const rows = filteredPairs().map(row => ({molecule_id: row.molecule_id, family_id: row.family_id, fold_id: row.fold_id,
        n_candidates: row.n_candidates, comparator: comparator(), sequential_config_id: row.sequential.config_id,
        comparator_config_id: row.baseline.config_id, sequential_calls: row.sequential.expensive_calls,
        comparator_calls: row.baseline.expensive_calls, calls_delta: row.calls_delta,
        sequential_regret_kcal: row.sequential.regret_kcal, comparator_regret_kcal: row.baseline.regret_kcal,
        regret_delta_kcal: row.regret_delta, sequential_success_1kcal: row.sequential.success_1kcal,
        comparator_success_1kcal: row.baseline.success_1kcal, sequential_stop_reason: row.sequential.stop_reason,
        comparator_stop_reason: row.baseline.stop_reason, scope: 'development_family_cv_retrospective', fresh_external_holdout: false}));
      if (rows.length) download('aqc-retrospective-paired-' + comparator() + '.csv', C.csv(rows, Object.keys(rows[0])), 'text/csv;charset=utf-8');
    }
    listen('cmp-search', 'input', setMoleculeOptions);
    listen('cmp-search', 'keydown', event => { if (event.key === 'Enter') guard(() => loadMolecule($('cmp-molecule').value)); });
    listen('cmp-load', 'click', () => guard(() => loadMolecule($('cmp-molecule').value)));
    listen('cmp-step', 'click', () => guard(() => controller.stepAll()));
    listen('cmp-run', 'click', () => guard(() => controller.runAll()));
    listen('cmp-archive-unavailable', 'click', () => guard(async () => {
      if (!snapshot().can_archive_unavailable) throw new Error('This comparison cannot be archived until its unavailable-session status is confirmed.');
      ui.awaitingFreshStart = true;
      await controller.archiveUnavailable();
      ui.candidateId = null; ui.geometryKey = null; ui.viewer?.setAutoRotate(false);
      renderComparison();
    }));
    listen('comparison-cases', 'click', event => { const button = event.target.closest('[data-comparison-case]'); if (button) guard(() => openComparison(button.dataset.comparisonCase)); });
    listen('comparison-lanes', 'click', event => {
      const button = event.target.closest('button'); if (!button) return;
      if (button.dataset.selectLane) chooseLane(button.dataset.selectLane);
      if (button.dataset.inspectLane) chooseLane(button.dataset.inspectLane, button.dataset.inspectCandidate);
      if (button.dataset.laneAction) guard(() => controller.actionLane(button.dataset.lane, button.dataset.laneAction));
      if (button.dataset.reconcileLane) guard(() => controller.reconcile(button.dataset.reconcileLane));
    });
    listen('cmp-lane-select', 'change', () => chooseLane($('cmp-lane-select').value));
    listen('cmp-conformer-select', 'change', () => { ui.candidateId = $('cmp-conformer-select').value; renderInspector(); });
    listen('cmp-history', 'click', event => { const target = event.target.closest('[data-trace-candidate]'); if (target) { ui.candidateId = target.dataset.traceCandidate; renderInspector(); } });
    listen('cmp-reset-camera', 'click', () => ui.viewer?.resetView());
    listen('cmp-style', 'change', () => ui.viewer?.setStyle($('cmp-style').value));
    listen('cmp-hydrogens', 'change', () => ui.viewer?.setHydrogens($('cmp-hydrogens').checked));
    listen('cmp-spin', 'change', () => ui.viewer?.setAutoRotate($('cmp-spin').checked));
    for (const [id, method, extension, type] of [['cmp-json', 'exportJSON', 'json', 'application/json'], ['cmp-csv', 'exportCSV', 'csv', 'text/csv;charset=utf-8']]) listen(id, 'click', () => guard(async () => download('aqc-comparison-' + (snapshot().molecule?.molecule_id || 'retained-history').replace(/[^a-zA-Z0-9_.-]/g, '_') + '.' + extension, controller[method](), type)));
    listen('diag-retry', 'click', loadDiagnostics);
    for (const id of ['diag-comparator', 'diag-search', 'diag-family', 'diag-behavior', 'diag-sort']) listen(id, id === 'diag-search' ? 'input' : 'change', () => { ui.page = 0; renderDiagnostics(); });
    listen('diag-clear', 'click', () => { $('diag-search').value = ''; $('diag-family').value = 'all'; $('diag-behavior').value = 'all'; $('diag-sort').value = 'regret'; ui.page = 0; renderDiagnostics(); });
    listen('diag-prev', 'click', () => { ui.page--; renderDiagnostics(); });
    listen('diag-next', 'click', () => { ui.page++; renderDiagnostics(); });
    listen('diag-export', 'click', exportDiagnostics);
    for (const id of ['diagnostic-rows', 'diagnostic-plot']) {
      listen(id, 'click', event => { const target = event.target.closest('[data-diagnostic-inspect]'); if (target) inspectDiagnostic(target.dataset.diagnosticInspect); });
      if (id === 'diagnostic-plot') listen(id, 'keydown', event => { const target = event.target.closest('[data-diagnostic-inspect]'); if (target && ['Enter', ' '].includes(event.key)) { event.preventDefault(); inspectDiagnostic(target.dataset.diagnosticInspect); } });
    }
    listen('diagnostic-detail', 'click', event => { const target = event.target.closest('[data-open-comparison]'); if (target) guard(() => openComparison(target.dataset.openComparison)); });
    let resizeTimer = null;
    root.addEventListener?.('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { if (ui.view === 'compare') renderInspector(); if (ui.view === 'diagnostics') renderDiagnostics(); }, 120); });
    function onView(name) {
      ui.view = name;
      if (name !== 'compare') ui.viewer?.setAutoRotate(false);
      if (name === 'compare') {
        loadDiagnostics();
        if (!controller) reportError('The comparison script did not load. Reload this page from the local app server.');
        else if (!ui.opening && !ui.fetching && !ui.awaitingFreshStart && !snapshot().molecule && ui.catalog) guard(() => loadMolecule($('cmp-molecule').value));
        else { renderComparison(); root.requestAnimationFrame?.(() => ui.viewer?.resize()); }
      }
      if (name === 'diagnostics') loadDiagnostics();
    }
    function ready(catalog) { ui.catalog = catalog; setMoleculeOptions(); }
    return Object.freeze({ready, onView, openComparison, loadDiagnostics,
      state: () => ({view: ui.view, comparison: snapshot(), diagnosticRows: ui.diagnostics?.rows.length || 0,
        filteredMolecules: filteredPairs().length, selectedMolecule: ui.selectedMolecule,
        selectedLane: ui.selectedLane, candidateId: ui.candidateId, viewer: ui.viewer?.getState() || null})});
  }
  const exported = {create, pairRows, filterPairs, behaviorLabels, observedProgress, pairedPlot};
  root.AQCExtras = exported;
  if (typeof module !== 'undefined' && module.exports) module.exports = exported;
})(typeof window !== 'undefined' ? window : globalThis);
