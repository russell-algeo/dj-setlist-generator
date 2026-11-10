import hashlib
from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from worker.jobs.yoon_sources import JACKSON, DONALD, reviewed_source
from worker.jobs.yoon_once import validate_descriptor, prepare
from worker.jobs.yoon_resume_store import ResumeStore
from worker.jobs.yoon_resume_policy import initial_state, may_reserve


def descriptor(source=DONALD):
    return dict(source.pins(), source_id=source.id, recognition_mode='resumable',
                source_url='https://dropbox.com/SYNTHETIC')


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.db = patch('worker.db.connect', side_effect=AssertionError('NO LIVE DB'))
        self.db.start(); self.addCleanup(self.db.stop)

    def test_finite_catalog_exact_pins_and_legacy_default(self):
        self.assertEqual(reviewed_source(JACKSON.pins()), JACKSON)
        self.assertEqual(reviewed_source(descriptor()), DONALD)
        self.assertEqual(DONALD.windows, 479)
        for change in [dict(source_id='unknown'), dict(source_sha256=JACKSON.sha256),
                       dict(source_bytes=DONALD.bytes+1), dict(source_start_seconds=3370),
                       dict(source_end_seconds=10570), dict(recognition_mode='full'),
                       dict(source_end_seconds=float(DONALD.end))]:
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                validate_descriptor(descriptor() | change)
        value=descriptor(); value.pop('source_id')
        with self.assertRaises(RuntimeError): validate_descriptor(value)

    def store(self, state, source=DONALD):
        store=ResumeStore('12345678-1234-1234-1234-123456789012','1','1')
        store.source=source
        @contextmanager
        def locked(**kwargs): yield Mock(), {}, state
        store.locked=locked; store.save_state=Mock()
        return store

    def test_fresh_digest_pinned_once_and_mismatch_pauses(self):
        state=initial_state(0)|dict(initialization_mode='fresh',fresh_source_initialized=True,status='preparing')
        store=self.store(state); digest='a'*64
        store.write(dict(status='prepared',audio_sha256=digest))
        self.assertEqual(state['expected_audio_sha256'],digest)
        state['status']='preparing'
        store.write(dict(status='prepared',audio_sha256=digest))
        with self.assertRaisesRegex(RuntimeError,'prepared_audio_changed'):
            store.write(dict(status='prepared',audio_sha256='b'*64))
        self.assertTrue(state['review_required'])
        self.assertEqual(state['audio_sha256'],digest)

    def test_missing_pin_cannot_bypass_jackson_or_prior_requests(self):
        for source,extra in [(JACKSON,{}),(DONALD,{'requests':1}),
                             (DONALD,{'origin':{'run_id':'fake'}}),
                             (DONALD,{'fresh_source_initialized':False})]:
            state=initial_state(0)|dict(initialization_mode='fresh',fresh_source_initialized=True,status='preparing')|extra
            with self.subTest(source=source.id,extra=extra), self.assertRaises(RuntimeError):
                self.store(state,source).write(dict(status='prepared',audio_sha256='a'*64))

    def test_fresh_run_requires_empty_evidence_and_first_continuation(self):
        state=initial_state(0)|dict(initialization_mode='fresh',continuations=1)
        store=self.store(state); cur=Mock(); cur.fetchone.side_effect=[{'n':0},{'n':0}]
        store.require_empty_fresh_source(cur,state)
        for counts in [[{'n':1}],[{'n':0},{'n':1}]]:
            cur=Mock();cur.fetchone.side_effect=counts
            with self.assertRaises(RuntimeError):store.require_empty_fresh_source(cur,state)
        for extra in [dict(origin={'run_id':'fake'}),dict(continuations=2),dict(requests=1),dict(provenance_seeded=True)]:
            with self.assertRaises(RuntimeError):store.require_empty_fresh_source(Mock(),state|extra)

    def test_prepare_uses_catalog_crop_and_download_pins(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); store=Mock();store.source=DONALD
            store.claim.return_value='https://dropbox.com/SYNTHETIC'
            store.require_owner.return_value={'recognition_mode':'resumable'}
            def transcode(args,**kwargs):Path(args[-1]).write_bytes(b'synthetic')
            with patch('worker.jobs.yoon_once.fetch') as fetch, \
                 patch('worker.jobs.yoon_once.shutil.disk_usage',return_value=Mock(free=10**10)), \
                 patch('worker.jobs.yoon_once.subprocess.run',side_effect=transcode) as ffmpeg, \
                 patch('audio_segmenter.AudioSegmenter.get_audio_duration_ffprobe',return_value=7200):
                prepare(store,root)
            fetch.assert_called_once_with(store.claim.return_value,root/'source.wav',DONALD)
            args=ffmpeg.call_args.args[0]
            self.assertEqual(args[args.index('-ss')+1],'3371')
            self.assertEqual(args[args.index('-t')+1],'7200')
            self.assertEqual(store.write.call_args.args[0]['audio_sha256'],hashlib.sha256(b'synthetic').hexdigest())

    def test_request_budget_derived_only_from_reviewed_geometry(self):
        base=dict(now=0,session_started=0,session_requests=0,window_attempts=0)
        self.assertEqual(may_reserve(initial_state(0)|{'requests':479*8},windows=DONALD.windows,**base),'lifetime_request_budget')
        for windows in (480,0,True,479.0):
            with self.assertRaises(RuntimeError):may_reserve(initial_state(0),windows=windows,**base)

    def test_locked_source_owner_and_audience_fences(self):
        store=ResumeStore('12345678-1234-1234-1234-123456789012','1','1')
        members=[dict(user_id='one',role='owner'),dict(user_id='two',role='member')]
        state=dict(version=1,initialization_mode='fresh',source_id=DONALD.id,
                   source_pins=DONALD.pins(),members=members,**store.owner)
        row=dict(status='private_resume_running',collection_id='collection',source_metadata={
            'yoon_fixed_input':descriptor(),'yoon_resume':state})
        cur=Mock();cur.fetchone.return_value=row;cur.fetchall.return_value=members
        @contextmanager
        def scope():yield cur
        conn=Mock();conn.cursor=scope;conn.transaction=scope
        @contextmanager
        def connect():yield conn
        store.connect=connect
        with store.locked():pass
        for extra,reason in [(dict(source_pins=JACKSON.pins()),'source_changed'),
                             (dict(workflow_run_id='wrong'),'owner_changed'),
                             (dict(members=[]),'audience_changed'),
                             (dict(origin={'run_id':'fake'}),'fresh_source_required')]:
            row['source_metadata']['yoon_resume']=state|extra
            with self.subTest(extra=extra),self.assertRaisesRegex(RuntimeError,reason):
                with store.locked():pass
