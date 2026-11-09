"""Offline only: all sockets and live DB connections are forbidden."""
import asyncio
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worker.jobs import yoon_recognition as rec
from worker.jobs import yoon_once as job
from worker.pipeline.models import Recognition
from config import Config


class FakeClock:
    def __init__(self): self.now = 0; self.waits = []
    def __call__(self): return self.now
    async def sleep(self, seconds): self.waits.append(seconds); self.now += seconds


class Response:
    def __init__(self, status=200, headers=None, value=None):
        self.status = status
        self.headers = headers or {}
        self.value = {'matches': []} if value is None else value
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def json(self): return self.value


class HTTP:
    def __init__(self, responses): self.responses = list(responses); self.calls = []; self.closed = False
    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.responses.pop(0)
    async def close(self): self.closed = True


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Legacy clustering tests install global stubs. Use the installed SDK here,
        # restore only those stubs afterward, and never unload/reinitialize native code.
        cls.stubs = {}
        for name in ('aiohttp_retry', 'shazamio'):
            if name in sys.modules and not getattr(sys.modules[name], '__file__', None):
                cls.stubs[name] = sys.modules.pop(name)
            importlib.import_module(name)

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.stubs)

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('worker.db.connect', side_effect=AssertionError('LIVE DB FORBIDDEN')))
        self.stack.enter_context(patch('socket.socket.connect', side_effect=AssertionError('NETWORK FORBIDDEN')))
        self.stack.enter_context(patch('socket.getaddrinfo', side_effect=AssertionError('DNS FORBIDDEN')))

    def session(self, responses, mode='probe', before_request=lambda: None):
        clock = FakeClock(); http = HTTP(responses)
        session = rec.PrivateRecognitionSession(rec.policy_for(mode), before_request=before_request,
                    clock=clock, wall_clock=lambda: 0, sleep=clock.sleep, session_factory=lambda **kw: http)
        async def recognize(_):
            return await session.transport.request('POST', 'https://provider.invalid/PRIVATE_URL',
                                                    headers={'Private': 'DO_NOT_SAVE'})
        session.recognizer.shazam = SimpleNamespace(recognize=recognize)
        return session, clock, http

    def run_windows(self, session, count):
        saved = []
        async def run():
            for i in range(count):
                await session.one({'index': i, 'timestamp': i*15, 'file': 'synthetic'}, saved.append)
            await session.close()
        asyncio.run(run())
        return saved

    def test_typed_rate_limit_without_numeric_message_and_wrapped(self):
        from shazamio.exceptions import RateLimited
        error = RateLimited('SYNTHETIC_PRIVATE_URL rate limited the request')
        self.assertEqual(rec.classify_error(error), ('RateLimited', True))
        outer = ValueError('wrapper'); outer.__cause__ = error
        self.assertEqual(rec.classify_error(outer), ('RateLimited', True))
        self.assertEqual(rec.classify_error(ValueError('429 is just untrusted text')), ('RecognitionError', False))
        outer.__cause__ = outer
        self.assertEqual(rec.classify_error(outer), ('RecognitionError', False))

    def test_retry_after_formats(self):
        for value, expected in [(None,(None,'absent')), ('120',(120,'delta_seconds')),
                ('0',(0,'delta_seconds')), ('-1',(None,'invalid')), ('1.5',(None,'invalid')),
                ('nan',(None,'invalid')), ('PRIVATE_URL',(None,'invalid')), ('9'*100,(10**12,'delta_seconds'))]:
            self.assertEqual(rec.retry_after(value,0), expected)
        now = datetime(2026,11,9,tzinfo=timezone.utc).timestamp()
        self.assertEqual(rec.retry_after('Mon, 09 Nov 2026 00:02:01 GMT',now), (121,'http_date'))
        self.assertEqual(rec.retry_after('Mon, 09 Nov 2026 00:00:00 GMT',now+1), (0,'http_date'))
        self.assertEqual(rec.retry_after('Mon, 09 Nov 2026 00:00:00',now), (None,'invalid'))

    def test_reuses_the_existing_segment_recognition_method(self):
        from track_recognizer import TrackRecognizer
        session,clock,http=self.session([Response()])
        self.assertIsInstance(session.recognizer,TrackRecognizer)
        self.assertIs(type(session.recognizer).recognize_segment,TrackRecognizer.recognize_segment)
        with patch.object(TrackRecognizer,'recognize_segment_with_backoff',side_effect=AssertionError('UNBOUNDED LOOP FORBIDDEN')):
            results=self.run_windows(session,1)
        self.assertEqual(len(results),1)
        self.assertFalse(results[0].recognized)

    def test_policy_limits_and_explicit_full_mode(self):
        self.assertEqual(rec.policy_for('probe').window_limit,5)
        self.assertEqual(rec.policy_for('probe').request_limit,6)
        self.assertEqual(rec.policy_for('full').window_limit,479)
        self.assertEqual(rec.policy_for('full').request_limit,480)
        with self.assertRaises(RuntimeError): rec.policy_for('anything')

    def test_sequential_spacing_and_safe_diagnostics(self):
        session, clock, http = self.session([Response() for _ in range(5)])
        results = self.run_windows(session,5)
        self.assertEqual(len(results),5)
        self.assertEqual(clock.waits,[8]*4)
        self.assertEqual([r['started_after_seconds'] for r in session.attempts], [0,8,16,24,32])
        self.assertEqual(session.diagnostics()['requests'],5)
        for args, kwargs in http.calls:
            self.assertFalse(kwargs['allow_redirects'])
            self.assertEqual(kwargs['timeout'].total,30)
        diagnostic = json.dumps(session.diagnostics())
        for forbidden in ['PRIVATE_URL','DO_NOT_SAVE','headers','https://','matches']:
            self.assertNotIn(forbidden,diagnostic)
        self.assertIn('shazamio',session.diagnostics()['versions'])
        self.assertTrue(http.closed)

    def test_actual_429_one_capped_retry_then_stop(self):
        session, clock, http = self.session([Response(429,{'Retry-After':'150'}), Response(429)])
        results = self.run_windows(session,10)
        self.assertEqual(len(http.calls),2)
        self.assertEqual(len(results),2)
        self.assertEqual(clock.waits,[150])
        self.assertTrue(all(r.was_rate_limited for r in results))
        self.assertTrue(session.stopped)
        self.assertEqual(session.reason,'rate_limited')
        self.assertEqual(session.attempts[0]['http_status'],429)
        self.assertEqual(session.attempts[0]['planned_retry_wait_seconds'],150)

    def test_rate_limit_retry_budget_is_global(self):
        session, clock, http = self.session([Response(429),Response(),Response(429)])
        results = self.run_windows(session,10)
        self.assertEqual(len(http.calls),3)
        self.assertEqual(clock.waits,[120,8])
        self.assertEqual([r.segment_index for r in results],[0,0,1])
        self.assertEqual(session.retries,1)
        self.assertTrue(session.stopped)

    def test_long_or_invalid_retry_after_stops_without_shortening(self):
        for value, reason in [('301','retry_after_exceeds_budget'), ('9'*100,'retry_after_exceeds_budget'),
                              ('not-a-date','invalid_retry_after')]:
            session, clock, http = self.session([Response(429,{'Retry-After':value})])
            self.run_windows(session,10)
            self.assertEqual(len(http.calls),1)
            self.assertEqual(clock.waits,[])
            self.assertEqual(session.reason,reason)

    def test_transport_request_cap_and_no_redirects(self):
        session, clock, http = self.session([Response() for _ in range(7)])
        self.run_windows(session,10)
        self.assertEqual(len(http.calls),6)
        self.assertTrue(session.stopped)
        session, clock, http = self.session([Response(302,{'Location':'PRIVATE_URL'})])
        self.run_windows(session,10)
        self.assertEqual(len(http.calls),1)
        self.assertEqual(session.attempts[0]['http_status'],302)

    def test_one_post_per_sdk_attempt(self):
        session, clock, http = self.session([Response(),Response()])
        async def changed_sdk(_):
            await session.transport.request('POST','PRIVATE_URL')
            return await session.transport.request('POST','PRIVATE_URL')
        session.recognizer.shazam.recognize = changed_sdk
        results=self.run_windows(session,5)
        self.assertEqual(len(http.calls),1)
        self.assertEqual(results[0].error_type,'PrivateBudgetStop')
        self.assertTrue(session.stopped)

    def test_invalid_response_and_server_error_are_not_no_match(self):
        for response in [Response(value={'error':'PRIVATE_URL'}), Response(503),
                         Response(value={'matches':[{}]})]:
            session,clock,http=self.session([response])
            results=self.run_windows(session,5)
            self.assertEqual(len(http.calls),1)
            self.assertTrue(results[0].error_type)
            self.assertIsNone(results[0].error_details)
            self.assertIsNone(results[0].raw_data)
            self.assertTrue(session.stopped)

    def test_typed_fallback_does_not_invent_http_status(self):
        from shazamio.exceptions import RateLimited
        session,clock,http=self.session([])
        async def fail(_): raise RateLimited('PRIVATE_URL')
        session.recognizer.shazam.recognize=fail
        results=self.run_windows(session,5)
        self.assertEqual(len(http.calls),0)
        self.assertEqual(len(results),2)
        self.assertTrue(all(row['http_status'] is None for row in session.attempts))
        self.assertNotIn('PRIVATE_URL',json.dumps(session.diagnostics()))

    def test_failure_checkpoint_precedes_backoff_and_owner_recheck(self):
        events=[]
        session,clock,http=self.session([Response(429),Response()],before_request=lambda:events.append('owner'))
        async def sleep(seconds): events.append('wait'); await clock.sleep(seconds)
        session.sleep=sleep
        async def run():
            await session.one({'index':0,'timestamp':0,'file':'synthetic'},lambda result:events.append('saved'))
            await session.close()
        asyncio.run(run())
        self.assertEqual(events,['owner','saved','wait','owner','saved'])

    def test_storage_failure_stops_without_retry(self):
        session,clock,http=self.session([Response(429),Response()])
        async def run():
            def fail(result): raise RuntimeError('storage')
            with self.assertRaises(RuntimeError):
                await session.one({'index':0,'timestamp':0,'file':'synthetic'},fail)
            await session.close()
        asyncio.run(run())
        self.assertEqual(len(http.calls),1)
        self.assertEqual(clock.waits,[])
        self.assertTrue(session.stopped)

    def test_attempt_timeout_stops_without_retry(self):
        session,clock,http=self.session([])
        from dataclasses import replace
        session.policy=replace(session.policy,attempt_timeout_seconds=.001)
        async def hang(_): await asyncio.sleep(5)
        session.recognizer.shazam.recognize=hang
        results=self.run_windows(session,5)
        self.assertEqual(results[0].error_type,'RequestTimeout')
        self.assertTrue(session.stopped)

    def exercise_job(self, mode='probe', fail=None):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); audio=root/'input.mp3'; audio.write_bytes(b'synthetic')
            writes=[]; saved={'audio_sha256':hashlib.sha256(b'synthetic').hexdigest(), 'recognition_mode':mode}
            store=SimpleNamespace(require_owner=lambda:saved,write=lambda data:writes.append(data))
            session,clock,http=self.session([Response(429),Response()]+[Response() for _ in range(4)],mode)
            async def fake_range(context,*,start_index,end_index,session,on_result):
                for i in range(start_index,end_index+1):
                    await session.one({'index':i,'timestamp':i*15,'file':'synthetic'},on_result)
                    if fail=='unexpected': raise RuntimeError('SYNTHETIC_PRIVATE_SECRET')
                    if fail=='cancel': raise asyncio.CancelledError()
            with patch.object(Config,'ASSETS_DIR',root/'assets'), patch.object(Config,'CHECKPOINT_DIR',root/'cp'), \
                 patch.object(Config,'OUTPUT_DIR',root/'output'), \
                 patch('audio_segmenter.AudioSegmenter.get_audio_duration_ffprobe',return_value=7200), \
                 patch('audio_segmenter.AudioSegmenter.calculate_total_segments',return_value=479), \
                 patch.object(job,'PrivateRecognitionSession',return_value=session), \
                 patch.object(job,'recognize_private_range',fake_range):
                if fail:
                    with self.assertRaises(asyncio.CancelledError if fail=='cancel' else RuntimeError):
                        asyncio.run(job.recognize(store,audio))
                else:
                    self.assertEqual(asyncio.run(job.recognize(store,audio)),'partial')
            self.assertTrue(http.closed)
            return writes

    def test_probe_partial_flushes_every_attempt_and_does_not_import(self):
        writes=self.exercise_job()
        self.assertEqual(len(writes),7)
        final=writes[-1]
        self.assertEqual(final['status'],'partial')
        self.assertEqual(final['reason'],'probe_complete')
        self.assertEqual(final['expected_windows'],479)
        self.assertEqual(final['valid_responses'],5)
        self.assertEqual(len(final['raw_recognitions']),5)
        self.assertEqual(len(final['recognition_diagnostics']['attempts']),6)
        self.assertTrue(writes[0]['raw_recognitions'][0]['was_rate_limited'])
        self.assertNotIn('clustered_setlist',final)

    def test_unexpected_failure_and_cancel_preserve_partial(self):
        for failure,reason in [('unexpected','worker_or_storage_error'),('cancel','cancelled')]:
            writes=self.exercise_job(fail=failure)
            self.assertEqual(writes[-1]['status'],'partial')
            self.assertEqual(writes[-1]['reason'],reason)
            self.assertEqual(writes[-1]['valid_responses'],1)
            self.assertNotIn('clustered_setlist',writes[-1])

    def test_owner_revocation_during_retry_wait_blocks_transmission(self):
        checks = []
        def owner():
            checks.append(True)
            if len(checks) > 1:
                raise RuntimeError('private_owner_mismatch')
        session,clock,http=self.session([Response(429),Response()],before_request=owner)
        results=self.run_windows(session,5)
        self.assertEqual(len(http.calls),1)
        self.assertEqual(len(checks),2)
        self.assertTrue(session.stopped)
        self.assertTrue(results[-1].error_type)

    def test_concurrent_callers_still_have_one_active_request(self):
        session,clock,http=self.session([Response() for _ in range(5)])
        active=0; maximum=0
        async def slow(_):
            nonlocal active,maximum
            active+=1; maximum=max(maximum,active)
            await asyncio.sleep(0)
            try:
                return await session.transport.request('POST','PRIVATE_URL')
            finally:
                active-=1
        session.recognizer.shazam.recognize=slow
        saved=[]
        async def run():
            await asyncio.gather(*(session.one({'index':i,'timestamp':i*15,'file':'synthetic'},saved.append)
                                   for i in range(5)))
            await session.close()
        asyncio.run(run())
        self.assertEqual(maximum,1)
        self.assertEqual(len(saved),5)
        self.assertEqual(len(http.calls),5)

    def test_cancel_during_backoff_preserves_durable_error(self):
        session,clock,http=self.session([Response(429),Response()])
        saved=[]
        async def cancelled(seconds): raise asyncio.CancelledError()
        session.sleep=cancelled
        async def run():
            with self.assertRaises(asyncio.CancelledError):
                await session.one({'index':0,'timestamp':0,'file':'synthetic'},saved.append)
            await session.close()
        asyncio.run(run())
        self.assertEqual(len(http.calls),1)
        self.assertEqual(len(saved),1)
        self.assertTrue(saved[0].was_rate_limited)
        self.assertEqual(session.attempts[0]['planned_retry_wait_seconds'],120)

    def test_aggregation_and_close_errors_still_flush_partial(self):
        for failure in ('aggregation','close'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                root=Path(temp); audio=root/'input.mp3'; audio.write_bytes(b'synthetic')
                saved={'audio_sha256':hashlib.sha256(b'synthetic').hexdigest(),'recognition_mode':'full'}
                writes=[]
                store=SimpleNamespace(require_owner=lambda:saved,write=lambda data:writes.append(data))
                session,clock,http=self.session([Response()],mode='full')
                async def fake_range(context,*,start_index,end_index,session,on_result):
                    await session.one({'index':0,'timestamp':0,'file':'synthetic'},on_result)
                async def fail_close():
                    await session.transport.close()
                    raise RuntimeError('PRIVATE_CLOSE_ERROR')
                if failure=='close': session.close=fail_close
                with patch.object(Config,'ASSETS_DIR',root/'assets'), patch.object(Config,'CHECKPOINT_DIR',root/'cp'), \
                     patch.object(Config,'OUTPUT_DIR',root/'output'), patch.object(job,'WINDOWS',1), \
                     patch('audio_segmenter.AudioSegmenter.get_audio_duration_ffprobe',return_value=7200), \
                     patch('audio_segmenter.AudioSegmenter.calculate_total_segments',return_value=1), \
                     patch.object(job,'PrivateRecognitionSession',return_value=session), \
                     patch.object(job,'recognize_private_range',fake_range), \
                     patch('worker.pipeline.aggregate.build_tracks_from_recognitions',side_effect=RuntimeError('PRIVATE_AGGREGATION_ERROR')):
                    self.assertEqual(asyncio.run(job.recognize(store,audio)),'partial')
                self.assertEqual(writes[-1]['status'],'partial')
                self.assertEqual(writes[-1]['valid_responses'],1)
                self.assertEqual(writes[-1]['reason'],'aggregation_error' if failure=='aggregation' else 'transport_close_error')
                self.assertNotIn('clustered_setlist',writes[-1])
                self.assertTrue(http.closed)

    def test_shared_range_existing_callers_keep_default_recognizer(self):
        from unittest.mock import AsyncMock
        from worker.pipeline import recognize as pipeline
        context=SimpleNamespace(checkpoint_manager=object(),audio_file=Path('synthetic'),total_segments=479)
        segments=[{'index':3,'timestamp':45,'file':Path('synthetic-segment')}]
        callback=lambda row: None
        default=SimpleNamespace(recognize_batch=AsyncMock(return_value=['unchanged']))
        extract=AsyncMock(return_value=segments)
        async def exercise():
            with patch.object(pipeline,'AudioSegmenter',return_value=SimpleNamespace(create_segments_batch=extract)), \
                 patch('track_recognizer.TrackRecognizer',return_value=default) as factory:
                result=await pipeline.recognize_segment_range(context,start_index=3,end_index=3,on_result=callback)
            self.assertEqual(result,['unchanged'])
            factory.assert_called_once_with()
            default.recognize_batch.assert_awaited_once_with(segments,total_segments=479,batch_start=3,on_result=callback)
            self.assertEqual(extract.await_args.args[:3],(context.audio_file,3,4))
        asyncio.run(exercise())

    def test_shared_range_private_adapter_checkpoint_error_and_cleanup(self):
        from unittest.mock import AsyncMock
        from worker.pipeline import recognize as pipeline
        for outcome in ('success','quota','cancel','callback'):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as temp:
                root=Path(temp)
                segments=[]
                for i in range(3):
                    path=root/f'{i}.mp3'; path.write_bytes(b'synthetic')
                    segments.append({'index':i,'timestamp':i*15,'file':path})
                responses=[Response(429,{'Retry-After':'301'})] if outcome=='quota' else [Response() for _ in range(3)]
                session,clock,http=self.session(responses)
                if outcome=='cancel':
                    async def cancel(_): raise asyncio.CancelledError()
                    session.recognizer.shazam.recognize=cancel
                saved=[]
                def checkpoint(result):
                    saved.append(result)
                    if outcome=='callback': raise RuntimeError('private_storage_failure')
                context=SimpleNamespace(checkpoint_manager=object(),audio_file=root/'audio',total_segments=479)
                async def exercise():
                    with patch.object(pipeline,'AudioSegmenter',return_value=SimpleNamespace(create_segments_batch=AsyncMock(return_value=segments))), \
                         patch('track_recognizer.TrackRecognizer',side_effect=AssertionError('DEFAULT MUST NOT BE CREATED')):
                        call=job.recognize_private_range(context,start_index=0,end_index=2,session=session,on_result=checkpoint)
                        if outcome=='cancel':
                            with self.assertRaises(asyncio.CancelledError): await call
                        elif outcome=='callback':
                            with self.assertRaises(RuntimeError): await call
                        else:
                            results=await call
                            self.assertEqual(len(results),3 if outcome=='success' else 1)
                    await session.close()
                asyncio.run(exercise())
                self.assertTrue(all(not segment['file'].exists() for segment in segments))
                if outcome=='success':
                    self.assertEqual([row.segment_index for row in saved],[0,1,2])
                elif outcome=='quota':
                    self.assertTrue(saved[0].was_rate_limited)
                    self.assertEqual(saved[0].error_type,'RateLimited')
                    self.assertIsNone(saved[0].error_details)
                    self.assertEqual(session.diagnostics()['requests'],1)
                elif outcome=='callback':
                    self.assertEqual(len(http.calls),1)
                    self.assertTrue(session.stopped)

    def test_workflow_keeps_ordinary_dependencies_unchanged(self):
        workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/process-set.yml').read_text()
        ordinary,private=workflow.split('  private-offline-tests:',1)
        offline, media = private.split('  private-prepare:', 1)
        self.assertNotIn('secrets.', offline)
        self.assertNotIn('upload-artifact', offline)
        self.assertIn("python-version: '3.11'", offline)
        self.assertIn('needs: private-offline-tests', media)
        self.assertNotIn('requirements-private-recognize.txt',ordinary)
        self.assertEqual(private.count('requirements-private-recognize.txt'),3)
        self.assertEqual(private.count("CONCURRENT_RECOGNITIONS: '1'"),2)
        self.assertIn('retention-days: 1',private)

if __name__=='__main__': unittest.main()
