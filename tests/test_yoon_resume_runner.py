import asyncio
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from worker.jobs.yoon_resume import recognize_resumable
from worker.jobs.yoon_resume_policy import initial_state
from worker.pipeline.models import Recognition

class FakeStore:
    def __init__(self,digest):
        self.now=0;self.state=initial_state(0)|dict(session_started=0,session_requests=0,audio_sha256=digest,continuations=1)
        self.valid=set(range(4));self.calls=[];self.completed=False;self.tickets={};self.finished=[];self.extractions=[]
    def require_owner(self):return self.state
    def check_owner(self): self.require_owner()
    def clock_state(self):return self.now,self.state
    def next_windows(self,slot_index=0,limit=10):
        return [{'segment_index':i} for i in range(479) if i not in self.valid and (i//20)%2==slot_index][:limit],0
    def reserve(self,index,slot_index=0):
        assert index not in self.valid and (index//20)%2==slot_index
        ticket=f'{index}:{len(self.calls)}';self.tickets[index]=ticket
        self.calls.append(index);self.state['session_requests']+=1;self.state['requests']+=1
        return ticket
    def finish(self,result,ticket,delay_seconds):
        assert self.tickets[result.segment_index]==ticket
        assert result.is_valid
        self.valid.add(result.segment_index);self.finished.append((result.segment_index,ticket,delay_seconds))

class Session:
    instances=[]
    def __init__(self,**kwargs):self.options=kwargs;self.closed=False;self.batches=[];self.instances.append(self)
    async def close(self):self.closed=True
    async def recognize_segment_with_backoff(self,segment):
        raise AssertionError("Batch-model fixture must use recognize_batch")
    async def recognize_batch(self,segments,**kwargs):
        self.batches.append([s['index'] for s in segments])
        # Reserve concurrent attempts before finishing any, like the shared engine.
        admitted=[(s,self.options['before_attempt'](s)) for s in segments]
        for s,ticket in admitted:
            result=Recognition(s['timestamp'],None,None,None,{'matches':[]},False,s['index'],http_status=200)
            self.options['on_attempt'](result,ticket,0)
        return []

class RunnerTests(unittest.TestCase):
    def run_case(self,slot_index=0,mutate=lambda s:None):
        with tempfile.TemporaryDirectory() as d:
            audio=Path(d)/'synthetic';audio.write_bytes(b'synthetic')
            store=FakeStore(hashlib.sha256(b'synthetic').hexdigest());mutate(store)
            async def extract(_self,_audio,start,end,_executor):
                store.extractions.append((start,end))
                paths=[]
                for index in range(start,end):
                    file=Path(d)/str(index);file.write_bytes(b'segment')
                    paths.append(dict(index=index,timestamp=index*15,file=file))
                return paths
            with patch('track_recognizer.TrackRecognizer',Session),patch('audio_segmenter.AudioSegmenter.create_segments_batch',extract),patch('audio_segmenter.AudioSegmenter.get_audio_duration_ffprobe',return_value=7200):
                result=asyncio.run(recognize_resumable(store,audio,slot_index=slot_index))
            return store,result
    def test_skips_seeded_windows_and_processes_more_than_24(self):
        store,result=self.run_case()
        self.assertEqual(result,'slot_complete')
        self.assertEqual(store.calls,[i for i in range(4,479) if (i//20)%2==0])
        self.assertGreater(len(store.calls),24)
        self.assertTrue(any(end-start>1 for start,end in store.extractions))
        self.assertTrue(Session.instances[-1].closed)
        self.assertTrue(Session.instances[-1].options['quiet'])
    def test_other_slot_does_not_touch_peers_or_release_global_owner(self):
        store,result=self.run_case(1)
        self.assertEqual(store.calls,[i for i in range(4,479) if (i//20)%2==1])
        self.assertEqual(result,'slot_complete')
    def test_elapsed_workflow_does_not_transmit(self):
        store,result=self.run_case(mutate=lambda s:setattr(s,'now',3590))
        self.assertEqual(store.calls,[]);self.assertEqual(result,'paused')
    def test_digest_drift_rejected_before_engine_construction(self):
        with self.assertRaisesRegex(RuntimeError,'private_audio_digest_mismatch'):
            self.run_case(mutate=lambda s:s.state.update(audio_sha256='bad'))

if __name__=='__main__':unittest.main()

class ActualEnginePauseTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_store_pause_reaches_runner_without_http_or_fake_response(self):
        from types import SimpleNamespace
        from track_recognizer import TrackRecognizer
        from recognition_transport import SingleAttemptHTTP
        from worker.jobs.yoon_resume_store import QueuePause
        calls=[];receipts=[]
        class HTTP:
            def request(self,*args,**kwargs):
                calls.append(True)
                raise AssertionError('must not transmit')
        def reserve(segment):
            raise QueuePause('window_attempt_budget')
        engine=TrackRecognizer(before_attempt=reserve,on_attempt=lambda *args:receipts.append(args),quiet=True)
        engine.transport=SingleAttemptHTTP(session_factory=lambda **kwargs:HTTP(),before_request=engine.before_request)
        async def recognize(_):return await engine.transport.request('POST','https://provider.invalid')
        engine.shazam=SimpleNamespace(recognize=recognize)
        with self.assertRaisesRegex(QueuePause,'window_attempt_budget'):
            await engine.recognize_batch([dict(index=8,timestamp=120,file=Path('synthetic'))],cleanup_files=False)
        self.assertEqual(calls,[]);self.assertEqual(receipts,[])
