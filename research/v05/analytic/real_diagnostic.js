/* Exploratory, original-development-only analysis, not production acquisition. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const paths=['results/real/prepared/development_features.jsonl','results/real/prepared/development_references.jsonl','results/lab/folds.json'];
const pins=['12132b13d0b9629f346a12dd8b3cbb140a8c1334','38b2e40ba649166833452412b566af828aeec3d6','5d0af44eaa882ed2397846a3fd87f0e1b8422139'];
const ref='81e5fb8228ecd65e108f9d9a6edf325f3d2b5f7e';
function blobHash(b){return crypto.createHash('sha1').update(`blob ${b.length}\0`).update(b).digest('hex');}
function readPinned(root){return paths.map((p,i)=>{const b=fs.readFileSync(path.join(root,p));if(blobHash(b)!==pins[i])throw Error(`Source pin mismatch: ${p}`);return b.toString('utf8');});}
function analyze(raw) {
 const check=(cond,msg)=>{if(!cond)throw Error(msg)};
 const [features,refs]=raw.slice(0,2).map(s=>s.trim().split('\n').map(JSON.parse)),assignments=JSON.parse(raw[2]).assignments;
 const R=new Map(refs.map(r=>[r.molecule_id,r.references])),F=new Map(assignments.map(a=>[a.molecule_id,a])),families=new Map();
 const rows=features.map(f=>{const a=F.get(f.molecule_id),r=R.get(f.molecule_id);check(a&&r&&a.family_id===f.family_id&&a.n_candidates===f.candidates.length,'pair');check(!families.has(f.family_id)||families.get(f.family_id)===a.fold_id,'family split');families.set(f.family_id,a.fold_id);const c=[...f.candidates].sort((a,b)=>a.cheap_kcal-b.cheap_kcal||(a.candidate_id<b.candidate_id?-1:a.candidate_id>b.candidate_id?1:0));check(c.length>=2&&Object.keys(r).length===c.length&&new Set(c.map(x=>x.candidate_id)).size===c.length&&c.every(x=>Number.isFinite(x.cheap_kcal)&&Number.isFinite(r[x.candidate_id])),'candidate data');const best=Math.min(...Object.values(r)),reg1=r[c[0].candidate_id]-best,reg2=Math.min(r[c[0].candidate_id],r[c[1].candidate_id])-best;return {family:f.family_id,fold:a.fold_id,gap:c[1].cheap_kcal-c[0].cheap_kcal,reg1,reg2,rescue:+(reg1>1&&reg2<=1)}});
 check(rows.length===478&&new Set(features.map(x=>x.molecule_id)).size===478&&R.size===478&&F.size===478&&families.size===287,'cohort');
 const cut=[.1,.25,.5,1,2,4],bin=x=>cut.filter(t=>x>=t).length;
 const fit=train=>{const prior=(1+train.reduce((s,r)=>s+r.rescue,0))/(2+train.length),bs=Array.from({length:7},()=>[0,0]);for(const r of train){bs[bin(r.gap)][0]+=r.rescue;bs[bin(r.gap)][1]++}return {prior,p:x=>{const [k,n]=bs[bin(x)];return (k+20*prior)/(n+20)}}};
 const preds=rows.map(r=>{const m=fit(rows.filter(s=>s.fold!==r.fold));return {...r,prior:m.prior,p:m.p(r.gap)}});
 const brier=k=>preds.reduce((s,r)=>s+(r[k]-r.rescue)**2,0)/preds.length;
 const choose=(name,t,p,prior)=>name==='top2'||name==='gap'&&p>t||name==='constant'&&prior>t?2:1;
 const evaluate=(name,t)=>{let calls=0,success=0,regret=0,rescues=0;for(const r of preds){const k=choose(name,t,r.p,r.prior),reg=k===2?r.reg2:r.reg1;calls+=k;success+=+(reg<=1);regret+=reg;rescues+=+(k===2&&r.rescue)}return {name,threshold:t,calls,success,mean_regret:regret/preds.length,rescues}};
 const results=[evaluate('top1',null),evaluate('top2',null),...([.02,.05,.10].flatMap(t=>[evaluate('constant',t),evaluate('gap',t)]))];
 const bins=Array.from({length:7},(_,i)=>{const b=preds.filter(r=>bin(r.gap)===i);return {bin:i,n:b.length,observed_rescues:b.reduce((s,r)=>s+r.rescue,0),mean_prediction:b.length?b.reduce((s,r)=>s+r.p,0)/b.length:null}});
 const boot=([.02,.05,.10]).map(t=>{
 const g=[...families.keys()].sort().map(f=>preds.filter(r=>r.family===f).reduce((a,r)=>{const k=choose('gap',t,r.p,r.prior);a.n++;a.saved+=2-k;a.diff+=+((k===2?r.reg2:r.reg1)<=1)-+(r.reg2<=1);return a},{n:0,saved:0,diff:0}));
 let seed=271828;const random=()=>{seed=(Math.imul(1664525,seed)+1013904223)>>>0;return seed/4294967296};const saved=[],diff=[];
 for(let i=0;i<5000;i++){let n=0,s=0,d=0;for(let j=0;j<g.length;j++){const x=g[Math.floor(random()*g.length)];n+=x.n;s+=x.saved;d+=x.diff}saved.push(s/(2*n));diff.push(d/n);}
 const ci=a=>{a.sort((x,y)=>x-y);return [a[124],a[4874]]};return {threshold:t,call_saving_ci95:ci(saved),success_difference_ci95:ci(diff)};
 });
 return {rows:rows.length,families:families.size,folds:[...new Set(rows.map(r=>r.fold))].sort(),brier:{constant:brier('prior'),gap:brier('p')},results,bins,paired_family_bootstrap:{draws:5000,seed:271828,comparison:'gap vs top2; conditional on fitted cross-fold predictions',intervals:boot}};
}
if(require.main===module){if(process.argv.length!==4){console.error('Usage: node real_diagnostic.js <pinned-repo-root> <new-output.json>');process.exit(2);}const data=analyze(readPinned(process.argv[2]));fs.writeFileSync(process.argv[3],JSON.stringify({scope:'exploratory original-development family CV; no fresh holdout',ref,pins,...data},null,2)+'\n',{flag:'wx'});}
module.exports={analyze,blobHash,readPinned,paths,pins,ref};
