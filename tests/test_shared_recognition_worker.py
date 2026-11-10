"""Durable policy/runner tests with synthetic extraction and no provider sockets."""
import asyncio
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from worker.jobs.shared_recognition import (budget_reason, valid_coverage, valid_result,
    recognize_continuation, audio_fingerprint, RecognitionPause)
from worker.pipeline.models import Recognition
from config import Config


def result(i=0,**kwargs):
    return Recognition(i*15,None,None,None,{'matches':[]},False,i,http_status=200,**kwargs)

def state():
    return dict(created_at=100,continuations=1,requests=0,request_limit=100,
                session_started=100,session_requests=0)

class PolicyTests(unittest.TestCase):
    def test_budget_boundaries_reserve_time_for_request(self):
        for patch_,now,expected in [({},150,None),({'requests':100},150,'lifetime_request_budget'),
                ({'continuations':257},150,'continuation_budget'),
                ({'session_requests':240},150,None),
                ({},3635,'workflow_time_budget'),({},604900,'lifetime_time_budget')]:
            self.assertEqual(budget_reason(dict(state(),**patch_),now),expected)

    def test_failure_not_no_match_and_exact_coverage(self):
        self.assertTrue(valid_result(result()))
        self.assertFalse(valid_result(result(error_type='RateLimited')))
        self.assertFalse(valid_coverage([{'segment_index':0,'raw_data':None}],1,versioned=False))
        self.assertFalse(valid_coverage([{'segment_index':1,'raw_data':{'matches':[]}}],1,versioned=False))
        self.assertFalse(valid_coverage([{'segment_index':0,'raw_data':{'error':'failed'}}],1,versioned=False))
        self.assertTrue(valid_coverage([{'segment_index':0,'raw_data':{'matches':[]}}],1,versioned=False))

class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        stack=ExitStack();self.addCleanup(stack.close)
        stack.enter_context(patch('socket.socket.connect',side_effect=AssertionError('NETWORK FORBIDDEN')))
        stack.enter_context(patch('socket.getaddrinfo',side_effect=AssertionError('DNS FORBIDDEN')))
        tmp=stack.enter_context(TemporaryDirectory())
        p=Path(tmp)/'synthetic';p.write_bytes(b'offline fixture')
        self.context=SimpleNamespace(audio_file=p,total_segments=1)
        self.saved=dict(state(),audio_sha256=audio_fingerprint(p),geometry=dict(
            segment_duration=Config.SEGMENT_DURATION,segment_overlap=Config.SEGMENT_OVERLAP,segment_count=1))
        self.lease={'id':'synthetic-lease','segment_start_index':0,'segment_end_index':0}
        self.store=SimpleNamespace(identity='9001:1',state=lambda:(150,self.saved),
            claim_lease=unittest.mock.Mock(side_effect=[self.lease,None]),
            missing_indices=lambda lease:[0],reserve=lambda *args:'ticket',
            finish=unittest.mock.Mock(),settle_lease=unittest.mock.Mock(return_value=True),
            pause=unittest.mock.Mock())
        self.transport=SimpleNamespace(close=AsyncMock())
        from track_recognizer import TrackRecognizer
        self.real_recognizer=TrackRecognizer
        self.factory=stack.enter_context(patch('track_recognizer.TrackRecognizer',return_value=self.transport))
        self.extract=stack.enter_context(patch('worker.pipeline.recognize.recognize_segment_range',new_callable=AsyncMock))

    async def test_uses_shared_engine_hooks_and_production_range(self):
        async def extract(context,**kw):
            self.assertIs(kw['recognizer'],self.transport)
            hooks=self.factory.call_args.kwargs
            ticket=hooks['before_attempt']({'index':0})
            hooks['on_attempt'](result(),ticket,0)
            kw['on_result'](result())
            return [result()]
        self.extract.side_effect=extract
        counts=await recognize_continuation(self.store,self.context,check_active=lambda:None,slot_index=11)
        self.assertEqual(counts,dict(lease_count=1,recognized_count=0))
        self.factory.assert_called_once()
        self.assertNotIn('single_attempt',self.factory.call_args.kwargs)
        self.assertTrue(callable(self.factory.call_args.kwargs['before_attempt']))
        self.store.finish.assert_called_once()
        self.transport.close.assert_awaited_once()
        self.assertIn('slot-11',self.store.claim_lease.call_args.args[0])

    async def test_completed_holes_not_extracted(self):
        self.store.missing_indices=lambda lease:[]
        await recognize_continuation(self.store,self.context,check_active=lambda:None)
        self.extract.assert_not_called()
        self.transport.close.assert_awaited_once()

    async def test_incomplete_lease_yields_without_deleting_results(self):
        self.store.settle_lease.return_value=False
        await recognize_continuation(self.store,self.context,check_active=lambda:None)
        self.store.pause.assert_called_with('recognition_retry_pending')
        self.store.claim_lease.assert_called_once()

    async def test_cancel_propagates_and_closes(self):
        self.extract.side_effect=asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await recognize_continuation(self.store,self.context,check_active=lambda:None)
        self.transport.close.assert_awaited_once()

    async def test_real_engine_store_deferral_yields_cleanly_without_http(self):
        from recognition_transport import SingleAttemptHTTP
        actual=self.real_recognizer
        class HTTP:
            calls=0
            def request(self,*a,**k):
                self.calls+=1
                raise AssertionError('must not transmit')
            async def close(self): pass
        http=HTTP()
        def construct(**kwargs):
            rec=actual(**kwargs)
            rec.transport=SingleAttemptHTTP(session_factory=lambda **k:http,before_request=rec.before_request)
            async def recognize(_):
                return await rec.transport.request('POST','https://provider.invalid')
            rec.shazam=SimpleNamespace(recognize=recognize)
            return rec
        self.factory.side_effect=construct
        self.store.reserve=lambda *a:(_ for _ in ()).throw(RecognitionPause('cooldown_pending'))
        async def extract(context,**kw):
            return await kw['recognizer'].recognize_batch(
                [{'index':0,'timestamp':0,'file':Path('/tmp/synthetic-no-file')}],cleanup_files=False)
        self.extract.side_effect=extract
        with patch.object(Config,'BASE_DELAY',0):
            counts=await recognize_continuation(self.store,self.context,check_active=lambda:None)
        self.assertEqual(http.calls,0)
        self.assertEqual(counts['lease_count'],0)
        self.store.pause.assert_called_with('cooldown_pending')
        self.store.finish.assert_not_called()

    async def test_changed_audio_pauses_before_transport_or_request(self):
        self.context.audio_file.write_bytes(b'changed')
        with self.assertRaises(RecognitionPause):
            await recognize_continuation(self.store,self.context,check_active=lambda:None)
        self.factory.assert_not_called()
        self.extract.assert_not_called()
