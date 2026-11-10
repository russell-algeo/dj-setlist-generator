"""Finite fractional/sample-aligned Sky Rivers & Adam Rose crop; no real recording/provider access."""
from array import array
from dataclasses import replace
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import wave
from worker.jobs.yoon_sources import SKY, JACKSON, DONALD, HALO, reviewed_source
from worker.jobs.yoon_once import prepare
from worker.jobs.yoon_resume_policy import initial_state, may_reserve


class SkySourceTests(unittest.TestCase):
    def test_pins_require_frames_and_exact_inventory(self):
        descriptor=dict(SKY.pins(),source_id=SKY.id,recognition_mode='resumable')
        self.assertEqual(reviewed_source(descriptor),SKY)
        for key in SKY.pins():
            value=descriptor.copy();value.pop(key)
            with self.subTest(missing=key),self.assertRaises(RuntimeError):reviewed_source(value)
        for change in [dict(source_start_frame=217628353),dict(source_end_frame=5333804353),
                       dict(source_sample_rate=48000),dict(source_start_seconds=4906),
                       dict(source_id=JACKSON.id),dict(recognition_mode='full')]:
            with self.subTest(change=change),self.assertRaises(RuntimeError):reviewed_source(descriptor|change)

    def test_integer_frames_pin_exact_geometry(self):
        self.assertEqual(SKY.end-SKY.start,9000)
        self.assertEqual((SKY.duration,SKY.windows),(9000,599))
        self.assertIs(type(SKY.windows),int)
        self.assertEqual(SKY.seek_seconds,4949)
        self.assertEqual(SKY.crop_filter_args(),['-af','atrim=start_sample=33804:end_sample=396933804,asetpts=PTS-STARTPTS'])
        self.assertEqual(SKY.start_frame*6+5548,1309713772)
        self.assertEqual(SKY.end_frame*6+5548,3691113772)
        for source in (JACKSON,DONALD,HALO):
            self.assertEqual(source.seek_seconds,source.start)
            self.assertEqual(source.crop_filter_args(),[])
            self.assertNotIn('source_start_frame',source.pins())
        self.assertEqual(may_reserve(initial_state(0)|dict(requests=599*8),now=0,
            session_started=0,session_requests=0,window_attempts=0,windows=SKY.windows),'lifetime_request_budget')

    def test_prepare_passes_exact_crop_without_fractional_seek(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);store=Mock();store.source=SKY
            store.claim.return_value='https://dropbox.com/SYNTHETIC'
            store.require_owner.return_value={'recognition_mode':'resumable'}
            def transcode(args,**kwargs):Path(args[-1]).write_bytes(b'synthetic')
            with patch('worker.jobs.yoon_once.fetch') as fetch, \
                 patch('worker.jobs.yoon_once.shutil.disk_usage',return_value=Mock(free=10**10)), \
                 patch('worker.jobs.yoon_once.subprocess.run',side_effect=transcode) as ffmpeg, \
                 patch('audio_segmenter.AudioSegmenter.get_audio_duration_ffprobe',return_value=9000):
                prepare(store,root)
            self.assertEqual(fetch.call_args.args[2],SKY)
            args=ffmpeg.call_args.args[0]
            self.assertEqual(args[args.index('-ss')+1],'4949')
            self.assertEqual(args[args.index('-t')+1],'9000')
            self.assertEqual(args[args.index('-af')+1],SKY.crop_filter_args()[1])

    def test_legacy_ffmpeg_arguments_remain_identical(self):
        for source in (JACKSON,DONALD,HALO):
            with self.subTest(source=source.id),tempfile.TemporaryDirectory() as d:
                root=Path(d);store=Mock();store.source=source
                store.claim.return_value='https://dropbox.com/SYNTHETIC'
                store.require_owner.return_value={'recognition_mode':'resumable'}
                def transcode(args,**kwargs):Path(args[-1]).write_bytes(b'synthetic')
                with patch('worker.jobs.yoon_once.fetch'), \
                     patch('worker.jobs.yoon_once.shutil.disk_usage',return_value=Mock(free=10**10)), \
                     patch('worker.jobs.yoon_once.subprocess.run',side_effect=transcode) as ffmpeg, \
                     patch('audio_segmenter.AudioSegmenter.get_audio_duration_ffprobe',return_value=source.duration):
                    prepare(store,root)
                old_args=['ffmpeg','-nostdin','-y','-v','error','-ss',str(source.start),
                    '-i',str(root/'source.wav'),'-t',str(source.duration),'-vn','-acodec','libmp3lame',
                    '-ab','128k','-ar','44100',str(root/'audio'/'input.mp3')]
                self.assertEqual(ffmpeg.call_args.args[0],old_args)
                self.assertEqual(ffmpeg.call_args.kwargs,dict(check=True,timeout=600,
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required for actual synthetic PCM verification')
    def test_ffmpeg_crop_preserves_exact_first_last_sample_and_count(self):
        # Same residual offset as Sky Rivers & Adam Rose; tiny synthetic master, no real audio.
        source=replace(SKY,start_frame=44100+33804,end_frame=88200+33804)
        samples=array('h',((i%60000)-30000 for i in range(4*44100)))
        with tempfile.TemporaryDirectory() as d:
            master=Path(d)/'master.wav';out=Path(d)/'crop.wav'
            with wave.open(str(master),'wb') as w:
                w.setparams((1,2,44100,0,'NONE','not compressed'));w.writeframes(samples.tobytes())
            subprocess.run(['ffmpeg','-nostdin','-y','-v','error','-ss',str(source.seek_seconds),
                '-i',str(master),*source.crop_filter_args(),'-t',str(source.duration),
                '-acodec','pcm_s16le',str(out)],check=True,timeout=20,capture_output=True)
            with wave.open(str(out),'rb') as w:
                self.assertEqual(w.getnframes(),44100)
                actual=w.readframes(w.getnframes())
            self.assertEqual(actual,samples[source.start_frame:source.end_frame].tobytes())
