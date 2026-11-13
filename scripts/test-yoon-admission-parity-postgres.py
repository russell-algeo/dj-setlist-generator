"""Native configured-capacity races in the existing disposable PostgreSQL harness.

No live DSN, stored auth or provider access. The inherited harness creates a
new local Unix-socket cluster, applies all migrations and seeds synthetic
registered families. Only the tests defined here are run by this entry point.
"""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('registry_fixture', Path(__file__).with_name('test-yoon-version-concurrency-postgres.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
a = fixture.admission


class AdmissionParityPostgresTests(fixture.RegistryConcurrencyTests):
    def race(self, limit):
        # Distinct native PostgreSQL sessions compete for the real transaction
        # lock; unlike the Python mutex model this checks committed visibility.
        barrier = threading.Barrier(20)
        def submit(x):
            with self.connect() as conn:
                conn.execute('SET ROLE set_list_worker')
                barrier.wait(timeout=10)
                try:
                    with conn.transaction():
                        self.reserve(conn, x)
                    return True
                except RuntimeError as exc:
                    self.assertEqual(str(exc), 'private_admission_capacity')
                    return False
        with patch.dict(os.environ, {'PROCESS_SET_MAX_ACTIVE_RUNS': str(limit)}):
            with ThreadPoolExecutor(max_workers=20) as pool:
                results = list(pool.map(submit, self.ids[:20]))
        self.assertEqual(sum(results), limit)
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) AS n FROM ops.set_runs WHERE source_metadata->'yoon_queue_v1'->>'status'='reserved'").fetchone()['n'], limit)

    def test_configured_one_real_sessions(self): self.race(1)
    def test_configured_two_real_sessions(self): self.race(2)
    def test_configured_ten_real_sessions(self): self.race(10)
    def test_configured_seventeen_real_sessions(self): self.race(17)

    def test_mixed_metadata_occupies_same_configured_limit(self):
        with patch.dict(os.environ, {'PROCESS_SET_MAX_ACTIVE_RUNS': '10'}), self.connect() as conn:
            with conn.transaction():
                a.lock(conn.cursor())
                conn.execute("UPDATE ops.set_runs SET source_metadata=source_metadata || %s::jsonb WHERE id=%s", (fixture.Jsonb({'yoon_metadata_enrichment_v1': {'status': 'reserved', 'owner': fixture.OWNER}}), self.ids[0]['run']))
            for x in self.ids[1:10]:
                with conn.transaction(): self.reserve(conn, x)
            with self.assertRaisesRegex(RuntimeError, 'private_admission_capacity'):
                with conn.transaction(): self.reserve(conn, self.ids[10])
            with conn.transaction():
                a.lock(conn.cursor())
                conn.execute("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_metadata_enrichment_v1,status}','\"complete\"') WHERE id=%s", (self.ids[0]['run'],))
            with conn.transaction(): self.reserve(conn, self.ids[10])

    def test_generation_and_rollback_preserve_full_capacity(self):
        with patch.dict(os.environ, {'PROCESS_SET_MAX_ACTIVE_RUNS': '10'}), self.connect() as conn:
            for x in self.ids[:10]:
                with conn.transaction(): self.reserve(conn, x)
            x = self.ids[0]
            before = self.snapshot(conn, x['set'])
            generation = conn.execute("SELECT source_metadata->'yoon_queue_v1'->>'generation' AS generation FROM ops.set_runs WHERE id=%s", (x['run'],)).fetchone()['generation']
            with conn.transaction():
                a.lock(conn.cursor())
                a.check(conn.cursor(), x['run'], x['set'], generation=generation)
            with self.assertRaisesRegex(RuntimeError, 'private_admission_duplicate_target'):
                with conn.transaction():
                    a.lock(conn.cursor())
                    a.check(conn.cursor(), x['run'], x['set'])
            self.assertEqual(self.snapshot(conn, x['set']), before)
            # A lower configured limit never expires or drops reservations.
            with patch.dict(os.environ, {'PROCESS_SET_MAX_ACTIVE_RUNS': '2'}):
                with self.assertRaisesRegex(RuntimeError, 'private_admission_capacity'):
                    with conn.transaction(): self.reserve(conn, self.ids[10])
            self.assertEqual(self.snapshot(conn, x['set']), before)


if __name__ == '__main__':
    with patch('socket.socket.connect', side_effect=AssertionError('provider network forbidden')), \
         patch('socket.getaddrinfo', side_effect=AssertionError('DNS forbidden')):
        names = [name for name in AdmissionParityPostgresTests.__dict__ if name.startswith('test_')]
        suite = unittest.TestSuite(AdmissionParityPostgresTests(name) for name in names)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
