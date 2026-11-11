"""Offline native PostgreSQL regression for 0025. Disposable cluster only.

Exercises actual fresh v2 init -> enqueue -> reserve -> finalize_ready -> claim
with 27 historical runs, legacy origin rows and retained JSON hit evidence.
No remote DSN, provider request, credential, or source media is used.
"""
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch
import importlib.util
import json
import os
import re
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
base_path=ROOT/'scripts/test-yoon-version-concurrency-postgres.py'
# This is a fixture selection only; all production modules remain unmodified.
ns={'__file__':str(base_path),'__name__':'bounded_fixture'}
base=base_path.read_text().replace('ORDER BY source_id LIMIT 1',
    'WHERE expected_windows='+str(int(os.environ.get('YOON_TEST_WINDOWS','359')))+' ORDER BY source_id LIMIT 1')
exec(compile(base,str(base_path),'exec'),ns)
Base=ns['RegistryConcurrencyTests']
Jsonb=ns['Jsonb'];uid=ns['uid'];psycopg=ns['psycopg']
# Reuse cluster/fixture helpers without inheriting the original test cases here.
class BoundedTests(Base):
    def setUp(self):
        super().setUp()
        with self.connect() as c:
            # Only synthetic fixture population bypasses write guards. Legacy
            # origin runs existed before bootstrap and must remain in scope.
            c.execute('ALTER TABLE ops.set_runs DISABLE TRIGGER yoon_version_write_guard')
            c.execute('ALTER TABLE ops.segment_hits DISABLE TRIGGER yoon_version_write_guard')
            self.origin=uid()
            c.execute('INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,publication_visibility,target_set_id,collection_id,source_metadata) SELECT %s,submission_id,requested_by,status,source_url,publication_visibility,target_set_id,collection_id,source_metadata FROM ops.set_runs WHERE id=%s',(self.origin,self.ids[0]['run']))
            c.execute("UPDATE ops.set_runs SET status='private_resume_complete' WHERE id<>%s",(self.new['run'],))
            # Realistic retained responses plus attempt diagnostics. The
            # compressible synthetic padding models large JSON traversal only.
            c.execute("""INSERT INTO ops.segment_hits(set_run_id,segment_index,timestamp_seconds,recognized,raw_data)
              SELECT r.id,i,i*15,false,jsonb_build_object('private_jackson_v2',jsonb_build_object('valid',true,'in_flight',false,
              'response',jsonb_build_object('segment_index',i,'timestamp',i*15,'http_status',200,'recognized',false,'raw',repeat('synthetic-provider-evidence-',160)),
              'attempts',jsonb_build_array(jsonb_build_object('status','finished','owner','synthetic','diagnostic',jsonb_build_object('http_status',200)))))
              FROM ops.set_runs r CROSS JOIN generate_series(0,478) i WHERE r.id<>%s""",(self.new['run'],))
            c.execute('ALTER TABLE ops.set_runs ENABLE TRIGGER yoon_version_write_guard')
            c.execute('ALTER TABLE ops.segment_hits ENABLE TRIGGER yoon_version_write_guard')
            c.execute('ANALYZE ops.set_runs; ANALYZE ops.segment_hits; ANALYZE ops.yoon_versions')
            c.execute('SELECT ops.initialize_yoon_version_execution(%s)',(self.new['set'],))
        with patch('dotenv.load_dotenv',return_value=False):
            from worker.jobs.yoon_resume_store import ResumeStore
            import worker.db
            from worker.jobs.yoon_queue import PrivateQueue,identity
        self.provider_patch=patch('recognition_transport.SingleAttemptHTTP.request',side_effect=AssertionError('provider forbidden'))
        self.provider=self.provider_patch.start();self.addCleanup(self.provider_patch.stop)
        @contextmanager
        def worker_connect():
            with self.connect() as c:
                c.execute('SET ROLE set_list_worker')
                yield c
        self.store=ResumeStore(self.new['run'],'9001','1',connect=worker_connect)
        queue=PrivateQueue(connect=worker_connect)
        with queue.store(self.new['run']).locked(owner=False) as (_,row,state): manifest=identity(row,state)
        self.assertEqual(queue.enqueue([manifest])['queued'],1)
        reservation=queue.refresh_and_reserve(self.new['run'])
        self.assertTrue(reservation)
        self.env=patch.dict(os.environ,{'SET_LIST_DISPATCH_GENERATION':reservation['generation']})
        self.env.start();self.addCleanup(self.env.stop)
        with self.connect() as c:
            self.before=self.hash(c,self.ids[0]['set'])
            self.initial_run=c.execute('SELECT source_metadata FROM ops.set_runs WHERE id=%s',(self.new['run'],)).fetchone()['source_metadata']
            self.acl=c.execute("SELECT oid::regprocedure::text AS name,proacl::text,proowner FROM pg_proc WHERE oid IN ('ops.yoon_mutation_guard()'::regprocedure,'ops.assert_yoon_version_execution(uuid,text,text)'::regprocedure,'ops.select_yoon_version(uuid,uuid,bigint,uuid,text,text,text,boolean)'::regprocedure) ORDER BY 1").fetchall()

    def restore_old(self,c):
        text=(ROOT/'drizzle/migrations/0024_yoon_version_registry.sql').read_text()
        for name in ('assert_yoon_version_execution','yoon_mutation_guard','select_yoon_version'):
            body=re.search(r'CREATE FUNCTION ops\.'+name+r'\([\s\S]*?END \$\$;',text).group(0)
            c.execute(body.replace('CREATE FUNCTION','CREATE OR REPLACE FUNCTION',1))

    def test_actual_fresh_claim_large_history(self):
        # First exact original function bodies, then additive migration.
        with self.connect() as c:self.restore_old(c)
        self.assertFalse(self.store.finalize_ready())
        started=time.perf_counter();old_failed=False
        try:self.store.claim()
        except psycopg.errors.QueryCanceled:
            old_failed=True
        baseline=time.perf_counter()-started
        with self.connect() as c:
            count=c.execute('SELECT count(*) n FROM ops.set_run_leases WHERE set_run_id=%s',(self.new['run'],)).fetchone()['n']
            state=c.execute('SELECT status,source_metadata FROM ops.set_runs WHERE id=%s',(self.new['run'],)).fetchone()
            if old_failed:
                self.assertEqual(count,0);self.assertEqual(state['status'],'private_resume_pending')
                self.assertEqual(state['source_metadata']['yoon_resume']['continuations'],0)
                self.assertIsNone(state['source_metadata']['yoon_queue_v1']['owner'])
            else:
                # A fast host may not reproduce the timing threshold. Do not
                # misreport it; restore only our disposable test fixture.
                c.execute('DELETE FROM ops.set_run_leases WHERE set_run_id=%s',(self.new['run'],))
                c.execute('ALTER TABLE ops.set_runs DISABLE TRIGGER yoon_version_write_guard')
                c.execute("UPDATE ops.set_runs SET status='private_resume_pending',source_metadata=%s WHERE id=%s",(Jsonb(self.initial_run),self.new['run']))
                c.execute('ALTER TABLE ops.set_runs ENABLE TRIGGER yoon_version_write_guard')
            c.execute((ROOT/'drizzle/migrations/0025_yoon_bounded_family_checks.sql').read_text())
            acl=c.execute("SELECT oid::regprocedure::text AS name,proacl::text,proowner FROM pg_proc WHERE oid IN ('ops.yoon_mutation_guard()'::regprocedure,'ops.assert_yoon_version_execution(uuid,text,text)'::regprocedure,'ops.select_yoon_version(uuid,uuid,bigint,uuid,text,text,text,boolean)'::regprocedure) ORDER BY 1").fetchall()
            self.assertEqual(acl,self.acl)
        started=time.perf_counter();self.assertFalse(self.store.finalize_ready());self.store.claim();elapsed=time.perf_counter()-started
        self.assertLess(elapsed,15)
        with self.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) n FROM ops.set_run_leases WHERE set_run_id=%s',(self.new['run'],)).fetchone()['n'],self.reserved['expected_windows'])
            state=c.execute('SELECT source_metadata FROM ops.set_runs WHERE id=%s',(self.new['run'],)).fetchone()['source_metadata']
            self.assertEqual(state['yoon_resume']['continuations'],1);self.assertEqual(state['yoon_resume']['requests'],0)
            self.assertTrue(state['yoon_resume']['fresh_source_initialized']);self.assertEqual(state['yoon_queue_v1']['owner'],{'workflow_run_id':'9001','run_attempt':'1'})
            self.assertEqual(self.hash(c,self.ids[0]['set']),self.before)
        self.assertEqual(self.provider.call_count,0)
        print('CLAIM_BENCHMARK '+json.dumps(dict(windows=self.reserved['expected_windows'],historical_runs=28,historical_hits=28*479,baseline_timeout=old_failed,baseline_seconds=round(baseline,3),repaired_finalize_claim_seconds=round(elapsed,3),provider_calls=0,predecessor_unchanged=True,acl_unchanged=True)),flush=True)

# Keep this harness focused; run the unmodified original native suite separately.
for name in dir(Base):
    if name.startswith('test_') and name not in BoundedTests.__dict__:setattr(BoundedTests,name,None)
if __name__=='__main__':unittest.main(defaultTest='BoundedTests',verbosity=2)
