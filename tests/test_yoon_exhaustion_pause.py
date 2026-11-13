"""Intentional cap refusal must not become a generic transport error."""
import copy
from contextlib import contextmanager
from dataclasses import asdict
from unittest import TestCase
from unittest.mock import Mock
from uuid import UUID
from worker.jobs.yoon_resume_store import ResumeStore, QueuePause
from worker.jobs.yoon_sources import JACKSON
from worker.pipeline.models import Recognition


def fixture(status=503, count=8):
    response = Recognition(0,None,None,None,None,False,0,error_type='RateLimited' if status==429 else 'ProviderServerError',http_status=status)
    attempts = [dict(state='finished',number=i+1,workflow_run_id='9001',run_attempt='1',
        ticket=str(UUID(int=i+1)),started_at=100+i,finished_at=100+i,
        diagnostic=dict(http_status=status,outcome=response.error_type,retry_after_format='absent')) for i in range(count)]
    return dict(valid=False,in_flight=False,attempts=attempts,response=asdict(response))


class ExhaustionTests(TestCase):
    def reserve(self, data, status='exhausted'):
        store=object.__new__(ResumeStore);store.run_id='synthetic';store.source=JACKSON
        store.owner={'workflow_run_id':'9001','run_attempt':'1'}
        store._slot=lambda state,index:(1,10)
        state=dict(throttle_policy_version=3,requests=8,throttle_requests=0,
                   session_started=100,session_requests=8,continuations=1,created_at=100)
        before=copy.deepcopy((state,data))
        cursor=Mock();cursor.fetchone.return_value={'id':'lease','status':status,'raw_data':{'private_jackson_v2':data}}
        @contextmanager
        def locked(*, capacity=False):
            self.assertTrue(capacity)
            yield cursor,{'db_now':110},state
        store.locked=locked;store.save_state=Mock()
        try:store.reserve(0)
        finally:
            self.assertEqual((state,data),before)
            self.assertEqual(cursor.execute.call_count,1)
            store.save_state.assert_not_called()

    def test_exact_effective_cap_intentionally_pauses(self):
        for status in ['pending','exhausted']:
            with self.assertRaisesRegex(QueuePause,'^window_attempt_budget$'):
                self.reserve(fixture(),status)
        mixed=fixture();tail=fixture(429,12)
        for i,a in enumerate(tail['attempts'],9):a.update(number=i,ticket=str(UUID(int=i)))
        mixed['attempts']+=tail['attempts'];mixed['response']=tail['response']
        with self.assertRaisesRegex(QueuePause,'^window_attempt_budget$'):
            self.reserve(mixed)

    def test_all_throttles_do_not_forge_effective_exhaustion(self):
        with self.assertRaises(RuntimeError) as caught:self.reserve(fixture(429,12))
        self.assertNotIsInstance(caught.exception,QueuePause)

    def test_other_lease_states_stay_fenced(self):
        for status in ['claimed','completed','cancelled']:
            with self.subTest(status=status),self.assertRaises(RuntimeError) as caught:
                self.reserve(fixture(),status)
            self.assertNotIsInstance(caught.exception,QueuePause)

    def test_malformed_or_unsettled_evidence_stays_fenced(self):
        cases=[]
        for key,value in [('valid',True),('in_flight',True),('valid',None),('attempts',[]),('response',{})]:
            d=fixture();d[key]=value;cases.append(d)
        for key,value in [('state','in_flight'),('diagnostic',{}),('ticket','bad'),('finished_at',float('nan')),('number',True)]:
            d=fixture();d['attempts'][0][key]=value;cases.append(d)
        d=fixture();d['attempts'][0]['diagnostic']['http_status']='503';cases.append(d)
        for data in cases:
            with self.subTest(data=data),self.assertRaises(RuntimeError) as caught:self.reserve(data)
            self.assertNotIsInstance(caught.exception,QueuePause)

    def test_transport_preserves_intentional_pause_without_http(self):
        import asyncio
        from recognition_transport import SingleAttemptHTTP
        class HTTP:
            calls=0
            def request(self,*args,**kwargs):
                self.calls+=1
                raise AssertionError('HTTP must not execute')
            async def close(self): pass
        http=HTTP()
        transport=SingleAttemptHTTP(session_factory=lambda **kwargs:http,
            before_request=lambda:self.reserve(fixture()))
        async def run():
            token=transport.begin()
            try:
                with self.assertRaisesRegex(QueuePause,'^window_attempt_budget$'):
                    await transport.request('POST','https://provider.invalid')
            finally:
                transport.end(token)
                await transport.close()
        asyncio.run(run())
        self.assertEqual(http.calls,0)
