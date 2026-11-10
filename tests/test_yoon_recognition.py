"""Private adapters reuse the shared provider engine; no network/live DB."""
import asyncio
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch
from worker.jobs import yoon_recognition as rec
from worker.jobs import yoon_once as job
from worker.pipeline.models import Recognition


def result(index=0,status=200):
    return Recognition(index*15,None,None,None,{'matches':[]} if status==200 else None,
        False,index,http_status=status,was_rate_limited=status==429,
        error_type='RateLimited' if status==429 else None)

class Engine:
    def __init__(self,**kwargs):
        self.options=kwargs;self.transport=SimpleNamespace();self.closed=False;self.responses=[200]
        self.batch_calls=[]
    async def close(self):self.closed=True
    async def recognize_segment_with_backoff(self,segment):
        for status in list(self.responses):
            ticket=self.options['before_attempt'](segment)
            value=result(segment['index'],status)
            self.options['on_attempt'](value,ticket,60 if status==429 else 0)
        return value
    async def recognize_batch(self,segments,**kwargs):
        self.batch_calls.append(kwargs)
        return await asyncio.gather(*(self.recognize_segment_with_backoff(s) for s in segments))

class Tests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('worker.db.connect',side_effect=AssertionError('LIVE DB FORBIDDEN')))
        self.stack.enter_context(patch('socket.socket.connect',side_effect=AssertionError('NETWORK FORBIDDEN')))
        self.stack.enter_context(patch('socket.getaddrinfo',side_effect=AssertionError('DNS FORBIDDEN')))
        self.stack.enter_context(patch('track_recognizer.TrackRecognizer',Engine))
    def session(self,**kwargs):return rec.PrivateRecognitionSession(**kwargs)
    def segment(self,index=0):return dict(index=index,timestamp=index*15,file=Path('synthetic'))
    def test_common_engine_and_quiet_mode(self):
        session=self.session();saved=[]
        asyncio.run(session.one(self.segment(),saved.append))
        self.assertIsInstance(session.recognizer,Engine)
        self.assertTrue(session.recognizer.options['quiet'])
        self.assertEqual(session.recognizer.options['max_retry_seconds'],600)
        self.assertEqual(saved[0].http_status,200)
    def test_attempts_persist_before_common_retry_and_owner_recheck(self):
        events=[];session=self.session(before_request=lambda:events.append('owner'))
        session.recognizer.responses=[429,200]
        asyncio.run(session.one(self.segment(),lambda r:events.append(r.http_status)))
        self.assertEqual(events,['owner',429,'owner',200])
        self.assertEqual(session.retries,1)
        self.assertEqual([r['http_status'] for r in session.attempts],[429,200])
        self.assertEqual(session.attempts[0]['planned_retry_wait_seconds'],60)
    def test_bounded_probe_and_full_caps_preserved(self):
        self.assertEqual(rec.policy_for('probe').request_limit,6)
        self.assertEqual(rec.policy_for('probe').window_limit,5)
        self.assertEqual(rec.policy_for('full').request_limit,480)
        self.assertEqual(rec.policy_for('full').window_limit,479)
        with self.assertRaises(RuntimeError):rec.policy_for('invalid')
    def test_retry_cap_stops_without_invented_result(self):
        session=self.session();session.recognizer.responses=[429,429,200];saved=[]
        asyncio.run(session.one(self.segment(),saved.append))
        self.assertEqual([r.http_status for r in saved],[429,429])
        self.assertTrue(session.stopped);self.assertEqual(session.reason,'retry_budget')
        self.assertEqual(session.requests,2)
    def test_owner_refusal_does_not_save_response(self):
        session=self.session(before_request=lambda:(_ for _ in ()).throw(RuntimeError('owner')))
        saved=[]
        with self.assertRaises(RuntimeError):asyncio.run(session.one(self.segment(),saved.append))
        self.assertEqual(saved,[]);self.assertEqual(session.requests,0)
    def test_budget_stops_before_transmission(self):
        session=self.session(policy=replace(rec.policy_for('probe'),request_limit=0));saved=[]
        asyncio.run(session.one(self.segment(),saved.append))
        self.assertEqual(saved,[]);self.assertEqual(session.requests,0)
        self.assertEqual(session.reason,'request_budget')
    def test_private_diagnostics_never_include_bodies_or_links(self):
        session=self.session();asyncio.run(session.one(self.segment(),lambda r:None))
        data=json.dumps(session.diagnostics())
        for forbidden in ['http://','https://','matches','headers','cookie']:
            self.assertNotIn(forbidden,data)
        self.assertEqual(session.diagnostics()['engine'],'shared-track-recognizer')
    def test_storage_failure_propagates_and_stops(self):
        session=self.session();session.recognizer.responses=[429,200]
        with self.assertRaisesRegex(RuntimeError,'storage'):
            asyncio.run(session.one(self.segment(),lambda r:(_ for _ in ()).throw(RuntimeError('storage'))))
        self.assertEqual(session.requests,1);self.assertTrue(session.stopped)
    def test_batch_delegates_concurrency_and_always_cleans_files(self):
        with tempfile.TemporaryDirectory() as d:
            segments=[]
            for i in range(3):
                path=Path(d)/str(i);path.write_bytes(b'x');segments.append(dict(index=i,timestamp=i*15,file=path))
            session=self.session();saved=[]
            rows=asyncio.run(session.recognize_batch(segments,total_segments=479,on_result=saved.append))
            self.assertEqual(len(rows),3);self.assertEqual(len(saved),3)
            self.assertEqual(len(session.recognizer.batch_calls),1)
            self.assertTrue(all(not s['file'].exists() for s in segments))
            asyncio.run(session.close());self.assertTrue(session.recognizer.closed)
    def test_batch_cleanup_after_checkpoint_failure(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'segment';path.write_bytes(b'x');session=self.session()
            with self.assertRaises(RuntimeError):
                asyncio.run(session.recognize_batch([dict(index=0,timestamp=0,file=path)],
                    on_result=lambda r:(_ for _ in ()).throw(RuntimeError('storage'))))
            self.assertFalse(path.exists())
    def test_shared_range_retains_default_engine_for_ordinary_callers(self):
        from worker.pipeline import recognize as pipeline
        context=SimpleNamespace(checkpoint_manager=object(),audio_file=Path('synthetic'),total_segments=479)
        default=SimpleNamespace(recognize_batch=AsyncMock(return_value=['unchanged']))
        extract=AsyncMock(return_value=[])
        async def run():
            with patch.object(pipeline,'AudioSegmenter',return_value=SimpleNamespace(create_segments_batch=extract)),patch('track_recognizer.TrackRecognizer',return_value=default) as factory:
                value=await pipeline.recognize_segment_range(context,start_index=3,end_index=3)
            self.assertEqual(value,['unchanged']);factory.assert_called_once_with()
        asyncio.run(run())
    def test_probe_job_persists_each_response_and_no_public_import(self):
        with tempfile.TemporaryDirectory() as d:
            audio=Path(d)/'input';audio.write_bytes(b'synthetic');writes=[]
            state=dict(audio_sha256=hashlib.sha256(b'synthetic').hexdigest(),recognition_mode='probe')
            store=SimpleNamespace(require_owner=lambda:state,write=lambda data:writes.append(data))
            async def fake_range(context,*,start_index,end_index,session,on_result):
                for i in range(start_index,end_index+1):await session.one(self.segment(i),on_result)
            with patch('audio_segmenter.AudioSegmenter.get_audio_duration_ffprobe',return_value=7200),patch.object(job,'recognize_private_range',fake_range):
                self.assertEqual(asyncio.run(job.recognize(store,audio)),'partial')
            self.assertEqual(writes[-1]['reason'],'probe_complete')
            self.assertEqual(writes[-1]['valid_responses'],5)
            self.assertNotIn('clustered_setlist',writes[-1])
            self.assertEqual(len(writes),6)
    def test_job_cancellation_or_error_flushes_partial_and_closes(self):
        for failure in ('cancel','unexpected','close'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as d:
                audio=Path(d)/'input';audio.write_bytes(b'synthetic');writes=[]
                state=dict(audio_sha256=hashlib.sha256(b'synthetic').hexdigest(),recognition_mode='probe')
                store=SimpleNamespace(require_owner=lambda:state,write=lambda data:writes.append(data))
                session=self.session()
                async def fake_range(context,*,start_index,end_index,session,on_result):
                    await session.one(self.segment(),on_result)
                    if failure=='cancel':raise asyncio.CancelledError()
                    if failure=='unexpected':raise RuntimeError('private_error')
                if failure=='close':
                    async def fail_close():
                        await session.recognizer.close()
                        raise RuntimeError('private_close_error')
                    session.close=fail_close
                with patch.object(job,'PrivateRecognitionSession',return_value=session),patch('audio_segmenter.AudioSegmenter.get_audio_duration_ffprobe',return_value=7200),patch.object(job,'recognize_private_range',fake_range):
                    if failure=='close':
                        self.assertEqual(asyncio.run(job.recognize(store,audio)),'partial')
                    else:
                        with self.assertRaises(asyncio.CancelledError if failure=='cancel' else RuntimeError):
                            asyncio.run(job.recognize(store,audio))
                self.assertTrue(session.recognizer.closed)
                self.assertEqual(writes[-1]['status'],'partial')
                self.assertEqual(writes[-1]['valid_responses'],1)
                self.assertNotIn('clustered_setlist',writes[-1])
                self.assertEqual(writes[-1]['reason'],{'cancel':'cancelled','unexpected':'worker_or_storage_error','close':'transport_close_error'}[failure])

    def test_no_private_provider_implementation_remains(self):
        text=Path(rec.__file__).read_text()
        for forbidden in ['class SingleAttemptHTTP','class PrivateHTTPError','def classify_error(',
                          'def retry_after(','from shazamio import Shazam','retry_floor_seconds','spacing_seconds']:
            self.assertNotIn(forbidden,text)

if __name__=='__main__':unittest.main()
