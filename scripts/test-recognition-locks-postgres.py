"""Real multi-connection lock/rollback tests in a disposable local PostgreSQL.

RECOGNITION_TEST_PG_BIN must name installed trusted PostgreSQL binaries. This
script creates its own empty cluster, listens only on a private Unix socket,
uses synthetic fixtures, and never reads a database URL or calls a provider.
PGlite's single-session SQL tests are complementary, not concurrency evidence.
"""
import asyncio
from contextlib import contextmanager
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import psycopg
from psycopg.rows import dict_row
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worker.jobs.shared_recognition import RecognitionStore, RecognitionFence, RecognitionPause
from worker.jobs.yoon_resume_store import ResumeStore, QueuePause
from worker.pipeline.models import Recognition

ROOT = Path(__file__).resolve().parents[1]
BIN = Path(os.environ['RECOGNITION_TEST_PG_BIN']).resolve()
RUN = 'a0000000-0000-4000-8000-000000000010'
SUB = '30000000-0000-4000-8000-000000000001'
COL = '20000000-0000-4000-8000-000000000001'
SET = '10000000-0000-4000-8000-000000000001'
KEY = 771009


class Cursor:
    def __init__(self, cursor, harness):
        self.cursor, self.harness = cursor, harness
    def __getattr__(self, name):
        return getattr(self.cursor, name)
    def __enter__(self):
        self.cursor.__enter__()
        return self
    def __exit__(self, *args):
        return self.cursor.__exit__(*args)
    def execute(self, query, params=()):
        # Accelerate only this synthetic test. Production retains its 5s wait.
        if query.startswith('SET LOCAL lock_timeout'):
            query = "SET LOCAL lock_timeout = '40ms'"
        self.cursor.execute(query, params)
        if self.harness.inject and self.harness.inject in query:
            self.cursor.execute('SELECT pg_advisory_xact_lock(%s)', (KEY,))
        return self


class Connection:
    def __init__(self, conn, harness):
        self.conn, self.harness = conn, harness
    def __getattr__(self, name):
        return getattr(self.conn, name)
    def cursor(self):
        return Cursor(self.conn.cursor(), self.harness)


class Harness:
    def __init__(self, test, private):
        self.test, self.private = test, private
        self.connections, self.inject, self.on_retry = 0, None, None
        self.blocker = None
        self.store = (ResumeStore(RUN, '9001', '1', connect=self.connect) if private else
                      RecognitionStore(RUN, workflow_id='9001', attempt='1', generation='g', connect=self.connect))
    @contextmanager
    def connect(self):
        self.connections += 1
        if self.connections > 1 and self.on_retry:
            self.on_retry(self.connections)
        with self.test.connect() as conn:
            yield Connection(conn, self)
    def hold(self, table=None):
        self.blocker = self.test.connect()
        self.blocker.execute('BEGIN')
        if table:
            self.blocker.execute(f'SELECT id FROM ops.{table} WHERE id=%s FOR UPDATE',
                                 (RUN if table == 'set_runs' else SUB,))
        else:
            self.blocker.execute('SELECT pg_advisory_xact_lock(%s)', (KEY,))
        self.test.addCleanup(self.unblock)
    def unblock(self):
        if self.blocker:
            self.blocker.rollback()
            self.blocker.close()
            self.blocker = None
    def reserve(self):
        return self.store.reserve(0) if self.private else self.store.reserve(0, self.test.lease, 'worker')
    def finish(self, ticket):
        result = Recognition(0, None, None, None, {'matches': []}, False, 0, http_status=200)
        return self.store.finish(result, ticket) if self.private else self.store.finish(ticket, result)
    def state(self):
        with self.test.connect() as c:
            row = c.execute('SELECT source_metadata FROM ops.set_runs WHERE id=%s', (RUN,)).fetchone()
            return row['source_metadata']['yoon_resume' if self.private else 'shared_recognition']
    def hit(self):
        with self.test.connect() as c:
            row = c.execute('SELECT raw_data FROM ops.segment_hits WHERE set_run_id=%s', (RUN,)).fetchone()
            return row['raw_data']['private_jackson_v2' if self.private else 'shared_recognition'] if row else None
    def mutate(self, sql, params=()):
        with self.test.connect() as c:
            c.execute(sql, params)


class LockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='recognition-pg-')
        cls.socket = Path(cls.temp.name)
        cls.data = cls.socket / 'data'
        subprocess.run([str(BIN/'initdb'), '-D', str(cls.data), '-A', 'trust', '--no-locale', '-E', 'UTF8'], check=True, capture_output=True)
        cls.started = False
        cls.addClassCleanup(cls.stop)
        try:
            subprocess.run([str(BIN/'pg_ctl'), '-D', str(cls.data), '-l', str(cls.socket/'server.log'),
                            '-o', f"-F -k {cls.socket} -c listen_addresses='' -p 55439", '-w', 'start'], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            print((cls.socket/'server.log').read_text(), file=sys.stderr)
            raise
        cls.started = True
        with cls.connect() as c:
            assert Path(c.execute("SHOW data_directory").fetchone()['data_directory']) == cls.data
            assert c.execute("SHOW listen_addresses").fetchone()['listen_addresses'] == ''
            print(c.execute('SELECT version() AS version').fetchone()['version'], flush=True)
            c.execute('CREATE ROLE set_list_worker')
            for file in sorted((ROOT/'drizzle/migrations').glob('[0-9]*.sql')):
                c.execute(file.read_text())
    @classmethod
    def connect(cls):
        # Explicit socket-only synthetic target. Never accept external DSNs.
        return psycopg.connect(host=str(cls.socket), port=55439, dbname='postgres',
                               autocommit=True, row_factory=dict_row)
    @classmethod
    def stop(cls):
        if cls.started:
            subprocess.run([str(BIN/'pg_ctl'), '-D', str(cls.data), '-m', 'immediate', '-w', 'stop'], check=True, capture_output=True)
        cls.temp.cleanup()
    def fixture(self, private):
        with self.connect() as c:
            c.execute('TRUNCATE ops.submissions, app.archive_collections, authn.users CASCADE')
            c.execute("INSERT INTO authn.users(id,email) VALUES('synthetic-owner','owner@example.invalid'),('synthetic-viewer','viewer@example.invalid')")
            now = c.execute('SELECT extract(epoch FROM clock_timestamp())::float8 AS now').fetchone()['now']
            common = dict(version=1, created_at=now, continuations=1, requests=0,
                          throttle_requests=0, session_started=now, session_requests=0,
                          next_allowed_at=0, review_required=False)
            if private:
                c.execute("INSERT INTO app.archive_collections(id,slug,title) VALUES(%s,'yoon-fest','Synthetic')", (COL,))
                c.execute("INSERT INTO app.archive_collection_members(collection_id,user_id,role) VALUES(%s,'synthetic-owner','manager'),(%s,'synthetic-viewer','viewer')", (COL,COL))
                c.execute("INSERT INTO app.sets(id,slug,title,normalized_title,visibility,collection_id) VALUES(%s,'synthetic','Synthetic','synthetic','private',%s)", (SET,COL))
                c.execute("INSERT INTO ops.submissions(id,requested_by,mode,status,visibility,collection_id) VALUES(%s,'synthetic-owner','set','private_analysis_pending','private',%s)", (SUB,COL))
                descriptor = dict(source_sha256='aa01c4b637efe4e59bac051ef67ce4014e270a1f41fad8b6cbba95310fa58aae', source_bytes=4290463660, source_start_seconds=3120, source_end_seconds=10320,
                                  source_url='https://www.dropbox.com/scl/fi/SYNTHETIC/source.wav?dl=1', recognition_mode='resumable')
                state = dict(common, workflow_run_id='9001', run_attempt='1', throttle_policy_version=3,
                             members=[dict(user_id='synthetic-owner',role='manager'),dict(user_id='synthetic-viewer',role='viewer')])
                metadata = dict(yoon_fixed_input=descriptor, yoon_resume=state)
                c.execute("INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,publication_visibility,target_set_id,collection_id,source_metadata) VALUES(%s,%s,'synthetic-owner','private_resume_running','local:synthetic','private',%s,%s,%s::jsonb)", (RUN,SUB,SET,COL,json.dumps(metadata)))
            else:
                c.execute("INSERT INTO ops.submissions(id,requested_by,mode,status,visibility) VALUES(%s,'synthetic-owner','set','running','public')", (SUB,))
                state = dict(common, owner='9001:1', policy_version=3, request_limit=8,
                             in_flight=False, in_flight_until=0, provider_next_allowed_at=0,
                             geometry=dict(segment_duration=30, segment_overlap=15, segment_count=1))
                metadata = dict(active_workflow_run_id='9001', dispatch_generation='g', shared_recognition=state)
                c.execute("INSERT INTO ops.set_runs(id,submission_id,requested_by,status,stage,source_url,publication_visibility,source_metadata) VALUES(%s,%s,'synthetic-owner','recognizing','recognizing','local:synthetic','public',%s::jsonb)", (RUN,SUB,json.dumps(metadata)))
            self.lease = c.execute("INSERT INTO ops.set_run_leases(set_run_id,slot_index,segment_start_index,segment_end_index,status,claimed_by) VALUES(%s,0,0,0,%s,%s) RETURNING id", (RUN,'pending' if private else 'claimed',None if private else 'worker')).fetchone()['id']
        return Harness(self, private)

    def test_real_run_and_submission_lock_contention(self):
        for private in (False, True):
            for table in ('set_runs', 'submissions'):
                with self.subTest(private=private, table=table):
                    h = self.fixture(private)
                    h.hold(table)
                    h.on_retry = lambda n: h.unblock()
                    self.assertTrue(h.reserve())
                    self.assertEqual(h.connections, 2)
                    self.assertEqual(h.state()['requests'], 1)
                    self.assertEqual(len(h.hit()['attempts']), 1)

    def test_late_reservation_timeout_rolls_back_all_evidence(self):
        for private in (False, True):
            with self.subTest(private=private):
                h = self.fixture(private)
                h.hold()
                h.inject = 'UPDATE ops.set_runs SET source_metadata'
                def retry(n):
                    self.assertEqual(h.state()['requests'], 0)
                    self.assertIsNone(h.hit())
                    if n == 3: h.unblock()
                h.on_retry = retry
                self.assertTrue(h.reserve())
                self.assertEqual(h.connections, 3)
                self.assertEqual(h.state()['requests'], 1)
                self.assertEqual(len(h.hit()['attempts']), 1)

    def test_late_finish_timeout_preserves_ticket_and_single_response(self):
        for private in (False, True):
            with self.subTest(private=private):
                h = self.fixture(private)
                ticket = h.reserve()
                h.connections = 0
                h.hold()
                h.inject = 'UPDATE ops.set_runs SET source_metadata'
                before = h.hit()
                def retry(n):
                    self.assertEqual(h.hit(), before)
                    self.assertEqual(h.state()['requests'], 1)
                    h.unblock()
                h.on_retry = retry
                h.finish(ticket)
                self.assertEqual(h.connections, 2)
                self.assertEqual(h.state()['requests'], 1)
                self.assertEqual(len(h.hit()['attempts']), 1)
                self.assertTrue(h.hit()['valid'])
                self.assertFalse(h.hit()['in_flight'])

    def test_exhaustion_is_three_attempts_and_no_reservation(self):
        for private in (False, True):
            with self.subTest(private=private):
                h = self.fixture(private)
                h.hold('set_runs')
                with self.assertRaises(psycopg.errors.LockNotAvailable if private else RecognitionFence):
                    h.reserve()
                h.unblock()
                self.assertEqual(h.connections, 3)
                self.assertEqual(h.state()['requests'], 0)
                self.assertIsNone(h.hit())

    def test_retry_rechecks_owner_cancel_scope_and_original_deadline(self):
        for private in (False, True):
            key = 'yoon_resume' if private else 'shared_recognition'
            owner = 'workflow_run_id' if private else 'owner'
            mutations = {
                'owner': (f"UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{{{key},{owner}}}','\"9002\"') WHERE id=%s", (RUN,)),
                'run_cancel': ('UPDATE ops.set_runs SET cancel_requested_at=now() WHERE id=%s', (RUN,)),
                'submission_cancel': ('UPDATE ops.submissions SET cancel_requested_at=now() WHERE id=%s', (SUB,)),
                'scope': ("UPDATE ops.set_runs SET create_playlist=true WHERE id=%s" if private else "UPDATE ops.set_runs SET stage='publishing_committed' WHERE id=%s", (RUN,)),
                'deadline': (f"UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{{{key},session_started}}','1') WHERE id=%s", (RUN,)),
            }
            for reason, (sql, params) in mutations.items():
                with self.subTest(private=private, reason=reason):
                    h = self.fixture(private)
                    h.hold('set_runs')
                    def retry(n):
                        h.unblock()
                        h.mutate(sql, params)
                    h.on_retry = retry
                    with self.assertRaises((RuntimeError, RecognitionFence, RecognitionPause, QueuePause)):
                        h.reserve()
                    self.assertEqual(h.connections, 2)
                    self.assertEqual(h.state()['requests'], 0)
                    self.assertIsNone(h.hit())

    def test_finish_rechecks_ticket_after_rollback(self):
        for private in (False, True):
            with self.subTest(private=private):
                h = self.fixture(private)
                ticket = h.reserve()
                h.connections = 0
                h.hold('set_runs')
                key, token = ('private_jackson_v2','ticket') if private else ('shared_recognition','token')
                def retry(n):
                    h.unblock()
                    h.mutate(f"UPDATE ops.segment_hits SET raw_data=jsonb_set(raw_data,'{{{key},attempts,0,{token}}}','\"other-ticket\"') WHERE set_run_id=%s", (RUN,))
                h.on_retry = retry
                with self.assertRaises(RuntimeError):
                    h.finish(ticket)
                self.assertEqual(h.connections, 2)
                self.assertTrue(h.hit()['in_flight'])
                self.assertFalse(h.hit()['valid'])

    def test_transport_posts_once_despite_reservation_and_finish_retries(self):
        from config import Config
        from recognition_transport import SingleAttemptHTTP
        from track_recognizer import TrackRecognizer
        class Response:
            status, headers = 200, {}
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def json(self): return {'matches': []}
        class HTTP:
            calls = 0
            def request(self, *args, **kwargs):
                self.calls += 1
                return Response()
            async def close(self): pass
        for private in (False, True):
            with self.subTest(private=private):
                h = self.fixture(private)
                h.hold('set_runs')
                h.on_retry = lambda n: h.unblock()
                http = HTTP()
                def finish(result, ticket, delay):
                    self.assertEqual(http.calls, 1)
                    h.connections = 0
                    h.hold()
                    h.inject = 'UPDATE ops.set_runs SET source_metadata'
                    return h.store.finish(result, ticket, delay) if private else h.store.finish(ticket, result, delay)
                async def run():
                    rec = TrackRecognizer(before_attempt=lambda segment: h.reserve(), on_attempt=finish, quiet=True)
                    rec.transport = SingleAttemptHTTP(session_factory=lambda **kwargs: http, before_request=rec.before_request)
                    async def recognize(_):
                        return await rec.transport.request('POST', 'https://provider.invalid')
                    rec.shazam = type('SDK', (), {'recognize': staticmethod(recognize)})()
                    try:
                        result = await rec.recognize_segment_with_backoff({'index':0,'timestamp':0,'file':Path('/synthetic-no-file')})
                        self.assertTrue(result.is_valid)
                    finally:
                        await rec.close()
                with patch.object(Config, 'BASE_DELAY', 0), patch('socket.socket.connect', side_effect=AssertionError('no provider sockets')):
                    asyncio.run(run())
                self.assertEqual(http.calls, 1)
                self.assertEqual(h.connections, 2)
                self.assertEqual(h.state()['requests'], 1)
                self.assertEqual(len(h.hit()['attempts']), 1)
                self.assertTrue(h.hit()['valid'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
