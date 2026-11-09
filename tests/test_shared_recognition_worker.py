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
                ({'session_requests':24},150,'workflow_request_budget'),
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
        self.store=SimpleNamespace(state=lambda:(150,self.saved),reserve=None,
                                  finish=lambda *_:None,pause=lambda *a,**k:None,authorize=lambda *_:None)
        self.transport=SimpleNamespace(close=AsyncMock())
        self.factory=stack.enter_context(patch('track_recognizer.TrackRecognizer',return_value=self.transport))
        self.extract=stack.enter_context(patch('worker.pipeline.recognize.recognize_segment_range',new_callable=AsyncMock))

    async def test_one_client_and_finish_before_next_reservation(self):
        events=[]
        def reserve():
            events.append('reserve')
            return ({'index':0,'token':'synthetic'},0,None) if len(events)==1 else (None,0,'complete')
        self.store.reserve=reserve
        self.store.finish=lambda *_:events.append('finish')
        async def extract(context,**kw):
            self.assertIs(kw['recognizer'],self.transport)
            kw['on_result'](result())
            return [result()]
        self.extract.side_effect=extract
        counts=await recognize_continuation(self.store,self.context,check_active=lambda:None)
        self.assertEqual(events,['reserve','finish','reserve'])
        self.assertEqual(counts,dict(lease_count=1,recognized_count=0))
        self.factory.assert_called_once()
        self.assertTrue(self.factory.call_args.kwargs['single_attempt'])
        self.assertTrue(callable(self.factory.call_args.kwargs['before_request']))
        self.transport.close.assert_awaited_once()

    async def test_cooldown_yields_without_request_and_keeps_due(self):
        saved=[]
        self.store.reserve=lambda:(None,600,'cooldown_pending')
        self.store.pause=lambda reason,**kw:saved.append((reason,kw['wait']))
        await recognize_continuation(self.store,self.context,check_active=lambda:None)
        self.extract.assert_not_called()
        self.assertEqual(saved,[('cooldown_pending',600)])

    async def test_missing_response_keeps_uncertain_reservation(self):
        saved=[]
        self.store.reserve=lambda:({'index':0,'token':'synthetic'},0,None)
        self.store.pause=lambda reason,**kw:saved.append(reason)
        self.extract.return_value=[]
        with self.assertRaises(RuntimeError):
            await recognize_continuation(self.store,self.context,check_active=lambda:None)
        self.assertEqual(saved,['worker_or_storage_error'])
        self.transport.close.assert_awaited_once()

    async def test_cancel_propagates_and_closes(self):
        self.store.reserve=lambda:({'index':0,'token':'synthetic'},0,None)
        self.extract.side_effect=asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await recognize_continuation(self.store,self.context,check_active=lambda:None)
        self.transport.close.assert_awaited_once()

    async def test_changed_audio_pauses_before_transport_or_request(self):
        self.context.audio_file.write_bytes(b'changed')
        with self.assertRaises(RecognitionPause):
            await recognize_continuation(self.store,self.context,check_active=lambda:None)
        self.factory.assert_not_called()
        self.extract.assert_not_called()
