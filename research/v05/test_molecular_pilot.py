import json, math, unittest
from pathlib import Path
import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem
import molecular_pilot as p
class Pilot(unittest.TestCase):
 def test_split(self):
  self.assertFalse(set(p.TRAIN)&set(p.TEST)); keys=[Chem.MolToSmiles(Chem.MolFromSmiles(s)) for g in (p.TRAIN,p.TEST) for v in g.values() for s in v]; self.assertEqual(len(set(keys)),36)
 def test_geometry(self):
  c=np.zeros((6,3));a=.2;g=p.paths(c,1,a);l,ds=g['linear'];r,_=g['circular'];np.testing.assert_allclose(l.mean(axis=1),0,atol=1e-14);np.testing.assert_allclose(r.mean(axis=1),0,atol=1e-14);np.testing.assert_allclose(np.sqrt(np.mean(np.sum(r*r,axis=2),axis=1)),a,atol=1e-14);self.assertAlmostEqual(np.sqrt(np.mean(np.sum(l[0]**2,axis=1))),a);self.assertAlmostEqual(np.linalg.norm(l[1]-l[0]),ds);self.assertFalse(np.allclose(r[0],r[-1]))
 def test_metrics(self):
  t=np.linspace(-1,1,p.N);e=t*t;ds=t[1]-t[0];sp,mac=p.metrics(e,ds,'linear');self.assertLess(sp,1e-20);self.assertAlmostEqual(mac,2);self.assertAlmostEqual(p.metrics(100+3*e,ds,'linear')[0],sp);self.assertAlmostEqual(p.metrics(100+3*e,ds,'linear')[1],6);self.assertEqual(p.metrics(np.zeros(p.N),ds,'linear'),(0,0))
 def test_calc_energy_coordinates(self):
  m=Chem.AddHs(Chem.MolFromSmiles('CCO'));self.assertEqual(AllChem.EmbedMolecule(m,randomSeed=10),0);AllChem.MMFFOptimizeMolecule(m);xyz=m.GetConformer().GetPositions();props=AllChem.MMFFGetMoleculeProperties(m);f=AllChem.MMFFGetMoleculeForceField(m,props,nonBondedThresh=1000);u=AllChem.UFFGetMoleculeForceField(m,vdwThresh=1000);point=p.paths(xyz,7,.1)['linear'][0][12];expected=(f.CalcEnergy(tuple(point.ravel())),u.CalcEnergy(tuple(point.ravel())));clone=Chem.Mol(m)
  for i,x in enumerate(point):clone.GetConformer().SetAtomPosition(i,tuple(x))
  fresh=(AllChem.MMFFGetMoleculeForceField(clone,AllChem.MMFFGetMoleculeProperties(clone),nonBondedThresh=1000).CalcEnergy(),AllChem.UFFGetMoleculeForceField(clone,vdwThresh=1000).CalcEnergy());np.testing.assert_allclose(expected,fresh,rtol=1e-10,atol=1e-8)
 def test_fit_boundary(self):
  rows=[dict(split='train',gap=.2,amp=a,method=m,spectral=.1,mac=3,rescue=1) for a in p.AMPS for m in ('linear','circular')];f=p.fit(rows,'spectral');self.assertGreater(f(dict(gap=.2,amp=.1,method='linear',spectral=.1)),.5);self.assertRaises(AssertionError,p.fit,[{**rows[0],'split':'test'}],None)
 def test_receipt(self):
  s=json.loads(Path('run/summary.json').read_text());self.assertEqual((s['train_trajectories'],s['test_trajectories']),(720,360));self.assertEqual(s['test_rescues'],30);self.assertGreater(s['train_cost_ratio'],0);self.assertTrue(all(r['n']==360 and 360<=r['calls']<=720 for r in s['policies']));self.assertTrue(all(r['cheap_points']==(128 if r['policy'] in ('spectral','mac') else 10)*360 for r in s['policies']));self.assertTrue(all(r['pairs']==60 and len(r['family_means'])==4 for r in s['paired']))
if __name__=='__main__':unittest.main()
