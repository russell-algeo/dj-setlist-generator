"""Cancellation regressions with synthetic rows, no provider/database requests."""
import asyncio
import os
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from worker.jobs import process_set as job
from worker import db


class CancellationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.row = {
            'id': 'run', 'submission_id': 'submission', 'status': 'recognizing',
            'stage': 'slot_0_recognizing', 'cancel_requested_at': None,
            'published_set_id': None, 'source_url': 'https://soundcloud.com/test/set',
            'source_metadata': {'segment_count': 1, 'mix_info': {'title': 'Test'}},
            'artist_name': None, 'create_playlist': False,
        }
        self.mocks = {}
        for name in ['_load_run', 'get_active_workflow_run_id', 'mark_run_stage',
                     'mark_set_run', 'cancel_set_run', 'insert_worker_event',
                     'finalize_submission_from_runs', 'claim_next_lease', 'claim_workflow_run', 'complete_lease',
                     'upsert_segment_hit', 'get_lease_rollup', 'list_segment_hits',
                     'update_set_run_metadata', '_revalidate']:
            self.mocks[name] = self.stack.enter_context(patch.object(job, name))
        self.mocks['_load_run'].side_effect = lambda _: dict(self.row)
        self.mocks['mark_run_stage'].return_value = {'id': 'run'}
        self.mocks['cancel_set_run'].return_value = {'id': 'run', 'submission_id': 'submission'}
        self.context = SimpleNamespace(mix_info={'title': 'Test'})
        self.restore = self.stack.enter_context(patch('worker.pipeline.recognize.restore_set_context', return_value=self.context))
        self.recognize = self.stack.enter_context(patch('worker.pipeline.recognize.recognize_segment_range', new_callable=AsyncMock))
        self.mocks['claim_next_lease'].side_effect = [
            {'id': 'lease', 'segment_start_index': 0, 'segment_end_index': 0}, None]

    async def test_cancelled_before_recognition_does_not_restore_or_claim(self):
        self.row['cancel_requested_at'] = 'now'
        self.assertEqual(await job.recognize_phase('run', slot_index=0),
                         {'lease_count': 0, 'recognized_count': 0})
        self.restore.assert_not_called()
        self.mocks['claim_next_lease'].assert_not_called()
        self.mocks['cancel_set_run'].assert_called_once()
        self.mocks['mark_set_run'].assert_not_called()

    async def test_cancel_during_recognition_stops_task_without_failed_lease_or_publish(self):
        stopped = asyncio.Event()
        async def recognition(*args, **kwargs):
            self.row['cancel_requested_at'] = 'now'
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        self.recognize.side_effect = recognition
        await job.recognize_phase('run', slot_index=0)
        self.assertTrue(stopped.is_set())
        self.mocks['complete_lease'].assert_not_called()
        self.mocks['mark_set_run'].assert_not_called()
        self.mocks['cancel_set_run'].assert_called_once()
        self.mocks['finalize_submission_from_runs'].assert_called_once_with('submission')

    async def test_normal_recognition_completes_lease(self):
        await job.recognize_phase('run', slot_index=0)
        self.mocks['complete_lease'].assert_called_once_with('lease', success=True)
        self.mocks['cancel_set_run'].assert_not_called()

    async def test_cancelled_before_bootstrap_never_downloads(self):
        self.row['status'] = 'cancelled'
        with patch('worker.pipeline.recognize.prepare_set_context') as prepare:
            self.assertEqual(await job.bootstrap_phase('run'), {})
        prepare.assert_not_called()

    async def test_cancelled_before_publish_has_no_provider_or_archive_calls(self):
        self.row['cancel_requested_at'] = 'now'
        with patch.object(job, '_publish_set_run_payload') as publish:
            self.assertIsNone(await job.publish_phase('run'))
        self.restore.assert_not_called()
        publish.assert_not_called()

    async def test_cancel_during_enrichment_does_not_publish(self):
        self.mocks['get_lease_rollup'].return_value = {
            'total_count': 1, 'pending_count': 0, 'claimed_count': 0,
            'failed_count': 0, 'completed_count': 1}
        self.mocks['list_segment_hits'].return_value = [{'segment_index': 0, 'raw_data': {'matches': []}}]
        def enrich(*args, **kwargs):
            self.row['cancel_requested_at'] = 'now'
            return [], {'title': 'Test'}
        with patch('source_url_normalizer.resolve_canonical_source_url', side_effect=lambda x: x), \
             patch('worker.pipeline.aggregate.recognitions_from_segment_hits', return_value=[]), \
             patch('worker.pipeline.aggregate.build_tracks_from_recognitions', return_value=([], [])), \
             patch('worker.pipeline.enrich.enrich_tracks', side_effect=enrich), \
             patch.object(job, '_publish_set_run_payload') as publish:
            self.assertIsNone(await job.publish_phase('run'))
        publish.assert_not_called()
        self.mocks['mark_set_run'].assert_not_called()
        self.mocks['cancel_set_run'].assert_called_once()

    def test_publish_rejection_maps_to_cancellation_not_failure(self):
        response = MagicMock(status_code=409, ok=False)
        response.json.return_value = {'errorCode': 'run_cancelled'}
        with patch.object(job, 'get_settings', return_value=SimpleNamespace(api_base_url='https://preview.test', internal_secret='synthetic')), \
             patch.object(job, 'post_callback', return_value=response):
            with self.assertRaises(job.RunCancelledError):
                job._publish_set_run_payload(set_run_id='run', payload={})

    def test_publish_sends_owner_and_superseded_rejection(self):
        response = MagicMock(status_code=409, ok=False)
        response.json.return_value = {'errorCode': 'workflow_superseded'}
        with patch.dict(os.environ, {'GITHUB_RUN_ID': 'current'}), \
             patch.object(job, 'get_settings', return_value=SimpleNamespace(api_base_url='https://preview.test', internal_secret='synthetic')), \
             patch.object(job, 'post_callback', return_value=response) as request:
            with self.assertRaises(job.WorkflowSupersededError):
                job._publish_set_run_payload(set_run_id='run', payload={})
        self.assertEqual(request.call_args.kwargs['json']['workflowRunId'], 'current')

    async def test_superseded_worker_cannot_acknowledge_new_owner_cancellation(self):
        self.row['cancel_requested_at'] = 'now'
        self.mocks['get_active_workflow_run_id'].return_value = 'new-owner'
        with patch.dict(os.environ, {'GITHUB_RUN_ID': 'old-owner'}):
            with self.assertRaises(job.WorkflowSupersededError):
                await job.recognize_phase('run', slot_index=0)
        self.mocks['cancel_set_run'].assert_not_called()

    def test_retired_workflow_cannot_force_claim_after_retry(self):
        self.mocks['claim_workflow_run'].return_value = None
        with patch.dict(os.environ, {'GITHUB_RUN_ID': 'retired'}):
            with self.assertRaises(job.WorkflowSupersededError):
                job._claim_workflow_ownership('run', force=True)
        self.mocks['update_set_run_metadata'].assert_not_called()

    def test_new_workflow_claims_once_after_retry(self):
        self.mocks['claim_workflow_run'].return_value = {'previous_workflow_run_id': 'awaiting_dispatch'}
        with patch.dict(os.environ, {'GITHUB_RUN_ID': 'new'}):
            self.assertEqual(job._claim_workflow_ownership('run', force=True), 'awaiting_dispatch')
        self.mocks['claim_workflow_run'].assert_called_once_with('run', workflow_run_id='new', force=True, dispatch_generation=None)

    async def test_delayed_old_dispatch_cannot_start_after_new_generation(self):
        self.row['source_metadata']['dispatch_generation'] = 'new-generation'
        with patch.dict(os.environ, {'GITHUB_RUN_ID': 'not-yet-recorded', 'SET_LIST_DISPATCH_GENERATION': 'old-generation'}):
            with self.assertRaisesRegex(job.WorkflowSupersededError, 'generation'):
                await job.bootstrap_phase('run')
        self.mocks['claim_workflow_run'].assert_not_called()
        self.restore.assert_not_called()

    def test_missing_generation_cannot_join_fenced_run(self):
        self.row['source_metadata']['dispatch_generation'] = 'new-generation'
        with self.assertRaisesRegex(job.WorkflowSupersededError, 'generation'):
            job._assert_not_cancelled('run')

    def test_finalize_cancellation_before_failed_state(self):
        self.row.update(status='failed', cancel_requested_at='now')
        job.finalize_phase('run', bootstrap_result='success', recognize_result='failure', publish_result='skipped')
        self.mocks['cancel_set_run'].assert_called_once()
        self.mocks['mark_set_run'].assert_not_called()

    def test_finalize_does_not_relabel_already_published_data(self):
        self.row.update(status='completed', published_set_id='set', cancel_requested_at='now')
        job.finalize_phase('run', bootstrap_result='success', recognize_result='success', publish_result='success')
        self.mocks['cancel_set_run'].assert_not_called()
        self.mocks['mark_set_run'].assert_not_called()

    def test_failure_does_not_reopen_uncertain_publication_boundary(self):
        self.row['stage'] = 'publishing_committed'
        job._mark_failed(self.row, RuntimeError('response lost'))
        self.mocks['mark_set_run'].assert_not_called()
        self.mocks['insert_worker_event'].assert_called_with(
            submission_id='submission', set_run_id='run', event_type='set_run.publish.uncertain',
            message='Publication was admitted; preserve its boundary pending reconciliation')


class CancellationSqlTests(unittest.TestCase):
    def test_cancel_compare_and_set_preserves_owner_and_committed_publication(self):
        with patch.object(db, 'fetch_one', return_value=None) as fetch:
            self.assertIsNone(db.cancel_set_run('run', workflow_run_id='owner'))
        sql, params = fetch.call_args.args
        self.assertIn("published_set_id is null", sql)
        self.assertIn("stage is distinct from 'publishing_committed'", sql)
        self.assertIn("status <> 'cancelled'", sql)
        self.assertIn("active_workflow_run_id", sql)
        self.assertIn("cancelled_leases", sql)
        self.assertEqual(params, ('run', 'owner', 'owner'))

    def test_stage_and_terminal_writes_do_not_erase_accepted_cancellation(self):
        with patch.object(db, 'fetch_one') as fetch:
            db.mark_run_stage('run', status='recognizing', stage='slot')
        self.assertIn('cancel_requested_at is null', fetch.call_args.args[0])
        with patch.object(db, 'execute') as execute:
            db.mark_set_run('run', status='failed', stage='failed')
        self.assertIn('cancel_requested_at is null', execute.call_args.args[0])
        self.assertIn("stage is distinct from 'publishing_committed'", execute.call_args.args[0])

    def test_completed_lease_cannot_revive_cancelled_lease(self):
        with patch.object(db, 'execute') as execute:
            db.complete_lease('lease', success=True)
        self.assertIn("lease.status = 'claimed'", execute.call_args.args[0])
        self.assertIn('run.cancel_requested_at is null', execute.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
