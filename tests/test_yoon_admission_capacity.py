"""Offline candidate configuration and unchanged reservation safety regressions."""
from pathlib import Path
import copy
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch
from worker.jobs import yoon_admission as admission
from worker.jobs.yoon_queue import PrivateQueue
from worker.scheduler import build_scheduler_plan
from test_yoon_admission import Cursor, row

def reservation(i):
    r = row(i, status='private_resume_pending')
    r['source_metadata']['yoon_queue_v1'] = dict(version=1, status='reserved',
        generation=f'gen-{i}', owner=None)
    return r


class QueueModel(PrivateQueue):
    """Real tick/check/occupied code, synthetic row store and no send adapter."""
    def __init__(self, size=30):
        self.todo = list(range(1, size + 1))
        self.rows = []
        self.blocked = set()
    def ids(self, **kwargs): return [str(i) for i in self.todo]
    def blocked_ids(self): return set(self.blocked)
    def refresh_and_reserve(self, run_id):
        i = int(run_id)
        if any(r['id'] == run_id for r in self.rows): return None
        admission.check(Cursor(self.rows), run_id, f'set{i}')
        self.rows.append(reservation(i))
        return dict(setRunId=run_id, generation=f'gen-{i}')
    def uncertain(self, payload): self.blocked.add(payload['setRunId'])


class OfflineParityTests(unittest.TestCase):
    def test_two_and_configured_ten_bound_200_contenders(self):
        for cap in (1, 2, 3, 10, 17):
            with patch.dict(os.environ, {'PROCESS_SET_MAX_ACTIVE_RUNS': str(cap)}):
                rows=[]; lock=threading.Lock()
                def submit(i):
                    with lock:
                        try: admission.check(Cursor(rows), str(i), f'set{i}')
                        except RuntimeError as e:
                            self.assertEqual(str(e), 'private_admission_capacity'); return False
                        rows.append(reservation(i)); return True
                with ThreadPoolExecutor(max_workers=32) as pool:
                    result=list(pool.map(submit,range(1,201)))
                self.assertEqual(sum(result), cap)
                self.assertEqual(len(rows), cap)

    def test_capacity_boundary_counts_mixed_work(self):
        for cap in (1, 2, 3, 10, 17):
            with patch.dict(os.environ, {'PROCESS_SET_MAX_ACTIVE_RUNS': str(cap)}):
                rows=[reservation(i) if i % 2 else row(i) for i in range(1,cap)]
                admission.check(Cursor(rows),'100','set100')
                e=row(cap,status='private_resume_complete')
                e['source_metadata']['yoon_metadata_enrichment_v1'] = dict(status='reserved',owner=dict(workflow_run_id='777',run_attempt='1'))
                rows.append(e)
                with self.assertRaisesRegex(RuntimeError,'private_admission_capacity'):
                    admission.check(Cursor(rows),'100','set100')
                e['source_metadata']['yoon_metadata_enrichment_v1']['status']='complete'
                admission.check(Cursor(rows),'100','set100')

    def test_generation_consumes_own_reservation_at_full_capacity(self):
        for cap in (1, 2, 3, 10, 17):
            with patch.dict(os.environ, {'PROCESS_SET_MAX_ACTIVE_RUNS': str(cap)}):
                rows=[reservation(i) for i in range(1,cap+1)]
                before=copy.deepcopy(rows)
                admission.check(Cursor(rows),'1','set1',generation='gen-1')
                for wrong in (None,'wrong','gen-2'):
                    with self.assertRaisesRegex(RuntimeError,'duplicate_target'):
                        admission.check(Cursor(rows),'1','set1',generation=wrong)
                self.assertEqual(rows,before)

    def test_duplicate_target_never_uses_spare_capacity(self):
        with patch.dict(os.environ, {'PROCESS_SET_MAX_ACTIVE_RUNS': '10'}):
            with self.assertRaisesRegex(RuntimeError,'duplicate_target'):
                admission.check(Cursor([reservation(1)]),'2','set1')

    def test_uncertain_owner_blocks_even_with_nine_free_slots(self):
        with patch.dict(os.environ, {'PROCESS_SET_MAX_ACTIVE_RUNS': '10'}):
            for key in ('review_required','in_flight'):
                r=row(1,status='private_resume_paused')
                r['source_metadata']['yoon_resume'][key]=True
                with self.assertRaisesRegex(RuntimeError,'uncertain_owner'):
                    admission.check(Cursor([r]),'2','set2')

    def test_tick_fills_only_available_capacity_then_no_resend(self):
        for cap in (1, 2, 3, 10, 17):
            with patch.dict(os.environ, {'PROCESS_SET_MAX_ACTIVE_RUNS': str(cap)}):
                q=QueueModel(); sends=[]
                result=q.tick(sends.append)
                self.assertEqual(result,dict(pending=30,reserved=cap,blocked=0))
                self.assertEqual(q.tick(sends.append)['reserved'],0)
                self.assertEqual(len(sends),cap)

    def test_tick_one_shot_stays_one_at_configured_ten(self):
        with patch.dict(os.environ, {'PROCESS_SET_MAX_ACTIVE_RUNS': '10'}):
            q=QueueModel(); sends=[]
            self.assertEqual(q.tick(sends.append,max_reservations=1)['reserved'],1)
            self.assertEqual(len(sends),1)

    def test_uncertain_send_never_retries_or_continues(self):
        with patch.dict(os.environ, {'PROCESS_SET_MAX_ACTIVE_RUNS': '10'}):
            q=QueueModel(); sends=[]
            def ambiguous(p):
                sends.append(p); raise TimeoutError('synthetic')
            first=q.tick(ambiguous)
            self.assertEqual(first,dict(pending=30,reserved=1,blocked=1))
            self.assertEqual(q.tick(ambiguous),dict(pending=30,reserved=0,blocked=1))
            self.assertEqual(len(sends),1)
            self.assertEqual(len(q.rows),1)

    def test_shared_auto_scheduler_long_set_geometry(self):
        with patch.dict(os.environ,{},clear=True):
            for windows in (239,240,359,394,479):
                p=build_scheduler_plan(windows)
                self.assertEqual(p.slot_count,12)
                self.assertEqual(p.lease_count,24)
                self.assertEqual(p.mode,'auto')
            p=build_scheduler_plan(1)
            self.assertEqual((p.slot_count,p.lease_size),(1,1))

    def test_shared_scheduler_respects_requested_manual_geometry(self):
        with patch.dict(os.environ,{'RECOGNITION_SLOT_COUNT_REQUESTED':'8','LEASE_SIZE_REQUESTED':'15'},clear=True):
            p=build_scheduler_plan(479)
            self.assertEqual((p.slot_count,p.lease_size,p.mode),(8,15,'manual'))



class CapacityConfigurationTests(unittest.TestCase):
    def test_reads_same_name_used_by_ordinary_dispatcher(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn('processSetMaxActiveRuns: getPositiveInt("PROCESS_SET_MAX_ACTIVE_RUNS", 10)', (root / 'apps/web/lib/env.ts').read_text())
        self.assertIn('const maxActive = env.processSetMaxActiveRuns;', (root / 'apps/web/lib/jobs/dispatch.ts').read_text())
        self.assertIn('PROCESS_SET_MAX_ACTIVE_RUNS: ${{ vars.PROCESS_SET_MAX_ACTIVE_RUNS }}', (root / '.github/workflows/process-set.yml').read_text())
        self.assertFalse(hasattr(admission, 'CAP'))

    def test_missing_blank_invalid_fail_before_database_or_send(self):
        values = [None, '', '0', '-1', '+10', '01', '10x', '10.5', '1e2', 'NaN', 'Infinity', ' 10', '10 ', '１０', '9007199254740992', '9'*10000]
        for value in values:
            with self.subTest(value=str(value)[:20]), patch.dict(os.environ, {}, clear=True):
                if value is not None:
                    os.environ['PROCESS_SET_MAX_ACTIVE_RUNS'] = value
                cur = Mock()
                queue = PrivateQueue(connect=Mock(side_effect=AssertionError('DB forbidden')))
                send = Mock()
                with self.assertRaisesRegex(RuntimeError, '^private_admission_capacity_(invalid|unconfigured)$'):
                    admission.check(cur, '1', 'set1')
                cur.execute.assert_not_called()
                with self.assertRaisesRegex(RuntimeError, '^private_admission_capacity_(invalid|unconfigured)$'):
                    queue.tick(send)
                queue.connect.assert_not_called()
                send.assert_not_called()

    def test_environment_value_is_not_frozen_at_module_import(self):
        with patch.dict(os.environ, {'PROCESS_SET_MAX_ACTIVE_RUNS': '2'}):
            self.assertEqual(admission.capacity(), 2)
            os.environ['PROCESS_SET_MAX_ACTIVE_RUNS'] = '17'
            self.assertEqual(admission.capacity(), 17)

    def test_lowered_capacity_retains_existing_reservations(self):
        rows = [reservation(i) for i in range(1, 11)]
        before = copy.deepcopy(rows)
        with patch.dict(os.environ, {'PROCESS_SET_MAX_ACTIVE_RUNS': '2'}):
            with self.assertRaisesRegex(RuntimeError, 'private_admission_capacity'):
                admission.check(Cursor(rows), '20', 'set20')
        self.assertEqual(rows, before)

    def test_oversized_pilot_limit_rejected_before_database(self):
        q = PrivateQueue(connect=Mock(side_effect=AssertionError('DB forbidden')))
        with patch.dict(os.environ, {'PROCESS_SET_MAX_ACTIVE_RUNS': '10'}):
            for value in (0, -1, 11, True, '10', 10.0):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    q.tick(Mock(), max_reservations=value)
        q.connect.assert_not_called()
