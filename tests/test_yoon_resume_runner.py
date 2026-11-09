import asyncio
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from worker.jobs.yoon_resume import recognize_resumable
from worker.jobs.yoon_resume_policy import initial_state,after_response
from worker.pipeline.models import Recognition

class FakeStore:
    def __init__(self,digest,outcomes):
        self.now=0;self.state=initial_state(0)|dict(session_started=0,session_requests=0,audio_sha256=digest,continuations=1)
        self.valid=set(range(4));self.outcomes=list(outcomes);self.calls=[];self.releases=[];self.completed=False
    def require_owner(self):return self.state
    def clock_state(self):return self.now,self.state
    def next_window(self):
        if len(self.valid)==479:return None,0
        return {'segment_index':next(i for i in range(479) if i not in self.valid)},max(0,self.state['next_allowed_at']-self.now)
    def reserve(self,index):
        assert index not in self.valid
        assert self.now>=self.state['next_allowed_at']
        self.calls.append((index,self.now));self.state['session_requests']+=1;self.state['requests']+=1
    def finish(self,result,diagnostic):
        valid=not result.error_type and not result.was_rate_limited
        if valid:self.valid.add(result.segment_index)
        self.state,reason=after_response(self.state,now=self.now,valid=valid,rate_limited=result.was_rate_limited,
            retry_seconds=diagnostic.get('retry_after_seconds'),retry_format=diagnostic.get('retry_after_format','absent'))
        return reason
    def release(self,reason):
        if self.completed:raise RuntimeError('already_complete')
        self.releases.append(reason)
    def summary(self):return {'valid':len(self.valid),'total':479},self.state
    def complete(self):
        assert len(self.valid)==479
        self.completed=True

class Session:
    def __init__(self,policy,before_request):self.before=before_request;self.attempts=[]
    async def close(self):pass

class RunnerTests(unittest.TestCase):
    def run_case(self,outcomes,mutate=lambda s:None):
        with tempfile.TemporaryDirectory() as d:
            audio=Path(d)/'synthetic';audio.write_bytes(b'synthetic')
            store=FakeStore(hashlib.sha256(b'synthetic').hexdigest(),outcomes);mutate(store)
            async def sleep(seconds):store.now+=seconds
            async def recognize(context,*,start_index,end_index,on_result,recognizer):
                self.assertEqual(start_index,end_index)
                recognizer.before();status,wait=store.outcomes.pop(0) if store.outcomes else (200,None)
                recognizer.attempts.append({'http_status':status,'retry_after_seconds':wait,'retry_after_format':'absent' if wait is None else 'delta_seconds'})
                on_result(Recognition(start_index*15,None,None,None,{'matches':[]} if status==200 else None,
                    False,start_index,was_rate_limited=status==429,error_type=None if status==200 else 'RateLimited'))
            with patch('worker.jobs.yoon_recognition.PrivateRecognitionSession',Session),patch('worker.pipeline.recognize.recognize_segment_range',recognize),patch('audio_segmenter.AudioSegmenter.get_audio_duration_ffprobe',return_value=7200),patch('worker.jobs.yoon_resume.asyncio.sleep',sleep):
                result=asyncio.run(recognize_resumable(store,audio))
            return store,result
    def test_skips_seeded_valid_windows_and_caps_requests(self):
        store,result=self.run_case([])
        self.assertEqual(result,'paused');self.assertEqual(len(store.calls),24)
        self.assertEqual([i for i,_ in store.calls],list(range(4,28)))
        self.assertEqual(store.releases,['workflow_request_budget'])
    def test_rate_limit_retries_same_unfinished_window_after_persisted_cooldown(self):
        store,_=self.run_case([(429,None),(200,None)])
        self.assertEqual(store.calls[:2],[(4,0),(4,300)])
        self.assertEqual(store.calls[2],(5,360))
        self.assertIn(4,store.valid)
    def test_long_provider_wait_pauses_without_truncation_or_second_request(self):
        store,_=self.run_case([(429,9000)])
        self.assertEqual(store.calls,[(4,0)]);self.assertEqual(store.state['next_allowed_at'],9000)
        self.assertEqual(store.releases,['cooldown_pending'])
    def test_four_consecutive_limits_pause_and_preserve_queue(self):
        store,_=self.run_case([(429,None)]*4)
        self.assertEqual(store.calls,[(4,0),(4,300),(4,900),(4,2100)])
        self.assertEqual(store.releases,['sustained_rate_limit_pause']);self.assertNotIn(4,store.valid)
    def test_elapsed_workflow_does_not_transmit(self):
        store,_=self.run_case([],lambda s:setattr(s,'now',3590))
        self.assertEqual(store.calls,[]);self.assertEqual(store.releases,['workflow_time_budget'])
    def test_last_allowed_request_can_complete_at_lifetime_limit(self):
        def setup(s):
            s.valid=set(range(455));s.state.update(requests=744,continuations=32)
        store,result=self.run_case([],setup)
        self.assertEqual(result,'complete');self.assertTrue(store.completed)
        self.assertEqual(len(store.calls),24);self.assertEqual(store.state['requests'],768)
        self.assertEqual(store.releases,[])
    def test_complete_evidence_finalizes_after_time_limit_without_request(self):
        def setup(s):s.valid=set(range(479));s.now=4000
        store,result=self.run_case([],setup)
        self.assertEqual(result,'complete');self.assertEqual(store.calls,[])

if __name__=='__main__':unittest.main()
