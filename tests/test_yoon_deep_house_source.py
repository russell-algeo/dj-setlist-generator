"""Offline finite source tests. No real audio, network or database calls."""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
import wave
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch
from worker.jobs.yoon_sources import DEEP_HOUSE as D, DONALD, reviewed_source
from worker.jobs.yoon_once import prepare, validate_descriptor

class DeepHouseTests(unittest.TestCase):
    def test_geometry_and_unchanged_donald(self):
        self.assertEqual((D.duration,D.windows,D.seek_seconds),(5400,359,10364))
        self.assertEqual((D.start_frame,D.end_frame,D.sample_rate),(457081056,695221056,44100))
        self.assertEqual(D.end_frame-D.start_frame,238140000)
        self.assertEqual((DONALD.start,DONALD.end,DONALD.duration),(3371,10571,7200))
        self.assertAlmostEqual(DONALD.end-D.start,206.350204082)
        self.assertEqual(D.sha256,DONALD.sha256)
        self.assertIn('Neither handoff has been acoustically verified',D.bounds)
        self.assertEqual(D.crop_filter_args(),['-af','atrim=start_sample=28656:end_sample=238168656,asetpts=PTS-STARTPTS'])
    def test_exact_identity_and_wrong_urls(self):
        d=dict(D.pins(),source_id=D.id,recognition_mode='resumable',source_url='https://dropbox.com/SYNTHETIC')
        self.assertIs(reviewed_source(d),D)
        for key in D.pins():
            bad=d.copy();bad.pop(key)
            with self.assertRaises(RuntimeError):reviewed_source(bad)
        for change in [dict(source_start_frame=457081057),dict(source_sha256='0'*64),dict(source_start_frame=float(D.start_frame)),dict(source_sample_rate=48000),dict(recognition_mode='full')]:
            with self.assertRaises(RuntimeError):reviewed_source(d|change)
        for url in ['https://evil.invalid/x','https://dropbox.com@evil.invalid/x','http://dropbox.com/x']:
            with self.assertRaises(RuntimeError):validate_descriptor(d|dict(source_url=url))
    def test_prepare_uses_unchanged_encoder(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);store=Mock();store.source=D;store.claim.return_value='https://dropbox.com/SYNTHETIC';store.require_owner.return_value={'recognition_mode':'resumable'}
            def encode(args,**kw):Path(args[-1]).write_bytes(b'synthetic analysis')
            with patch('worker.jobs.yoon_once.fetch') as fetch,patch('worker.jobs.yoon_once.shutil.disk_usage',return_value=Mock(free=10**10)),patch('worker.jobs.yoon_once.subprocess.run',side_effect=encode) as run,patch('audio_segmenter.AudioSegmenter.get_audio_duration_ffprobe',return_value=5400):
                prepare(store,root)
            self.assertIs(fetch.call_args.args[2],D)
            args=run.call_args.args[0];self.assertEqual(args[args.index('-ss')+1],'10364');self.assertEqual(args[args.index('-t')+1],'5400');self.assertEqual(args[args.index('-af')+1],D.crop_filter_args()[1])
    @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg unavailable')
    def test_sample_exact_24_bit_stereo_and_original_preservation(self):
        src=replace(D,start_frame=44100+28656,end_frame=88200+28656)
        data=b''.join((i%100000).to_bytes(3,'little')+((i+17)%100000).to_bytes(3,'little') for i in range(4*44100))
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'original.wav';out=Path(td)/'analysis.wav'
            with wave.open(str(p),'wb') as w:w.setparams((2,3,44100,0,'NONE','not compressed'));w.writeframes(data)
            before=p.read_bytes()
            subprocess.run(['ffmpeg','-nostdin','-v','error','-ss',str(src.seek_seconds),'-i',str(p),*src.crop_filter_args(),'-t',str(src.duration),'-acodec','pcm_s24le',str(out)],check=True,capture_output=True)
            with wave.open(str(out),'rb') as w:self.assertEqual(w.getnframes(),44100);self.assertEqual(w.readframes(44100),data[src.start_frame*6:src.end_frame*6])
            self.assertEqual(p.read_bytes(),before)
