"""Real PostgreSQL races for the private Yoon version registry.

Run with YOON_TEST_PG_BIN pointing to trusted installed PostgreSQL 17 binaries.
Only a new disposable cluster and private Unix socket are used. This harness
never reads a DSN, stored authentication, source media, or credentials.
Provider transmission is patched to fail if accidentally called; dotenv is disabled.
A test-only advisory barrier is inserted in one function for the deterministic
stale-read interleaving, then the exact production function is restored.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from worker.jobs import yoon_admission as admission
from worker.recognition_transactions import recognition_transaction, retry_lock_timeouts

BIN = Path(os.environ['YOON_TEST_PG_BIN']).resolve()
PORT = 55441
GLOBAL = (183601, 2)
BARRIER = 78333121
CHECKS = ('independent_review', 'source_matched', 'ordered_windows',
          'stable_derivative', 'import_complete', 'metadata_complete',
          'timestamps_and_spans', 'audience_unchanged')
OWNER = {'workflow_run_id': '9001', 'run_attempt': '1'}


def uid():
    return str(uuid.uuid4())


class RegistryConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Short explicit path stays below macOS Unix socket length limits.
        cls.temp = tempfile.TemporaryDirectory(prefix='yoon-pg-', dir='/tmp')
        cls.socket = Path(cls.temp.name).resolve()
        cls.data = cls.socket / 'data'
        cls.started = False
        cls.addClassCleanup(cls.stop)
        try:
            subprocess.run([str(BIN / 'initdb'), '-D', str(cls.data), '-A', 'trust',
                            '--no-locale', '-E', 'UTF8'], check=True, capture_output=True)
        except subprocess.CalledProcessError as exc:
            print(exc.stderr.decode(errors='replace'), file=sys.stderr)
            raise
        try:
            subprocess.run([str(BIN / 'pg_ctl'), '-D', str(cls.data), '-l', str(cls.socket / 'server.log'),
                            '-o', f"-F -k {cls.socket} -c listen_addresses='' -p {PORT}",
                            '-w', 'start'], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            print((cls.socket / 'server.log').read_text(), file=sys.stderr)
            raise
        cls.started = True
        with cls.connect() as c:
            assert Path(c.execute('SHOW data_directory').fetchone()['data_directory']) == cls.data
            assert c.execute('SHOW listen_addresses').fetchone()['listen_addresses'] == ''
            print(c.execute('SELECT version() AS v').fetchone()['v'], flush=True)
            c.execute('CREATE ROLE set_list_worker')
        migration = ROOT / 'drizzle/migrations/0024_yoon_version_registry.sql'
        print('MIGRATION_SHA256 ' + hashlib.sha256(migration.read_bytes()).hexdigest(), flush=True)

    @classmethod
    def connect(cls):
        # Never accept external DSNs or ambient PGHOST/database URL values.
        return psycopg.connect(host=str(cls.socket), port=PORT, dbname='postgres',
                               autocommit=True, row_factory=dict_row,
                               options='-c statement_timeout=10000 -c lock_timeout=5000')

    @classmethod
    def stop(cls):
        if cls.started:
            subprocess.run([str(BIN / 'pg_ctl'), '-D', str(cls.data), '-m', 'immediate',
                            '-w', 'stop'], check=True, capture_output=True)
        cls.temp.cleanup()

    def setUp(self):
        with self.connect() as c:
            c.execute('DROP SCHEMA IF EXISTS ops,app,authn CASCADE')
            for file in sorted((ROOT / 'drizzle/migrations').glob('[0-9]*.sql')):
                c.execute(file.read_text())
            # Existing app/ops access is fixture-only. Registry privileges come
            # solely from the production migration: SELECT, never UPDATE.
            c.execute('GRANT USAGE ON SCHEMA app,ops,authn TO set_list_worker')
            c.execute('GRANT SELECT ON ALL TABLES IN SCHEMA app,authn TO set_list_worker')
            c.execute('GRANT SELECT,INSERT,UPDATE ON ops.set_runs,ops.submissions,ops.segment_hits,ops.set_run_leases TO set_list_worker')
            self.assertFalse(c.execute("SELECT has_table_privilege('set_list_worker','ops.yoon_version_families','UPDATE') AS ok").fetchone()['ok'])
        self.pool = ThreadPoolExecutor(max_workers=5)
        self.addCleanup(self.pool.shutdown, wait=True, cancel_futures=True)
        self.col = uid()
        with self.connect() as c:
            c.execute("INSERT INTO authn.users(id,email) VALUES('owner','owner@example.invalid'),('viewer','viewer@example.invalid')")
            c.execute("INSERT INTO app.archive_collections(id,slug,title) VALUES(%s,'yoon-fest','Synthetic')", (self.col,))
            c.execute("INSERT INTO app.archive_collection_members(collection_id,user_id,role) VALUES(%s,'owner','manager'),(%s,'viewer','viewer')", (self.col, self.col))
            self.reserved = c.execute('SELECT * FROM ops.yoon_reserved_versions ORDER BY source_id LIMIT 1').fetchone()
            self.ids = [dict(set=str(self.reserved['logical_set_id']) if i == 0 else uid(),
                             run=uid(), sub=uid(), media=uid(), source=f'legacy{i}', slug=f'legacy{i}',
                             revision='legacy', descriptor=dict(source_sha256='a' * 64, source_bytes=100,
                                                               source_start_seconds=0, source_end_seconds=30))
                        for i in range(27)]
            for x in self.ids:
                self.insert_rows(c, x)
            self.audience = c.execute('SELECT ops.yoon_audience(%s) AS sha', (self.col,)).fetchone()['sha']
            snapshots = [dict(set_id=x['set'], snapshot_sha256=self.hash(c, x['set'])) for x in self.ids]
            with c.transaction():
                c.execute('INSERT INTO ops.yoon_version_collections(collection_id,audience_sha256,bootstrap_manifest,bootstrap_sha256) VALUES(%s,%s,%s,ops.yoon_sha(%s))', (self.col, self.audience, Jsonb(snapshots), Jsonb(snapshots)))
                for x in self.ids:
                    c.execute('INSERT INTO ops.yoon_version_families(logical_set_id,collection_id,selected_set_id) VALUES(%s,%s,%s)', (x['set'], self.col, x['set']))
                    self.register(c, x)
            r = self.reserved
            self.new = dict(set=str(r['set_id']), run=str(r['run_id']), sub=str(r['submission_id']),
                            media=str(r['media_id']), source=r['source_id'], slug='synthetic-v2',
                            revision=r['media_revision'], descriptor={**r['descriptor'], 'source_url': 'https://www.dropbox.com/scl/fi/SYNTHETIC/source.wav?dl=1'})
            with c.transaction():
                self.register(c, self.new, self.ids[0]['set'])
                self.insert_rows(c, self.new)

    def insert_rows(self, c, x):
        c.execute("INSERT INTO app.sets(id,slug,title,normalized_title,visibility,collection_id,source_id) VALUES(%s,%s,'Synthetic','synthetic','private',%s,%s)", (x['set'], x['slug'], self.col, x['source']))
        c.execute("INSERT INTO ops.submissions(id,requested_by,mode,status,visibility,collection_id) VALUES(%s,'owner','set','private_analysis_pending','private',%s)", (x['sub'], self.col))
        c.execute("INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,publication_visibility,target_set_id,collection_id,source_metadata) VALUES(%s,%s,'owner','private_resume_pending','local:synthetic','private',%s,%s,%s)", (x['run'], x['sub'], x['set'], self.col, Jsonb({'yoon_fixed_input': x['descriptor']})))
        c.execute("INSERT INTO app.set_media(id,set_id,revision,content_type,duration_seconds,recording_sources,source_spans) VALUES(%s,%s,%s,'audio/wav',30,'[]','[]')", (x['media'], x['set'], x['revision']))

    def register(self, c, x, pred=None):
        source_sha = c.execute("SELECT ops.yoon_sha(jsonb_build_object('source_url','local:synthetic','descriptor',%s::jsonb)) AS sha", (Jsonb(x['descriptor']),)).fetchone()['sha']
        media_sha = c.execute("SELECT ops.yoon_sha(jsonb_build_object('id',%s::uuid,'set_id',%s::uuid,'revision',%s::text,'content_type','audio/wav','duration_seconds',30.000000::numeric(12,6),'recording_sources','[]'::jsonb,'source_spans','[]'::jsonb)) AS sha", (x['media'], x['set'], x['revision'])).fetchone()['sha']
        c.execute('''INSERT INTO ops.yoon_versions(set_id,logical_set_id,model_version,source_id,run_id,submission_id,media_id,slug,media_revision,collection_id,requested_by,predecessor_set_id,manifest_sha256,source_sha256,media_sha256,audience_sha256,processing_approved,released)
                     VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'owner',%s,%s,%s,%s,%s,true,%s)''',
                  (x['set'], pred or x['set'], self.reserved['model_version'] if pred else 'v1', x['source'], x['run'], x['sub'], x['media'], x['slug'], x['revision'], self.col, pred, 'b' * 64, source_sha, media_sha, self.audience, not pred))

    def hash(self, c, sid):
        return c.execute('SELECT ops.yoon_sha(ops.yoon_version_snapshot(%s)) AS sha', (sid,)).fetchone()['sha']

    def snapshot(self, c, sid):
        return c.execute('SELECT ops.yoon_version_snapshot(%s) AS snapshot', (sid,)).fetchone()['snapshot']

    def review(self, c, old, new):
        old_hash, new_hash = self.hash(c, old), self.hash(c, new)
        doc = dict(old_set_id=old, new_set_id=new, old_snapshot_sha256=old_hash,
                   new_snapshot_sha256=new_hash, reviewer='synthetic-independent-reviewer',
                   checks={key: True for key in CHECKS})
        review = c.execute('SELECT ops.yoon_sha(%s) AS sha', (Jsonb(doc),)).fetchone()['sha']
        c.execute('INSERT INTO ops.yoon_release_reviews(review_sha256,review) VALUES(%s,%s) ON CONFLICT DO NOTHING', (review, Jsonb(doc)))
        return old_hash, new_hash, review

    def select(self, c, revision=0, rollback=False):
        old, new = (self.new['set'], self.ids[0]['set']) if rollback else (self.ids[0]['set'], self.new['set'])
        return c.execute('SELECT ops.select_yoon_version(%s,%s,%s,%s,%s,%s,%s,%s) AS revision',
                         (self.ids[0]['set'], old, revision, new, *self.review(c, old, new), rollback)).fetchone()['revision']

    def complete_candidate(self):
        x = self.new
        with self.connect() as c:
            with c.transaction():
                admission.lock(c.cursor())
                c.execute("UPDATE ops.set_runs SET status='private_resume_complete',source_metadata=source_metadata || %s::jsonb WHERE id=%s", (Jsonb(dict(yoon_resume=dict(status='complete', expected_audio_sha256='c' * 64, audio_sha256='c' * 64, source_id=x['source']), yoon_metadata_publication_v1=dict(status='complete', run_id=x['run'], target_set_id=x['set']))), x['run']))
                c.execute("INSERT INTO ops.segment_hits(set_run_id,segment_index,timestamp_seconds,recognized,raw_data) SELECT %s,i,i*15,false,jsonb_build_object('private_jackson_v2',jsonb_build_object('valid',true,'in_flight',false,'response',jsonb_build_object('segment_index',i,'timestamp',i*15))) FROM generate_series(0,%s::integer-1) i", (x['run'], self.reserved['expected_windows']))
                c.execute("INSERT INTO app.set_entries(set_id,position,display_artist,display_title,start_time_seconds,confidence) VALUES(%s,1,'Test','Track',0,'HIGH')", (x['set'],))

    def running(self, c, x):
        c.execute("UPDATE ops.set_runs SET status='private_resume_running',source_metadata=source_metadata || %s::jsonb WHERE id=%s", (Jsonb({'yoon_resume': dict(OWNER)}), x['run']))

    def reserve(self, c, x):
        # Call the actual production aggregate cap/registry admission hook.
        cur = c.cursor()
        admission.lock(cur)
        cur.execute('SELECT id FROM ops.set_runs WHERE id=%s FOR UPDATE', (x['run'],))
        admission.check(cur, x['run'], x['set'])
        c.execute("UPDATE ops.set_runs SET source_metadata=source_metadata || %s::jsonb WHERE id=%s", (Jsonb({'yoon_queue_v1': dict(version=1, status='reserved', owner=None, generation=uid())}), x['run']))

    def blocked(self, c, pid, expected=None):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            row = c.execute('SELECT wait_event_type,wait_event FROM pg_stat_activity WHERE pid=%s', (pid,)).fetchone()
            if row and row['wait_event_type'] == 'Lock' and (expected is None or row['wait_event'] == expected):
                return row
            time.sleep(.005)
        self.fail(f'PID {pid} did not reach expected lock wait: {row}')

    def connect_cleanup(self):
        c = self.connect()
        self.addCleanup(c.close)
        self.addCleanup(c.rollback)
        return c

    def raw(self, c, kind, x=None, index=0):
        x = x or self.ids[0]
        if kind == 'hit':
            c.execute("INSERT INTO ops.segment_hits(set_run_id,segment_index,timestamp_seconds,recognized,raw_data) VALUES(%s,%s,%s,false,'{}')", (x['run'], index, index * 15))
        else:
            c.execute("INSERT INTO ops.set_run_leases(set_run_id,slot_index,segment_start_index,segment_end_index,status) VALUES(%s,%s,%s,%s,'completed')", (x['run'], index, index, index))

    def test_global_then_row_serializes_sibling_reservations_and_cap_two(self):
        first, second, observer = self.connect_cleanup(), self.connect_cleanup(), self.connect_cleanup()
        first.execute('SET ROLE set_list_worker')
        second.execute('SET ROLE set_list_worker')
        first.execute('BEGIN')
        self.reserve(first, self.ids[0])
        def contender():
            with second.transaction():
                self.reserve(second, self.new)
        future = self.pool.submit(contender)
        self.blocked(observer, second.info.backend_pid, 'advisory')
        # The waiting admission does not already own the row: a third session can lock it.
        with observer.transaction():
            observer.execute('SELECT id FROM ops.set_runs WHERE id=%s FOR UPDATE NOWAIT', (self.new['run'],))
        first.commit()
        with self.assertRaisesRegex(psycopg.errors.RaiseException, 'logical_family_occupied'):
            future.result(timeout=3)
        with observer.transaction():
            self.reserve(observer, self.ids[1])
        with self.assertRaisesRegex(RuntimeError, 'private_admission_capacity'):
            with observer.transaction():
                self.reserve(observer, self.ids[2])
        self.assertEqual(observer.execute("SELECT count(*) AS n FROM ops.set_runs WHERE source_metadata->'yoon_queue_v1'->>'status'='reserved'").fetchone()['n'], 2)
        self.assertEqual(admission.CAP, 2)

    def test_stale_prelock_registry_read_cannot_authorize_after_promotion(self):
        self.complete_candidate()
        barrier, reader, writer = self.connect_cleanup(), self.connect_cleanup(), self.connect_cleanup()
        original = writer.execute("SELECT pg_get_functiondef('ops.assert_yoon_version_execution(uuid,text,text)'::regprocedure) AS body").fetchone()['body']
        needle = ' PERFORM ops.yoon_registry_lock();'
        self.assertEqual(original.count(needle), 1)
        writer.execute(original.replace(needle, f' PERFORM pg_advisory_xact_lock({BARRIER});\n' + needle))
        self.addCleanup(lambda: self.restore_function(original))
        barrier.execute('BEGIN')
        barrier.execute('SELECT pg_advisory_xact_lock(%s)', (BARRIER,))
        future = self.pool.submit(reader.execute, "SELECT ops.assert_yoon_version_execution(%s,'admit')", (self.ids[0]['run'],))
        self.blocked(writer, reader.info.backend_pid, 'advisory')
        self.assertEqual(self.select(writer), 1)
        barrier.commit()
        with self.assertRaisesRegex(psycopg.errors.RaiseException, 'execution_not_approved'):
            future.result(timeout=3)

    def restore_function(self, original):
        with self.connect() as c:
            c.execute(original)

    def test_selection_cas_null_and_stale_reject_rollback_preserves_evidence_and_playback(self):
        self.complete_candidate()
        with self.connect() as c:
            before = {x['set']: self.snapshot(c, x['set']) for x in (self.ids[0], self.new)}
            for revision in (None, -1, 1):
                with self.assertRaisesRegex(psycopg.errors.RaiseException, 'selection_cas_conflict'):
                    self.select(c, revision)
            self.assertEqual(self.select(c), 1)
            with self.assertRaisesRegex(psycopg.errors.RaiseException, 'selection_cas_conflict'):
                self.select(c, 0)
            self.assertEqual(self.select(c, 1, rollback=True), 2)
            self.assertEqual(c.execute('SELECT selected_set_id,selection_revision FROM ops.yoon_version_families WHERE logical_set_id=%s', (self.ids[0]['set'],)).fetchone(), {'selected_set_id': uuid.UUID(self.ids[0]['set']), 'selection_revision': 2})
            for sid, snapshot in before.items():
                self.assertEqual(self.snapshot(c, sid), snapshot)
                self.assertTrue(c.execute('SELECT app.yoon_version_readable(%s) AS ok', (sid,)).fetchone()['ok'])
            self.assertEqual(c.execute('SELECT count(*) AS n FROM ops.yoon_version_history').fetchone()['n'], 2)

    def test_raw_hit_holds_parent_until_commit(self):
        self.assert_raw_holds_parent('hit')

    def test_raw_lease_holds_parent_until_commit(self):
        self.assert_raw_holds_parent('lease')

    def assert_raw_holds_parent(self, kind):
        self.complete_candidate()
        raw, release, observer = self.connect_cleanup(), self.connect_cleanup(), self.connect_cleanup()
        self.running(observer, self.ids[0])
        raw.execute('BEGIN')
        self.raw(raw, kind)
        # Independently show the parent lock persists after the raw statement returns.
        with self.assertRaises(psycopg.errors.LockNotAvailable):
            observer.execute('SELECT id FROM ops.set_runs WHERE id=%s FOR UPDATE NOWAIT', (self.ids[0]['run'],))
        with self.assertRaisesRegex(psycopg.errors.RaiseException, 'family_not_quiescent'):
            self.select(observer)
        def releasing():
            with release.transaction():
                admission.lock(release.cursor())
                release.execute("UPDATE ops.set_runs SET status='private_resume_pending' WHERE id=%s", (self.ids[0]['run'],))
        future = self.pool.submit(releasing)
        self.blocked(observer, release.info.backend_pid)
        self.assertFalse(future.done())
        raw.commit()
        future.result(timeout=3)
        retained = self.snapshot(observer, self.ids[0]['set'])
        self.assertEqual(self.select(observer), 1)
        self.assertEqual(self.snapshot(observer, self.ids[0]['set']), retained)

    def test_blocked_raw_hit_cannot_commit_after_release_and_promotion(self):
        self.assert_blocked_raw_cannot_commit_after_promotion('hit')

    def test_blocked_raw_lease_cannot_commit_after_release_and_promotion(self):
        self.assert_blocked_raw_cannot_commit_after_promotion('lease')

    def assert_blocked_raw_cannot_commit_after_promotion(self, kind):
        self.complete_candidate()
        release, raw, observer = self.connect_cleanup(), self.connect_cleanup(), self.connect_cleanup()
        self.running(observer, self.ids[0])
        release.execute('BEGIN')
        admission.lock(release.cursor())
        release.execute("UPDATE ops.set_runs SET status='private_resume_pending' WHERE id=%s", (self.ids[0]['run'],))
        # Raw's first registry SELECT sees unfrozen. Its parent lock then blocks.
        future = self.pool.submit(self.raw, raw, kind)
        self.blocked(observer, raw.info.backend_pid)
        self.assertEqual(self.select(release), 1)
        frozen_snapshot = self.snapshot(release, self.ids[0]['set'])
        release.commit()
        with self.assertRaisesRegex(psycopg.errors.RaiseException, 'frozen_evidence'):
            future.result(timeout=3)
        self.assertEqual(self.snapshot(observer, self.ids[0]['set']), frozen_snapshot)

    def test_busy_windows_ignore_unrelated_global_lock_and_measure_latency(self):
        holder, one, two = self.connect_cleanup(), self.connect_cleanup(), self.connect_cleanup()
        self.running(one, self.ids[0])
        self.running(two, self.ids[1])
        holder.execute('BEGIN')
        admission.lock(holder.cursor())
        start = threading.Barrier(2)
        windows = 40
        def writes(c, x):
            start.wait(timeout=3)
            timings = []
            for i in range(windows):
                began = time.perf_counter()
                with c.transaction():
                    self.raw(c, 'hit', x, i)
                    self.raw(c, 'lease', x, i)
                    c.execute("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_resume,requests}',to_jsonb(%s::int)) WHERE id=%s", (i + 1, x['run']))
                    self.assertEqual(c.execute("SELECT count(*) AS n FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory' AND classid=%s AND objid=%s", GLOBAL).fetchone()['n'], 0)
                timings.append((time.perf_counter() - began) * 1000)
            return timings
        began = time.perf_counter()
        a = self.pool.submit(writes, one, self.ids[0])
        b = self.pool.submit(writes, two, self.ids[1])
        times = a.result(timeout=5) + b.result(timeout=5)
        elapsed = time.perf_counter() - began
        # A global holder still exists after both window streams finish.
        self.assertEqual(holder.execute("SELECT count(*) AS n FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory'").fetchone()['n'], 1)
        holder.rollback()
        self.assertLess(max(times), 1000)
        print('BUSY_PATH ' + json.dumps(dict(streams=2, windows=len(times), elapsed_ms=round(elapsed * 1000, 3), median_ms=round(statistics.median(times), 3), p95_ms=round(sorted(times)[int(len(times) * .95) - 1], 3), max_ms=round(max(times), 3), provider_calls=0, global_locks_per_window=0)), flush=True)

    def test_actual_store_parallel_reserve_finish_has_no_global_contention_or_extra_attempts(self):
        with patch('dotenv.load_dotenv', return_value=False):
            from worker.jobs.yoon_resume_store import ResumeStore
            import worker.jobs.yoon_once
        from recognition_transport import SingleAttemptHTTP
        from worker.pipeline.models import Recognition
        x = self.new
        holder = self.connect_cleanup()
        holder.execute('SELECT ops.initialize_yoon_version_execution(%s)', (x['set'],))
        connections = []
        @contextmanager
        def counted_connect():
            connections.append(1)
            with self.connect() as c:
                c.execute('SET ROLE set_list_worker')
                yield c
        stores = [ResumeStore(x['run'], '9001', '1', connect=counted_connect) for _ in range(2)]
        stores[0].claim()
        connections.clear()
        # Both concurrent slots share the pre-existing parent lock, not global
        # admission. The global lock remains held for the entire benchmark.
        holder.execute('BEGIN')
        admission.lock(holder.cursor())
        start = threading.Barrier(2)
        windows = 20
        def cycle(store, first):
            start.wait(timeout=3)
            times = []
            for i in range(first, first + windows):
                began = time.perf_counter()
                ticket = store.reserve(i)
                response = Recognition(i * 15, None, None, None, {'matches': []}, False, i, http_status=200)
                store.finish(response, ticket)
                times.append((time.perf_counter() - began) * 1000)
            return times
        with patch.object(SingleAttemptHTTP, 'request', side_effect=AssertionError('provider call forbidden')) as provider:
            began = time.perf_counter()
            a = self.pool.submit(cycle, stores[0], 0)
            b = self.pool.submit(cycle, stores[1], windows)
            times = a.result(timeout=5) + b.result(timeout=5)
            elapsed = time.perf_counter() - began
            self.assertEqual(provider.call_count, 0)
        self.assertEqual(holder.execute("SELECT count(*) AS n FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory'").fetchone()['n'], 1)
        holder.rollback()
        with self.connect() as c:
            state = c.execute('SELECT source_metadata FROM ops.set_runs WHERE id=%s', (x['run'],)).fetchone()['source_metadata']['yoon_resume']
            hits = c.execute('SELECT raw_data FROM ops.segment_hits WHERE set_run_id=%s', (x['run'],)).fetchall()
        self.assertEqual(len(connections), 4 * windows)
        self.assertEqual(state['requests'], 2 * windows)
        self.assertEqual(state['session_requests'], 2 * windows)
        self.assertEqual(len(hits), 2 * windows)
        for hit in hits:
            data = hit['raw_data']['private_jackson_v2']
            self.assertEqual(len(data['attempts']), 1)
            self.assertEqual(data['attempts'][0]['state'], 'finished')
            self.assertTrue(data['valid'])
            self.assertFalse(data['in_flight'])
        self.assertLess(max(times), 1000)
        print('ACTUAL_STORE_BUSY_PATH ' + json.dumps(dict(streams=2, windows=len(times), elapsed_ms=round(elapsed * 1000, 3), median_ms=round(statistics.median(times), 3), p95_ms=round(sorted(times)[int(len(times) * .95) - 1], 3), max_ms=round(max(times), 3), provider_calls=0, attempts_per_window=1, database_transactions=len(connections), charged_requests=state['requests'])), flush=True)

    def test_app_import_and_quiescent_writes_fail_closed_without_global_order(self):
        holder, writer = self.connect_cleanup(), self.connect_cleanup()
        self.running(writer, self.ids[0])
        holder.execute('BEGIN')
        admission.lock(holder.cursor())
        statements = [
            ("UPDATE app.sets SET title='changed' WHERE id=%s", (self.ids[0]['set'],)),
            ("INSERT INTO app.set_entries(set_id,position,display_artist,display_title,start_time_seconds,confidence) VALUES(%s,1,'Test','Track',0,'HIGH')", (self.ids[0]['set'],)),
            ("SELECT ops.assert_yoon_version_execution(%s,'import')", (self.ids[0]['run'],)),
            ("UPDATE ops.set_runs SET status='private_resume_running' WHERE id=%s", (self.ids[1]['run'],)),
            ("INSERT INTO ops.segment_hits(set_run_id,segment_index,timestamp_seconds,recognized,raw_data) VALUES(%s,0,0,false,'{}')", (self.ids[1]['run'],)),
            ("INSERT INTO ops.set_run_leases(set_run_id,slot_index,segment_start_index,segment_end_index,status) VALUES(%s,0,0,0,'completed')", (self.ids[1]['run'],)),
        ]
        for sql, params in statements:
            with self.subTest(sql=sql), self.assertRaisesRegex(psycopg.errors.LockNotAvailable, 'yoon_admission_busy_retry_transaction'):
                writer.execute(sql, params)
        holder.rollback()
        with writer.transaction():
            admission.lock(writer.cursor())
            for sql, params in statements:
                writer.execute(sql, params)

    def test_actual_finalize_ready_waits_global_before_row_without_provider_call(self):
        # Disable dotenv before importing runtime configuration. The explicit
        # connection factory bypasses settings and stored authentication entirely.
        with patch('dotenv.load_dotenv', return_value=False):
            from worker.jobs.yoon_resume_store import ResumeStore
            from worker.jobs.yoon_queue import identity
            import worker.jobs.yoon_once
        from recognition_transport import SingleAttemptHTTP
        holder, observer = self.connect_cleanup(), self.connect_cleanup()
        x = self.new
        generation = uid()
        with observer.transaction():
            admission.lock(observer.cursor())
            observer.execute('SELECT ops.initialize_yoon_version_execution(%s)', (x['set'],))
            row = observer.execute('SELECT * FROM ops.set_runs WHERE id=%s', (x['run'],)).fetchone()
            state = row['source_metadata']['yoon_resume']
            queue = dict(version=1, status='reserved', owner=None, generation=generation,
                         identity=identity(row, state))
            observer.execute("UPDATE ops.set_runs SET source_metadata=source_metadata || %s::jsonb WHERE id=%s", (Jsonb({'yoon_queue_v1': queue}), x['run']))
            observer.execute("""INSERT INTO ops.segment_hits(set_run_id,segment_index,timestamp_seconds,recognized,raw_data)
                SELECT %s,i,i*15,false,jsonb_build_object('private_jackson_v2',jsonb_build_object('valid',true,'in_flight',false,
                  'response',jsonb_build_object('segment_index',i,'timestamp',i*15,'track_title',null,'artist',null,
                      'shazam_track_id',null,'raw_data',jsonb_build_object('matches','[]'::jsonb),'recognized',false)))
                FROM generate_series(0,%s::integer-1) i""", (x['run'], self.reserved['expected_windows']))
        connections = []
        connected = threading.Event()
        @contextmanager
        def connect_finalizer():
            with self.connect() as c:
                c.execute('SET ROLE set_list_worker')
                connections.append(c.info.backend_pid)
                connected.set()
                yield c
        store = ResumeStore(x['run'], '9001', '1', connect=connect_finalizer)
        holder.execute('BEGIN')
        admission.lock(holder.cursor())
        with patch.object(SingleAttemptHTTP, 'request', side_effect=AssertionError('provider call forbidden')) as provider, patch.dict(os.environ, SET_LIST_DISPATCH_GENERATION=generation):
            future = self.pool.submit(store.finalize_ready)
            self.assertTrue(connected.wait(timeout=3))
            self.blocked(observer, connections[0], 'advisory')
            with observer.transaction():
                observer.execute('SELECT id FROM ops.set_runs WHERE id=%s FOR UPDATE NOWAIT', (x['run'],))
            holder.commit()
            self.assertTrue(future.result(timeout=3))
            self.assertEqual(provider.call_count, 0)
        self.assertEqual(len(connections), 1)
        result = observer.execute('SELECT status,source_metadata FROM ops.set_runs WHERE id=%s', (x['run'],)).fetchone()
        self.assertEqual(result['status'], 'private_resume_complete')
        self.assertEqual(result['source_metadata']['yoon_queue_v1']['status'], 'complete')
        self.assertEqual(result['source_metadata']['yoon_resume']['requests'], 0)
        self.assertEqual(result['source_metadata']['yoon_resume']['valid_responses'], self.reserved['expected_windows'])

    def test_no_generic_serialization_or_registry_busy_retry(self):
        calls = []
        @contextmanager
        def counted_connect():
            calls.append(1)
            with self.connect() as c:
                yield c
        @retry_lock_timeouts
        def serialized_failure():
            with recognition_transaction(counted_connect) as c:
                c.execute("DO $$ BEGIN RAISE EXCEPTION 'synthetic serialization' USING ERRCODE='40001'; END $$")
        with self.assertRaises(psycopg.errors.SerializationFailure):
            serialized_failure()
        self.assertEqual(len(calls), 1)
        calls.clear()
        holder = self.connect_cleanup()
        holder.execute('BEGIN')
        admission.lock(holder.cursor())
        @retry_lock_timeouts
        def registry_busy():
            with recognition_transaction(counted_connect) as c:
                c.execute('SELECT ops.yoon_registry_lock()')
        with self.assertRaisesRegex(psycopg.errors.LockNotAvailable, 'yoon_admission_busy_retry_transaction'):
            registry_busy()
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
