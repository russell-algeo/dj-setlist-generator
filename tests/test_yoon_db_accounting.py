from contextlib import contextmanager
import asyncio
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from psycopg import OperationalError
from psycopg.pq import ConnStatus, TransactionStatus
from worker.jobs import yoon_db_accounting as dbio
from worker.recognition_transactions import recognition_transaction, retry_lock_timeouts
from test_recognition_transactions import Connection as TransactionConnection, timeout


SECRET = b'PRIVATE_SOURCE_PROVIDER_CREDENTIAL_MUST_NOT_ESCAPE'


class Result:
    def __init__(self, rows):
        self.rows = rows
        self.ntuples = len(rows)
        self.nfields = len(rows[0]) if rows else 0

    def get_value(self, row, column):
        return self.rows[row][column]


class Cursor:
    def __init__(self, result=None, error=None):
        self.pgresult, self.error = result, error
        self.fetches = 0
        self.calls = []

    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error is not None: raise self.error
        return self
    def fetchone(self):
        self.fetches += 1
        return {'opaque': SECRET}
    def fetchall(self):
        self.fetches += 1
        return [{'opaque': SECRET}]
    def nextset(self): return None


class Connection(TransactionConnection):
    def __init__(self, cursor, **options):
        super().__init__(**options)
        self._cursor = cursor

    def cursor(self, *args, **kwargs): return self._cursor


@contextmanager
def connected(connection):
    yield connection


class AccountingTests(unittest.TestCase):
    def test_disabled_returns_exact_factory_no_wrapping(self):
        connect = lambda: None
        self.assertIs(dbio.measured_connect(connect), connect)

    def test_session_resets_and_nested_scopes_are_separate(self):
        with dbio.session() as outer:
            with dbio.session() as inner:
                self.assertIsNot(outer, inner)
                self.assertIs(dbio._active.get(), inner)
            self.assertIs(dbio._active.get(), outer)
        self.assertIsNone(dbio._active.get())

    def test_exact_encoded_lengths_nulls_and_no_row_consumption(self):
        values = [[b'abc', None, '\u96ea'.encode()], [SECRET, b'', memoryview(b'ab')]]
        cur = Cursor(Result(values)); conn = Connection(cur)
        with dbio.session() as meter:
            connect = dbio.measured_connect(lambda: connected(conn))
            with recognition_transaction(connect) as observed:
                self.assertIs(observed.info, conn.info)
                with observed.cursor() as wrapped:
                    self.assertIs(wrapped.execute(SECRET, (SECRET,)), wrapped)
                    self.assertEqual(cur.fetches, 0)
                    self.assertEqual(wrapped.fetchone(), {'opaque': SECRET})
                    self.assertEqual(wrapped.fetchall(), [{'opaque': SECRET}])
        expected = 3 + 3 + len(SECRET) + 2
        counts = meter.snapshot()
        self.assertEqual(counts['connection_attempts'], 1)
        self.assertEqual(counts['connections_opened'], 1)
        self.assertEqual(counts['execute_calls'], 1)
        self.assertEqual(counts['result_payload_bytes'], expected)
        self.assertEqual(counts['data_row_frame_bytes'], expected + 2 * (7 + 4 * 3))
        self.assertEqual((counts['result_rows'], counts['result_cells']), (2, 6))
        self.assertEqual(cur.calls, [((SECRET, (SECRET,)), {})])
        self.assertNotIn(SECRET.decode(), meter.line())
        self.assertNotIn('opaque', meter.line())
        self.assertEqual(conn.info.transaction_status, TransactionStatus.IDLE)

    def test_command_result_zero_rows_is_measured_not_unsupported(self):
        meter = dbio.Meter(); meter.observe(Cursor(Result([])))
        self.assertEqual(meter.snapshot()['result_sets'], 1)
        self.assertEqual(meter.snapshot()['unmeasured_results'], 0)
        self.assertEqual(meter.snapshot()['result_payload_bytes'], 0)

    def test_unsupported_or_large_results_explicitly_incomplete(self):
        for result in (None, SimpleNamespace(ntuples=2, nfields=1_000_000),
                       SimpleNamespace(ntuples=1_000_001, nfields=0),
                       SimpleNamespace(ntuples=True, nfields=1),
                       SimpleNamespace(ntuples=-1, nfields=1)):
            meter = dbio.Meter(); meter.observe(Cursor(result))
            self.assertEqual(meter.snapshot()['unmeasured_results'], 1)
            self.assertEqual(meter.snapshot()['result_payload_bytes'], 0)

    def test_observation_failure_never_formats_or_changes_query_result(self):
        class Hostile:
            @property
            def ntuples(self): raise ValueError(SECRET)
            def __str__(self): raise AssertionError('must not format')
        for result in (Hostile(), Result([[SECRET, 'not bytes']])):
            cur = Cursor(result); meter = dbio.Meter()
            wrapped = dbio._Cursor(cur, meter)
            self.assertIs(wrapped.execute(SECRET), wrapped)
            self.assertEqual(meter.snapshot()['measurement_failures'], 1)
            self.assertEqual(meter.snapshot()['result_payload_bytes'], 0)
            self.assertNotIn(SECRET.decode(), meter.line())

    def test_execute_errors_and_cancellation_remain_identical(self):
        for error in (OperationalError(SECRET), asyncio.CancelledError(SECRET)):
            cur = Cursor(Result([[SECRET]]), error); meter = dbio.Meter()
            with self.assertRaises(type(error)) as caught:
                dbio._Cursor(cur, meter).execute(SECRET)
            self.assertIs(caught.exception, error)
            counts = meter.snapshot()
            self.assertEqual((counts['execute_calls'], counts['execute_failures']), (1, 1))
            self.assertEqual(counts['result_sets'], 0)

    def test_connection_failure_counts_attempt_without_retry(self):
        calls = []
        @contextmanager
        def failing():
            calls.append(1)
            raise OperationalError(SECRET)
            yield
        with dbio.session() as meter:
            with self.assertRaises(OperationalError):
                with dbio.measured_connect(failing)(): pass
        self.assertEqual(calls, [1])
        self.assertEqual(meter.snapshot()['connection_attempts'], 1)
        self.assertEqual(meter.snapshot()['connections_opened'], 0)

    def test_observation_preserves_confirmed_rollback_retry(self):
        calls = []
        @contextmanager
        def factory():
            calls.append(1)
            cur = Cursor(Result([[b'first']]))
            conn = Connection(cur)
            yield conn
        with dbio.session() as meter:
            connect = dbio.measured_connect(factory)
            @retry_lock_timeouts
            def operation():
                with recognition_transaction(connect) as conn:
                    with conn.cursor() as cur: cur.execute('synthetic')
                    if len(calls) == 1:
                        conn.info.transaction_status = TransactionStatus.INERROR
                        raise timeout()
                return 'settled'
            self.assertEqual(operation(), 'settled')
        self.assertEqual(len(calls), 2)
        self.assertEqual(meter.snapshot()['connections_opened'], 2)
        self.assertEqual(meter.snapshot()['result_payload_bytes'], 10)

    def test_uncertain_commit_and_rollback_do_not_become_retriable(self):
        for stage in ('commit', 'rollback'):
            error = OperationalError(SECRET)
            options = {'commit_error': error} if stage == 'commit' else {'rollback_error': error}
            conn = Connection(Cursor(Result([])), **options)
            with dbio.session() as meter:
                connect = dbio.measured_connect(lambda: connected(conn))
                @retry_lock_timeouts
                def operation():
                    with recognition_transaction(connect) as observed:
                        if stage == 'rollback':
                            observed.info.transaction_status = TransactionStatus.INERROR
                            raise timeout()
                with self.assertRaises(OperationalError) as caught: operation()
            self.assertIs(caught.exception, error)
            self.assertEqual(meter.snapshot()['connection_attempts'], 1)

    def test_summary_has_fixed_keys_only_and_copy_is_detached(self):
        meter = dbio.Meter(); snapshot = meter.snapshot()
        snapshot['result_payload_bytes'] = 999
        self.assertEqual(meter.snapshot()['result_payload_bytes'], 0)
        tokens = meter.line().strip().split()
        self.assertEqual(tokens[:4], ['private_db_io', 'version=1', 'scope=process', 'metric=libpq_result_values'])
        self.assertEqual([t.split('=')[0] for t in tokens[4:]], list(dbio._FIELDS))
        self.assertTrue(all(t.split('=')[1].isdecimal() for t in tokens[4:]))

    def test_diagnostic_sink_failure_does_not_change_control_flow(self):
        from worker.jobs import yoon_recognition_diagnostics as diag
        with patch.object(diag, '_fd', 99), patch.object(diag.os, 'write', side_effect=OSError(SECRET)):
            diag.report_db_io(dbio.Meter())

    def test_both_private_stores_opt_in_only_inside_session(self):
        from worker.jobs.yoon_once import Store
        from worker.jobs.yoon_resume_store import ResumeStore
        factory = lambda: connected(Connection(Cursor(Result([]))))
        run = 'a0000000-0000-4000-8000-000000000010'
        with patch('worker.db.connect', factory):
            for cls in (Store, ResumeStore):
                self.assertIs(cls(run, '9001', '1').connect, factory)
                with dbio.session() as meter:
                    store = cls(run, '9001', '1')
                    with store.connect() as conn:
                        with conn.cursor() as cur: cur.execute('synthetic')
                self.assertEqual(meter.snapshot()['connections_opened'], 1)
                self.assertEqual(meter.snapshot()['execute_calls'], 1)

    def test_actual_diagnostic_process_emits_only_aggregate(self):
        code = '''
import os, sys, types
from contextlib import contextmanager
from worker.jobs import yoon_recognition_diagnostics as d
from worker.jobs.yoon_db_accounting import measured_connect
class Result:
    ntuples=1; nfields=2
    def get_value(self, row, column):
        return b'PRIVATE_SOURCE_PROVIDER_CREDENTIAL_MUST_NOT_ESCAPE' if column == 0 else None
class Cursor:
    pgresult=Result()
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def execute(self,*args): return self
class Connection:
    def cursor(self): return Cursor()
@contextmanager
def factory(): yield Connection()
def main():
    with measured_connect(factory)() as conn:
        with conn.cursor() as cur: cur.execute('PRIVATE_SOURCE_PROVIDER_CREDENTIAL_MUST_NOT_ESCAPE')
    os.write(1,b'PRIVATE_SOURCE_PROVIDER_CREDENTIAL_MUST_NOT_ESCAPE')
    os.write(2,b'PRIVATE_SOURCE_PROVIDER_CREDENTIAL_MUST_NOT_ESCAPE')
    return 0
m=types.ModuleType('worker.jobs.yoon_once'); m.main=main
sys.modules[m.__name__]=m
sys.argv=['diagnostics','recognize']
raise SystemExit(d.run())
'''
        result = subprocess.run([sys.executable, '-c', code], capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'')
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertNotIn(SECRET, result.stderr)
        values = dict(token.split('=') for token in result.stderr.decode().strip().split()[1:])
        self.assertEqual(values['result_payload_bytes'], str(len(SECRET)))
        self.assertEqual(values['data_row_frame_bytes'], str(7 + 4 * 2 + len(SECRET)))
        self.assertEqual(values['connection_attempts'], '1')
        self.assertEqual(values['execute_calls'], '1')


if __name__ == '__main__': unittest.main()
