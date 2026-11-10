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
    def execute(self,sql): self.sql.append(sql)
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
    def test_shared_pipeline_byte_identical(self):
        here=Path(__file__).resolve().parents[1]
        # Shared engine bytes stay pinned. Only the private adapter pin changes
        # for allowlisted diagnostic scopes; provider/budget bytes stay fixed.
        pins={'worker/jobs/shared_recognition.py': '5b5944064c2402208cfbe83ecad8a4b467e0923dc755212eec0239c07cda672c', 'worker/jobs/yoon_resume.py': 'a7518ca758c52837a31c0d6cbd5c323d4a19ce538c2a59c746cd041915851612', 'worker/jobs/yoon_recognition.py': 'a6fa53971ca4cc5633205c2988b5c48eef3568fc71f97b76dcf4b8f59eb74beb', 'track_recognizer.py': '5deb90a7f063df2910c910e5c434d0cb6bdf0f404d1a7eb60a4d2b82b90045f2', 'recognition_transport.py': 'efd802d7fc498eee4b6a4dd4b74e0fa00ef99b3a010ed85ea0a31040d971c63d', 'worker/jobs/yoon_resume_policy.py': 'b0bf11d70ba4d7dc6929a39ec10e69233694a7d4bf8270cd9b0aa1dbbec6fde9', 'worker/pipeline/aggregate.py': 'c56af3972aae077686311ffdf056c85617996170cecb33aaba6f01d1e9e1934a'}
        for name,expected in pins.items():
            self.assertEqual(hashlib.sha256((here/name).read_bytes()).hexdigest(),expected,name)
    def test_per_run_workflow_group(self):
        text=(Path(__file__).resolve().parents[1]/'.github/workflows/process-set.yml').read_text()
        self.assertIn("format('process-set-private-analysis-{0}', github.event.inputs.set_run_id)",text)
        self.assertIn("cancel-in-progress: ${{ github.event.inputs.private_analysis != 'true' }}",text)

if __name__=='__main__':unittest.main()
