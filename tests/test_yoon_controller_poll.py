"""Controller cadence changes scheduling only, never admission or rollover fences."""
import json
from pathlib import Path
import re
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from worker.jobs.yoon_queue import main, PrivateQueue
from worker.jobs import yoon_admission as admission
from test_yoon_admission import Cursor, row


PENDING = dict(pending=4, reserved=0, blocked=0)
EMPTY = dict(pending=0, reserved=0, blocked=0)


class ControllerPollTests(TestCase):
    def setUp(self):
        self.enterContext(patch.dict('os.environ', {'PROCESS_SET_MAX_ACTIVE_RUNS': '2'}))

    def run_controller(self, results=None, *, tick_seconds=0, rollover_ids=None, send_error=None,
                       once=None, queue_override=None, after_send=None, monotonic_values=None):
        clock = SimpleNamespace(now=0)
        ticks, sleeps = [], []
        results = iter(results) if results is not None else None

        def tick(send, **kwargs):
            ticks.append(clock.now)
            clock.now += tick_seconds
            if queue_override:
                return queue_override.tick(send, **kwargs)
            return next(results) if results is not None else dict(PENDING)

        def sleep(seconds):
            self.assertGreater(seconds, 0)
            self.assertLessEqual(seconds, 180)
            sleeps.append(seconds)
            clock.now += seconds

        queue = SimpleNamespace(tick=Mock(side_effect=tick),
                                ids=Mock(return_value=rollover_ids or []))
        response = Mock()
        response.__enter__ = Mock(return_value=SimpleNamespace(status=200))
        response.__exit__ = Mock(return_value=False)
        env = dict(PROCESS_SET_MAX_ACTIVE_RUNS='2', GITHUB_ACTIONS='true', RUNNER_OS='Linux',
                   GITHUB_REPOSITORY='russell-algeo/dj-setlist-generator',
                   GITHUB_REF='refs/heads/preview', WORKER_DEPLOYMENT_TARGET='development',
                   GITHUB_RUN_ID='9001', GITHUB_RUN_ATTEMPT='1')
        if once is not None:
            env['PRIVATE_QUEUE_ONCE'] = once
        def open_callback(*args, **kwargs):
            if send_error:
                raise send_error
            if after_send:
                after_send()
            return response
        with patch.dict('os.environ', env, clear=True), \
             patch('socket.socket.connect', side_effect=AssertionError('network forbidden')), \
             patch('socket.getaddrinfo', side_effect=AssertionError('DNS forbidden')), \
             patch('psycopg.connect', side_effect=AssertionError('live DB forbidden')), \
             patch('worker.jobs.yoon_queue.PrivateQueue', return_value=queue), \
             patch('worker.jobs.yoon_queue.time.monotonic',
                   side_effect=monotonic_values if monotonic_values is not None else lambda: clock.now) as monotonic, \
             patch('worker.jobs.yoon_queue.time.sleep', side_effect=sleep), \
             patch('worker.jobs.yoon_queue.print'), \
             patch('worker.config.get_settings', return_value=SimpleNamespace(api_base_url='https://example.invalid')), \
             patch('worker.callbacks.validate_callback_settings'), \
             patch('worker.callbacks.callback_headers', return_value={}), \
             patch('worker.callbacks._open', side_effect=open_callback) as send:
            if send_error and once != 'true':
                with self.assertRaises(type(send_error)) as caught:
                    main()
                self.assertIs(caught.exception, send_error)
                result = None
            else:
                result = main()
        return SimpleNamespace(result=result, clock=clock, ticks=ticks, sleeps=sleeps,
                               queue=queue, send=send, monotonic=monotonic)

    def test_first_tick_immediate_then_fixed_180_seconds_without_final_sleep(self):
        run = self.run_controller([dict(PENDING), dict(EMPTY)])
        self.assertEqual(run.result, 0)
        self.assertEqual(run.ticks, [0, 180])
        self.assertEqual(run.sleeps, [180])
        run.queue.ids.assert_not_called()
        run.send.assert_not_called()

    def test_blocker_stops_without_sleep_or_rollover(self):
        run = self.run_controller([dict(PENDING, blocked=1)])
        self.assertEqual(run.result, 1)
        self.assertEqual(run.ticks, [0])
        self.assertEqual(run.sleeps, [])
        run.queue.ids.assert_not_called()
        run.send.assert_not_called()

    def test_four_hours_has_80_ticks_and_exactly_one_fenced_rollover(self):
        run = self.run_controller(rollover_ids=['synthetic-first', 'synthetic-second'])
        self.assertEqual(run.result, 0)
        self.assertEqual(run.ticks, list(range(0, 14400, 180)))
        self.assertEqual(run.sleeps, [180] * 80)
        self.assertEqual(run.clock.now, 14400)
        run.queue.ids.assert_called_once_with(rollover=True)
        run.send.assert_called_once()
        request = run.send.call_args.args[0]
        self.assertEqual(request.full_url, 'https://example.invalid/api/internal/private-yoon-dispatch')
        self.assertEqual(request.method, 'POST')
        self.assertEqual(json.loads(request.data), dict(setRunId='synthetic-first', controller=True,
                                                     workflowRunId='9001', runAttempt='1'))
        self.assertEqual(run.send.call_args.kwargs, {'timeout': 90})

    def test_last_sleep_is_truncated_to_deadline_after_slow_tick(self):
        run = self.run_controller(tick_seconds=14363)
        self.assertEqual(run.ticks, [0])
        self.assertEqual(run.sleeps, [37])
        self.assertEqual(run.clock.now, 14400)
        run.queue.ids.assert_called_once_with(rollover=True)
        run.send.assert_not_called()

    def test_tick_already_past_deadline_does_not_sleep_or_start_another_tick(self):
        run = self.run_controller(tick_seconds=14401)
        self.assertEqual(run.ticks, [0])
        self.assertEqual(run.sleeps, [])
        run.queue.ids.assert_called_once_with(rollover=True)
        run.send.assert_not_called()

    def test_empty_rollover_queue_does_not_send(self):
        run = self.run_controller()
        run.queue.ids.assert_called_once_with(rollover=True)
        run.send.assert_not_called()

    def test_uncertain_rollover_is_never_retried(self):
        error = RuntimeError('synthetic uncertain send')
        run = self.run_controller(rollover_ids=['synthetic-first'], send_error=error)
        self.assertEqual(len(run.ticks), 80)
        run.queue.ids.assert_called_once_with(rollover=True)
        run.send.assert_called_once()

    def capacity_queue(self, occupied):
        """Real tick and admission check, synthetic transactional row adapter."""
        rows = [row(index) for index in range(1, occupied + 1)]
        queue = object.__new__(PrivateQueue)
        blocked = set()
        queue.blocked_ids = lambda: set(blocked)
        queue.ids = Mock(return_value=['10', '11', '12', '13'])
        def reserve(run_id):
            admission.check(Cursor(rows), run_id, f'set{run_id}')
            reserved = row(run_id, status='private_resume_pending')
            reserved['source_metadata']['yoon_queue_v1'] = dict(
                version=1, status='reserved', generation=f'fence{run_id}', owner=None)
            rows.append(reserved)
            return dict(setRunId=run_id, generation=f'fence{run_id}')
        queue.refresh_and_reserve = Mock(side_effect=reserve)
        queue.uncertain = Mock(side_effect=lambda reservation: blocked.add(reservation['setRunId']))
        return queue, rows, blocked

    def test_once_zero_one_or_two_available_slots_never_sleeps_or_rolls_over(self):
        for occupied in (0, 1, 2):
            with self.subTest(occupied=occupied):
                queue, rows, _ = self.capacity_queue(occupied)
                run = self.run_controller(once='true', queue_override=queue)
                self.assertEqual(run.result, 0)
                self.assertEqual(run.ticks, [0])
                self.assertEqual(run.sleeps, [])
                self.assertEqual(run.send.call_count, min(1, 2 - occupied))
                self.assertEqual(len(rows), occupied + min(1, 2 - occupied))
                run.queue.ids.assert_not_called()  # no main-loop rollover
                run.queue.tick.assert_called_once()
                self.assertEqual(run.queue.tick.call_args.kwargs, {'max_reservations': 1})

    def test_once_cumulative_limit_holds_when_each_child_finishes_immediately(self):
        queue, rows, _ = self.capacity_queue(0)
        run = self.run_controller(once='true', queue_override=queue, after_send=rows.clear)
        self.assertEqual(run.result, 0)
        self.assertEqual(run.send.call_count, 1)
        self.assertEqual(queue.refresh_and_reserve.call_count, 1)
        self.assertEqual(rows, [])
        self.assertEqual(run.sleeps, [])
        run.queue.ids.assert_not_called()

    def test_once_ignores_clock_jump_and_cannot_reach_rollover(self):
        queue, _, _ = self.capacity_queue(0)
        run = self.run_controller(once='true', queue_override=queue,
                                  monotonic_values=[0, 4 * 60 * 60 + 1])
        self.assertEqual(run.result, 0)
        self.assertEqual(run.ticks, [0])
        run.send.assert_called_once()
        self.assertEqual(run.sleeps, [])
        run.queue.ids.assert_not_called()
        run.monotonic.assert_not_called()

    def test_default_tick_keeps_cap_two_without_new_cumulative_limit(self):
        for immediately_finished in (False, True):
            with self.subTest(immediately_finished=immediately_finished):
                queue, rows, _ = self.capacity_queue(0)
                send = Mock(side_effect=(lambda reservation: rows.clear()) if immediately_finished else None)
                result = queue.tick(send)
                self.assertEqual(send.call_count, 4 if immediately_finished else 2)
                self.assertEqual(result['reserved'], send.call_count)
                self.assertEqual(result['blocked'], 0)

    def test_once_blocker_prevents_dispatch(self):
        queue, _, blocked = self.capacity_queue(0)
        blocked.add('10')
        run = self.run_controller(once='true', queue_override=queue)
        self.assertEqual(run.result, 1)
        queue.refresh_and_reserve.assert_not_called()
        run.send.assert_not_called()
        self.assertEqual(run.sleeps, [])
        run.queue.ids.assert_not_called()

    def test_once_can_reconcile_finished_rows_before_first_reservation(self):
        queue, _, _ = self.capacity_queue(0)
        reserve = queue.refresh_and_reserve.side_effect
        queue.ids.return_value = ['done', '10', '11']
        queue.refresh_and_reserve.side_effect = lambda run_id: None if run_id == 'done' else reserve(run_id)
        run = self.run_controller(once='true', queue_override=queue)
        self.assertEqual(run.result, 0)
        self.assertEqual([call.args[0] for call in queue.refresh_and_reserve.call_args_list], ['done', '10'])
        run.send.assert_called_once()
        self.assertEqual(run.sleeps, [])
        run.queue.ids.assert_not_called()

    def test_once_still_runs_final_blocker_check_after_dispatch_limit(self):
        queue, _, _ = self.capacity_queue(0)
        queue.blocked_ids = Mock(side_effect=[set(), set(), {'newly-blocked-peer'}])
        run = self.run_controller(once='true', queue_override=queue)
        self.assertEqual(run.result, 1)
        self.assertEqual(queue.blocked_ids.call_count, 3)
        run.send.assert_called_once()
        queue.refresh_and_reserve.assert_called_once_with('10')
        self.assertEqual(run.sleeps, [])
        run.queue.ids.assert_not_called()

    def test_once_uncertain_send_preserves_reservation_and_stops(self):
        queue, rows, _ = self.capacity_queue(0)
        run = self.run_controller(once='true', queue_override=queue,
                                  send_error=RuntimeError('uncertain dispatch'))
        self.assertEqual(run.result, 1)
        self.assertEqual(len(rows), 1)
        self.assertTrue(admission.occupied(rows[0]))
        queue.uncertain.assert_called_once()
        run.send.assert_called_once()
        queue.refresh_and_reserve.assert_called_once_with('10')
        self.assertEqual(run.sleeps, [])
        run.queue.ids.assert_not_called()

    def test_invalid_once_values_fail_closed_before_tick(self):
        for value in ('', 'TRUE', 'False', '1', 'yes', ' true', 'false '):
            with self.subTest(value=value):
                run = self.run_controller(once=value)
                self.assertEqual(run.result, 2)
                self.assertEqual(run.ticks, [])
                self.assertEqual(run.sleeps, [])
                run.send.assert_not_called()
                run.queue.ids.assert_not_called()

    def test_explicit_false_keeps_normal_controller_loop(self):
        run = self.run_controller([dict(PENDING), dict(EMPTY)], once='false')
        self.assertEqual(run.ticks, [0, 180])
        self.assertEqual(run.sleeps, [180])
        self.assertEqual(run.queue.tick.call_args.kwargs, {})

    def test_dispatch_limit_cannot_exceed_cap_or_accept_coerced_values(self):
        queue, _, _ = self.capacity_queue(0)
        for limit in (0, 3, -1, True, '2', 2.0):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                queue.tick(Mock(), max_reservations=limit)
        queue.ids.assert_not_called()

    def test_tenth_boolean_input_is_private_queue_job_only(self):
        text = (Path(__file__).resolve().parents[1]/'.github/workflows/process-set.yml').read_text()
        inputs = text.split('    inputs:\n', 1)[1].split('\nconcurrency:', 1)[0]
        self.assertEqual(len(re.findall(r'^      \w+:$', inputs, flags=re.M)), 10)
        self.assertIn('      private_queue_once:\n', inputs)
        once = inputs.split('      private_queue_once:\n', 1)[1]
        self.assertIn('        default: false\n        type: boolean', once)
        before, job = text.split('\n  private-queue:\n', 1)
        self.assertNotIn('PRIVATE_QUEUE_ONCE:', before)
        self.assertEqual(job.count('PRIVATE_QUEUE_ONCE:'), 1)
        self.assertIn("PRIVATE_QUEUE_ONCE: ${{ github.event.inputs.private_queue_once || 'false' }}", job)
