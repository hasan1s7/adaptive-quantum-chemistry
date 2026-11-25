"""Erkidu offline analytic shape stress lab. No molecular or quantum labels.

All model surfaces and reference surfaces are synthetic. Metrics are explicit
operational proxies, NOT an exact reproduction of the supplied thesis.
"""
from __future__ import annotations
import argparse, csv, json, math, random, statistics as st
from pathlib import Path

N = 128
DEGREE = 16
AMPLITUDES = (.05, .10, .20)
REGIMES = ('aligned', 'independent', 'anti_aligned', 'shift')
THRESHOLD = .1  # synthetic energy units, not kcal/mol
COSTS = (0., .001, .01)  # hypothetical cost per cheap evaluation / reference query
PENALTY = .05  # synthetic utility penalty per reference-query equivalent
TS = tuple(-math.cos(math.pi*j/(N-1)) for j in range(N))
BASIS = tuple(tuple(math.cos(k*math.pi*j/(N-1)) for j in range(N)) for k in range(DEGREE+1))

def metrics(y, speed):
    """Fraction of nonconstant Chebyshev spectral power above order 2;
    mean absolute d²E/ds² on the actual constant-speed path. Both use the
    same Lobatto samples; the latter is NOT curvature of the energy graph.
    """
    if len(y)!=N or not all(math.isfinite(v) for v in y) or not math.isfinite(speed) or speed<=0:
        raise ValueError('invalid energy trace or path speed')
    q=[v-y[0] for v in y]
    # DCT-I on the reversed Chebyshev grid: odd terms flip sign, power does not.
    c=[2/(N-1)*sum((.5 if j in (0,N-1) else 1)*v*b[j] for j,v in enumerate(q)) for b in BASIS]
    total=sum(v*v for v in c[1:]); tail=sum(v*v for v in c[3:])
    spectral=tail/total if total>1e-24 else 0.
    # Control volume around each interior sample; physical arc length s=speed*t.
    num=den=0.
    for j in range(1,N-1):
        a,b=TS[j]-TS[j-1],TS[j+1]-TS[j]
        d2=2*((q[j+1]-q[j])/b-(q[j]-q[j-1])/a)/(a+b)/speed**2
        w=(a+b)/2;num+=abs(d2)*w;den+=w
    return spectral,num/den

def point(t,a,theta,method):
    u=(math.cos(theta),math.sin(theta));v=(-u[1],u[0])
    if method=='linear': return a*t*u[0],a*t*u[1]
    phi=math.pi*(t+1)
    return a*(math.cos(phi)*u[0]+math.sin(phi)*v[0]),a*(math.cos(phi)*u[1]+math.sin(phi)*v[1])

def candidate_indices(method):
    # Exclude repeated endpoint for circle. Ten distinct candidates; all are
    # contained in the shape grid, so exactly 118 additional cheap evaluations.
    return tuple(round((N-1)*i/(9 if method=='linear' else 10)) for i in range(10))

def generate(regime,seed=271828,centres=60,seeds=5):
    if regime not in REGIMES or centres<10 or seeds<1: raise ValueError('bad design')
    rng=random.Random(seed); out=[]
    for centre in range(centres):
        split='train' if centre<2*centres//3 else 'test'
        rough=rng.uniform(.05,1.5); hidden=rng.uniform(.05,1.5)
        # Deliberate structural stress cases, not empirically estimated models.
        if regime=='aligned' or regime=='shift' and split=='train': error=.25+1.2*rough
        elif regime=='anti_aligned' or regime=='shift': error=.25+1.2*(1.55-rough)
        else: error=.25+1.2*hidden
        phase=[rng.uniform(-math.pi,math.pi) for _ in range(5)]
        lx,ly=rng.uniform(-5,5),rng.uniform(-5,5)
        def cheap(x,y):
            return lx*x+ly*y+5*x*x+3*y*y+rough*(.6*math.sin(29*x+13*y+phase[0])+.4*math.cos(17*x-31*y+phase[1]))
        def reference(x,y):
            return cheap(x,y)+error*(.6*math.sin(47*x-23*y+phase[2])+.4*math.cos(19*x+41*y+phase[3]))+.4*math.sin(7*x+9*y+phase[4])
        for s in range(seeds):
            theta=rng.uniform(0,2*math.pi)
            for a in AMPLITUDES:
                for method in ('linear','circular'):
                    xy=[point(t,a,theta,method) for t in TS]
                    ch=[cheap(*p) for p in xy]; ref=[reference(*p) for p in xy]
                    speed=a if method=='linear' else math.pi*a
                    cs,cm=metrics(ch,speed);rs,rm=metrics(ref,speed)
                    idx=candidate_indices(method); ranked=sorted(idx,key=lambda i:(ch[i],i))
                    best=min(ref[i] for i in idx);r1=ref[ranked[0]]-best;r2=min(ref[ranked[0]],ref[ranked[1]])-best
                    out.append(dict(regime=regime,centre=centre,split=split,seed=s,amplitude=a,method=method,gap=ch[ranked[1]]-ch[ranked[0]],cheap_spectral=cs,cheap_mac=cm,reference_spectral=rs,reference_mac=rm,delta_spectral=rs-cs,delta_mac=rm-cm,regret1=r1,regret2=r2,rescue=int(r1>THRESHOLD>=r2)))
    return out

def gap_bin(gap): return sum(gap>=x for x in (.01,.05,.20,.50))

def fit(train,shape=False):
    if not train or any(r['split']!='train' for r in train): raise ValueError('fit requires train only')
    # Shape threshold is fitted only on train centres. Within amplitude/method
    # avoids treating their different scales as shape signal.
    cuts={(a,m):st.median(r['cheap_spectral'] for r in train if (r['amplitude'],r['method'])==(a,m)) for a in AMPLITUDES for m in ('linear','circular')}
    prior=(1+sum(r['rescue'] for r in train))/(2+len(train)); counts={}
    def key(f):
        g=gap_bin(f['gap']);return (g,int(f['cheap_spectral']>=cuts[(f['amplitude'],f['method'])])) if shape else (g,)
    for r in train:
        k=key(r);n,y=counts.get(k,(0,0));counts[k]=(n+1,y+r['rescue'])
    def predict(features):
        n,y=counts.get(key(features),(0,0));return (y+20*prior)/(n+20)
    return predict

def policy(probability,penalty=PENALTY):
    # Called with probability only, never reference labels or regret.
    return 2 if probability>penalty else 1

def evaluate(rows):
    train=[r for r in rows if r['split']=='train'];test=[r for r in rows if r['split']=='test']
    assert set(r['centre'] for r in train).isdisjoint(r['centre'] for r in test)
    gap,shape=fit(train),fit(train,True);results=[]
    for name,model in [('top1',None),('top2',None),('gap',gap),('gap_shape',shape)]:
        preds=[];calls=success=0;regrets=[]
        for r in test:
            features={k:r[k] for k in ('gap','cheap_spectral','amplitude','method')}
            p=model(features) if model else None
            if p is not None: preds.append((p-r['rescue'])**2)
            k=1 if name=='top1' else 2 if name=='top2' else policy(p)
            regret=r['regret1'] if k==1 else r['regret2'];calls+=k;success+=regret<=THRESHOLD;regrets.append(regret)
        # All methods pay for ten candidate predictions. Shape additionally
        # pays for 118 evaluations in a new fixed sampled path. No ref shape
        # metrics are made available to decision or fit features.
        extra=(N-10 if name=='gap_shape' else 0)*len(test)
        results.append(dict(policy=name,n=len(test),success=success,calls=calls,additional_cheap_evaluations=extra,mean_regret=st.mean(regrets),brier=st.mean(preds) if preds else None,cost_sensitivity=[dict(cheap_unit_cost=c,total_cost=calls+c*(10*len(test)+extra),utility=success/len(test)-PENALTY*(calls+c*(10*len(test)+extra))/len(test)) for c in COSTS]))
    return results

def cluster_interval(values,seed=271828,draws=1000):
    # Equal centre weighting. Every centre contributes the same number of pairs.
    groups=sorted(values); means=[st.mean(values[g]) for g in groups];rng=random.Random(seed)
    draws_=sorted(st.mean(rng.choices(means,k=len(means))) for _ in range(draws))
    return dict(centre_mean=st.mean(means),ci95=[draws_[int(.025*draws)],draws_[min(draws-1,int(.975*draws))]],centres=len(means),draws=draws)

def paired(rows):
    test=[r for r in rows if r['split']=='test'];out=[]
    for a in AMPLITUDES:
        matches={}
        for r in test:
            if r['amplitude']==a: matches.setdefault((r['centre'],r['seed']),{})[r['method']]=r
        for field in ('delta_spectral','delta_mac'):
            values={};linear=[];circular=[]
            for (centre,_),pair in matches.items():
                l,c=pair['linear'][field],pair['circular'][field];linear.append(l);circular.append(c);values.setdefault(centre,[]).append(l-c)
            out.append(dict(amplitude=a,metric=field,pairs=len(matches),linear_median=st.median(linear),circular_median=st.median(circular),**cluster_interval(values)))
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    rows=[];summary={'scope':'analytic synthetic stress test; no molecular measurements','seed':271828,'centres_per_regime':60,'train_centres':40,'test_centres':20,'seeds_per_centre':5,'amplitudes':AMPLITUDES,'points_per_path':N,'reference_success_tolerance_synthetic_units':THRESHOLD,'decision_penalty':PENALTY,'regimes':{}}
    for regime in REGIMES:
        data=generate(regime);rows.extend(data);summary['regimes'][regime]={'policy':evaluate(data),'paired_shape':paired(data)}
    summary['trajectory_count']=len(rows);summary['sample_count_per_fidelity']=len(rows)*N
    with (args.out/'trajectories.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
    (args.out/'synthetic-results.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:[{z:r[z] for z in ('policy','success','calls','brier')} for r in v['policy']] for k,v in summary['regimes'].items()},indent=2))
if __name__=='__main__':main()
