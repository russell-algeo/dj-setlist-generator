"""Fast offline regressions for the one shared recognition engine.

No provider, socket or database calls. Verify policy parity and hooks rather
than claiming synthetic timing predicts real Shazam throughput.
"""
import asyncio
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from config import Config
from recognition_transport import SingleAttemptHTTP, RequestAuthorizationError, RequestDeferred
from track_recognizer import TrackRecognizer
from worker.scheduler import build_scheduler_plan


class Reply:
    def __init__(self, status=200, headers=None):
        self.status, self.headers = status, headers or {}
    async def __aenter__(self): return self
    async def __aexit__(self,*args): pass
    async def json(self): return {'matches': []}


class HTTP:
    def __init__(self,replies): self.replies=list(replies); self.calls=0
    def request(self,*args,**kwargs):
        self.calls+=1
        return self.replies.pop(0)
    async def close(self): pass


def segment(index):
    return {'index':index,'timestamp':index*15,'file':Path('synthetic')}


class Tests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack=ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('socket.socket.connect',side_effect=AssertionError('NETWORK FORBIDDEN')))
        self.stack.enter_context(patch('socket.getaddrinfo',side_effect=AssertionError('DNS FORBIDDEN')))
        self.now=0; self.waits=[]
        async def sleep(seconds):
            self.now+=seconds; self.waits.append(seconds)
        # Do not patch asyncio's global sleep; the event loop still needs it.
        self.stack.enter_context(patch('track_recognizer.time',SimpleNamespace(monotonic=lambda:self.now,time=lambda:self.now)))
        self.stack.enter_context(patch('track_recognizer.random.uniform',return_value=0))
        self.sleep=sleep

    def recognizer(self,replies,**kwargs):
        rec=TrackRecognizer(quiet=True,**kwargs)
        http=HTTP(replies)
        rec.transport=SingleAttemptHTTP(session_factory=lambda **kw:http,
                                        before_request=rec.before_request)
        async def recognize(_):
            return await rec.transport.request('POST','https://provider.invalid')
        rec.shazam=SimpleNamespace(recognize=recognize)
        return rec,http

    async def test_production_retry_curve_and_durable_attempts(self):
        recorded=[]; tickets=[]
        def reserve(seg):
            ticket=(seg['index'],len(tickets)); tickets.append(ticket); return ticket
        rec,http=self.recognizer([Reply(429),Reply(503),Reply()],before_attempt=reserve,
            on_attempt=lambda r,t,d:recorded.append((r.http_status,t,d)))
        with patch('track_recognizer.asyncio.sleep',self.sleep):
            result=await rec.recognize_segment_with_backoff(segment(8))
        self.assertTrue(result.is_valid)
        self.assertEqual([r[0] for r in recorded],[429,503,200])
        self.assertEqual([r[1] for r in recorded],tickets)
        self.assertEqual([r[2] for r in recorded],[Config.BASE_DELAY*2,Config.BASE_DELAY*4,0])
        self.assertEqual(http.calls,3)
        self.assertNotIn(30,self.waits)

    async def test_quota_cooldown_after_same_retry_group_as_production(self):
        recorded=[]
        rec,http=self.recognizer([Reply(429)]*Config.MAX_RETRIES+[Reply()],
            before_attempt=lambda seg:seg['index'],
            on_attempt=lambda r,t,d:recorded.append(d))
        with patch('track_recognizer.asyncio.sleep',self.sleep):
            result=await rec.recognize_segment_with_backoff(segment(0))
        self.assertTrue(result.is_valid)
        self.assertEqual(http.calls,Config.MAX_RETRIES+1)
        self.assertEqual(recorded[Config.MAX_RETRIES-1],Config.QUOTA_COOLDOWN_DURATION)
        self.assertEqual(rec.retry_options.attempts,Config.MAX_RETRIES)
        self.assertEqual(rec.retry_options._random_interval_size,Config.JITTER_INTERVAL_SIZE)
        self.assertEqual(rec.retry_options._max_timeout,Config.MAX_BACKOFF_DELAY)

    async def test_retry_after_persisted_even_beyond_continuation(self):
        recorded=[]
        rec,http=self.recognizer([Reply(429,{'Retry-After':'600'})],max_retry_seconds=10,
            before_attempt=lambda seg:'ticket',on_attempt=lambda r,t,d:recorded.append(d))
        with patch('track_recognizer.asyncio.sleep',self.sleep):
            result=await rec.recognize_segment_with_backoff(segment(0))
        self.assertFalse(result.is_valid)
        self.assertEqual(recorded,[600]); self.assertEqual(http.calls,1)

    async def test_actual_two_way_concurrency_and_no_24_request_limit(self):
        started=set(); active=0; peak=0; released=asyncio.Event(); receipts=[]
        rec,http=self.recognizer([Reply()]*40,before_attempt=lambda seg:seg['index'],
            on_attempt=lambda r,t,d:receipts.append((r.segment_index,t,d)))
        original=rec.shazam.recognize
        async def recognize(path):
            nonlocal active,peak
            active+=1; peak=max(peak,active)
            if active==2: released.set()
            await released.wait()
            try: return await original(path)
            finally: active-=1
        rec.shazam.recognize=recognize
        output=StringIO()
        with redirect_stdout(output):
            results=await rec.recognize_batch([segment(i) for i in range(40)],cleanup_files=False)
        self.assertTrue(all(r.is_valid for r in results)); self.assertEqual(http.calls,40)
        self.assertEqual(peak,2)
        self.assertEqual({r[0] for r in receipts},set(range(40)))
        self.assertTrue(all(i==t and d==0 for i,t,d in receipts))
        self.assertEqual(output.getvalue(),'')
        self.assertEqual(build_scheduler_plan(479).slot_count,12)

    async def test_fence_refusal_is_not_stored_as_provider_attempt(self):
        receipts=[]
        def refuse(seg): raise RuntimeError('private owner changed')
        rec,http=self.recognizer([Reply()],before_attempt=refuse,
            on_attempt=lambda *args:receipts.append(args))
        with self.assertRaises(RequestAuthorizationError):
            await rec.recognize_segment_with_backoff(segment(0))
        self.assertEqual(http.calls,0); self.assertEqual(receipts,[])

    async def test_later_batch_keeps_absolute_continuation_deadline(self):
        rec,http=self.recognizer([Reply(429,{'Retry-After':'20'})],
            max_retry_seconds=300,continuation_deadline=100)
        self.now=90
        with patch('track_recognizer.asyncio.sleep',self.sleep):
            result=await rec.recognize_segment_with_backoff(segment(7))
        self.assertFalse(result.is_valid)
        self.assertEqual(http.calls,1)
        self.assertNotIn(20,self.waits)
        self.now=101
        result=await rec.recognize_segment_with_backoff(segment(8))
        self.assertEqual(result.error_type,'RetryBudgetExceeded')
        self.assertEqual(http.calls,1)

    async def test_deliberate_admission_pause_preserves_control_flow(self):
        receipts=[]
        def defer(seg): raise RequestDeferred('window_attempt_budget')
        rec,http=self.recognizer([Reply()],before_attempt=defer,
            on_attempt=lambda *args:receipts.append(args))
        with self.assertRaisesRegex(RequestDeferred,'^window_attempt_budget$'):
            await rec.recognize_batch([segment(0)],cleanup_files=False)
        self.assertEqual(http.calls,0); self.assertEqual(receipts,[])
