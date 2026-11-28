#!/usr/bin/env python3
"""Development-only equal-budget conformer decision audit.

PLAN deliberately opens no reference-energy file. SCORE reveals labels only after
recomputing and verifying the sealed plan. Data/code are never pushed or deployed.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
import time
import numpy as np

PIN = '6d81701875b996426c07f383789767ea423a899a'
H = {
 'development_features.jsonl':'9f59c48bd532f4abd0184fdfb2392bcb4e02b410cb8c526fec01a24a5c0b62a0',
 'development_geometry.json.gz':'05949303658ab98af392c79a6b9f63cfd8ca310f3faf1bfcf57d38106308df7a',
 'folds.json':'969e74925d1d3c8144216590e3e5a968218360bc158f56a2df0e9b5a86e5fc7f',
 'development_references.jsonl':'396365e0b1987f773beeff0b4daba75f9201af14a934de76deef51864c97296c',
}
COV = {'H':.31,'C':.76,'N':.71,'O':.66,'F':.57,'P':1.07,'S':1.05,'Cl':1.02,'Br':1.20}
VDW = {'H':1.20,'C':1.70,'N':1.55,'O':1.52,'F':1.47,'P':1.80,'S':1.80,'Cl':1.75,'Br':1.85}
WINDOW = 2.0   # cheap-energy kcal/mol relative to rank #2
STER_SCALE = .80
BOND_SCALE = 1.25
THRESHOLD = 1.0
SEVERE = 3.0
POLICIES = ('top2','torsion','steric','torsion_plus_steric')
SCHEMA = 'erkidu-two-call/development-v1'
SEED = 271828
B = 2000

def sha_bytes(x:bytes)->str:return hashlib.sha256(x).hexdigest()
def canonical(o)->str:return json.dumps(o,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def sha_json(o)->str:return sha_bytes(canonical(o).encode())
def check_hash(inputs:Path,name:str)->None:
    got=sha_bytes((inputs/name).read_bytes())
    if got != H[name]:raise ValueError(f'Input identity mismatch: {name}: {got}')
def lines(path):return [json.loads(s) for s in path.read_text().splitlines()]
def mapped(rows,key):
    d={key(r):r for r in rows}
    if len(rows)!=len(d):raise ValueError('Duplicate ID')
    return d

def load_prelabel(inputs):
    # The references filename is not opened, read, or hashed in this function.
    for name in ('development_features.jsonl','development_geometry.json.gz','folds.json'): check_hash(inputs,name)
    feats=mapped(lines(inputs/'development_features.jsonl'),lambda x:x['molecule_id'])
    with gzip.open(inputs/'development_geometry.json.gz','rt') as f:geo=json.load(f)
    geoms=mapped(geo['molecules'],lambda x:x['molecule_id'])
    folds=mapped(json.loads((inputs/'folds.json').read_text())['assignments'],lambda x:x['molecule_id'])
    if not(len(feats)==478 and feats.keys()==geoms.keys()==folds.keys()):raise ValueError('Pool sets differ')
    result={};famfold=defaultdict(set)
    for mid in sorted(feats):
        f=feats[mid]; g=mapped(geoms[mid]['candidates'],lambda x:x['candidate_id'])
        c=mapped(f['candidates'],lambda x:x['candidate_id']);fold=folds[mid]
        if set(c)!=set(g) or len(c)<2 or f['family_id']!=fold['family_id']:raise ValueError('Geometry/feature mismatch '+mid)
        order=sorted(c,key=lambda x:(float(c[x]['cheap_kcal']),x))
        sym=g[order[0]]['symbols'];n=len(sym)
        if n<2 or any(s not in COV for s in sym):raise ValueError('Invalid elements '+mid)
        for cid in order:
            arr=np.asarray(g[cid]['coordinates_angstrom'],dtype=float)
            if g[cid]['symbols']!=sym or arr.shape!=(n,3) or not np.all(np.isfinite(arr)) or not math.isfinite(float(c[cid]['cheap_kcal'])):
                raise ValueError('Invalid prelabel geometry '+mid+'/'+cid)
        result[mid]={'order':order,'family':f['family_id'],'fold':int(fold['fold_id']),
                     'cheap':{cid:float(c[cid]['cheap_kcal']) for cid in order},'geom':g,'symbols':sym}
        famfold[f['family_id']].add(fold['fold_id'])
    if len(famfold)!=287 or any(len(x)!=1 for x in famfold.values()):raise ValueError('Family contamination')
    return result

def bond_topology(symbols,xyz):
    n=len(symbols);graph=[set() for _ in range(n)]
    for i in range(n):
        for j in range(i+1,n):
            d=float(np.linalg.norm(xyz[i]-xyz[j]))
            if .55 < d < BOND_SCALE*(COV[symbols[i]]+COV[symbols[j]]):
                graph[i].add(j);graph[j].add(i)
    return graph

def is_bridge(graph,a,b):
    seen={a};stack=[a]
    while stack:
        v=stack.pop()
        for w in graph[v]:
            if (v==a and w==b) or (v==b and w==a):continue
            if w not in seen:seen.add(w);stack.append(w)
    return b not in seen

def torsion_quadruples(graph,symbols):
    out=[];heavy=lambda i:symbols[i]!='H'
    for a in range(len(graph)):
        if not heavy(a):continue
        for b in sorted(graph[a]):
            if b<=a or not heavy(b) or not is_bridge(graph,a,b):continue
            left=sorted(i for i in graph[a] if i!=b and heavy(i))
            right=sorted(i for i in graph[b] if i!=a and heavy(i))
            if left and right:out.append((left[0],a,b,right[0]))
    return out

def angle(x,q):
    i,j,k,l=q; b0=x[i]-x[j];b1=x[k]-x[j];b2=x[l]-x[k]
    norm=float(np.linalg.norm(b1))
    if norm<1e-9:return None
    b1=b1/norm
    v=b0-np.dot(b0,b1)*b1;w=b2-np.dot(b2,b1)*b1
    if np.linalg.norm(v)<1e-8 or np.linalg.norm(w)<1e-8:return None
    return math.atan2(float(np.dot(np.cross(b1,v),w)),float(np.dot(v,w)))

def heavy_nonbonded(symbols,graph):
    ix=[i for i,s in enumerate(symbols) if s!='H'];pairs=[]
    for ii,i in enumerate(ix):
        for j in ix[ii+1:]:
            if j in graph[i] or any(j in graph[k] for k in graph[i]):continue
            pairs.append((i,j))
    return pairs

def overlap(x,symbols,pairs):
    if not pairs:return None
    penalty=0.
    for i,j in pairs:
        cutoff=STER_SCALE*(VDW[symbols[i]]+VDW[symbols[j]])
        distance=float(np.linalg.norm(x[i]-x[j]))
        penalty+=(max(0.,cutoff-distance)/cutoff)**2
    return penalty/max(1,sum(s!='H' for s in symbols))

def feature_scores(pool,eligible):
    order=pool['order'];x0=np.asarray(pool['geom'][order[0]]['coordinates_angstrom'],dtype=float)
    graph=bond_topology(pool['symbols'],x0)
    quads=torsion_quadruples(graph,pool['symbols'])
    pairs=heavy_nonbonded(pool['symbols'],graph)
    a0=[angle(x0,q) for q in quads]
    ans={};bad_torsion=False;bad_steric=False
    for cid in eligible:
        x=np.asarray(pool['geom'][cid]['coordinates_angstrom'],dtype=float)
        ang=[angle(x,q) for q in quads]
        if not quads or any(a is None for a in a0+ang):t=None;bad_torsion=True
        else:t=math.sqrt(sum(math.atan2(math.sin(a-b),math.cos(a-b))**2 for a,b in zip(ang,a0))/len(ang))
        s=overlap(x,pool['symbols'],pairs)
        if s is None:bad_steric=True
        ans[cid]={'torsion_rms_rad':t,'steric_overlap_per_heavy':s}
    return ans,{'inferred_bonds':sum(len(v) for v in graph)//2,
                'rotatable_torsions':len(quads),'nonbonded_heavy_pairs':len(pairs),
                'torsion_valid':not bad_torsion,'steric_valid':not bad_steric,
                'topology_source':'inferred_from_rank1_xyz_unreviewed'}

def choose(pool):
    order=pool['order'];c=pool['cheap'];rank2=order[1]
    eligible=[cid for cid in order[1:5] if c[cid]-c[rank2]<=WINDOW+1e-12]
    vals,quality=feature_scores(pool,eligible)
    choices={'top2':rank2}; reasons={'top2':'fixed cheap rank 2'}
    if quality['torsion_valid']:
        choices['torsion']=max(eligible,key=lambda cid:(vals[cid]['torsion_rms_rad'],-order.index(cid),cid))
        reasons['torsion']='max torsional distance from rank 1'
    else:choices['torsion']=rank2;reasons['torsion']='invalid/no torsions; rank2 fallback'
    if quality['steric_valid']:
        choices['steric']=min(eligible,key=lambda cid:(vals[cid]['steric_overlap_per_heavy'],order.index(cid),cid))
        reasons['steric']='min normalized nonbonded heavy-atom overlap'
    else:choices['steric']=rank2;reasons['steric']='invalid/no nonbonded pairs; rank2 fallback'
    if quality['torsion_valid'] and quality['steric_valid']:
        t=[vals[x]['torsion_rms_rad'] for x in eligible]
        s=[vals[x]['steric_overlap_per_heavy'] for x in eligible]
        def norm(v,z,positive):
            lo=min(v);hi=max(v)
            return (z-lo)/(hi-lo) if hi-lo>1e-12 else 0.
        score={cid:norm(t,vals[cid]['torsion_rms_rad'],True)-norm(s,vals[cid]['steric_overlap_per_heavy'],False) for cid in eligible}
        choices['torsion_plus_steric']=max(eligible,key=lambda cid:(score[cid],-order.index(cid),cid))
        reasons['torsion_plus_steric']='unweighted normalized torsion minus steric ablation'
    else:choices['torsion_plus_steric']=rank2;reasons['torsion_plus_steric']='feature unavailable; rank2 fallback'
    hashes={cid:sha_json(pool['geom'][cid]) for cid in order}
    return {'pool_id':None,'family_id':pool['family'],'fold_id':pool['fold'],
            'candidate_ids_xTB_order':order,'geometry_sha256':hashes,
            'cheap_kcal':pool['cheap'],'eligible':eligible,
            'feature_values':vals,'feature_quality':quality,
            'choices':choices,'choice_reasons':reasons,'first_call':order[0],
            'calls_planned_per_policy':2}

def compute_plan(pools):
    rows=[];clock={p:0 for p in POLICIES}
    for mid in sorted(pools):
        t=time.process_time_ns();r=choose(pools[mid]);spent=time.process_time_ns()-t
        clock['top2']+=0;clock['torsion']+=spent # joint feature extraction, not attributable to a policy
        r['pool_id']=mid;rows.append(r)
    return rows,clock

def plan_cmd(inp,out):
    if out.exists() and any(out.iterdir()):raise ValueError('Refusing to overwrite previous plan')
    out.mkdir(parents=True,exist_ok=True)
    t=time.perf_counter();pools=load_prelabel(inp);load_s=time.perf_counter()-t
    t=time.perf_counter();rows,clock=compute_plan(pools);plan_s=time.perf_counter()-t
    raw=''.join(canonical(r)+'\n' for r in rows).encode()
    (out/'sealed_prelabel_plan.jsonl').write_bytes(raw)
    manifest={'schema':SCHEMA,'evidence_scope':'development_only_prelabel','repository_pin':PIN,
      'policies':list(POLICIES),'reference_file_opened_during_plan':False,
      'configuration':{'budget':2,'first_rank':1,'eligible_ranks':[2,3,4,5],
                       'energy_window_relative_to_rank2_kcal':WINDOW,
                       'steric_radius_factor':STER_SCALE,'bond_inference_factor':BOND_SCALE,
                       'threshold_kcal':THRESHOLD,'severe_miss_kcal':SEVERE,
                       'resampling_seed':SEED,'cluster_bootstrap_draws':B},
      'source_input_hashes':{k:H[k] for k in ('development_features.jsonl','development_geometry.json.gz','folds.json')},
      'plan_sha256':sha_bytes(raw),'policy_code_sha256':sha_bytes(Path(__file__).read_bytes()),
      'pools':len(rows),'families':len(set(x['family_id'] for x in rows)),
      'mean_candidate_count':sum(len(x['candidate_ids_xTB_order']) for x in rows)/len(rows),
      'measured_local_prelabel_seconds':{'input_loading_wall_clock':load_s,'feature_and_policy_wall_clock':plan_s,
       'feature_and_policy_joint_cpu_seconds':clock['torsion']/1e9},
      'limitations':'XYZ connectivity inferred; no chemistry review, queue or reference-job timing'}
    (out/'freeze.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    print('PLAN SEALED',len(rows),'pools',len(set(x['family_id'] for x in rows)),'families',manifest['plan_sha256'])

def load_labels(inp,pools):
    check_hash(inp,'development_references.jsonl')
    refs=mapped(lines(inp/'development_references.jsonl'),lambda x:x['molecule_id'])
    if set(refs)!=set(pools):raise ValueError('Label pool mismatch')
    out={}
    for mid in refs:
        r={cid:float(e) for cid,e in refs[mid]['references'].items()}
        if set(r)!=set(pools[mid]['order']) or not all(math.isfinite(e) for e in r.values()):
            raise ValueError('Label identity invalid '+mid)
        out[mid]=r
    return out

def metrics(rows):
    v=np.array([r['regret_kcal'] for r in rows]);n=len(rows)
    return {'pools':n,'success':int(sum(r['success'] for r in rows)),
      'success_rate':sum(r['success'] for r in rows)/n,'mean_regret_kcal':float(np.mean(v)),
      'median_regret_kcal':float(np.median(v)),'p90_regret_kcal':float(np.quantile(v,.9)),
      'p95_regret_kcal':float(np.quantile(v,.95)),'p99_regret_kcal':float(np.quantile(v,.99)),
      'worst_regret_kcal':float(np.max(v)),'severe_misses_gt3':int(np.sum(v>SEVERE)),
      'attempted_calls':sum(r['attempted_calls'] for r in rows),
      'replayed_completed_labels':sum(r['replayed_completed_labels'] for r in rows)}

def compare(rows,other):
    lookup={r['pool_id']:r for r in other};w=l=t=0;rw=rl=rt=0;rescues=[];harms=[]
    for r in rows:
        base=lookup[r['pool_id']]
        if r['success']>base['success']:w+=1;rescues.append(r['pool_id'])
        elif r['success']<base['success']:l+=1;harms.append(r['pool_id'])
        else:t+=1
        d=r['regret_kcal']-base['regret_kcal']
        if d<-1e-9:rw+=1
        elif d>1e-9:rl+=1
        else:rt+=1
    return {'threshold_gains':w,'threshold_losses':l,'threshold_ties':t,
            'regret_wins':rw,'regret_losses':rl,'regret_ties':rt,
            'rescued_pool_ids':rescues,'harmed_pool_ids':harms}

def paired_family_bootstrap(by_policy,seed=SEED,draws=B):
    rng=np.random.default_rng(seed);base=by_policy['top2'];fams=defaultdict(list)
    for i,r in enumerate(base):fams[r['family_id']].append(i)
    keys=sorted(fams);ix=[np.array(fams[k],dtype=int) for k in keys];n=len(keys)
    bsucc=np.array([r['success'] for r in base]);breg=np.array([r['regret_kcal'] for r in base])
    out={}
    for policy,rows in by_policy.items():
        if policy=='top2':continue
        ds=np.array([r['success'] for r in rows])-bsucc
        dr=np.array([r['regret_kcal'] for r in rows])-breg
        s=[];rg=[]
        for _ in range(draws):
            sample=rng.integers(0,n,size=n)
            chosen=np.concatenate([ix[j] for j in sample])
            s.append(float(np.mean(ds[chosen])));rg.append(float(np.mean(dr[chosen])))
        out[policy]={'delta_success_rate':float(np.mean(ds)),
          'success_diff_cluster_bootstrap_95':[float(x) for x in np.quantile(s,[.025,.975])],
          'delta_mean_regret_kcal':float(np.mean(dr)),
          'regret_diff_cluster_bootstrap_95':[float(x) for x in np.quantile(rg,[.025,.975])],
          'clusters':n,'draws':draws,'seed':seed,
          'interpretation':'development descriptive, conditional on frozen policy and inferred family assignments'}
    return out

def score_cmd(inp,out):
    freeze=json.loads((out/'freeze.json').read_text());raw=(out/'sealed_prelabel_plan.jsonl').read_bytes()
    if freeze['schema']!=SCHEMA or freeze['plan_sha256']!=sha_bytes(raw) or freeze['policy_code_sha256']!=sha_bytes(Path(__file__).read_bytes()):
        raise ValueError('Plan or code seal mismatch')
    pools=load_prelabel(inp)
    recomputed,_=compute_plan(pools)
    if raw != ''.join(canonical(r)+'\n' for r in recomputed).encode():raise ValueError('Plan drift on recompute')
    rows=[json.loads(x) for x in raw.decode().splitlines()]
    # Deliberate label boundary: open references only below this line.
    refs=load_labels(inp,pools)
    outrows=[];by_policy={p:[] for p in POLICIES};cases=[]
    for r in rows:
        mid=r['pool_id'];lab=refs[mid];best=min(lab.values());order=r['candidate_ids_xTB_order'];first=order[0]
        if len(order)>=4:
            r2=min(lab[first],lab[order[1]])-best
            r4=min(lab[first],lab[order[3]])-best
            category='rescue' if r2>THRESHOLD and r4<=THRESHOLD else 'harm' if r2<=THRESHOLD and r4>THRESHOLD else None
            if category:
                cases.append({'kind':category,'pool_id':mid,'family_id':r['family_id'],
                  'candidate_rank_1':first,'candidate_rank_2':order[1],'candidate_rank_4':order[3],
                  'geometry_sha256':{x:r['geometry_sha256'][x] for x in (first,order[1],order[3])},
                  'cheap_gap_rank2_minus_rank1_kcal':r['cheap_kcal'][order[1]]-r['cheap_kcal'][first],
                  'cheap_gap_rank4_minus_rank1_kcal':r['cheap_kcal'][order[3]]-r['cheap_kcal'][first],
                  'pre_reference_feature_rank2':r['feature_values'].get(order[1]),
                  'pre_reference_feature_rank4':r['feature_values'].get(order[3]),
                  'regret_top2_kcal':r2,'regret_rank4_kcal':r4,
                  'paired_regret_difference_abs':abs(r2-r4),
                  'hypothesis_status':'no qualified chemist review; retrospective development'})
        for policy in POLICIES:
            second=r['choices'][policy]
            if second==first or second not in r['eligible']:raise ValueError('Invalid second action '+mid)
            queried=(first,second)
            regret=min(lab[x] for x in queried)-best
            row={'pool_id':mid,'family_id':r['family_id'],'fold_id':r['fold_id'],
              'policy':policy,'query1_candidate_id':first,'query2_candidate_id':second,
              'query2_rank':order.index(second)+1,'attempted_calls':2,'replayed_completed_labels':2,
              'real_jobs_submitted':0,'real_jobs_completed':0,'real_jobs_failed':0,'real_jobs_retried':0,
              'best_pool_candidate_id':min(order,key=lambda x:(lab[x],order.index(x))),
              'regret_kcal':regret,'success':int(regret<=THRESHOLD),
              'geometry_hash_query1':r['geometry_sha256'][first],
              'geometry_hash_query2':r['geometry_sha256'][second],
              'query2_xtb_delta_vs_2_kcal':r['cheap_kcal'][second]-r['cheap_kcal'][order[1]],
              'second_choice_reason':r['choice_reasons'][policy]}
            outrows.append(row);by_policy[policy].append(row)
    cases.sort(key=lambda x:(-x['paired_regret_difference_abs'],x['pool_id']))
    outcome={'scope':'retrospective_development_only_not_independent_validation',
      'reference_inputs_sha256':H['development_references.jsonl'],
      'sealed_plan_sha256':freeze['plan_sha256'],'source_pin':PIN,
      'candidate_pool_count':len(rows),'chemical_family_count':len(set(x['family_id'] for x in rows)),
      'policy_metrics':{name:metrics(rows) for name,rows in by_policy.items()},
      'paired_vs_top2':{p:compare(by_policy[p],by_policy['top2']) for p in POLICIES if p!='top2'},
      'cluster_bootstrap':paired_family_bootstrap(by_policy),
      'by_fold':{p:{str(f):metrics([r for r in rs if r['fold_id']==f]) for f in sorted(set(r['fold_id'] for r in rs))} for p,rs in by_policy.items()},
      'families':{p:{fam:metrics([r for r in rs if r['family_id']==fam]) for fam in sorted(set(r['family_id'] for r in rs))} for p,rs in by_policy.items()},
      'rank4_counterexamples':{'rescue_count':sum(x['kind']=='rescue' for x in cases),
                               'harm_count':sum(x['kind']=='harm' for x in cases),
                               'sorted_case_count':len(cases)},
      'reference_accounting':{p:{'attempted_offline_replay_calls':2*len(rows),
                                  'labels_replayed_as_completed':2*len(rows),
                                  'live_submissions':0,'live_completed':0,'live_failed':0,
                                  'free_replacement_calls':0} for p in POLICIES},
      'scheduling':'not measured; no real quantum jobs; no parallelism or queue cost measured'}
    (out/'results.json').write_text(json.dumps(outcome,indent=2,sort_keys=True)+'\n')
    with (out/'per_pool.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=outrows[0].keys());w.writeheader();w.writerows(outrows)
    (out/'rank4_rescue_harm.json').write_text(json.dumps(cases,indent=2,sort_keys=True)+'\n')
    print('SCORED DEVELOPMENT',len(rows),'pools')
    for name,rs in by_policy.items():
        v=metrics(rs);print(name,v['success'],'/',v['pools'],'mean regret',round(v['mean_regret_kcal'],4),
                                 'p95',round(v['p95_regret_kcal'],4),'attempts',v['attempted_calls'])
    print('rank4 rescues/harm',outcome['rank4_counterexamples'])

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('plan','score'))
    parser.add_argument('--inputs',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    a=parser.parse_args()
    if a.stage=='plan':plan_cmd(a.inputs,a.out)
    else:score_cmd(a.inputs,a.out)
if __name__=='__main__':main()
