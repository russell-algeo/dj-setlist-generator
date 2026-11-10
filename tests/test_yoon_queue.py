import copy
from pathlib import Path
import unittest
import threading
from unittest.mock import patch, Mock
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from worker.jobs import yoon_admission as a
from worker.jobs.yoon_queue import consume, identity, PrivateQueue
from test_yoon_admission import Cursor, row

class QueueTests(unittest.TestCase):
    def queued(self,i,status='reserved'):
        r=row(i,status='private_resume_pending')
        r['source_metadata']['yoon_queue_v1']={'version':1,'status':status,'generation':'fence'+str(i),'owner':None}
        return r
    def test_queued_does_not_use_capacity_but_reservation_does(self):
        self.assertFalse(a.occupied(self.queued(1,'queued')))
        for status in ('reserved','sending','dispatched'):
            self.assertTrue(a.occupied(self.queued(1,status)))
            with self.assertRaisesRegex(RuntimeError,'capacity'):
                a.check(Cursor([self.queued(1,status),row(2)]),'3','set3')
    def test_only_exact_reservation_exempts_its_existing_slot(self):
        rows=[self.queued(1),row(2)]
        a.check(Cursor(rows),'1','set1',generation='fence1')
        for fence in (None,'wrong'):
            with self.assertRaises(RuntimeError):a.check(Cursor(rows),'1','set1',generation=fence)
        rows[0]['source_metadata']['yoon_queue_v1']['owner']={'workflow_run_id':'5','run_attempt':'1'}
        with self.assertRaises(RuntimeError):a.check(Cursor(rows),'1','set1',generation='fence1')
    def test_queue_does_not_hide_uncertainty_or_metadata(self):
        for key in ('uncertain_hit','claimed_lease'):
            r=self.queued(1);r[key]=True
            with self.assertRaises(RuntimeError):a.occupied(r)
        r=self.queued(1);r['source_metadata']['yoon_metadata_enrichment_v1']={'status':'reserved','owner':{'workflow_run_id':'9','run_attempt':'1'}}
        with self.assertRaises(RuntimeError):a.occupied(r)
        r=self.queued(1,'garbage')
        with self.assertRaises(RuntimeError):a.occupied(r)
    def test_concurrent_queue_admission_model_counts_reservations(self):
        # Explicit advisory-lock model, not a multi-backend PostgreSQL test.
        mutex=threading.Lock();barrier=threading.Barrier(20);rows=[]
        def reserve(i):
            barrier.wait()
            with mutex:
                try:a.check(Cursor(rows),str(i),'set'+str(i))
                except RuntimeError:return False
                rows.append(self.queued(i));return True
        with ThreadPoolExecutor(max_workers=20) as pool:
            self.assertEqual(sum(pool.map(reserve,range(1,21))),2)
        self.assertEqual(len(rows),2)

    def test_retained_blocker_prevents_any_new_reservation_on_restart(self):
        queue=object.__new__(PrivateQueue)
        queue.blocked_ids=lambda:{'uncertain'}
        queue.ids=lambda:['unstarted','uncertain']
        queue.refresh_and_reserve=Mock()
        send=Mock()
        self.assertEqual(queue.tick(send),{'pending':2,'reserved':0,'blocked':1})
        queue.refresh_and_reserve.assert_not_called();send.assert_not_called()

    def test_same_tick_stops_immediately_after_send_exception(self):
        queue=object.__new__(PrivateQueue)
        queue.blocked_ids=lambda:set()
        queue.ids=lambda:['first','second']
        queue.refresh_and_reserve=Mock(side_effect=lambda run:{'setRunId':run,'generation':'fence'})
        queue.uncertain=Mock()
        send=Mock(side_effect=RuntimeError('uncertain'))
        self.assertEqual(queue.tick(send),{'pending':2,'reserved':1,'blocked':1})
        queue.refresh_and_reserve.assert_called_once_with('first')
        send.assert_called_once();queue.uncertain.assert_called_once()

    def test_same_tick_stops_immediately_after_refresh_exception(self):
        queue=object.__new__(PrivateQueue)
        queue.blocked_ids=lambda:set()
        queue.ids=lambda:['first','second']
        queue.refresh_and_reserve=Mock(side_effect=RuntimeError('private_queue_identity_changed'))
        send=Mock()
        self.assertEqual(queue.tick(send),{'pending':2,'reserved':0,'blocked':1})
        queue.refresh_and_reserve.assert_called_once_with('first');send.assert_not_called()

    def test_same_tick_stops_when_refresh_persists_blocked(self):
        queue=object.__new__(PrivateQueue)
        queue.blocked_ids=Mock(side_effect=[set(),{'first'},{'first'}])
        queue.ids=lambda:['first','second']
        queue.refresh_and_reserve=Mock(return_value=None)
        send=Mock()
        self.assertEqual(queue.tick(send),{'pending':2,'reserved':0,'blocked':1})
        queue.refresh_and_reserve.assert_called_once_with('first');send.assert_not_called()

    def test_controller_stops_on_blocker_without_sleep_or_rollover(self):
        from worker.jobs.yoon_queue import main
        fake=SimpleNamespace(tick=lambda send:{'pending':5,'reserved':0,'blocked':1})
        env={'GITHUB_ACTIONS':'true','RUNNER_OS':'Linux','GITHUB_REPOSITORY':'russell-algeo/dj-setlist-generator',
             'GITHUB_REF':'refs/heads/preview','WORKER_DEPLOYMENT_TARGET':'development'}
        with patch.dict('os.environ',env,clear=True), patch('worker.jobs.yoon_queue.PrivateQueue',return_value=fake), \
             patch('worker.config.get_settings',return_value=SimpleNamespace(api_base_url='https://example.invalid')), \
             patch('worker.callbacks.validate_callback_settings'), patch('worker.callbacks._open') as send, \
             patch('worker.jobs.yoon_queue.time.sleep') as sleep:
            self.assertEqual(main(),1)
            send.assert_not_called();sleep.assert_not_called()

    def test_finite_controller_is_privately_fenced(self):
        root=Path(__file__).resolve().parents[1]
        workflow=(root/'.github/workflows/process-set.yml').read_text()
        job=workflow.split('\n  private-queue:\n',1)[1]
        for token in ("github.ref == 'refs/heads/preview'", "deployment_target == 'development'", "private_analysis == 'true'", 'timeout-minutes: 250', 'persist-credentials: false'):
            self.assertIn(token,job)
        for token in ('actions: write','GH_PAT','PRODUCTION_DATABASE','upload-artifact','SPOTIFY','DISCOGS'):
            self.assertNotIn(token,job)
        self.assertIn("'process-set-private-queue-preview'",workflow)
        self.assertIn('time.sleep(60)',(root/'worker/jobs/yoon_queue.py').read_text())
    def test_public_dispatch_and_cleanup_remain_isolated(self):
        root=Path(__file__).resolve().parents[1]
        text=(root/'apps/web/lib/jobs/dispatch.ts').read_text()
        self.assertIn('eq(setRuns.publicationVisibility, "public")',text)
        self.assertNotIn('yoon_queue',text)
        queue=(root/'worker/jobs/yoon_queue.py').read_text()
        for token in ('DELETE FROM','set_runs SET status=', 'worker.jobs.process_set','requests.post'):
            self.assertNotIn(token,queue)

if __name__=='__main__':unittest.main()
