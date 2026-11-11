import hashlib
import copy
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from worker.jobs import yoon_admission as a


def row(i, status='private_resume_running', **extra):
    value=dict(id=str(i),target_set_id='set'+str(i),status=status,
       source_metadata={'yoon_resume':{'workflow_run_id':str(i),'run_attempt':'1'}},
       uncertain_hit=False,claimed_lease=False)
    value.update(extra)
    return value

class Cursor:
    def __init__(self,rows): self.rows=rows;self.sql=[]
    def execute(self,sql,params=None): self.sql.append(sql)
    def fetchall(self): return self.rows
    def fetchone(self): return {'transaction_isolation':'read committed'}

class AdmissionTests(unittest.TestCase):
    def test_cap_and_legacy_occupancy(self):
        rows=[row(1)]
        a.check(Cursor(rows),'2','set2')
        rows.append(row(2))
        with self.assertRaisesRegex(RuntimeError,'capacity'):a.check(Cursor(rows),'3','set3')
        for run,target in [('1','other'),('3','set1')]:
            with self.assertRaisesRegex(RuntimeError,'duplicate'):a.check(Cursor(rows),run,target)
        rows[0]['status']='private_resume_complete'
        a.check(Cursor(rows),'3','set3')
    def test_uncertain_and_missing_owner_fail_closed(self):
        for r in [row(1,status='unrecognized'),row(1,source_metadata={}),
                  row(1,status='private_resume_paused',uncertain_hit=True),
                  row(1,status='private_resume_paused',claimed_lease=True),
                  row(1,source_metadata={'yoon_resume':{'review_required':True}})]:
            with self.assertRaises(RuntimeError):a.check(Cursor([r]),'2','set2')
        # In-flight requests in an owned running workflow are legitimate occupancy.
        self.assertTrue(a.occupied(row(1,uncertain_hit=True,claimed_lease=True)))
    def test_enrichment_shares_capacity_and_uncertainty(self):
        r=row(1,status='private_resume_complete')
        r['source_metadata']['yoon_spotify_enrichment']={'status':'reserved','owner':{'workflow_run_id':'7','run_attempt':'1'}}
        self.assertTrue(a.occupied(r))
        with self.assertRaisesRegex(RuntimeError,'capacity'):a.check(Cursor([r,row(2)]),'3','set3')
        r['source_metadata']['yoon_spotify_enrichment']['status']='complete'
        self.assertFalse(a.occupied(r))
        r['source_metadata']['yoon_spotify_recheck_v1']={'status':'partial'}
        with self.assertRaises(RuntimeError):a.occupied(r)
    def test_running_queue_compares_owner_pair_not_full_resume_receipt(self):
        r=row(1,uncertain_hit=True,claimed_lease=True)
        r['source_metadata']['yoon_resume'].update(status='recognizing',requests=17,continuations=1)
        r['source_metadata']['yoon_queue_v1']={'version':1,'status':'running',
            'owner':{'workflow_run_id':'1','run_attempt':'1'}}
        self.assertTrue(a.occupied(r))
        a.check(Cursor([r]),'2','set2')
        with self.assertRaisesRegex(RuntimeError,'private_admission_capacity'):
            a.check(Cursor([r,row(2)]),'3','set3')
        for run,target in [('1','other'),('3','set1')]:
            with self.assertRaisesRegex(RuntimeError,'private_admission_duplicate_target'):
                a.check(Cursor([r]),run,target)

    def test_running_queue_mismatched_or_malformed_owner_still_blocks(self):
        r=row(1)
        for owner in (None,[],{}, {'workflow_run_id':'2','run_attempt':'1'},
                      {'workflow_run_id':'1','run_attempt':'2'},
                      {'workflow_run_id':1,'run_attempt':'1'},
                      {'workflow_run_id':'1','run_attempt':'invalid'}):
            with self.subTest(owner=owner):
                r['source_metadata']['yoon_queue_v1']={'version':1,'status':'running','owner':owner}
                with self.assertRaisesRegex(RuntimeError,'private_admission_uncertain_queue'):
                    a.check(Cursor([r]),'2','set2')

    def test_clean_released_queue_owner_is_idle_but_uncertainty_is_not(self):
        r=row(1,status='private_resume_paused')
        r['source_metadata']['yoon_resume'].update(status='paused',reason='cooldown_pending')
        r['source_metadata']['yoon_queue_v1']={'version':1,'status':'running',
            'owner':{'workflow_run_id':'1','run_attempt':'1'}}
        self.assertFalse(a.occupied(r))
        for key in ('uncertain_hit','claimed_lease'):
            r[key]=True
            with self.assertRaisesRegex(RuntimeError,'private_admission_uncertain_owner'):a.occupied(r)
            r[key]=False
        for key in ('review_required','in_flight'):
            r['source_metadata']['yoon_resume'][key]=True
            with self.assertRaisesRegex(RuntimeError,'private_admission_uncertain_owner'):a.occupied(r)
            r['source_metadata']['yoon_resume'].pop(key)
        r['source_metadata']['yoon_queue_v1']['owner']=None
        with self.assertRaisesRegex(RuntimeError,'private_admission_uncertain_queue'):a.occupied(r)
    def test_concurrent_admission_model(self):
        # Models the PostgreSQL transaction lock, NOT a multi-backend DB test.
        mutex=threading.Lock();barrier=threading.Barrier(12);rows=[]
        def submit(i):
            barrier.wait()
            with mutex:
                try:a.check(Cursor(rows),str(i),'set'+str(i))
                except RuntimeError:return False
                rows.append(row(i));return True
        with ThreadPoolExecutor(max_workers=12) as pool:results=list(pool.map(submit,range(1,13)))
        self.assertEqual(sum(results),2)
        self.assertEqual(len(rows),2)
    def test_global_lock_and_isolation(self):
        cur=Cursor([]);a.lock(cur);self.assertEqual(cur.sql[-1],a.LOCK_SQL)
        cur.fetchone=lambda:{'transaction_isolation':'repeatable read'}
        with self.assertRaises(RuntimeError):a.lock(cur)
    def test_shared_pipeline_reviewed_throttle_policy_pins(self):
        here=Path(__file__).resolve().parents[1]
        # Reviewed policy3 changes the common retry engine, not private-only pacing.
        # Database-only lock retries are reviewed separately; provider transport,
        # aggregation and source recognizer remain pinned unchanged.
        pins={'worker/jobs/shared_recognition.py': '5b3ffa77ff131992671cfb9d512f82b8428102bb4825325101126d8b473395c0', 'worker/jobs/yoon_resume.py': 'eabc4d50a7d931c9953440d732c9f1e83645261400271e093520c48f09fe65d6', 'worker/jobs/yoon_recognition.py': 'a6fa53971ca4cc5633205c2988b5c48eef3568fc71f97b76dcf4b8f59eb74beb', 'track_recognizer.py': 'd7d93f4ea8ac591baf868533876d5ec90462edf0355700752a6dc9cbd1a075c5', 'recognition_transport.py': '3eb691ef807eb82fe2e69dcdd1f8c398d28e7cc6f6c5d8acf038989693796a4b', 'worker/jobs/yoon_resume_policy.py': '50fca4b2c3413b255b37555783ecf0c2db1ae916df604d8b4813ca4eec0a80f8', 'worker/pipeline/aggregate.py': 'c56af3972aae077686311ffdf056c85617996170cecb33aaba6f01d1e9e1934a'}
        for name,expected in pins.items():
            self.assertEqual(hashlib.sha256((here/name).read_bytes()).hexdigest(),expected,name)
    def test_per_run_workflow_group(self):
        text=(Path(__file__).resolve().parents[1]/'.github/workflows/process-set.yml').read_text()
        self.assertIn("format('process-set-private-analysis-{0}', github.event.inputs.set_run_id)",text)
        self.assertIn("cancel-in-progress: ${{ github.event.inputs.private_analysis != 'true' }}",text)

if __name__=='__main__':unittest.main()
