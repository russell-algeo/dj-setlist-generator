"""Fail-closed retry policy, independent of a live database or provider."""
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from psycopg import OperationalError
from psycopg.errors import DeadlockDetected, LockNotAvailable, QueryCanceled
from psycopg.pq import ConnStatus, TransactionStatus as TS
from worker.recognition_transactions import recognition_transaction, retry_lock_timeouts


def timeout(message='canceling statement due to lock timeout'):
    return LockNotAvailable(message, info={ord('M'): message.encode(), ord('C'): b'55P03'})


class Connection:
    def __init__(self, *, initial=TS.IDLE, rollback=TS.IDLE, commit_error=None,
                 rollback_error=None, closed=False, broken=False, status=ConnStatus.OK):
        self.info = SimpleNamespace(transaction_status=initial, status=status)
        self.rollback = rollback
        self.commit_error = commit_error
        self.rollback_error = rollback_error
        self.closed, self.broken = closed, broken

    @contextmanager
    def transaction(self):
        self.info.transaction_status = TS.INTRANS
        try:
            yield
        except BaseException:
            self.info.transaction_status = self.rollback
            if self.rollback_error:
                raise self.rollback_error
            raise
        else:
            if self.commit_error:
                raise self.commit_error
            self.info.transaction_status = TS.IDLE


class TransactionTests(unittest.TestCase):
    def exercise(self, errors, *, connection=None, connection_error=None, cleanup_error=None):
        self.calls = self.bodies = 0
        @contextmanager
        def connect():
            self.calls += 1
            if connection_error:
                raise connection_error
            conn = connection() if connection else Connection()
            try:
                yield conn
            finally:
                if cleanup_error:
                    raise cleanup_error
        @retry_lock_timeouts
        def operation():
            with recognition_transaction(connect) as conn:
                self.bodies += 1
                if self.bodies <= len(errors):
                    conn.info.transaction_status = TS.INERROR
                    raise errors[self.bodies-1]
                return 'committed'
        return operation()

    def test_fresh_whole_operation_replayed_only_after_rollback(self):
        self.assertEqual(self.exercise([timeout(), timeout()]), 'committed')
        self.assertEqual((self.calls, self.bodies), (3, 3))

    def test_three_total_attempts_not_three_retries(self):
        errors = [timeout() for _ in range(4)]
        with self.assertRaises(LockNotAvailable) as caught:
            self.exercise(errors)
        self.assertIs(caught.exception, errors[2])
        self.assertEqual(self.calls, 3)

    def test_other_sqlstates_and_generic_operational_errors_do_not_retry(self):
        for error in (OperationalError('connection lost'), QueryCanceled('timeout'),
                      DeadlockDetected('deadlock'), RuntimeError('owner changed'),
                      timeout('could not obtain lock on row in relation "synthetic"')):
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(type(error)):
                    self.exercise([error])
                self.assertEqual(self.calls, 1)

    def test_failed_or_unconfirmed_rollback_never_retries(self):
        for options in ({'rollback': TS.INERROR}, {'rollback': TS.UNKNOWN},
                        {'initial': TS.INTRANS}, {'closed': True}, {'broken': True},
                        {'status': ConnStatus.BAD},
                        {'rollback_error': OperationalError('rollback lost')}):
            with self.subTest(options=options):
                with self.assertRaises(OperationalError):
                    self.exercise([timeout()], connection=lambda: Connection(**options))
                self.assertEqual(self.calls, 1)

    def test_connect_commit_and_cleanup_errors_never_retry_even_for_55p03(self):
        for stage in ('connect', 'commit', 'cleanup'):
            for error in (timeout(), OperationalError('unknown outcome')):
                kw = ({'connection_error': error} if stage == 'connect' else
                      {'connection': lambda: Connection(commit_error=error)} if stage == 'commit' else
                      {'cleanup_error': error})
                with self.subTest(stage=stage, error=type(error).__name__):
                    with self.assertRaises(type(error)):
                        self.exercise([timeout()] if stage == 'cleanup' else [], **kw)
                    self.assertEqual(self.calls, 1)

    def test_missing_status_evidence_fails_closed(self):
        conn = Connection()
        del conn.info.status
        with self.assertRaises(LockNotAvailable):
            self.exercise([timeout()], connection=lambda: conn)
        self.assertEqual(self.calls, 1)

    def test_exact_store_method_retry_boundaries(self):
        from worker.jobs.shared_recognition import RecognitionStore
        from worker.jobs.yoon_resume_store import ResumeStore
        for cls, expected in ((RecognitionStore, {
                'begin','prepared','state','claim_lease','missing_indices','reserve','finish','settle_lease','pause'}),
                (ResumeStore, {'claim','require_owner','write','prepare_scheduler','next_windows','reserve',
                              'finish','release','finalize_ready','summary','complete','clock_state'})):
            actual = {name for name, fn in vars(cls).items() if hasattr(fn, '__wrapped__') and name != 'locked'}
            self.assertEqual(actual, expected)

    def test_retry_does_not_sleep_or_reset_provider_clock(self):
        with patch('time.sleep', side_effect=AssertionError('provider pacing changed')), \
             patch('time.monotonic', side_effect=AssertionError('provider deadline reset')):
            self.assertEqual(self.exercise([timeout()]), 'committed')


if __name__ == '__main__':
    unittest.main()
