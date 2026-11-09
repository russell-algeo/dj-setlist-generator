"""Exercise discovery orchestration without provider or database side effects."""
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch
from worker.jobs import discover_artist as job
from config import Config

class DiscoveryJobTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.mocks = {}
        for name in ['fetch_one', 'execute', 'insert_worker_event', 'mark_submission',
                     'finalize_submission_from_runs', '_dispatch_pending', 'ArtistManager',
                     'DjSetDiscoverer', 'resolve_canonical_source_url', 'json_value']:
            self.mocks[name] = self.stack.enter_context(patch.object(job, name))
        self.mocks['resolve_canonical_source_url'].side_effect = lambda url: url
        self.mocks['json_value'].side_effect = lambda value: value
        self.mocks['fetch_one'].side_effect = [
            {'id': 'submission', 'artist_name': 'Test DJ', 'artist_aliases': ['Alias'], 'max_sets_override': 1},
            {'count': 1},
        ]
        self.original_limit = Config.MAX_SETS_PER_ARTIST

    def test_discovery_queues_then_dispatches_and_restores_limit(self):
        candidate = SimpleNamespace(url='https://soundcloud.com/test/set', platform='soundcloud',
            title='Test set', duration_minutes=30, event=None, year=None, source_links=[])
        def discover():
            self.assertEqual(Config.MAX_SETS_PER_ARTIST, 1)
            return [candidate]
        self.mocks['DjSetDiscoverer'].return_value.discover.side_effect = discover
        job.run('submission')
        statements = [call.args[0] for call in self.mocks['execute'].call_args_list]
        self.assertTrue(any('insert into ops.set_runs' in sql and 'not exists' in sql for sql in statements))
        run_sql = next(sql for sql in statements if 'insert into ops.set_runs' in sql)
        self.assertIn('publication_visibility', run_sql)
        self.assertIn("pub.publication_visibility = 'public'", run_sql)
        self.assertIn("published.visibility = 'public'", run_sql)
        self.assertIn('pub.archive_removed_at is null', run_sql)
        self.assertIn("s.visibility = 'public'", run_sql)
        self.mocks['_dispatch_pending'].assert_called_once()
        self.assertEqual(Config.MAX_SETS_PER_ARTIST, self.original_limit)

    def test_empty_discovery_fails_without_dispatch(self):
        self.mocks['DjSetDiscoverer'].return_value.discover.return_value = []
        job.run('submission')
        self.mocks['mark_submission'].assert_called_with('submission', status='failed', error_summary='No DJ sets discovered')
        self.mocks['_dispatch_pending'].assert_not_called()
        self.assertEqual(Config.MAX_SETS_PER_ARTIST, self.original_limit)

    def test_provider_failure_records_failure_and_restores_limit(self):
        self.mocks['DjSetDiscoverer'].return_value.discover.side_effect = RuntimeError('provider unavailable')
        with self.assertRaisesRegex(RuntimeError, 'provider unavailable'):
            job.run('submission')
        self.mocks['mark_submission'].assert_called_with('submission', status='failed', error_summary='provider unavailable')
        self.mocks['_dispatch_pending'].assert_not_called()
        self.assertEqual(Config.MAX_SETS_PER_ARTIST, self.original_limit)

    def test_already_published_discovery_finishes_without_new_dispatch(self):
        self.mocks['fetch_one'].side_effect = [
            {'id':'submission','artist_name':'Test DJ','artist_aliases':[],'max_sets_override':1}, {'count':0}]
        self.mocks['DjSetDiscoverer'].return_value.discover.return_value = [SimpleNamespace(
            url='https://soundcloud.com/test/set', platform='soundcloud', title='Test set',
            duration_minutes=30, event=None, year=None, source_links=[])]
        job.run('submission')
        self.mocks['finalize_submission_from_runs'].assert_called_once_with('submission')
        self.mocks['_dispatch_pending'].assert_not_called()
