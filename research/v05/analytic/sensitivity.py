"""Post-initial-run exploratory cost sweep; consumes the existing synthetic CSV."""
import csv,json,statistics as st,sys
from pathlib import Path
from shape_lab import AMPLITUDES, COSTS, REGIMES, THRESHOLD, N, gap_bin, policy

def main():
    source=Path(sys.argv[1]);out=Path(sys.argv[2])
    if out.exists():raise FileExistsError(out)
    rows=list(csv.DictReader(source.open()))
    for r in rows:
        for k in ('amplitude','gap','cheap_spectral','cheap_mac','regret1','regret2'):r[k]=float(r[k])
        for k in ('centre','rescue'):r[k]=int(r[k])
    result=[]
    for regime in REGIMES:
        train=[r for r in rows if r['regime']==regime and r['split']=='train'];test=[r for r in rows if r['regime']==regime and r['split']=='test']
        prior=(1+sum(r['rescue'] for r in train))/(2+len(train))
        for name,fields in [('gap',()),('gap_spectral',('cheap_spectral',)),('gap_mac',('cheap_mac',)),('gap_both',('cheap_spectral','cheap_mac'))]:
            cuts={(f,a,m):st.median(r[f] for r in train if (r['amplitude'],r['method'])==(a,m)) for f in fields for a in AMPLITUDES for m in ('linear','circular')}
            def key(r):return (gap_bin(r['gap']),)+tuple(int(r[f]>=cuts[(f,r['amplitude'],r['method'])]) for f in fields)
            counts={}
            for r in train:
                k=key(r);n,y=counts.get(k,(0,0));counts[k]=(n+1,y+r['rescue'])
            preds=[]
            for r in test:
                n,y=counts.get(key(r),(0,0));preds.append((y+20*prior)/(n+20))
            brier=st.mean((p-r['rescue'])**2 for p,r in zip(preds,test));extra=(N-10)*len(test) if fields else 0
            for penalty in (.05,.10,.15,.20,.25):
                ks=[policy(p,penalty) for p in preds];calls=sum(ks);success=sum((r['regret1'] if k==1 else r['regret2'])<=THRESHOLD for r,k in zip(test,ks));n=len(test)
                result.append(dict(regime=regime,policy=name,penalty=penalty,n=n,success=success,calls=calls,brier=brier,extra_cheap_evaluations=extra,cost_sensitivity=[dict(cheap_unit_cost=c,total_cost=calls+c*(10*n+extra),utility=(success-penalty*(calls+c*(10*n+extra)))/n) for c in COSTS]))
    out.write_text(json.dumps({'scope':'post-initial-run exploratory sensitivity; no selection or independent test','rows':result},indent=2)+'\n')
    print('rows',len(result))
    for c in COSTS:
        comparisons=[]
        for r in result:
            if r['policy']=='gap':continue
            baseline=next(b for b in result if b['policy']=='gap' and b['regime']==r['regime'] and b['penalty']==r['penalty'])
            u=lambda x:next(y['utility'] for y in x['cost_sensitivity'] if y['cheap_unit_cost']==c)
            comparisons.append(u(r)-u(baseline))
        print('cost',c,'positive',sum(x>1e-12 for x in comparisons),'negative',sum(x< -1e-12 for x in comparisons),'ties',sum(abs(x)<=1e-12 for x in comparisons),'max delta',max(comparisons))
if __name__=='__main__': main()
