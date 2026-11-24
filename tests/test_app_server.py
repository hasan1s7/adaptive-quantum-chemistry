"""Actual loopback HTTP and subprocess checks for the local MVP boundary."""
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import http.client
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from aqc.oracle import PolicySession, run_policy
from aqc_app.data import DevelopmentStore
from aqc_app.server import LocalHTTPServer, MAX_BODY_BYTES

ROOT = Path(__file__).resolve().parents[1]


class AppHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = DevelopmentStore(ROOT)
        cls.molecule_id = 'astex_1g9v'

    def setUp(self):
        self.server = LocalHTTPServer(store=self.store, port=0, quiet=True, worker_timeout=1.0)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, payload=None, *, raw=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=6)
        request_headers = dict(headers or {})
        body = raw
        if payload is not None:
            body = json.dumps(payload).encode()
        if body is not None:
            request_headers.setdefault('Content-Type', 'application/json')
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        data = response.read()
        status, response_headers = response.status, dict(response.getheaders())
        connection.close()
        if response_headers.get('Content-Type', '').startswith('application/json') and data:
            return status, json.loads(data), response_headers
        return status, data, response_headers

    def raw_headers(self, method, path, headers, body=b''):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=6)
        connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for key, value in headers:
            connection.putheader(key, value)
        connection.endheaders(body)
        response = connection.getresponse()
        status, data = response.status, response.read()
        connection.close()
        return status, json.loads(data)

    def create(self, config=None):
        status, state, _ = self.request('POST', '/api/sessions', {'molecule_id': self.molecule_id, 'config': config or {'kind': 'fixed', 'k': 2}})
        self.assertEqual(status, 201, state)
        return state

    def action(self, state, action, payload=None, **kwargs):
        return self.request('POST', '/api/sessions/' + state['session_id'] + '/' + action, {} if payload is None else payload, **kwargs)

    def assert_boundary(self, state):
        queried = {row['candidate_id'] for row in state['queries'] if row['charged']}
        self.assertTrue(set(state['observations']) <= queried)
        for row in state['queries']:
            if 'reference_kcal' in row:
                self.assertIn(row['candidate_id'], queried)
        self.assertNotIn('references', state)
        self.assertNotIn('best_reference_kcal', json.dumps(state))
        if not state['stopped']:
            self.assertIsNone(state['evaluation'])
            self.assertNotIn('regret_kcal', json.dumps(state))
        if state['best_verified']:
            self.assertIn(state['best_verified']['candidate_id'], queried)

    def test_catalog_and_geometry_are_development_only_and_label_free(self):
        status, health, _ = self.request('GET', '/api/health')
        self.assertEqual(status, 200)
        self.assertEqual(health['counts']['molecules'], 478)
        self.assertEqual(health['reference_boundary'], 'server_authoritative')
        status, catalog, _ = self.request('GET', '/api/catalog')
        self.assertEqual(status, 200)
        self.assertEqual(len(catalog['molecules']), 478)
        self.assertEqual({p['id'] for p in catalog['policies']}, {'full','fixed','adaptive','sequential','manual'})
        status, molecule, _ = self.request('GET', '/api/molecules/' + self.molecule_id)
        self.assertEqual(status, 200)
        self.assertEqual(len(molecule['candidates']), 10)
        for candidate in molecule['candidates']:
            self.assertEqual(len(candidate['symbols']), len(candidate['coordinates_angstrom']))
            self.assertEqual(len(candidate['geometry_sha256']), 64)
        for public in (health, catalog, molecule):
            text = json.dumps(public)
            self.assertNotIn('"references"', text)
            self.assertNotIn('"reference_kcal"', text)
            self.assertNotIn('"regret_kcal"', text)
        self.assertEqual(self.request('GET','/api/molecules/astex_1hnn')[0], 404)
        self.assertEqual(self.request('POST','/api/sessions',{'molecule_id':'astex_1hnn','config':{'kind':'full'}})[0],404)

    def test_initial_session_has_zero_calls_and_step_only_reveals_paid_labels(self):
        state = self.create()
        self.assertEqual(state['expensive_calls'], 0)
        self.assertEqual(state['observations'], {})
        self.assertIsNone(state['selected_candidate'])
        first = state['pending_candidate']
        self.assert_boundary(state)
        status, state, _ = self.action(state, 'step')
        self.assertEqual(status, 200)
        self.assertEqual(state['expensive_calls'], 1)
        self.assertEqual(set(state['observations']), {first})
        self.assertFalse(state['stopped'])
        self.assert_boundary(state)
        status, state, _ = self.action(state, 'run')
        self.assertEqual(status, 200)
        self.assertTrue(state['stopped'])
        self.assertEqual(state['expensive_calls'], 2)
        self.assert_boundary(state)
        candidates, refs = self.store.session_inputs(self.molecule_id)
        expected = run_policy(candidates, refs, {'kind':'fixed','k':2})
        self.assertEqual(state['selected_candidate'], expected['selected_candidate'])
        self.assertEqual(state['queries'], expected['queries'])
        self.assertAlmostEqual(state['evaluation']['regret_kcal'], refs[state['selected_candidate']] - min(refs.values()))

    def test_unchanged_worker_parity_for_all_policy_kinds(self):
        candidates, refs = self.store.session_inputs(self.molecule_id)
        configs = [{'kind':'full'}, {'kind':'fixed','k':3}, {'kind':'adaptive','k':1,'gap':.25,'cap':2},
                   {'kind':'sequential','one_gap':8.,'one_ratio':.3,'error_scale':2.,'slack':.25,'cap':2}]
        for config in configs:
            with self.subTest(config=config):
                state = self.create(config)
                status, state, _ = self.action(state, 'run')
                self.assertEqual(status, 200)
                expected = run_policy(candidates, refs, config)
                for key in ('selected_candidate','queries','expensive_calls','fallback','stop_reason','observations','policy_events'):
                    self.assertEqual(state[key], expected[key], key)
                if config['kind'] == 'full':
                    self.assertEqual(state['evaluation']['regret_kcal'], 0.)
                    self.assertEqual(state['expensive_calls'], len(candidates))

    def test_manual_requires_verification_and_duplicate_queries_are_cached(self):
        state = self.create({'kind':'manual'})
        self.assertEqual(self.action(state,'finish')[0],409)
        candidate = self.store.public_molecule(self.molecule_id)['candidates'][0]['candidate_id']
        status, state, _ = self.action(state,'query',{'candidate_id':candidate})
        self.assertEqual(status,200)
        self.assertEqual(state['expensive_calls'],1)
        status, state, _ = self.action(state,'query',{'candidate_id':candidate})
        self.assertEqual(status,200)
        self.assertEqual(state['expensive_calls'],1)
        self.assertEqual(state['queries'][-1]['status'],'cached')
        status, invalid, _ = self.action(state,'query',{'candidate_id':'unknown'})
        self.assertEqual(status,400)
        self.assertEqual(invalid['session']['expensive_calls'],1)
        self.assertEqual(invalid['session']['queries'][-1]['status'],'rejected')
        status, state, _ = self.action(state,'finish')
        self.assertEqual(status,200)
        self.assertEqual(state['status'],'completed')
        self.assertIsNotNone(state['evaluation'])
        self.assertEqual(self.action(state,'query',{'candidate_id':candidate})[0],409)

    def test_reset_and_exports_preserve_prior_charges_without_extra_labels(self):
        state = self.create({'kind':'manual'})
        candidates = self.store.public_molecule(self.molecule_id)['candidates']
        first, second = candidates[0]['candidate_id'], candidates[1]['candidate_id']
        _, state, _ = self.action(state,'query',{'candidate_id':first})
        _, state, _ = self.action(state,'reset')
        self.assertEqual(state['expensive_calls'],0)
        self.assertEqual(state['session_expensive_calls'],1)
        self.assertEqual(state['reset_count'],1)
        self.assertEqual(state['observations'],{})
        _, state, _ = self.action(state,'query',{'candidate_id':second})
        self.assertEqual(state['session_expensive_calls'],2)
        status, export, _ = self.request('GET','/api/sessions/'+state['session_id']+'/export.json')
        self.assertEqual(status,200)
        self.assertEqual(export['accounting']['charged_jobs'],2)
        self.assertEqual(set(export['previous_runs'][0]['observations']),{first})
        self.assertEqual(set(export['session']['observations']),{second})
        self.assertNotIn('"references"',json.dumps(export))
        self.assertNotIn('regret_kcal',json.dumps(export))
        status, raw, _ = self.request('GET','/api/sessions/'+state['session_id']+'/export.csv')
        self.assertEqual(status,200)
        rows=list(csv.DictReader(io.StringIO(raw.decode())))
        self.assertEqual(sum(int(row['charged']) for row in rows),2)
        self.assertEqual({row['candidate_id'] for row in rows},{first,second})
        self.assertTrue(all(row['regret_kcal']=='' for row in rows))

    def test_concurrent_manual_duplicate_queries_charge_only_once(self):
        state = self.create({'kind':'manual'})
        candidate = self.store.public_molecule(self.molecule_id)['candidates'][0]['candidate_id']
        with ThreadPoolExecutor(max_workers=8) as executor:
            results=list(executor.map(lambda _:self.action(state,'query',{'candidate_id':candidate}),range(8)))
        self.assertTrue(all(result[0]==200 for result in results))
        _, final, _=self.request('GET','/api/sessions/'+state['session_id'])
        self.assertEqual(final['expensive_calls'],1)
        self.assertEqual(len(final['queries']),8)
        self.assertEqual(sum(row['charged'] for row in final['queries']),1)

    def test_concurrent_retried_step_is_idempotent_and_distinct_steps_serialize(self):
        state=self.create({'kind':'fixed','k':4})
        headers={'Idempotency-Key':'same-operation'}
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(lambda _:self.action(state,'step',headers=headers),range(2)))
        self.assertTrue(all(result[0]==200 for result in results))
        self.assertEqual(results[0][1],results[1][1])
        self.assertEqual(results[0][1]['expensive_calls'],1)
        self.assertEqual(self.action(state,'reset',headers=headers)[0],409)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(lambda _:self.action(state,'step'),range(2)))
        self.assertTrue(all(result[0]==200 for result in results))
        _, final, _=self.request('GET','/api/sessions/'+state['session_id'])
        self.assertEqual(final['expensive_calls'],3)
        self.assertEqual(len({row['candidate_id'] for row in final['queries']}),3)

    def test_client_disconnect_does_not_erase_a_charged_mutation(self):
        state=self.create({'kind':'fixed','k':2})
        path='/api/sessions/'+state['session_id']+'/step'
        request=(f'POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nContent-Type: application/json\r\nIdempotency-Key: disconnected\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{{}}').encode()
        with socket.create_connection(('127.0.0.1',self.port),timeout=2) as connection:
            connection.sendall(request)
        deadline=time.monotonic()+2
        while self.server.sessions.get(state['session_id']).oracle.expensive_calls<1 and time.monotonic()<deadline:
            time.sleep(.01)
        status,retried,_=self.action(state,'step',headers={'Idempotency-Key':'disconnected'})
        self.assertEqual(status,200)
        self.assertEqual(retried['expensive_calls'],1)

    def test_session_capacity_delete_expiry_and_query_caps(self):
        self.server.sessions.max_sessions=2
        first=self.create({'kind':'manual'})
        second=self.create({'kind':'manual'})
        self.assertEqual(self.request('POST','/api/sessions',{'molecule_id':self.molecule_id,'config':{'kind':'manual'}})[0],429)
        self.assertEqual(self.request('DELETE','/api/sessions/'+second['session_id'])[0],200)
        self.server.sessions.ttl=.05
        expiring=self.create({'kind':'manual'})
        time.sleep(.08)
        self.assertEqual(self.request('GET','/api/sessions/'+expiring['session_id'])[0],410)
        runtime=self.server.sessions.get(first['session_id'])
        runtime.limits['max_query_events']=1
        candidate=self.store.public_molecule(self.molecule_id)['candidates'][0]['candidate_id']
        self.assertEqual(self.action(first,'query',{'candidate_id':candidate})[0],200)
        self.assertEqual(self.action(first,'query',{'candidate_id':candidate})[0],429)
        self.assertEqual(runtime.oracle.expensive_calls,1)

    def test_idle_janitor_closes_worker_without_another_request(self):
        self.server.sessions.ttl=.1
        state=self.create()
        runtime=self.server.sessions.get(state['session_id'])
        process=runtime._transport._process
        deadline=time.monotonic()+2
        while (not runtime.closed or process.poll() is None) and time.monotonic()<deadline:
            time.sleep(.02)
        self.assertTrue(runtime.closed)
        self.assertIsNotNone(process.poll())

    def test_unsafe_host_origin_and_duplicate_security_headers_are_rejected(self):
        for host in ('evil.example',f'evil.example:{self.port}','127.0.0.1:1',f'127.0.0.1:{self.port}@evil'):
            self.assertEqual(self.request('GET','/api/health',headers={'Host':host})[0],403)
        for origin in ('https://evil.example','null',f'http://localhost:{self.port}'):
            self.assertEqual(self.request('GET','/api/health',headers={'Origin':origin})[0],403)
        self.assertEqual(self.request('GET','/api/health',headers={'Origin':f'http://127.0.0.1:{self.port}'})[0],200)
        headers=[('Host',f'127.0.0.1:{self.port}'),('Host','evil.example')]
        self.assertEqual(self.raw_headers('GET','/api/health',headers)[0],403)
        headers=[('Host',f'127.0.0.1:{self.port}'),('Origin',f'http://127.0.0.1:{self.port}'),('Origin','null')]
        self.assertEqual(self.raw_headers('GET','/api/health',headers)[0],403)
        self.assertEqual(self.request('OPTIONS','/api/sessions',headers={'Origin':'https://evil.example'})[0],403)

    def test_body_size_content_type_and_ambiguous_json_are_rejected(self):
        self.assertEqual(self.request('POST','/api/sessions',raw=b'{}',headers={'Content-Length':str(MAX_BODY_BYTES+1)})[0],413)
        self.assertEqual(self.request('POST','/api/sessions',raw=b'{}',headers={'Content-Length':'9'*100})[0],413)
        self.assertEqual(self.request('POST','/api/sessions',raw=b'{}',headers={'Content-Type':'text/plain'})[0],415)
        self.assertEqual(self.request('POST','/api/sessions',raw=b'{}',headers={'Transfer-Encoding':'chunked'})[0],400)
        malformed=[b'{"molecule_id":"x","molecule_id":"y"}',b'{"x":NaN}',b'{"x":Infinity}',b'{"x":1e999}',b'[]',b'{',b'\xff']
        for raw in malformed:
            with self.subTest(raw=raw):
                self.assertEqual(self.request('POST','/api/sessions',raw=raw)[0],400)
        headers=[('Host',f'127.0.0.1:{self.port}'),('Content-Type','application/json'),('Content-Length','2'),('Content-Length','2')]
        self.assertEqual(self.raw_headers('POST','/api/sessions',headers,b'{}')[0],400)

    def test_invalid_configs_and_feature_injection_are_rejected(self):
        configs=[{},None,[],{'kind':'unknown'},{'kind':'manual','reference_kcal':0},
                 {'kind':'fixed','k':True},{'kind':'fixed','k':0}, {'kind':'full','references':{}},
                 {'kind':'adaptive','k':3,'gap':.1,'cap':2},
                 {'kind':'sequential','one_gap':0,'one_ratio':2,'error_scale':1,'slack':.25,'cap':2}]
        for config in configs:
            with self.subTest(config=config):
                self.assertEqual(self.request('POST','/api/sessions',{'molecule_id':self.molecule_id,'config':config})[0],400)
        self.assertEqual(self.request('POST','/api/sessions',{'molecule_id':self.molecule_id,'config':{'kind':'full'},'references':{}})[0],400)
        state=self.create()
        self.assertEqual(self.action(state,'step',{'cheap_kcal':0})[0],400)
        self.assertEqual(self.action(state,'query',{'candidate_id':'rmsd111-opt'})[0],409)

    def test_traversal_and_old_label_containing_files_are_not_served(self):
        paths=['/../results/real/prepared/development_references.jsonl','/%2e%2e/results/real/prepared/development_references.jsonl',
               '/assets/../index.html','/assets/%2fmolecule-viewer.js','/assets\\molecule-viewer.js',
               '/results/lab/dashboard.html','/results/real/prepared/development_references.jsonl',
               '/data/development_geometry.json.gz','/aqc/policy_worker.py','/api/results/per_molecule.csv',
               '/api/results/decision_ledger.jsonl.gz']
        for path in paths:
            with self.subTest(path=path):
                self.assertIn(self.request('GET',path)[0],(400,404))
        self.assertEqual(self.request('GET','/api/health?references=1')[0],400)

    def test_static_app_and_summary_downloads_are_allowlisted(self):
        status,html,headers=self.request('GET','/')
        self.assertEqual(status,200)
        self.assertIn(b'<html',html.lower())
        self.assertIn("script-src 'self'",headers['Content-Security-Policy'])
        self.assertEqual(headers['X-Frame-Options'],'DENY')
        self.assertNotIn(b'-708918.4384808392',html)
        status,results,_=self.request('GET','/api/results')
        self.assertEqual(status,200)
        self.assertEqual(len(results['experiments']),1020)
        self.assertEqual(results['scope'],'development_family_cv')
        self.assertNotIn('"references"',json.dumps(results))
        for name in self.store.EXPORT_NAMES:
            status,raw,headers=self.request('GET','/api/results/'+name)
            self.assertEqual(status,200)
            self.assertEqual(hashlib.sha256(raw).hexdigest(),hashlib.sha256(self.store.export(name)).hexdigest())
            self.assertIn('attachment',headers['Content-Disposition'])

    def _fault(self, tail, *, wait_for_exit=False, timeout=1.0):
        with tempfile.TemporaryDirectory(prefix='aqc-http-fault-') as directory:
            worker=Path(directory)/'worker.py'
            worker.write_text("import sys,json,time\npayload=json.loads(sys.stdin.readline())\ncid=payload['candidates'][0]['candidate_id']\nprint(json.dumps({'type':'query','candidate_id':cid}),flush=True)\n"+tail,encoding='utf-8')
            self.server.sessions.worker_timeout=timeout
            with patch('aqc.oracle._WORKER_PATH',worker):
                state=self.create()
                if wait_for_exit:
                    self.server.sessions.get(state['session_id'])._transport._process.wait(timeout=2)
                status,result,_=self.action(state,'step')
            self.assertEqual(status,502,result)
            failed=result['session']
            self.assertEqual(failed['expensive_calls'],1)
            self.assertEqual(sum(event['charged'] for event in failed['queries']),1)
            self.assertEqual(len(failed['observations']),1)
            self.assertEqual(failed['status'],'failed')
            self.assertIsNone(failed['evaluation'])
            self.assert_boundary(failed)
            status,export,_=self.request('GET','/api/sessions/'+state['session_id']+'/export.json')
            self.assertEqual(status,200)
            self.assertEqual(export['accounting']['charged_jobs'],1)
            return failed

    def test_worker_malformed_json_keeps_actual_paid_ledger(self):
        failed=self._fault("sys.stdin.readline()\nprint('broken-json',flush=True)\n")
        self.assertEqual(failed['failure']['cause_type'],'JSONDecodeError')

    def test_worker_eof_keeps_actual_paid_ledger(self):
        failed=self._fault("sys.stdin.readline()\n")
        self.assertEqual(failed['failure']['cause_type'],'EOFError')

    def test_worker_broken_pipe_after_paid_resolution_keeps_ledger(self):
        failed=self._fault("",wait_for_exit=True)
        self.assertEqual(failed['failure']['cause_type'],'BrokenPipeError')

    def test_worker_timeout_keeps_actual_paid_ledger(self):
        failed=self._fault("sys.stdin.readline()\ntime.sleep(5)\n",timeout=.08)
        self.assertEqual(failed['failure']['cause_type'],'TimeoutError')

    def test_cleanup_failure_after_real_query_retains_paid_ledger(self):
        class CleanupFault(PolicySession):
            def close(self):
                super().close()
                raise OSError('injected cleanup failure after process teardown')
        self.server.sessions.transport_factory=CleanupFault
        state=self.create({'kind':'fixed','k':1})
        status,result,_=self.action(state,'step')
        self.assertEqual(status,502)
        failed=result['session']
        self.assertEqual(failed['expensive_calls'],1)
        self.assertEqual(len(failed['observations']),1)
        self.assertIsNone(failed['evaluation'])
        self.assertEqual(failed['failure']['failure_stage'],'cleanup')
        self.assertEqual(failed['failure']['cause_type'],'OSError')
        self.assertEqual(failed['failure']['cleanup_errors'][0]['operation'],'interactive_transport.close')

    def test_missing_label_fallback_is_paid_and_matches_original_worker(self):
        candidates,refs=self.store.session_inputs(self.molecule_id)
        first=min(candidates,key=lambda row:(row['cheap_kcal'],row['candidate_id']))['candidate_id']
        missing=dict(refs); missing[first]=None
        with patch.object(self.store,'session_inputs',return_value=(candidates,missing)):
            state=self.create({'kind':'fixed','k':1})
        status,state,_=self.action(state,'run')
        self.assertEqual(status,200)
        expected=run_policy(candidates,missing,{'kind':'fixed','k':1})
        self.assertEqual(state['queries'],expected['queries'])
        self.assertEqual(state['expensive_calls'],len(candidates))
        self.assertTrue(state['fallback'])
        self.assertNotIn(first,state['observations'])
        self.assertEqual(state['evaluation']['regret_kcal'],0.)

    def test_data_loading_never_opens_historical_reference_file(self):
        original=Path.open
        def guarded(path,*args,**kwargs):
            if path.name=='evaluation_references.jsonl':
                raise AssertionError('historical reference file opened')
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',guarded):
            store=DevelopmentStore(ROOT)
        self.assertEqual(store.counts['molecules'],478)

    def test_standard_library_mode_imports_and_cli_help(self):
        result=subprocess.run([sys.executable,'-S','-m','aqc_app','--help'],cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('--no-open',result.stdout)
        self.assertNotIn('--bind',result.stdout)


if __name__=='__main__':
    unittest.main()
