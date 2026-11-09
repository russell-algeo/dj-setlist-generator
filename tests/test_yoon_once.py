import asyncio
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worker.jobs import yoon_once as job
from worker.pipeline.models import Recognition
from config import Config

RUN = '12345678-1234-1234-1234-123456789012'
TARGET = '12345678-1234-1234-1234-123456789013'
COLLECTION = '12345678-1234-1234-1234-123456789014'

def descriptor():
    return dict(source_sha256=job.SOURCE_SHA, source_bytes=job.SOURCE_BYTES,
                source_start_seconds=3120, source_end_seconds=10320,
                source_url='https://www.dropbox.com/scl/fi/SYNTHETIC_PRIVATE_CAPABILITY?dl=1')

class FakeStore:
    def __init__(self, digest): self.saved = {'audio_sha256': digest}; self.writes = []
    def require_owner(self): return self.saved
    def write(self, value): self.writes.append(value)

class Tests(unittest.TestCase):
    def setUp(self):
        self.no_db = patch('worker.db.connect', side_effect=AssertionError('LIVE DB FORBIDDEN IN TESTS'))
        self.no_db.start()
        self.addCleanup(self.no_db.stop)

    def test_descriptor_and_source_allowlist(self):
        self.assertIn('dropbox.com', job.validate_descriptor(descriptor()))
        for key in ['source_sha256', 'source_bytes', 'source_start_seconds', 'source_end_seconds']:
            value = descriptor(); value[key] = 'wrong'
            with self.assertRaises(RuntimeError): job.validate_descriptor(value)
        for url in ['http://dropbox.com/a', 'https://dropbox.com.evil/a', 'https://u:p@dropbox.com/a',
                    'https://dropbox.com:bad/a', 'https://example.com/private']:
            self.assertFalse(job.allowed_source(url))

    def test_external_redirect_denied(self):
        with self.assertRaises(RuntimeError): job.Redirects().redirect_request(None,None,302,'',{},'https://evil.invalid/token')

    def test_guard_requires_all_private_scopes(self):
        for clause in ["r.publication_visibility = 'private'", "s.visibility = 'private'", "u.visibility = 'private'",
                       'r.target_set_id = s.id', 'r.collection_id = s.collection_id', 'u.collection_id = r.collection_id',
                       'r.cancel_requested_at IS NULL', 'r.published_set_id IS NULL', 'r.create_playlist = false']:
            self.assertIn(clause, job.PRIVATE_GUARD)

    def test_claim_requires_fresh_private_run(self):
        store = job.Store(RUN, '1234', '1')
        row = {'status':'private_analysis_pending','source_metadata':{'yoon_fixed_input':descriptor()}}
        with patch.object(store,'read',return_value=row), patch.object(store,'write') as write:
            store.claim(); write.assert_called_once_with({'status':'preparing', 'recognition_mode':'probe'},claim=True)
        row['source_metadata']['yoon_analysis'] = {'workflow_run_id':'old'}
        with patch.object(store,'read',return_value=row), patch.object(store,'write') as write:
            with self.assertRaises(RuntimeError): store.claim()
            write.assert_not_called()

    def test_owner_mismatch_stops(self):
        store = job.Store(RUN,'1234','1')
        row={'status':'private_analysis_running','source_metadata':{'yoon_analysis':{'workflow_run_id':'OTHER'}}}
        with patch.object(store,'read',return_value=row):
            with self.assertRaises(RuntimeError): store.require_owner()

    def test_bound_sql_and_owner_fence(self):
        store=job.Store(RUN,'1234','1'); store.target=(TARGET,COLLECTION); calls=[]
        class Cursor:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def execute(self,q,p): calls.append((q,p))
            def fetchone(self): return {'id':RUN}
        class Conn:
            def cursor(self): return Cursor()
        @contextmanager
        def connect(): yield Conn()
        store.connect=connect; store.write({'status':'recognizing','raw_recognitions':[]})
        q,p=calls[0]; self.assertIn(job.PRIVATE_GUARD,q); self.assertIn('run_attempt',q)
        self.assertEqual(p[2:],(RUN,TARGET,COLLECTION,'1234','1'))
        self.assertNotIn('worker_events',q); self.assertNotIn('error_summary',q)

    def synthetic(self,mode):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); audio=root/'input.mp3'; audio.write_bytes(b'synthetic')
            store=FakeStore(hashlib.sha256(b'synthetic').hexdigest()); calls=[]
            store.saved['recognition_mode'] = 'full'
            async def fake(context,*,start_index,end_index,session,on_result):
                calls.append((start_index,end_index))
                if mode in ('timeout','cancel'):
                    on_result(Recognition(start_index*15,'known','artist','id',{},True,start_index))
                    if mode=='cancel': raise asyncio.CancelledError()
                    await asyncio.sleep(.05)
                for i in reversed(range(start_index,end_index+1)):
                    on_result(Recognition(i*15,'SYNTHETIC_PRIVATE_TITLE','SYNTHETIC_PRIVATE_ARTIST','id',{},True,i,
                        error_type='NetworkError' if mode=='error' and i==0 else None))
            with patch.object(Config,'ASSETS_DIR',root/'assets'), patch.object(Config,'CHECKPOINT_DIR',root/'cp'), \
                 patch.object(Config,'OUTPUT_DIR',root/'output'), patch.object(job,'WINDOWS',12), \
                 patch.object(job,'BUDGET',.01 if mode=='timeout' else 10), \
                 patch('audio_segmenter.AudioSegmenter.get_audio_duration_ffprobe',return_value=7200), \
                 patch('audio_segmenter.AudioSegmenter.calculate_total_segments',return_value=12), \
                 patch.object(job,'recognize_private_range',fake):
                if mode=='cancel':
                    with self.assertRaises(asyncio.CancelledError): asyncio.run(job.recognize(store,audio))
                    status=store.writes[-1]['status']
                else:
                    status=asyncio.run(job.recognize(store,audio))
            if mode=='complete':
                self.assertEqual(status,'complete'); self.assertEqual(calls,[(0,9),(10,11)])
                self.assertEqual(len(store.writes[-1]['raw_recognitions']),12)
                self.assertEqual([r['segment_index'] for r in store.writes[-1]['raw_recognitions']],list(range(12)))
                self.assertIn('clustered_setlist',store.writes[-1])
                self.assertEqual(len(store.writes),13)  # Each response + final flush.
            else:
                self.assertEqual(status,'partial'); self.assertNotIn('clustered_setlist',store.writes[-1])
                if mode in ('timeout','cancel'):
                    self.assertEqual(len(store.writes[-1]['raw_recognitions']),1)
                    self.assertEqual(store.writes[-1]['reason'],'cancelled' if mode=='cancel' else 'time_budget')
    def test_complete_private_checkpoint_and_cluster(self): self.synthetic('complete')
    def test_error_stays_partial(self): self.synthetic('error')
    def test_timeout_stays_partial(self): self.synthetic('timeout')
    def test_cancellation_flushes_completed_responses(self): self.synthetic('cancel')

    def test_process_output_suppression(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            # Explicitly fresh env: no credentials, no inherited HOME/auth files, no DB config.
            env={'PATH':'/usr/bin:/bin','HOME':temp,'PYTHONDONTWRITEBYTECODE':'1','GITHUB_ACTIONS':'true',
                 'RUNNER_OS':'Linux','GITHUB_REPOSITORY':'russell-algeo/dj-setlist-generator',
                 'WORKER_DEPLOYMENT_TARGET':'development','RUNNER_TEMP':temp,
                 'PRIVATE_RUN_ID':'SYNTHETIC_PRIVATE_CAPABILITY','GITHUB_RUN_ID':'1','GITHUB_RUN_ATTEMPT':'1'}
            result=subprocess.run([sys.executable,'-m','worker.jobs.yoon_once','prepare'],cwd=root,env=env,capture_output=True)
            self.assertNotEqual(result.returncode,0); self.assertEqual(result.stdout,b''); self.assertEqual(result.stderr,b'')

    def test_native_and_child_output_suppression(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            env={'PATH':'/usr/bin:/bin','HOME':temp,'PYTHONDONTWRITEBYTECODE':'1','GITHUB_ACTIONS':'true',
                 'RUNNER_OS':'Linux','GITHUB_REPOSITORY':'russell-algeo/dj-setlist-generator',
                 'WORKER_DEPLOYMENT_TARGET':'development','RUNNER_TEMP':temp,
                 'PRIVATE_RUN_ID':'12345678-1234-1234-1234-123456789012','GITHUB_RUN_ID':'1','GITHUB_RUN_ATTEMPT':'1'}
            code = """import os, subprocess, sys
from worker.jobs import yoon_once as j
from types import SimpleNamespace
j.Store=lambda *args: SimpleNamespace(read=lambda: {'source_metadata': {}})
def fake(*args):
    print('SYNTHETIC_PRIVATE_TITLE', flush=True)
    os.write(2, b'SYNTHETIC_PRIVATE_CAPABILITY')
    subprocess.run(['/bin/echo', 'SYNTHETIC_PRIVATE_CHILD'])
j.prepare=fake
sys.argv=['worker', 'prepare']
raise SystemExit(j.main())
"""
            r=subprocess.run([sys.executable,'-c',code],cwd=root,env=env,capture_output=True)
            self.assertEqual(r.returncode,0); self.assertEqual(r.stdout,b''); self.assertEqual(r.stderr,b'')

    def test_workflow_audio_only_existing_auth(self):
        t=(Path(__file__).resolve().parents[1]/'.github/workflows/process-set.yml').read_text()
        private=t.split('  private-prepare:',1)[1]
        self.assertEqual(private.count('actions/upload-artifact'),1)
        self.assertIn('/fixed-analysis/audio/input.mp3',t); self.assertIn('retention-days: 1',t)
        self.assertIn('secrets.DEVELOPMENT_DATABASE_URL_DIRECT',t)
        for forbidden in ['GH_PAT','YOON_SOURCE_URL','INTERNAL_WORKER_SHARED_SECRET','worker.callbacks']:
            self.assertNotIn(forbidden,private)
        self.assertEqual(private.count('>/dev/null 2>&1'),3)
        ordinary=t.split('  private-prepare:',1)[0]
        self.assertEqual(ordinary.count("if: ${{ github.event.inputs.private_analysis != 'true'"),2)
        self.assertEqual(ordinary.count("if: ${{ always() && github.event.inputs.private_analysis != 'true'"),2)
        self.assertIn("github.ref == 'refs/heads/preview'",private)
        self.assertIn("github.event.inputs.deployment_target == 'development'",private)

if __name__=='__main__': unittest.main()
