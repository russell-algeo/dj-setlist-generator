"""Offline finite Halo source regression, with synthetic audio/provider responses."""
import asyncio
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from worker.jobs.yoon_sources import HALO, JACKSON, DONALD, reviewed_source
from worker.jobs.yoon_resume_policy import initial_state, may_reserve
from worker.jobs.yoon_resume import recognize_resumable
from worker.jobs.yoon_once import prepare
from worker.scheduler import build_scheduler_plan
from test_yoon_resume_runner import Session


class HaloSourceTests(unittest.TestCase):
    def test_exact_pins_geometry_and_budget(self):
        self.assertEqual((HALO.start,HALO.end,HALO.duration,HALO.windows),(10320,15720,5400,359))
        self.assertEqual((HALO.sha256,HALO.bytes),(JACKSON.sha256,JACKSON.bytes))
        self.assertEqual((JACKSON.windows,DONALD.windows),(479,479))
        descriptor=dict(HALO.pins(),source_id=HALO.id,recognition_mode='resumable')
        self.assertEqual(reviewed_source(descriptor),HALO)
        for change in [dict(source_id=JACKSON.id),dict(source_end_seconds=15721),
                       dict(source_start_seconds=10319),dict(recognition_mode='full')]:
            with self.assertRaises(RuntimeError):reviewed_source(descriptor|change)
        base=dict(now=0,session_started=0,session_requests=0,window_attempts=0,windows=HALO.windows)
        self.assertIsNone(may_reserve(initial_state(0)|dict(requests=359*8-1),**base))
        self.assertEqual(may_reserve(initial_state(0)|dict(requests=359*8),**base),'lifetime_request_budget')
        with patch.dict('os.environ',{'RECOGNITION_SLOT_COUNT_REQUESTED':'8'}):
            self.assertEqual(build_scheduler_plan(HALO.windows).slot_count,8)

    def test_prepare_uses_halo_crop(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);store=Mock();store.source=HALO
            store.claim.return_value='https://dropbox.com/SYNTHETIC'
            store.require_owner.return_value={'recognition_mode':'resumable'}
            def transcode(args,**kwargs):Path(args[-1]).write_bytes(b'synthetic')
            with patch('worker.jobs.yoon_once.fetch') as fetch, \
                 patch('worker.jobs.yoon_once.shutil.disk_usage',return_value=Mock(free=10**10)), \
                 patch('worker.jobs.yoon_once.subprocess.run',side_effect=transcode) as ffmpeg, \
                 patch('audio_segmenter.AudioSegmenter.get_audio_duration_ffprobe',return_value=5400):
                prepare(store,root)
            self.assertEqual(fetch.call_args.args[2],HALO)
            args=ffmpeg.call_args.args[0]
            self.assertEqual(args[args.index('-ss')+1],'10320')
            self.assertEqual(args[args.index('-t')+1],'5400')

    def test_shared_runner_processes_exactly_359_windows(self):
        class Store:
            def __init__(self):
                self.state=initial_state(0)|dict(source_id=HALO.id,session_started=0,session_requests=0,
                    audio_sha256=hashlib.sha256(b'synthetic').hexdigest())
                self.valid=set();self.calls=[]
            def require_owner(self):return self.state
            def check_owner(self): self.require_owner()
            def clock_state(self):return 0,self.state
            def next_windows(self,slot_index,limit):
                return [{'segment_index':i} for i in range(HALO.windows) if i not in self.valid][:limit],0
            def reserve(self,index,slot_index):
                self.calls.append(index);self.state['requests']+=1;return str(index)
            def finish(self,result,ticket,delay):self.valid.add(result.segment_index)
        with tempfile.TemporaryDirectory() as d:
            audio=Path(d)/'audio';audio.write_bytes(b'synthetic');store=Store()
            async def extract(_self,_audio,start,end,_executor):
                rows=[]
                for i in range(start,end):
                    file=Path(d)/str(i);file.write_bytes(b'segment')
                    rows.append(dict(index=i,timestamp=i*15,file=file))
                return rows
            with patch('track_recognizer.TrackRecognizer',Session), \
                 patch('audio_segmenter.AudioSegmenter.create_segments_batch',extract), \
                 patch('audio_segmenter.AudioSegmenter.get_audio_duration_ffprobe',return_value=5400):
                self.assertEqual(asyncio.run(recognize_resumable(store,audio)),'slot_complete')
            self.assertEqual(store.calls,list(range(359)))
            self.assertTrue(Session.instances[-1].closed)
