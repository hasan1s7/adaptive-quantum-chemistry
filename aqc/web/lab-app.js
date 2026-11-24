(function () {
  'use strict';
  const E = window.AQCEngine;
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const number = (value, places = 2) => typeof value === 'number' && Number.isFinite(value)
    ? value.toLocaleString('en-US', {minimumFractionDigits: places, maximumFractionDigits: places}) : '—';
  const pct = (value, places = 2) => typeof value === 'number' && Number.isFinite(value) ? number(value * 100, places) + '%' : '—';
  const roleNames = {fixed_top_k:'Fixed top-k · fold selected', fixed_matched:'Fixed · matched risk',
    matched_simple:'Matched simple comparator', adaptive:'Cheap-window adaptive', sequential:'Sequential acquisition',
    full_rerank:'Full reference rerank', cheap_only:'Cheap-only · unverified'};
  const kindNames = {fixed:'Fixed top-k', adaptive:'Cheap window', sequential:'Sequential', full:'Full rerank', diagnostic:'Unverified'};
  const colors = {fixed:'#66dce5', adaptive:'#b5a5f2', sequential:'#baf278', full:'#c8d4e1', diagnostic:'#f2c077', matched_simple:'#90c2df'};
  let D, bank, catalog, activePage = 'explore', scope = 'development';
  let visibleExperiments = [], selectedExperiment = null, page = 0, sortField = 'mean_calls', sortDescending = false;
  let moleculeId = null, evaluator = null, runner = null, currentConfig = null, selectedRegistryConfig = null, playing = null;
  let geometryRecords = null, geometryViewer = null, geometryChoice = null, geometryViewerKey = null, geometryError = null, geometryRuntimeVerified = false, geometryApplyingControls = false;
  let toastTimer = null;
  const pageSize = 25;
  function toast(message) {
    $('toast').textContent = message; $('toast').hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').hidden = true; }, 3500);
  }
  function metric(label, value, note, color = '') {
    return '<article class="metric"><div class="metric-label">' + esc(label) + '</div><div class="metric-value ' + color + '">' + esc(value) + '</div><div class="metric-note">' + esc(note) + '</div></article>';
  }
  function switchPage(name) {
    if (!['explore', 'simulator', 'failures', 'verification'].includes(name)) return;
    const changed=activePage!==name;
    if (name !== 'simulator') pausePlay();
    activePage = name;
    document.querySelectorAll('.page').forEach(node => { node.hidden = node.id !== 'page-' + name; });
    document.querySelectorAll('[data-page]').forEach(node => {
      node.classList.toggle('active', node.dataset.page === name);
      if (node.dataset.page === name) node.setAttribute('aria-current', 'page'); else node.removeAttribute('aria-current');
    });
    $('section-label').textContent = {explore:'Experiment explorer', simulator:'Query simulator', failures:'Failure anatomy', verification:'Evidence & integrity'}[name];
    if (name === 'simulator' && evaluator) renderGeometry();
    if (name !== 'simulator' && geometryViewer) geometryViewer.setAutoRotate(false);
    if(changed)window.scrollTo?.({top:0,behavior:'auto'});
  }
  function inferKind(policy, config) {
    if (config?.kind) return config.kind;
    if (policy === 'cheap_only') return 'diagnostic';
    if (policy === 'full_rerank') return 'full';
    if (policy.startsWith('fixed')) return 'fixed';
    if (policy.startsWith('adaptive')) return 'adaptive';
    if (policy.startsWith('sequential')) return 'sequential';
    return policy;
  }
  function scopedRows() {
    if (scope === 'development') return D.experiments;
    const rows = scope === 'cv' ? D.cv.aggregate || [] : D.historical.aggregate || [];
    return rows.map(row => {
      const config = scope === 'historical' ? D.historical.frozen.policies?.[row.policy] : null;
      return {...row, config_id: row.policy, kind: inferKind(row.policy, config), config};
    });
  }
  function switchScope(next) {
    scope = next; page = 0; selectedExperiment = null;
    $('experiment-search').value = ''; $('kind-filter').value = 'all';
    document.querySelectorAll('[data-scope]').forEach(node => node.setAttribute('aria-selected', String(node.dataset.scope === scope)));
    const dev = scope === 'development';
    for (const id of ['risk-filter','calls-filter','target-filter','reset-filters','kind-filter','experiment-search']) $(id).disabled = !dev;
    $('filter-scope').textContent = dev ? 'Filters inspect existing development measurements.'
      : scope === 'cv' ? 'Fold-selected procedure results. These controls do not retune the folds.'
      : 'Historical evidence is read-only. No historical tuning controls.';
    $('scope-banner').className = 'scope-banner ' + (scope === 'historical' ? 'history' : scope === 'development' ? 'warning' : '');
    const devCounts = D.meta.development_counts, historical = D.meta.historical_counts;
    if (dev) {
      $('scope-banner').innerHTML = '<strong>Development only · exploratory.</strong> ' + esc(number(devCounts.molecules,0)) + ' molecules in ' + esc(number(devCounts.families,0)) + ' families. These are selection-data measurements, not fresh validation. Filters never change a measured result.';
      $('table-title').textContent = 'Measured experiment registry';
      $('registry-description').textContent = D.meta.pending ? 'The expanded sweep is pending. No replacement measurements have been invented.' : 'All ' + number(D.experiments.length,0) + ' configurations use the same original development pools.';
      $('plot-subtitle').textContent = 'Each point is one measured configuration; overlapping points are not jittered.';
    } else if (scope === 'cv') {
      $('scope-banner').innerHTML = '<strong>Out-of-fold development evidence.</strong> Entire families stay together. Each fold selects a configuration using its training families, then scores the held-out development families. The ' + esc(number(historical.families,0)) + ' historical families are excluded.';
      $('table-title').textContent = 'Cross-validated acquisition procedures';
      $('registry-description').textContent = 'Rows aggregate fold-specific choices. A procedure may use a different configuration in each fold.';
      $('plot-subtitle').textContent = 'Out-of-fold procedures; whiskers are descriptive family intervals conditional on fold choices.';
    } else {
      $('scope-banner').innerHTML = '<strong>Immutable historical evaluation.</strong> ' + esc(number(historical.molecules,0)) + ' molecules / ' + esc(number(historical.families,0)) + ' families from v0.1. These saved results are shown as context and are not rescored by the expanded registry.';
      $('table-title').textContent = 'Original frozen operating points';
      $('registry-description').textContent = 'Saved evaluation artifacts. The historical primary comparison remains unchanged.';
      $('plot-subtitle').textContent = 'Original sealed evidence with saved family intervals. The new sequential procedure is not evaluated here.';
    }
    $('fold-panel').hidden = scope !== 'cv' || !D.cv.choices?.folds?.length;
    renderCVDecision();
    renderExperiments();
  }
  function renderCVDecision() {
    const decision=D.cv.decision;
    $('cv-decision-panel').hidden=scope!=='cv'||!decision?.paired_difference;
    if(scope!=='cv'||!decision?.paired_difference)return;
    const pair=decision.paired_difference;
    $('cv-target-state').textContent=decision.observed_joint_target_met?'POINT-ESTIMATE TARGET MET':'TARGET NOT MET';
    $('cv-target-state').className='chip '+(decision.observed_joint_target_met?'lime':'amber');
    const metrics=metric('Sequential success',pct(decision.sequential_success_rate),'Within 1 kcal/mol · OOF development','lime')
      +metric('Matched simple success',pct(decision.comparator_success_rate),'Training-selected comparator per fold')
      +metric('Relative calls saved',pct(pair.relative_call_savings),pct(pair.relative_call_savings_ci_low)+'–'+pct(pair.relative_call_savings_ci_high)+' descriptive interval','cyan')
      +metric('Success difference',number(pair.delta_success_rate*100,2)+' pp',number(pair.delta_success_rate_ci_low*100,2)+'–'+number(pair.delta_success_rate_ci_high*100,2)+' pp descriptive interval');
    const availability=decision.target_risk_comparison_available?'Both procedures reach 95% observed success in development CV.': 'The 95% observed-success target is not reached by both procedures; a target-risk comparison is unavailable.';
    const primary=(D.cv.aggregate||[]).find(row=>row.policy==='sequential'),comparator=(D.cv.aggregate||[]).find(row=>row.policy==='matched_simple');
    const outcome=primary&&comparator?'Sequential used '+number(primary.total_calls,0)+' calls versus '+number(comparator.total_calls,0)+' for the matched simple comparator. '+(pair.relative_call_savings<0?'It used more calls. ':pair.relative_call_savings===0?'It saved no calls. ':'')+(pair.delta_success_rate<0?'Its observed success was '+number(-pair.delta_success_rate*100,2)+' percentage points lower.':''):'';
    $('cv-decision-content').innerHTML='<div class="metric-grid">'+metrics+'</div><p class="decision-outcome">'+esc(outcome)+'</p><p>'+esc(availability)+'</p><p>'+esc(decision.inference||'Descriptive family intervals conditional on the selected fold policies; no fresh external validation.')+'</p><p>No wall-clock savings or shape-probe benefit has been measured.</p>';
  }
  function renderGlobal() {
    const n = D.experiments.length, folds = D.cv.choices?.folds?.length || 0;
    $('global-metrics').innerHTML = metric('Configurations measured', D.meta.pending ? 'Pending' : number(n,0),
      D.meta.pending ? 'Expanded sweep not yet loaded' : number(new Set(D.experiments.map(row=>row.behavior_signature)).size,0)+' distinct observed behaviors', 'cyan')
      + metric('Development pools', number(D.meta.development_counts.molecules,0), number(D.meta.development_counts.families,0) + ' chemical families')
      + metric('Family-blocked CV', folds ? number(folds,0) + ' folds' : 'Pending', folds ? 'Training-selected choices, OOF scoring' : 'No cross-validation result substituted')
      + metric('Historical holdout', number(D.meta.historical_counts.families,0) + ' families', 'Original evidence · no new tuning', 'lime');
    $('nav-count').textContent = n ? number(n,0) : '…';
    $('source-revision').textContent = D.meta.source_revision ? D.meta.source_revision.slice(0,12) : 'Synthetic engineering fixture';
    $('top-integrity').innerHTML = '<span class="status-dot"></span>' + (D.meta.dataset_kind === 'synthetic' ? 'SYNTHETIC FIXTURE · ' : '') + (D.meta.pending ? 'Development inputs checked' : 'Artifact seals checked at build');
    const maxCalls = Math.max(...catalog.map(row => row.n_candidates), 1);
    $('calls-filter').max = String(maxCalls); $('calls-filter').value = String(maxCalls);
    $('calls-max-label').textContent = maxCalls + ' calls';
  }
  function renderExperiments() {
    const all = scopedRows();
    $('risk-value').textContent = number(Number($('risk-filter').value),1) + '%';
    $('calls-value').textContent = number(Number($('calls-filter').value),1);
    const filtered = scope === 'development' ? E.filterExperiments(all, {
      query: $('experiment-search').value, kind: $('kind-filter').value,
      maxRisk: Number($('risk-filter').value), maxCalls: Number($('calls-filter').value)
    }) : all;
    visibleExperiments = E.sortExperiments(filtered, sortField, sortDescending);
    if (page * pageSize >= visibleExperiments.length) page = Math.max(0, Math.ceil(visibleExperiments.length / pageSize) - 1);
    $('filtered-count').textContent = number(filtered.length,0) + ' / ' + number(all.length,0) + ' rows';
    $('point-count').textContent = number(all.length,0) + ' measured points';
    if (!selectedExperiment && visibleExperiments.length) selectedExperiment = visibleExperiments[0];
    const displayed = visibleExperiments.slice(page * pageSize, (page + 1) * pageSize);
    $('experiment-rows').innerHTML = displayed.length ? displayed.map(row => {
      const selected = selectedExperiment?.config_id === row.config_id;
      const title = scope === 'development' ? row.config_id : roleNames[row.policy] || row.policy;
      const detail = scope === 'development' ? row.equivalence_representative && row.equivalence_representative !== row.config_id ? 'Same measured behavior as another registry point' : 'Measured on original development pools' : scope === 'cv' ? 'Configuration selected separately within each fold' : 'Original frozen choice';
      return '<tr data-experiment="' + esc(row.config_id) + '" class="' + (selected ? 'selected' : '') + '"><td><button class="config-button" data-experiment="' + esc(row.config_id) + '">' + esc(title) + '</button><span class="table-sub">' + esc(detail) + '</span></td><td><span class="kind-label ' + esc(row.kind) + '">' + esc(kindNames[row.kind] || roleNames[row.policy] || row.kind) + '</span></td><td class="mono ' + (row.success_rate >= .95 ? 'positive' : '') + '">' + pct(row.success_rate) + '</td><td class="mono">' + number(row.mean_calls,3) + '</td><td class="mono">' + number(row.p95_regret_kcal,3) + '</td><td class="mono">' + pct(row.fallback_rate,1) + '</td><td><span class="muted" aria-hidden="true">View</span></td></tr>';
    }).join('') : '<tr><td colspan="7" class="empty">' + (D.meta.pending && scope !== 'historical' ? 'Expanded measurements are not loaded yet. The real development query simulator is ready.' : 'No measured configurations match these filters.') + '</td></tr>';
    $('page-count').textContent = filtered.length ? number(page * pageSize + 1,0) + '–' + number(Math.min((page + 1) * pageSize, filtered.length),0) + ' of ' + number(filtered.length,0) : '0 measured rows';
    $('previous-page').disabled = page === 0; $('next-page').disabled = (page + 1) * pageSize >= filtered.length;
    $('export-experiments').disabled = !filtered.length;
    renderRiskChart(all, new Set(filtered.map(row => row.config_id))); renderExperimentDetail();
  }
  function selectExperiment(id) {
    selectedExperiment = scopedRows().find(row => row.config_id === id) || null;
    renderExperiments();
  }
  function renderRiskChart(rows, activeIds) {
    if (!rows.length) {
      $('risk-chart').innerHTML = '<div class="empty"><h3>Evidence will appear here</h3><p style="margin-top:10px">' + (D.meta.pending ? 'The expanded sweep is pending. Use the query simulator now, or inspect the original historical evidence.' : 'No results are available for this evidence population.') + '</p></div>';
      return;
    }
    const w = 850, h = 390, l = 75, r = 27, t = 27, b = 64;
    const xmax = Math.max(2, Math.ceil(Math.max(...rows.map(row => row.mean_calls))));
    const observedMax = Math.max(...rows.map(row => 100 * (1 - (scope!=='development'&&row.success_rate_ci_low!=null?row.success_rate_ci_low:row.success_rate))));
    const ymax = Math.max(10, Math.ceil(observedMax / 5) * 5);
    const X = value => l + value / xmax * (w - l - r), Y = value => h - b - value / ymax * (h - t - b);
    let svg = '<svg viewBox="0 0 ' + w + ' ' + h + '" aria-hidden="true">';
    for (let i = 0; i <= 4; i++) {
      const y = ymax * i / 4, py = Y(y);
      svg += '<line x1="' + l + '" y1="' + py + '" x2="' + (w-r) + '" y2="' + py + '" stroke="#27394d"/><text x="' + (l-14) + '" y="' + (py+5) + '" text-anchor="end" font-size="14" fill="#9db1c6">' + number(y, y % 1 ? 1 : 0) + '%</text>';
    }
    for (let i = 0; i <= xmax; i++) {
      const px = X(i);
      svg += '<text x="' + px + '" y="' + (h-b+26) + '" text-anchor="middle" font-size="14" fill="#9db1c6">' + i + '</text>';
    }
    svg += '<line x1="' + l + '" y1="' + Y(5) + '" x2="' + (w-r) + '" y2="' + Y(5) + '" stroke="#f2c077" stroke-dasharray="6 5" opacity=".8"/><text x="' + (w-r) + '" y="' + (Y(5)-9) + '" text-anchor="end" fill="#f2c077" font-size="14">5% target risk</text>';
    for (const row of rows) {
      const active = activeIds.has(row.config_id), selected = selectedExperiment?.config_id === row.config_id;
      const color = colors[row.kind] || '#90c2df';
      if(scope!=='development'&&row.success_rate_ci_low!=null&&row.success_rate_ci_high!=null){
        const x=X(row.mean_calls),low=Y(100*(1-row.success_rate_ci_high)),high=Y(100*(1-row.success_rate_ci_low));
        svg+='<line x1="'+x+'" x2="'+x+'" y1="'+low+'" y2="'+high+'" stroke="'+color+'" opacity=".5"/><line x1="'+(x-4)+'" x2="'+(x+4)+'" y1="'+low+'" y2="'+low+'" stroke="'+color+'"/><line x1="'+(x-4)+'" x2="'+(x+4)+'" y1="'+high+'" y2="'+high+'" stroke="'+color+'"/>';
      }
      svg += '<circle data-point="' + esc(row.config_id) + '" cx="' + X(row.mean_calls) + '" cy="' + Y(100*(1-row.success_rate)) + '" r="' + (selected ? 7 : rows.length > 50 ? 4 : 6) + '" fill="' + color + '" fill-opacity="' + (active ? selected ? 1 : rows.length > 50 ? .38 : .9 : .07) + '" stroke="' + (selected ? '#fff' : 'none') + '" stroke-width="2" style="cursor:pointer"/>';
    }
    if (selectedExperiment && rows.some(row => row.config_id === selectedExperiment.config_id)) svg += '<circle cx="' + X(selectedExperiment.mean_calls) + '" cy="' + Y(100*(1-selectedExperiment.success_rate)) + '" r="10" fill="none" stroke="#eef4fa" stroke-width="1.4" pointer-events="none"/>';
    svg += '<text x="' + ((l+w-r)/2) + '" y="' + (h-12) + '" text-anchor="middle" fill="#c1cfdf" font-size="15">Mean expensive calls per molecule</text><text x="19" y="' + ((t+h-b)/2) + '" transform="rotate(-90 19 ' + ((t+h-b)/2) + ')" text-anchor="middle" fill="#c1cfdf" font-size="15">Failure risk</text></svg>';
    $('risk-chart').innerHTML = svg;
  }
  function renderExperimentDetail() {
    const row = selectedExperiment;
    if (!row) { $('experiment-detail').innerHTML = '<p class="muted">Select a measured point or table row. Pending results are never replaced with illustrative values.</p>'; return; }
    const id = scope === 'development' ? row.config_id : roleNames[row.policy] || row.policy;
    let html = '<h3>' + esc(id) + '</h3><div class="detail-kpis"><div><span class="value">' + pct(row.success_rate,1) + '</span><span class="label">success ≤1 kcal/mol</span></div><div><span class="value">' + number(row.mean_calls,2) + '</span><span class="label">calls / molecule</span></div></div>';
    if (row.config) html += '<div class="param-list">' + Object.entries(row.config).filter(([key]) => key !== 'kind').map(([key,value]) => '<span>' + esc(key) + ' ' + esc(value) + '</span>').join('') + '</div>';
    if (scope === 'development') {
      html += '<p>' + (row.success_rate >= .95 ? 'Meets the 95% target on pooled development data. This is an exploratory point estimate.' : 'Does not meet the 95% target on pooled development data.') + '</p>';
      if (row.config?.kind !== 'diagnostic') html += '<button class="button" data-simulate="' + esc(row.config_id) + '">Inspect in query simulator</button>';
      else html += '<p>Zero verification. Excluded from paid baseline comparisons.</p>';
    } else if (scope === 'cv') html += '<p>Aggregated out-of-fold procedure. Its configuration is selected separately in each fold; inspect the fold choices below.</p>';
    else html += '<p>Historical frozen evidence. This view has no acquisition or tuning controls.</p>';
    if (row.success_rate_ci_low != null) html += '<p>95% family interval: ' + pct(row.success_rate_ci_low,1) + '–' + pct(row.success_rate_ci_high,1) + '. No population guarantee.</p>';
    if(scope==='cv'&&row.interval_conditioning)html+='<p>'+esc(row.interval_conditioning)+'</p>';
    $('experiment-detail').innerHTML = html;
  }
  function renderFolds() {
    const folds = D.cv.choices?.folds || [];
    const rows = D.cv.per_molecule || [];
    if (!folds.length) return;
    $('fold-table').innerHTML = '<table><thead><tr><th>Fold</th><th>Validation population</th><th>Selected sequential config</th><th>Training success</th><th>OOF success</th><th>OOF calls / mol</th></tr></thead><tbody>' + folds.map(fold => {
      const choice = fold.choices?.sequential;
      const outcomes = rows.filter(row => String(row.fold_id) === String(fold.fold_id) && row.policy === 'sequential');
      const n = outcomes.length, success = n ? outcomes.filter(row => row.regret_kcal <= 1 + 1e-9).length / n : null;
      const meanCalls = n ? outcomes.reduce((sum,row) => sum + row.expensive_calls,0) / n : null;
      return '<tr><td class="mono">' + esc(fold.fold_id) + '</td><td>' + n + ' molecules<span class="table-sub">' + new Set(outcomes.map(row => row.family_id)).size + ' families</span></td><td class="mono">' + esc(choice?.config_id || 'Unavailable') + '</td><td>' + pct(choice?.training_metrics?.success_rate) + '</td><td>' + pct(success) + '</td><td>' + number(meanCalls,3) + '</td></tr>';
    }).join('') + '</tbody></table>';
  }
  function csvDownload(rows, filename) {
    if (!rows.length) { toast('No measured rows to export'); return; }
    const fields = [...new Set(rows.flatMap(row => Object.keys(row)))];
    const cell = value => '"' + String(value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : value).replace(/"/g,'""') + '"';
    const text = fields.map(cell).join(',') + '\n' + rows.map(row => fields.map(key => cell(row[key])).join(',')).join('\n') + '\n';
    download(text, filename, 'text/csv;charset=utf-8');
  }
  function download(content, filename, type = 'application/json') {
    const blob = new Blob([content], {type}); const url = URL.createObjectURL(blob);
    const link = document.createElement('a'); link.href = url; link.download = filename;
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function currentPool() { return catalog.find(row => row.molecule_id === moleculeId); }
  async function loadGeometry() {
    if (!D.geometry?.available) { geometryError = D.geometry?.reason || 'Verified geometry is unavailable in this build.'; renderGeometry(); return; }
    try {
      if (!window.DecompressionStream) throw new Error('This browser cannot decompress the bundled coordinates. Open this file in a current Chromium, Firefox, or Safari browser.');
      const bytes = Uint8Array.from(atob(D.geometry.payload_gzip_base64), character => character.charCodeAt(0));
      delete D.geometry.payload_gzip_base64;
      if (window.crypto?.subtle) {
        const hash = [...new Uint8Array(await window.crypto.subtle.digest('SHA-256', bytes))].map(value => value.toString(16).padStart(2,'0')).join('');
        if (hash !== D.geometry.compressed_sha256) throw new Error('Bundled geometry checksum mismatch; coordinates were not loaded.');
        geometryRuntimeVerified = true;
      }
      const decompressed = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
      const content = JSON.parse(await new Response(decompressed).text());
      if (content.scope !== 'original_development_only' || content.molecule_count !== catalog.length) throw new Error('Bundled geometry has an unexpected scope or population.');
      geometryRecords = new Map(content.molecules.map(molecule => [molecule.molecule_id,new Map(molecule.candidates.map(candidate => [candidate.candidate_id,candidate]))]));
      if (geometryRecords.size !== catalog.length || catalog.some(pool => !geometryRecords.has(pool.molecule_id) || geometryRecords.get(pool.molecule_id).size !== pool.n_candidates || pool.candidates.some(candidate => !geometryRecords.get(pool.molecule_id).has(candidate.candidate_id)))) throw new Error('Bundled geometry candidate IDs differ from development pools.');
      renderGeometry();
    } catch (error) { geometryRecords = null; geometryError = error.message; renderGeometry(); }
  }
  function renderGeometry() {
    if (!evaluator || !currentPool()) return;
    const pool=currentPool(),state=evaluator.snapshot(),policy=runner?.snapshot();
    const manual=$('simulation-policy').value==='manual';
    $('geometry-paid-calls').textContent=state.expensive_calls+' paid '+(state.expensive_calls===1?'call':'calls')+' / '+pool.n_candidates;
    $('geometry-best-paid').textContent='Best verified: '+(state.best_verified||'none yet');
    $('geometry-trial-result').textContent=state.evaluation?'Regret '+number(state.evaluation.regret_kcal,3)+' kcal/mol · stopped':'Regret locked until stop';
    for(const id of ['geometry-step-policy','geometry-run-policy']){$(id).hidden=manual;$(id).disabled=state.stopped||policy?.done;}
    $('geometry-finish-manual').hidden=!manual;$('geometry-finish-manual').disabled=state.stopped||!state.best_verified;
    const ranked=[...pool.candidates].sort((a,b)=>a.cheap_kcal-b.cheap_kcal||E.lexical(a.candidate_id,b.candidate_id));
    if (!geometryChoice || !pool.candidates.some(candidate=>candidate.candidate_id===geometryChoice) || $('geometry-follow').checked) {
      geometryChoice=state.stopped?state.best_verified:policy?.pending_candidate||state.queries.at(-1)?.candidate_id||ranked[0].candidate_id;
    }
    $('geometry-conformer').innerHTML=ranked.map((candidate,index)=>'<option value="'+esc(candidate.candidate_id)+'">'+String(index+1).padStart(2,'0')+' · '+esc(candidate.candidate_id)+'</option>').join('');
    $('geometry-conformer').value=geometryChoice;
    const observed=Object.prototype.hasOwnProperty.call(state.observations,geometryChoice);
    const first=state.queries.find(query=>query.status==='succeeded');
    $('geometry-identity').textContent=pool.molecule_id+' / '+geometryChoice;
    $('geometry-reference').className='geometry-reference'+(observed?' known':'');
    const failed=state.queries.some(query=>query.candidate_id===geometryChoice&&query.status==='failed');
    $('geometry-reference').textContent=observed?'Paid reference Δ '+number(state.observations[geometryChoice]-first.reference_kcal,3)+' kcal/mol':failed?'Paid query · output unavailable':'Reference hidden · no paid query';
    $('geometry-reveal').disabled=state.stopped||observed||state.queries.some(query=>query.candidate_id===geometryChoice&&query.status==='failed');
    const geometry=geometryRecords?.get(pool.molecule_id)?.get(geometryChoice);
    for(const id of ['geometry-style','geometry-hydrogens','geometry-spin','geometry-reset'])$(id).disabled=!geometry;
    if(!geometry){$('geometry-loading').hidden=false;$('geometry-loading').textContent=geometryError||'Loading verified development coordinates…';$('geometry-renderer').textContent=geometryError?'UNAVAILABLE':'LOADING 3D';$('geometry-provenance').textContent='Coordinates are a display aid; acquisition policies do not receive geometry features.';return;}
    if(!window.AQCMoleculeViewer){geometryError='The offline molecular renderer is not included in this build.';$('geometry-loading').hidden=false;$('geometry-loading').textContent=geometryError;$('geometry-renderer').textContent='UNAVAILABLE';return;}
    if(activePage!=='simulator')return;
    try {
      geometryApplyingControls=true;
      if(!geometryViewer)geometryViewer=window.AQCMoleculeViewer.create($('molecule-viewport'),{background:'#09131f',onStateChange:state=>{
        if(geometryApplyingControls)return;
        $('geometry-style').value=state.style;$('geometry-hydrogens').checked=state.hydrogens;$('geometry-spin').checked=state.autoRotate;
      }});
      const key=pool.molecule_id+'/'+geometryChoice;
      if(key!==geometryViewerKey){
        const atoms=geometry.symbols.map((element,index)=>({element,x:geometry.coordinates_angstrom[index][0],y:geometry.coordinates_angstrom[index][1],z:geometry.coordinates_angstrom[index][2]}));
        geometryViewer.setGeometry({atoms},{molecule_id:pool.molecule_id,candidate_id:geometryChoice,label:key,bonds_inferred:true});geometryViewerKey=key;
      }
      geometryViewer.setStyle($('geometry-style').value||'ball-stick');
      geometryViewer.setHydrogens($('geometry-hydrogens').checked);
      geometryViewer.setAutoRotate($('geometry-spin').checked);
      geometryViewer.resize?.();
      const viewerState=geometryViewer.getState();
      $('geometry-loading').hidden=true;$('geometry-renderer').textContent=viewerState.renderer==='webgl'?'WEBGL · 3D':'CANVAS · 3D';
      $('geometry-provenance').textContent=geometry.symbols.length+' atoms · verified XYZ coordinates in Å · inferred bonds are visual guides, not verified bond orders. Geometry is not a policy feature.';
      $('geometry-checksum').textContent='Geometry SHA-256\n'+geometry.geometry_sha256+'\nSource XYZ SHA-256\n'+geometry.xyz_sha256+'\nBundled asset SHA-256\n'+D.geometry.compressed_sha256+'\n'+(geometryRuntimeVerified?'Asset digest checked in this browser.':'Asset digest checked at build; browser digest API unavailable.');
    }catch(error){geometryError=error.message;$('geometry-loading').hidden=false;$('geometry-loading').textContent='3D viewer unavailable: '+geometryError;$('geometry-renderer').textContent='UNAVAILABLE';}
    finally{geometryApplyingControls=false;}
  }
  function foldSequential(pool) {
    const fold = (D.cv.choices?.folds || []).find(row => String(row.fold_id) === String(pool.fold_id));
    if (fold?.choices?.sequential?.config) return fold.choices.sequential.config;
    const recorded = (D.cv.per_molecule || []).find(row => row.molecule_id === pool.molecule_id && row.policy === 'sequential');
    const config = recorded ? D.experiments.find(row => row.config_id === recorded.config_id)?.config : null;
    return config || {kind:'sequential', one_gap:8, one_ratio:.3, error_scale:2, slack:.25, cap:4};
  }
  function resolveConfig(mode = $('simulation-policy').value) {
    if (mode === 'manual') return null;
    if (mode === 'fixed') return {kind:'fixed',k:2};
    if (mode === 'full') return {kind:'full'};
    if (mode === 'adaptive') return D.historical.frozen.policies?.adaptive || {kind:'adaptive',k:2,gap:0,cap:4};
    if (mode === 'selected') return selectedRegistryConfig;
    return foldSequential(currentPool());
  }
  function renderMoleculeOptions() {
    const search = $('molecule-search').value.toLowerCase();
    const matches = catalog.filter(row => row.molecule_id.toLowerCase().includes(search));
    const retained = matches.some(row => row.molecule_id === moleculeId) ? matches : [currentPool(),...matches].filter(Boolean);
    $('molecule-select').innerHTML = retained.map(row => '<option value="' + esc(row.molecule_id) + '">' + esc(row.molecule_id) + ' · ' + row.n_candidates + ' candidates' + (row.molecule_id === moleculeId && !matches.includes(row) ? ' · current' : '') + '</option>').join('');
    $('molecule-select').value = moleculeId;
    $('molecule-count').textContent = '· ' + matches.length + ' matching';
  }
  function pausePlay() {
    if (playing != null) clearTimeout(playing);
    playing = null;
    if ($('play-policy')) $('play-policy').textContent = 'Play slowly';
  }
  function resetTrial() {
    pausePlay();
    evaluator = bank.open(moleculeId);
    currentConfig = resolveConfig();
    runner = currentConfig ? E.createPolicyRunner(currentPool().candidates, currentConfig, evaluator.query) : null;
    $('simulation-comparison').innerHTML = '<p class="muted">Run the comparison to inspect independent calls and regret on this development molecule. This does not change any saved experiment.</p>';
    renderSimulation();
  }
  function closePolicyIfDone() {
    const state = runner?.snapshot();
    if (state?.done) {
      pausePlay();
      if (state.result.selected_candidate) evaluator.finish(state.result.selected_candidate, state.result.stop_reason);
    }
  }
  function stepPolicy() {
    if (!runner || evaluator.snapshot().stopped) return;
    try { runner.step(); closePolicyIfDone(); renderSimulation(); }
    catch (error) { pausePlay(); toast(error.message); renderSimulation(); }
  }
  function runPolicy() {
    pausePlay();
    if (!runner || evaluator.snapshot().stopped) return;
    try { runner.run(); closePolicyIfDone(); renderSimulation(); }
    catch (error) { toast(error.message); renderSimulation(); }
  }
  function playPolicy() {
    if (playing != null) { pausePlay(); return; }
    if (!runner || evaluator.snapshot().stopped) return;
    const tick = () => {
      stepPolicy();
      if (runner && !runner.snapshot().done) { $('play-policy').textContent = 'Pause replay'; playing = setTimeout(tick, 850); }
      else pausePlay();
    };
    $('play-policy').textContent = 'Pause replay'; playing = setTimeout(tick, 250);
  }
  function revealCandidate(id) {
    pausePlay();
    if (evaluator.snapshot().stopped) return;
    if ($('simulation-policy').value !== 'manual') {
      $('simulation-policy').value = 'manual'; runner = null; currentConfig = null;
      toast('Manual acquisition · existing paid observations retained');
    }
    try { evaluator.query(id); renderSimulation(); }
    catch (error) { toast(error.message); renderSimulation(); }
  }
  function finishManual() {
    try { evaluator.finish(undefined, 'manual_stop'); renderSimulation(); }
    catch (error) { toast(error.message); }
  }
  function renderSimulation() {
    if (!evaluator) return;
    const pool = currentPool(), state = evaluator.snapshot(), policy = runner?.snapshot();
    const observations = state.observations, firstPaid = state.queries.find(row => row.status === 'succeeded');
    const base = firstPaid ? firstPaid.reference_kcal : null, best = state.best_verified;
    const bestDelta = best && base != null ? observations[best] - base : null;
    $('molecule-family').textContent = pool.family_id + (pool.fold_id != null ? ' · fold ' + pool.fold_id : '') + (pool.is_acyclic ? ' · acyclic' : '');
    $('candidate-count').textContent = pool.n_candidates + ' fixed candidates';
    $('simulation-parameters').textContent = currentConfig ? JSON.stringify(currentConfig,null,2) + (D.meta.pending && currentConfig.kind === 'sequential' ? '\n\nDemonstration parameters; expanded sweep not yet loaded. This local replay is not an aggregate performance claim.' : '') : 'Manual acquisition. Query any candidate; the evaluator returns the best successfully verified candidate when you stop.';
    $('simulation-metrics').innerHTML = metric('Expensive calls charged', state.expensive_calls + ' / ' + pool.n_candidates, 'A first query costs one replay job', 'cyan')
      + metric('Best reference verified', best || 'None yet', best ? 'Lowest paid reference so far' : 'No selection without a paid query', 'lime')
      + metric('Best paid reference Δ', bestDelta == null ? 'Hidden' : number(bestDelta,3), 'kcal/mol from first paid reference')
      + metric('Evaluator regret', state.evaluation ? number(state.evaluation.regret_kcal,3) : 'Locked', state.evaluation ? 'kcal/mol · scored after stop' : 'Available only after this trial stops', state.evaluation?.success_within_1_kcal ? 'lime' : '');
    const manual = $('simulation-policy').value === 'manual';
    for (const id of ['run-policy','step-policy','play-policy']) { $(id).disabled = manual || state.stopped || policy?.done; $(id).hidden = manual; }
    $('finish-manual').hidden = !manual; $('finish-manual').disabled = state.stopped || !best;
    $('trial-status').textContent = state.stopped ? 'Stopped · best queried conformer selected' : manual ? 'Manual mode · choose the next reference to buy' : policy?.pending_candidate ? 'Next paid query: ' + policy.pending_candidate : 'No verified candidate available';
    const ranked = [...pool.candidates].sort((a,b) => a.cheap_kcal-b.cheap_kcal || E.lexical(a.candidate_id,b.candidate_id));
    const maxCheap = Math.max(...ranked.map(row => row.cheap_kcal), 1e-9);
    const failedIds = new Set(state.queries.filter(row => row.status === 'failed').map(row => row.candidate_id));
    $('candidate-rows').innerHTML = ranked.map((row,index) => {
      const known = Object.prototype.hasOwnProperty.call(observations,row.candidate_id);
      const isNext = !state.stopped && policy?.pending_candidate === row.candidate_id;
      const delta = known && base != null ? observations[row.candidate_id] - base : null;
      return '<tr class="' + (best === row.candidate_id ? 'best' : isNext ? 'next' : '') + '"><td><span class="candidate-rank">' + String(index+1).padStart(2,'0') + '</span><span class="candidate-id">' + esc(row.candidate_id) + '</span>' + (best === row.candidate_id ? '<span class="table-sub positive">Best verified</span>' : isNext ? '<span class="table-sub">Next policy query</span>' : '') + '</td><td><span class="mono">' + number(row.cheap_kcal,3) + '</span><div class="cheap-bar"><span style="width:' + (100*row.cheap_kcal/maxCheap) + '%"></span></div></td><td>' + (known ? '<span class="reference-value">' + number(delta,3) + '</span>' : '<span class="reference-hidden">' + (failedIds.has(row.candidate_id) ? 'Output unavailable' : 'Hidden · not queried') + '</span>') + '</td><td>' + (known ? '<span class="positive">Verified</span>' : '<button class="button small secondary" data-reveal="' + esc(row.candidate_id) + '" ' + (state.stopped || failedIds.has(row.candidate_id) ? 'disabled' : '') + '>Reveal +1</button>') + '</td></tr>';
    }).join('');
    $('query-ledger').innerHTML = state.queries.length ? state.queries.map(query => '<div class="ledger-item"><span class="ledger-number">' + query.order + '</span><div><div class="ledger-id">' + esc(query.candidate_id) + '</div><div class="ledger-meta">' + (query.status === 'succeeded' || query.status === 'cached' ? 'Reference Δ ' + number(query.reference_kcal-base,3) + ' kcal/mol' : esc(query.error || query.status)) + '</div></div><span class="ledger-charge">' + (query.charged ? '+1 job' : 'cached') + '</span></div>').join('') : '<div class="ledger-empty">The ledger starts empty. Revealing a candidate records its ID, order, reference result, and charge here.</div>';
    renderEnergyChart(ranked, observations, base, policy?.pending_candidate, state.stopped);
    renderGeometry();
    renderPolicyReason(policy, state);
    $('stop-result').hidden = !state.evaluation;
    if (state.evaluation) {
      const result = state.evaluation, success = result.success_within_1_kcal;
      $('stop-result').className = 'stop-result' + (success === false ? ' failed' : '');
      $('stop-result').innerHTML = '<div class="eyebrow">EVALUATOR · AFTER STOP</div><div class="result-value">' + number(result.regret_kcal,3) + ' kcal/mol</div><p>' + (success ? 'Within the 1 kcal/mol target on this pool.' : success === false ? 'Above the 1 kcal/mol target on this pool.' : 'Regret unavailable for an incomplete reference pool.') + '</p><p>Selected <code>' + esc(result.selected_candidate) + '</code><br>Best in full pool <code>' + esc(result.best_pool_candidate || 'unavailable') + '</code></p><p><code>' + esc(result.stop_reason) + '</code></p>';
    }
  }
  function renderPolicyReason(policy, state) {
    if (!policy) { $('policy-explanation').textContent = state.stopped ? 'Manual trial stopped. The evaluator selected the best reference-verified conformer you purchased.' : 'Manual acquisition: choose which candidate deserves the next paid reference. Existing observations remain charged.'; return; }
    const events = policy.events || [];
    const relevant = [...events].reverse().find(event => ['empirical_envelope','cheap_separation','fallback','escalation'].includes(event.event));
    let text = 'The policy begins with a paid reference. Unqueried labels never enter its input.';
    if (relevant?.event === 'empirical_envelope') {
      text = 'Observed cheap/reference discrepancy: ' + number(relevant.max_observed_discrepancy_kcal,3) + ' kcal/mol. The empirical envelope is ' + number(relevant.envelope_error_kcal,3) + '. ' + (relevant.action === 'stop' ? 'The heuristic stopping condition is satisfied.' : relevant.action === 'fallback' ? 'The condition is unresolved at the cap; query the full remainder.' : 'The condition is unresolved; buy another reference.') + ' This envelope is not a certified bound.';
    } else if (relevant?.event === 'cheap_separation') {
      text = 'The first cheap-energy gap is ' + number(relevant.gap12_kcal,3) + ' kcal/mol (' + pct(relevant.gap_ratio,1) + ' of the cheap span). ' + (relevant.action === 'stop' ? 'The cheap-separation heuristic stops after one verification. It is not a risk certificate.' : 'The separation gate does not stop the policy; acquire another reference.');
    } else if (relevant?.event === 'fallback') text = 'Full-rerank fallback: ' + relevant.reason.replaceAll('_',' ') + '. Every remaining candidate is queried and charged once.';
    else if (relevant?.event === 'escalation') text = 'The next candidate is within the cheap-energy window (' + number(relevant.cheap_gap_kcal,3) + ' kcal/mol). Acquire another reference.';
    else if (currentConfig?.kind === 'fixed') text = 'Buy the first ' + currentConfig.k + ' candidates in cheap-energy order, then select their best observed reference.';
    else if (currentConfig?.kind === 'full') text = 'Query every candidate. This pays for the fixed-pool ceiling.';
    if (policy.done) text += ' Stop: ' + policy.result.stop_reason.replaceAll('_',' ') + '.';
    $('policy-explanation').textContent = text;
  }
  function renderEnergyChart(ranked, observations, base, pendingId, stopped) {
    const w=820,h=225,l=62,r=22,t=22,b=46;
    const values = ranked.map(row=>row.cheap_kcal).concat(Object.values(observations).map(value=>value-base));
    const min=Math.min(0,...values), max=Math.max(1,...values), span=Math.max(1,max-min);
    const lo=min-span*.12, hi=max+span*.14;
    const X=index=>l+index/Math.max(1,ranked.length-1)*(w-l-r), Y=value=>h-b-(value-lo)/(hi-lo)*(h-t-b);
    let svg='<svg viewBox="0 0 '+w+' '+h+'" aria-hidden="true">';
    for(let i=0;i<4;i++){const value=min+(max-min)*i/3;svg+='<line x1="'+l+'" x2="'+(w-r)+'" y1="'+Y(value)+'" y2="'+Y(value)+'" stroke="#27394d"/><text x="'+(l-10)+'" y="'+(Y(value)+5)+'" text-anchor="end" fill="#9db1c6" font-size="14">'+number(value,1)+'</text>';}
    svg+='<polyline points="'+ranked.map((row,index)=>X(index)+','+Y(row.cheap_kcal)).join(' ')+'" fill="none" stroke="#66dce5" stroke-width="2"/>';
    ranked.forEach((row,index)=>{const x=X(index);svg+='<circle cx="'+x+'" cy="'+Y(row.cheap_kcal)+'" r="4" fill="#66dce5"/><text x="'+x+'" y="'+(h-b+23)+'" text-anchor="middle" fill="#9db1c6" font-size="14">'+(index+1)+'</text>';if(Object.prototype.hasOwnProperty.call(observations,row.candidate_id))svg+='<circle cx="'+x+'" cy="'+Y(observations[row.candidate_id]-base)+'" r="6" fill="#baf278" stroke="#0b1421" stroke-width="2"/>';else if(!stopped&&row.candidate_id===pendingId)svg+='<circle cx="'+x+'" cy="'+Y(row.cheap_kcal)+'" r="9" fill="none" stroke="#eef4fa" stroke-width="1.5"/>';});
    svg+='<text x="'+(w-r)+'" y="16" text-anchor="end" fill="#66dce5" font-size="14">Cheap Δ</text><text x="'+(w-r-100)+'" y="16" text-anchor="end" fill="#baf278" font-size="14">● Paid reference Δ</text><text x="'+((l+w-r)/2)+'" y="'+(h-2)+'" text-anchor="middle" fill="#9db1c6" font-size="14">Cheap-energy rank</text></svg>';
    $('energy-chart').innerHTML=svg;
  }
  function comparePolicies() {
    const pool=currentPool();
    const configs=[['Fixed top-2',{kind:'fixed',k:2}],['Sequential',foldSequential(pool)],['Full rerank',{kind:'full'}]];
    try {
      const rows=configs.map(([label,config])=>{const local=bank.open(pool.molecule_id);const run=E.createPolicyRunner(pool.candidates,config,local.query).run();const evalResult=local.finish(run.result.selected_candidate,run.result.stop_reason);return {label,config,...run.result,...local.snapshot(),...evalResult};});
      $('simulation-comparison').innerHTML='<table><thead><tr><th>Independent replay</th><th>Calls</th><th>Regret kcal/mol</th><th>Selected candidate</th><th>Stop reason</th></tr></thead><tbody>'+rows.map(row=>'<tr><td>'+esc(row.label)+'</td><td class="mono">'+row.expensive_calls+'</td><td class="mono '+(row.success_within_1_kcal?'positive':'negative')+'">'+number(row.regret_kcal,3)+'</td><td class="mono">'+esc(row.selected_candidate)+'</td><td class="mono">'+esc(row.stop_reason)+'</td></tr>').join('')+'</tbody></table><p style="margin-top:14px">Each row is a separate local development replay. The current trial and saved aggregate measurements are unchanged.</p>';
    } catch(error){toast(error.message);}
  }
  function openMolecule(id) {
    if (!catalog.some(row=>row.molecule_id===id)) return;
    moleculeId=id;$('molecule-search').value='';renderMoleculeOptions();resetTrial();switchPage('simulator');
    window.scrollTo?.({top:0,behavior:'auto'});
  }
  function renderFailureAnatomy() {
    const f=D.failure_analysis,n=f.n_molecules;
    $('failure-metrics').innerHTML=metric('Within 1 · one paid query',pct(f.first_successes/n),f.first_successes+' / '+n+' development molecules')
      +metric('Within 1 · two paid queries',pct(f.second_successes/n),f.second_successes+' / '+n+' development molecules','cyan')
      +metric('Rescued by the second query',number(f.rescued_on_second,0),'Crossed from >1 to ≤1 kcal/mol','lime')
      +metric('Still above 1 after two',number(n-f.second_successes,0),'Pool minima remain outside top-2');
    const segments=[['Already within 1',f.first_successes,'#66dce5'],['Rescued on second',f.rescued_on_second,'#baf278'],['Still above 1',n-f.second_successes,'#ff9a96']];
    $('rescue-chart').innerHTML=segments.map(([label,count,color])=>'<div class="rescue-segment"><span class="name">'+esc(label)+'</span><div class="rescue-track"><span style="width:'+(100*count/n)+'%;background:'+color+'"></span></div><span class="count">'+count+'</span></div>').join('')+'<p class="muted" style="font-size:14px;margin-top:22px">The second reference changes the selected candidate in '+f.second_changes_selection+' pools. A changed selection is not necessarily a threshold rescue.</p>';
    $('coverage-details').innerHTML='<div class="coverage-row"><span>Acyclic molecules · development</span><strong>'+f.acyclic_development+'</strong></div><div class="coverage-row"><span>Acyclic molecules · historical evaluation</span><strong>'+D.historical.acyclic_evaluation+'</strong></div><div class="coverage-row"><span>Historical held-out families</span><strong>'+D.meta.historical_counts.families+'</strong></div><p>All acyclic structures share one inferred family. The historical split does not evaluate that class. These are prefiltered, DFT-optimized, small fixed conformer pools; results do not establish general conformer-search performance.</p>';
    renderFailureRows();
  }
  function renderFailureRows() {
    const kind=$('failure-filter').value,query=$('failure-search').value.toLowerCase();
    const rows=D.failure_analysis.rows.filter(row=>(!query||row.molecule_id.toLowerCase().includes(query))&&(kind==='all'||kind==='rescued'&&row.rescued_on_second||kind==='remaining'&&row.regret_two>1+1e-9||kind==='changed'&&row.second_changes_selection));
    rows.sort((a,b)=>b.regret_two-a.regret_two||b.regret_one-a.regret_one||E.lexical(a.molecule_id,b.molecule_id));
    $('failure-count').textContent=rows.length+' cases'+(rows.length>100?' · first 100 shown':'');
    $('failure-rows').innerHTML=rows.length?rows.slice(0,100).map(row=>'<tr><td class="mono">'+esc(row.molecule_id)+(row.is_acyclic?'<span class="table-sub">Acyclic family</span>':'')+'</td><td class="mono '+(row.regret_one>1+1e-9?'negative':'')+'">'+number(row.regret_one,3)+'</td><td class="mono '+(row.regret_two>1+1e-9?'negative':'positive')+'">'+number(row.regret_two,3)+'</td><td class="mono">'+row.best_cheap_rank+'</td><td><button class="button small secondary" data-open-molecule="'+esc(row.molecule_id)+'">Open</button></td></tr>').join(''):'<tr><td class="empty" colspan="5">No development cases match this filter.</td></tr>';
  }
  function renderIntegrity() {
    const v=D.verification;
    const cards=[['Expanded experiment lab',v.lab,v.lab.verified?'Complete artifact seal':'Sweep pending'],['Historical evaluation',v.historical,v.historical.sealed_files.length+' primary files checked'],['Simulator inputs',v.prepared,'Development tables checked']];
    if(v.geometry?.available){cards.push(['Molecular coordinates',{verified:true,warnings:['Every atom-coordinate digest matches the original geometry manifest. Development IDs, source revision, input hashes, and compressed asset checksum checked. Bonds are display-only distance inference.']},number(v.geometry.candidate_count,0)+' geometries checked']);$('integrity-cards').classList.add('with-geometry');}
    $('integrity-cards').innerHTML=cards.map(([label,item,state])=>'<article class="integrity-card"><h2>'+esc(label)+'</h2><div class="state '+(!item.verified?'pending':'')+'">'+esc(state)+'</div><p>'+(item.warnings?.length?esc(item.warnings.join(' ')):label==='Simulator inputs'?'Feature IDs, family assignment, candidate counts, prepared checksums, and split self-hash checked. No evaluation reference table loaded.':'Declared artifact bytes checked against the saved seal at HTML build time.')+'</p></article>').join('');
    $('integrity-files').innerHTML=v.files.map(file=>'<tr><td class="mono">'+esc(file.name)+'<span class="table-sub">'+esc(file.scope)+'</span></td><td class="mono">'+number(file.bytes,0)+'</td><td>'+esc(file.verification_status||(file.sealed?(file.scope==='simulator_development'?'Prepared checksum checked':'Saved artifact seal checked'):'Hash recorded · outside artifact seal'))+'</td><td>'+esc(file.sha256)+'</td></tr>').join('');
    const limits=[...v.source_limits,'The new registry and CV use original development families only. The historical holdout is already observed and is not fresh validation.','Empirical sequential envelopes and one-query cheap-gap stops are heuristics, not guaranteed error bounds.','The browser contains inspectable development labels; the evaluator closure prevents accidental sharing with built-in policy functions, not malicious inspection.','Seals detect inconsistency against recorded hashes. They are not an external audit or proof that the underlying quantum calculations converged.'];
    $('scientific-limits').innerHTML=limits.map(text=>'<li>'+esc(text)+'</li>').join('');
  }
  function wireEvents() {
    document.querySelectorAll('[data-page]').forEach(node=>node.addEventListener('click',()=>switchPage(node.dataset.page)));
    document.querySelectorAll('[data-scope]').forEach(node=>node.addEventListener('click',()=>switchScope(node.dataset.scope)));
    for(const id of ['risk-filter','calls-filter','experiment-search'])$(id).addEventListener('input',()=>{page=0;renderExperiments();});
    $('kind-filter').addEventListener('change',()=>{page=0;renderExperiments();});
    $('target-filter').addEventListener('click',()=>{$('risk-filter').value='5';page=0;renderExperiments();});
    $('reset-filters').addEventListener('click',()=>{$('risk-filter').value='100';$('calls-filter').value=$('calls-filter').max;$('kind-filter').value='all';$('experiment-search').value='';page=0;renderExperiments();});
    document.querySelectorAll('[data-sort]').forEach(node=>node.addEventListener('click',()=>{if(sortField===node.dataset.sort)sortDescending=!sortDescending;else{sortField=node.dataset.sort;sortDescending=sortField==='success_rate';}page=0;renderExperiments();}));
    $('previous-page').addEventListener('click',()=>{page=Math.max(0,page-1);renderExperiments();});
    $('next-page').addEventListener('click',()=>{page++;renderExperiments();});
    $('experiment-rows').addEventListener('click',event=>{const target=event.target.closest('[data-experiment]');if(target)selectExperiment(target.dataset.experiment);});
    $('risk-chart').addEventListener('click',event=>{const target=event.target.closest('[data-point]');if(target)selectExperiment(target.dataset.point);});
    $('risk-chart').addEventListener('mousemove',event=>{const target=event.target.closest('[data-point]');if(!target){$('plot-tooltip').hidden=true;return;}const row=scopedRows().find(row=>row.config_id===target.dataset.point);if(!row)return;const tip=$('plot-tooltip');tip.innerHTML='<strong>'+esc(row.config_id)+'</strong><span>'+pct(row.success_rate)+' success · '+number(row.mean_calls,3)+' calls / molecule</span><span>'+esc(scope==='development'?'Pooled development · exploratory':scope==='cv'?'Out-of-fold development procedure':'Immutable historical evidence')+'</span>';tip.style.left=Math.min(event.clientX+15,window.innerWidth-350)+'px';tip.style.top=Math.max(10,event.clientY-85)+'px';tip.hidden=false;});
    $('risk-chart').addEventListener('mouseleave',()=>{$('plot-tooltip').hidden=true;});
    $('experiment-detail').addEventListener('click',event=>{const target=event.target.closest('[data-simulate]');if(!target)return;const row=D.experiments.find(row=>row.config_id===target.dataset.simulate);if(!row?.config)return;selectedRegistryConfig=row.config;const option=$('simulation-policy').querySelector('option[value="selected"]');option.disabled=false;option.textContent='Registry · '+row.config_id;$('simulation-policy').value='selected';resetTrial();switchPage('simulator');});
    $('export-experiments').addEventListener('click',()=>csvDownload(visibleExperiments,'aqc-'+scope+'-visible.csv'));
    $('molecule-search').addEventListener('input',renderMoleculeOptions);
    $('molecule-select').addEventListener('change',()=>{moleculeId=$('molecule-select').value;resetTrial();});
    $('simulation-policy').addEventListener('change',resetTrial);
    $('geometry-conformer').addEventListener('change',()=>{geometryChoice=$('geometry-conformer').value;$('geometry-follow').checked=false;renderGeometry();});
    $('geometry-style').addEventListener('change',renderGeometry);$('geometry-hydrogens').addEventListener('change',renderGeometry);$('geometry-follow').addEventListener('change',renderGeometry);$('geometry-spin').addEventListener('change',renderGeometry);
    $('geometry-reset').addEventListener('click',()=>{geometryViewer?.resetView();});
    $('geometry-reveal').addEventListener('click',()=>revealCandidate(geometryChoice));
    $('geometry-step-policy').addEventListener('click',stepPolicy);$('geometry-run-policy').addEventListener('click',runPolicy);$('geometry-finish-manual').addEventListener('click',finishManual);$('geometry-reset-trial').addEventListener('click',resetTrial);
    $('run-policy').addEventListener('click',runPolicy);$('step-policy').addEventListener('click',stepPolicy);$('play-policy').addEventListener('click',playPolicy);$('finish-manual').addEventListener('click',finishManual);$('reset-trial').addEventListener('click',resetTrial);
    $('candidate-rows').addEventListener('click',event=>{const target=event.target.closest('[data-reveal]');if(target)revealCandidate(target.dataset.reveal);});
    $('toggle-parameters').addEventListener('click',()=>{const show=$('simulation-parameters').hidden;$('simulation-parameters').hidden=!show;$('toggle-parameters').setAttribute('aria-expanded',String(show));$('toggle-parameters').textContent=show?'Hide policy parameters':'Policy parameters';});
    $('compare-policies').addEventListener('click',comparePolicies);
    $('export-trace').addEventListener('click',()=>{const snapshot=evaluator.snapshot();download(JSON.stringify({scope:'interactive_development_replay',molecule_id:moleculeId,family_id:currentPool().family_id,config:currentConfig,policy:currentConfig?.kind||'manual',...snapshot,policy_events:runner?.snapshot().events||[]},null,2)+'\n','aqc-trial-'+moleculeId+'.json');});
    $('failure-search').addEventListener('input',renderFailureRows);$('failure-filter').addEventListener('change',renderFailureRows);
    $('failure-rows').addEventListener('click',event=>{const target=event.target.closest('[data-open-molecule]');if(target)openMolecule(target.dataset.openMolecule);});
    document.querySelectorAll('.scope-tabs [role=tab]').forEach(node=>node.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight'].includes(event.key))return;const order=['development','cv','historical'],delta=event.key==='ArrowRight'?1:-1;switchScope(order[(order.indexOf(scope)+delta+3)%3]);document.querySelector('[data-scope="'+scope+'"]').focus();event.preventDefault();}));
  }
  try {
    const payloadNode=$('lab-payload');D=JSON.parse(payloadNode.textContent);
    bank=E.createEvaluatorBank(D.simulator_pools);catalog=bank.catalog;
    delete D.simulator_pools;payloadNode.remove();
    if(!catalog.length)throw new Error('No verified development simulator pools');
    const useful=D.failure_analysis.rows.find(row=>row.rescued_on_second);
    moleculeId=useful?.molecule_id||catalog[0].molecule_id;
    if(D.meta.pending)$('simulation-policy').querySelector('option[value="sequential"]').textContent='Sequential · demonstration parameters';
    renderGlobal();renderMoleculeOptions();wireEvents();switchScope('development');renderFolds();resetTrial();renderFailureAnatomy();renderIntegrity();
    if(D.meta.pending){$('simulator-scope').textContent='Expanded sweep pending. This simulator uses '+(D.meta.dataset_kind==='synthetic'?'a labeled synthetic engineering fixture':'the real original development pools')+'. Sequential settings here are demonstration parameters until fold-selected results are loaded. No new aggregate performance is claimed.';switchPage('simulator');}
    if(D.meta.dataset_kind==='synthetic'){$('simulator-title').textContent='Synthetic fixture simulator';$('candidate-note').textContent='Hand-authored synthetic energies; no real chemical measurements.';document.querySelector('.sidebar-note p').textContent='Labeled synthetic fixture. No chemical-performance claim.';}
    switchPage('simulator');
    loadGeometry();
    // A narrow inspection surface for functional tests; no unqueried labels.
    window.AQCLab=Object.freeze({switchPage,switchScope,stepPolicy,runPolicy,revealCandidate,finishManual,resetTrial,comparePolicies,openMolecule,
      state:()=>({page:activePage,scope,visibleExperiments:visibleExperiments.length,selectedExperiment:selectedExperiment?.config_id,moleculeId,simulation:evaluator.snapshot(),geometry:{available:!!geometryRecords,error:geometryError,candidate_id:geometryChoice,runtime_digest_verified:geometryRuntimeVerified,viewer:geometryViewer?.getState()||null}})});
  }catch(error){$('fatal-error').hidden=false;$('fatal-error').textContent='Workbench could not load verified evidence: '+error.message;$('top-integrity').textContent='Evidence unavailable';}
})();
