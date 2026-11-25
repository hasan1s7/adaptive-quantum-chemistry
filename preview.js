(function preview(){
  'use strict';
  const $=id=>document.getElementById(id);
  const E=window.AQCEngine;
  const cases={rescue:{cheap:[0,.1,.2,2.8,4],ref:[2.3,2.1,0,3.4,5]},waste:{cheap:[0,.1,.2,.3,.4],ref:[0,2,3,4,5]},early:{cheap:[0,2,2.4,3,4],ref:[3.2,.2,0,3,4]},tie:{cheap:[0,0,0,.5,2],ref:[1.5,.9,0,2,4]}};
  const names=['Fixed top-2','Cheap window','Sequential feedback','Full rerank'];
  const configs=[{kind:'fixed',k:2},{kind:'adaptive',k:2,gap:.25,cap:3},{kind:'sequential',one_gap:.01,one_ratio:.3,error_scale:1,slack:.25,cap:5},{kind:'full'}];
  let lanes=[],record,viewer=null;
  const symbols=['C','C','C','C','H','H','H','H','H','H','H','H','H','H'];
  function geometry(i){
    const theta=i*Math.PI/4, c=Math.cos(theta),s=Math.sin(theta);
    const atoms=[[0,0,0],[1.54,0,0],[2.05,1.45,0],[2.6,1.9+1.05*c,1.05*s]];
    const h=[[-.35,.7,.7],[-.35,-.95,.1],[-.35,.35,-.95],[1.9,-.5,.9],[1.9,-.5,-.9],[1.4,1.95,.8],[1.4,1.95,-.8],[3.45,1.9+1.05*c,.5+1.05*s],[2.1,2.5+1.05*c,.8+1.05*s],[2.1,2.5+1.05*c,-.8+1.05*s]];
    return {symbols,coordinates_angstrom:atoms.concat(h)};
  }
  function start(){
    const f=cases[$('scenario').value];record={candidates:f.cheap.map((v,i)=>({candidate_id:'C'+(i+1),cheap_kcal:v})),references:Object.fromEntries(f.ref.map((v,i)=>['C'+(i+1),v]))};
    lanes=configs.map(config=>{const evaluator=E.createEvaluator(record);return {evaluator,runner:E.createPolicyRunner(record.candidates,config,evaluator.query),config};});
    $('candidate').replaceChildren(...record.candidates.map(c=>new Option(c.candidate_id,c.candidate_id)));
    render();showGeometry();
  }
  function step(i,all=false){
    const l=lanes[i];if(l.runner.snapshot().done)return;
    const r=all?l.runner.run():l.runner.step();
    if(r.done&&r.result.selected_candidate)l.evaluator.finish(r.result.selected_candidate,r.result.stop_reason);
  }
  function render(){
    $('lanes').replaceChildren(...lanes.map((l,i)=>{
      const s=l.evaluator.snapshot(),r=l.runner.snapshot(),p=document.createElement('article');p.className='panel';
      const h=document.createElement('h2');h.textContent=names[i];p.append(h);
      const m=document.createElement('div');m.className='metric';m.textContent=s.expensive_calls+' / '+record.candidates.length;p.append(m);
      const t=document.createElement('div');t.className='sub';t.textContent='Simulated reference calls';p.append(t);
      const d=document.createElement('p');d.textContent=s.stopped?'Regret: '+s.evaluation.regret_kcal.toFixed(3)+' kcal/mol · '+(s.evaluation.success_within_1_kcal?'within tolerance':'missed tolerance'):'Next: '+(r.pending_candidate||'—')+' · regret hidden';p.append(d);
      const b=document.createElement('button');b.textContent=r.done?'Complete':'Step +1 query';b.disabled=r.done;b.onclick=()=>safe(()=>{step(i);render()});p.append(b);return p;
    }));
    const done=lanes.every(l=>l.runner.snapshot().done);$('step').disabled=done;$('run').disabled=done;
    inspect();
  }
  function inspect(){
    const i=Number($('lane').value),s=lanes[i].evaluator.snapshot(),r=lanes[i].runner.snapshot(),id=$('candidate').value;
    $('observation').textContent=names[i]+' · '+id+' · reference: '+(Object.hasOwn(s.observations,id)?s.observations[id].toFixed(3)+' kcal/mol':'not queried in this lane');
    $('energy').replaceChildren(...record.candidates.map(c=>{
      const row=document.createElement('div');row.className='energyrow'+(c.candidate_id===id?' active':'');
      const n=document.createElement('span');n.textContent=c.candidate_id;
      const bar=document.createElement('div');bar.className='bar';bar.style.width=(8+92*c.cheap_kcal/Math.max(...record.candidates.map(x=>x.cheap_kcal),1))+'%';
      const val=document.createElement('span');val.textContent=c.cheap_kcal.toFixed(2)+' cheap';row.append(n,bar,val);return row;
    }));
    $('trail').replaceChildren(...r.events.map(ev=>{const li=document.createElement('li');li.textContent=[ev.event,ev.candidate_id,ev.reason||ev.action].filter(Boolean).join(' · ');return li;}));
  }
  function showGeometry(){if(viewer)viewer.setGeometry(geometry(Number($('candidate').value.slice(1))-1),{molecule_id:'illustrative',candidate_id:$('candidate').value});}
  function safe(fn){try{$('error').hidden=true;fn()}catch(err){$('error').hidden=false;$('error').textContent=String(err.message||err)}}
  $('scenario').onchange=()=>safe(start);$('reset').onclick=()=>safe(start);
  $('step').onclick=()=>safe(()=>{lanes.forEach((_,i)=>step(i));render()});
  $('run').onclick=()=>safe(()=>{lanes.forEach((_,i)=>step(i,true));render()});
  $('lane').onchange=()=>safe(inspect);$('candidate').onchange=()=>safe(()=>{showGeometry();inspect()});
  $('style').onchange=()=>safe(()=>viewer&&viewer.setStyle($('style').value));
  $('hydrogens').onchange=()=>safe(()=>viewer&&viewer.setHydrogens($('hydrogens').checked));
  $('camera').onclick=()=>safe(()=>viewer&&viewer.resetView());
  $('export').onclick=()=>safe(()=>{const report={scope:'synthetic_browser_demo_not_scientific_evidence',scenario:$('scenario').value,lanes:lanes.map(l=>({config:l.config,state:l.evaluator.snapshot(),policy:l.runner.snapshot()}))};const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='aqc-synthetic-replay.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)});
  safe(start);try{viewer=window.AQCMoleculeViewer.create($('viewer'));showGeometry()}catch(err){$('viewer').textContent='3D unavailable: '+err.message;}
})();
