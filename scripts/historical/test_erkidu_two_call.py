import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
import numpy as np
import erkidu_two_call as e

BASE=Path(__file__).resolve().parent
class TwoCallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pools=e.load_prelabel(BASE/'inputs')
        cls.frozen=json.loads((BASE/'run_001'/'freeze.json').read_text())
        cls.plan=[json.loads(x) for x in (BASE/'run_001'/'sealed_prelabel_plan.jsonl').read_text().splitlines()]
        cls.results=json.loads((BASE/'run_001'/'results.json').read_text())
        with (BASE/'run_001'/'per_pool.csv').open(encoding='utf-8',newline='') as stream:
            cls.rows=list(__import__('csv').DictReader(stream))

    def test_input_integrity_protected(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)
            for name in ('development_features.jsonl','development_geometry.json.gz','folds.json'):
                (p/name).symlink_to(BASE/'inputs'/name)
            self.assertEqual(len(e.load_prelabel(p)),478)
            (p/'development_features.jsonl').unlink()
            (p/'development_features.jsonl').write_text('tampered')
            with self.assertRaises(ValueError):e.load_prelabel(p)

    def test_planning_cannot_require_reference_file(self):
        with tempfile.TemporaryDirectory() as temp:
            inp=Path(temp)/'inputs';inp.mkdir()
            for name in ('development_features.jsonl','development_geometry.json.gz','folds.json'):
                (inp/name).symlink_to(BASE/'inputs'/name)
            self.assertFalse((inp/'development_references.jsonl').exists())
            with self.assertRaises(FileNotFoundError):e.load_labels(inp,self.pools)
            p=e.load_prelabel(inp)
            self.assertEqual(e.choose(p[sorted(p)[0]])['calls_planned_per_policy'],2)

    def test_plan_seal_reproducible_byte_for_byte(self):
        regenerated,_=e.compute_plan(self.pools)
        raw=''.join(e.canonical(r)+'\n' for r in regenerated).encode()
        self.assertEqual(e.sha_bytes(raw),self.frozen['plan_sha256'])
        self.assertEqual(len(self.plan),478)

    def test_all_budgets_and_first_identities(self):
        self.assertEqual(len(self.rows),478*len(e.POLICIES))
        for row in self.plan:
            self.assertEqual(set(row['choices']),set(e.POLICIES))
            self.assertEqual(row['calls_planned_per_policy'],2)
            for k,cid in row['choices'].items():
                self.assertIn(cid,row['eligible'])
                self.assertNotEqual(cid,row['first_call'])
        for policy,m in self.results['policy_metrics'].items():
            self.assertEqual(m['attempted_calls'],956)
            self.assertEqual(m['replayed_completed_labels'],956)
        self.assertEqual(self.results['policy_metrics']['top2']['success'],457)

    def test_rotation_translation_invariant_contact_and_dihedral(self):
        p=next(p for p in self.pools.values() if len(p['symbols'])>5)
        x=np.array(p['geom'][p['order'][0]]['coordinates_angstrom'])
        graph=e.bond_topology(p['symbols'],x)
        pairs=e.heavy_nonbonded(p['symbols'],graph)
        base=e.overlap(x,p['symbols'],pairs)
        theta=.39
        rot=np.array([[math.cos(theta),-math.sin(theta),0],[math.sin(theta),math.cos(theta),0],[0,0,1.]])
        after=x@rot+np.array([70,13,-27])
        self.assertAlmostEqual(e.overlap(after,p['symbols'],pairs),base or 0,places=9)
        q=e.torsion_quadruples(graph,p['symbols'])
        if q:
            self.assertAlmostEqual(e.angle(x,q[0]),e.angle(after,q[0]),places=9)

    def test_graph_excludes_12_13(self):
        graph=[{1},{0,2},{1,3},{2}];symbols=['C']*4
        self.assertEqual(e.heavy_nonbonded(symbols,graph),[(0,3)])
        self.assertEqual(e.torsion_quadruples(graph,symbols),[(0,1,2,3)])

    def test_fallback_and_tie(self):
        cids=['a','b','c']
        p={'order':cids,'cheap':{'a':0.,'b':.1,'c':.2},'family':'f','fold':0,
           'symbols':['O','H','H'],
           'geom':{cid:{'symbols':['O','H','H'],'coordinates_angstrom':[[0,0,0],[1,0,0],[0,1,0]],'candidate_id':cid} for cid in cids}}
        q=e.choose(p)
        self.assertEqual(q['choices']['torsion'],'b')
        self.assertEqual(q['choices']['steric'],'b')
        self.assertIn('fallback',q['choice_reasons']['torsion'])

    def test_rank_four_case_definition_not_implied_by_rank3_recoverability(self):
        c=self.results['rank4_counterexamples']
        self.assertEqual((c['rescue_count'],c['harm_count']),(4,14))
        cases=json.loads((BASE/'run_001'/'rank4_rescue_harm.json').read_text())
        self.assertEqual(len(cases),18)
        for case in cases:
            self.assertGreaterEqual(case['paired_regret_difference_abs'],0)
            if case['kind']=='rescue':
                self.assertGreater(case['regret_top2_kcal'],1)
                self.assertLessEqual(case['regret_rank4_kcal'],1)
            else:
                self.assertLessEqual(case['regret_top2_kcal'],1)
                self.assertGreater(case['regret_rank4_kcal'],1)

    def test_development_scope_and_zero_live_jobs(self):
        self.assertIn('development_only',self.results['scope'])
        for k,v in self.results['reference_accounting'].items():
            self.assertEqual(v['live_submissions'],0)
            self.assertEqual(v['live_completed'],0)
            self.assertEqual(v['free_replacement_calls'],0)

    def test_pairs_have_exactly_one_row_each(self):
        keys=[(row['pool_id'],row['policy']) for row in self.rows]
        self.assertEqual(len(keys),len(set(keys)))
        self.assertTrue(all(row['query1_candidate_id']!=row['query2_candidate_id'] for row in self.rows))
        self.assertTrue(all(int(row['attempted_calls'])==2 for row in self.rows))

if __name__=='__main__':unittest.main()
