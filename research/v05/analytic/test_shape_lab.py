import math, unittest
from shape_lab import *
class ShapeTests(unittest.TestCase):
    def test_constant(self): self.assertEqual(metrics([8.]*N,1),(0.,0.))
    def test_quadratic(self):
        s,m=metrics([t*t for t in TS],2)
        self.assertLess(s,1e-20);self.assertAlmostEqual(m,.5,places=8)
    def test_high_order(self): self.assertGreater(metrics([8*t**4-8*t*t+1 for t in TS],1)[0],.999999)
    def test_shift(self):
        y=[math.sin(5*t) for t in TS];a=metrics(y,1);b=metrics([v+100 for v in y],1)
        for x,z in zip(a,b):self.assertAlmostEqual(x,z,places=8)
    def test_scaling(self):
        y=[math.sin(5*t) for t in TS];a=metrics(y,1);b=metrics(y,2)
        self.assertAlmostEqual(a[0],b[0]);self.assertAlmostEqual(a[1]/4,b[1])
    def test_geometry(self):
        for method in ('linear','circular'):
            self.assertEqual(len(set(candidate_indices(method))),10)
        for t in TS:self.assertAlmostEqual(math.hypot(*point(t,.2,.3,'circular')),.2)
        self.assertEqual(point(0,.2,.3,'linear'),(0.,0.))
        self.assertAlmostEqual(math.dist(point(-1,.2,.3,'circular'),point(1,.2,.3,'circular')),0)
    def test_invalid(self):
        for y,s in [([0.],1),([0.]*N,0),([float('nan')]*N,1)]:
            with self.assertRaises(ValueError):metrics(y,s)
    def test_train_test(self):
        data=generate('aligned',centres=10,seeds=1);train=[r for r in data if r['split']=='train'];test=[r for r in data if r['split']=='test']
        self.assertEqual(len(data),60);self.assertTrue(set(r['centre'] for r in train).isdisjoint(r['centre'] for r in test))
        with self.assertRaises(ValueError):fit(test)
        self.assertTrue(all(r['regret2']<=r['regret1'] for r in data))
        result=evaluate(data);self.assertEqual(result[0]['calls'],len(test));self.assertEqual(result[1]['calls'],2*len(test));self.assertEqual(result[-1]['additional_cheap_evaluations'],118*len(test));self.assertEqual(len(paired(data)),6)
    def test_policy(self):self.assertEqual([policy(p) for p in (.01,.05,.051)],[1,1,2])
    def test_bootstrap(self):
        z=cluster_interval({1:[1.,1.],2:[1.,1.]},draws=100);self.assertEqual(z['ci95'],[1.,1.])
if __name__=='__main__':unittest.main()
