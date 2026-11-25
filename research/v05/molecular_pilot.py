"""New, generated molecular force-field pilot. Not quantum or MLIP validation."""
import argparse, csv, hashlib, json, math, platform, statistics, time
from pathlib import Path
import numpy as np
from rdkit import Chem, rdBase
from rdkit.Chem import AllChem

# Frozen before execution; explicit chemical-class blocks, not external families.
TRAIN = {'alkane':['CCCC','CCCCC','CCCCCC'], 'alcohol':['CCO','CCCO','CCCCO'],
 'ether':['COC','CCOC','CCOCC'], 'ketone':['CC(=O)C','CC(=O)CC','CC(=O)CCC'],
 'ester':['CC(=O)OC','CC(=O)OCC','CCC(=O)OC'], 'amine':['CCN','CCCN','CCNCC'],
 'cycloalkane':['C1CCCC1','C1CCCCC1','CC1CCCCC1'], 'aromatic':['c1ccccc1','Cc1ccccc1','CCc1ccccc1']}
TEST = {'amide':['CC(=O)N','CCC(=O)N','CC(=O)NC'], 'nitrile':['CC#N','CCC#N','CCCC#N'],
 'thioether':['CSC','CCSC','CCSCC'], 'haloalkane':['CCCl','CCCCl','CCCCCl']}
N=128; SEEDS=5; AMPS=(.05,.10,.20); PENALTIES=(.02,.05,.10); TOL=1.; DEGREE=16
CAND=np.round(np.linspace(0,N-1,10)).astype(int)
BASE_SEED=271828

def protocol():
 return {'train':TRAIN,'test':TEST,'seed':BASE_SEED,'directions':SEEDS,'amplitudes_angstrom_rms':AMPS,'points':N,'candidate_indices':CAND.tolist(),'degree':DEGREE,'tolerance_kcal_mol':TOL,'penalties':PENALTIES,'primary_penalty':.05,'cheap':'UFF','comparison':'MMFF94 (not quantum truth)','shape':'spectral power above degree 2; finite difference mean abs d2E/ds2','split':'explicit class blocks; generated cohort; no previous labels used; cross-class similarity not excluded','timing':'perf_counter_ns around batched CalcEnergy calls, single process, warmup before sampling; excludes setup and feature extraction; no monetary cost'}

def paths(center, seed, amp):
 rng=np.random.default_rng(seed); v=rng.normal(size=center.shape); v-=v.mean(axis=0); v/=np.linalg.norm(v); w=rng.normal(size=center.shape); w-=w.mean(axis=0); w-=np.sum(v*w)*v; w/=np.linalg.norm(w)
 radius=amp*math.sqrt(len(center)); t=np.linspace(-1,1,N); theta=np.linspace(0,2*np.pi,N,endpoint=False)
 linear=center+radius*t[:,None,None]*v
 circular=center+radius*(np.cos(theta)[:,None,None]*v+np.sin(theta)[:,None,None]*w)
 return {'linear':(linear,2*radius/(N-1)), 'circular':(circular,2*np.pi*radius/N)}

def metrics(e, ds, method):
 e=np.asarray(e,float); z=e-e.mean(); coef=np.polynomial.chebyshev.chebfit(np.linspace(-1,1,len(e)),z,DEGREE); p=np.square(coef[1:]); spectral=float(p[2:].sum()/p.sum()) if p.sum()>1e-24 else 0.
 d2=(np.roll(e,1)-2*e+np.roll(e,-1)) if method=='circular' else np.diff(e,n=2)
 return spectral,float(np.mean(np.abs(d2))/ds**2)

def energy(ff, xyz):
 start=time.perf_counter_ns(); e=np.array([ff.CalcEnergy(tuple(x.ravel())) for x in xyz]); elapsed=time.perf_counter_ns()-start
 if not np.isfinite(e).all(): raise ValueError('nonfinite energy')
 return e,elapsed

def build_rows():
 rows=[]; centers=[]; canon=set()
 for split,groups in [('train',TRAIN),('test',TEST)]:
  for family,smiles_list in groups.items():
   for smiles in smiles_list:
    key=Chem.MolToSmiles(Chem.MolFromSmiles(smiles)); assert key not in canon; canon.add(key)
    seed=int(hashlib.sha256(key.encode()).hexdigest()[:8],16)%2147483646+1
    m=Chem.AddHs(Chem.MolFromSmiles(smiles)); assert AllChem.EmbedMolecule(m,randomSeed=seed)==0
    assert AllChem.MMFFHasAllMoleculeParams(m) and AllChem.UFFHasAllMoleculeParams(m)
    assert AllChem.MMFFOptimizeMolecule(m,maxIters=1000)==0
    xyz=m.GetConformer().GetPositions(); props=AllChem.MMFFGetMoleculeProperties(m,mmffVariant='MMFF94'); cheap=AllChem.UFFGetMoleculeForceField(m,vdwThresh=1000); ref=AllChem.MMFFGetMoleculeForceField(m,props,nonBondedThresh=1000)
    cheap.CalcEnergy(tuple(xyz.ravel())); ref.CalcEnergy(tuple(xyz.ravel()))
    centers.append({'molecule':key,'family':family,'split':split,'atoms':[a.GetSymbol() for a in m.GetAtoms()],'coordinates':xyz.tolist(),'bonds':[[b.GetBeginAtomIdx(),b.GetEndAtomIdx()] for b in m.GetBonds()]})
    for direction in range(SEEDS):
     for amp in AMPS:
      for method,(points,ds) in paths(xyz,BASE_SEED+seed+direction,amp).items():
       # Alternate timing order; reference evaluation is retrospective only.
       if direction%2: y,tr=energy(ref,points); x,tc=energy(cheap,points)
       else: x,tc=energy(cheap,points); y,tr=energy(ref,points)
       cs,cm=metrics(x,ds,method); rs,rm=metrics(y,ds,method)
       order=CAND[np.argsort(x[CAND],kind='stable')]; best=y[CAND].min(); r1=float(y[order[0]]-best);r2=float(min(y[order[0]],y[order[1]])-best)
       rows.append(dict(split=split,family=family,molecule=key,direction=direction,amp=amp,method=method,gap=float(x[order[1]]-x[order[0]]),spectral=cs,mac=cm,ref_spectral=rs,ref_mac=rm,regret1=r1,regret2=r2,rescue=int(r1>TOL>=r2),cheap_ns=tc,reference_ns=tr,cheap_energy=(x-x.min()).tolist(),reference_energy=(y-y.min()).tolist(),coords=points[CAND].tolist()))
 return rows,centers

def fit(train, feature):
 assert train and all(r['split']=='train' for r in train)
 prior=(1+sum(r['rescue'] for r in train))/(2+len(train)); counts={}
 cuts={(a,m):statistics.median(r[feature] for r in train if r['amp']==a and r['method']==m) for a in AMPS for m in ('linear','circular')} if feature else {}
 def key(f):
  gap=sum(f['gap']>=b for b in (.1,.25,.5,1,2,4)); return (gap,int(f[feature]>=cuts[f['amp'],f['method']])) if feature else (gap,)
 for r in train:
  k=key(r);n,s=counts.get(k,(0,0));counts[k]=n+1,s+r['rescue']
 def predict(f):
  n,s=counts.get(key(f),(0,0));return (s+20*prior)/(n+20)
 return predict

def summarize(rows):
 train=[r for r in rows if r['split']=='train']; test=[r for r in rows if r['split']=='test']; assert set(r['family'] for r in train).isdisjoint(r['family'] for r in test)
 models={'gap':fit(train,None),'spectral':fit(train,'spectral'),'mac':fit(train,'mac')}; out=[]
 # Cost ratio estimated from training only. All timings empirical local CPU.
 ratio=sum(r['cheap_ns'] for r in train)/sum(r['reference_ns'] for r in train)
 for p in PENALTIES:
  for name in ['top1','top2',*models]:
   probs=[]; calls=0;success=0;regrets=[];cheap_points=0
   for r in test:
    features={k:r[k] for k in ('gap','amp','method','spectral','mac')}; prob=models[name](features) if name in models else None
    k=2 if name=='top2' or prob is not None and prob>p else 1
    regret=r['regret2'] if k==2 else r['regret1'];calls+=k;success+=regret<=TOL;regrets.append(regret);cheap_points+=N if name in ('spectral','mac') else 10
    if prob is not None:probs.append((prob-r['rescue'])**2)
   cost=calls+ratio*cheap_points
   out.append(dict(penalty=p,policy=name,n=len(test),success=int(success),calls=calls,cheap_points=cheap_points,mean_regret=statistics.mean(regrets),brier=statistics.mean(probs) if probs else None,cost=cost,utility=success/len(test)-p*cost/len(test)))
 pairs=[]
 for a in AMPS:
  for f in ('spectral','mac'):
   d={}
   for r in test:
    if r['amp']==a:d.setdefault((r['family'],r['molecule'],r['direction']),{})[r['method']]=r['ref_'+f]-r[f]
   family_means={fam:statistics.mean(v['linear']-v['circular'] for k,v in d.items() if k[0]==fam) for fam in TEST}
   pairs.append(dict(amp=a,metric=f,pairs=len(d),family_means=family_means,mean=statistics.mean(family_means.values())))
 return dict(scope='generated real molecular geometries; UFF versus MMFF94 force-field comparison, not quantum validation',protocol=protocol(),rdkit=rdBase.rdkitVersion,numpy=np.__version__,python=platform.python_version(),train_trajectories=len(train),test_trajectories=len(test),train_rescues=sum(r['rescue'] for r in train),test_rescues=sum(r['rescue'] for r in test),train_cost_ratio=ratio,train_cheap_us_per_point=sum(r['cheap_ns'] for r in train)/len(train)/N/1000,train_reference_us_per_point=sum(r['reference_ns'] for r in train)/len(train)/N/1000,test_cheap_us_per_point=sum(r['cheap_ns'] for r in test)/len(test)/N/1000,test_reference_us_per_point=sum(r['reference_ns'] for r in test)/len(test)/N/1000,policies=out,paired=pairs)

def main():
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--protocol-only',action='store_true');a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
 (a.out/'protocol.json').write_text(json.dumps(protocol(),indent=2)+'\n')
 if a.protocol_only:return
 rows,centers=build_rows();s=summarize(rows)
 (a.out/'summary.json').write_text(json.dumps(s,indent=2)+'\n');(a.out/'centers.json').write_text(json.dumps(centers,separators=(',',':'))+'\n')
 # Keep all trajectories and point energies; geometry recoverable from centre and seed.
 with (a.out/'trajectories.jsonl').open('w') as f:
  for r in rows:f.write(json.dumps({k:v for k,v in r.items() if k!='coords'},separators=(',',':'))+'\n')
 print(json.dumps({k:v for k,v in s.items() if k not in ('protocol','paired')},indent=2))
if __name__=='__main__':main()
