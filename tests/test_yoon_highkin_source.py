"""Offline only: no original recordings, DB, network or provider calls."""
import copy
from contextlib import contextmanager
from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import wave

from worker.jobs.yoon_highkin_source import HIGHKIN, Piece, JoinedSource, reviewed_highkin, _assemble
from worker.jobs.yoon_sources import reviewed_source
from worker.jobs.yoon_spotify_enrich import Store
from worker.jobs.yoon_once import validate_descriptor, prepare


class HighkinTests(unittest.TestCase):
    def descriptor(self):
        return dict(HIGHKIN.pins(), source_id=HIGHKIN.id, recognition_mode='resumable')

    def test_exact_geometry_and_live_fail_closed(self):
        self.assertEqual((HIGHKIN.frames, HIGHKIN.duration, HIGHKIN.windows), (317520000,7200,479))
        self.assertEqual(HIGHKIN.pieces[0].end_frame-HIGHKIN.pieces[0].start_frame, 4080*44100)
        self.assertEqual(HIGHKIN.pieces[1].end_frame,3120*44100)
        self.assertIs(reviewed_highkin(self.descriptor()),HIGHKIN)
        self.assertIs(reviewed_source(self.descriptor()), HIGHKIN)
        with self.assertRaises(RuntimeError): Store({},'1','1','highkin-unreviewed')

    def test_exact_pins_fail_closed(self):
        mutations = [lambda d:d['source_parts'].reverse(),
            lambda d:d['source_parts'].pop(),
            lambda d:d['source_parts'][0].update(start_frame=535148353),
            lambda d:d['source_parts'][0].update(start_frame=535148352.0),
            lambda d:d['source_parts'][1].update(start_frame=False),
            lambda d:d['source_parts'][1].update(sample_rate=48000),
            lambda d:d['source_parts'][0].update(sha256='0'*64),
            lambda d:d.update(source_total_frames=317520001),
            lambda d:d.update(source_id='jackson-sunday'),
            lambda d:d.update(recognition_mode='full'),
            lambda d:d.update(source_url='not-a-locator'),
            lambda d:d.update(source_start_frame=0)]
        for mutate in mutations:
            d=self.descriptor();mutate(d)
            with self.subTest(d=d),self.assertRaises(RuntimeError):reviewed_highkin(d)
        for k in self.descriptor():
            d=self.descriptor();d.pop(k)
            with self.subTest(missing=k),self.assertRaises(RuntimeError):reviewed_highkin(d)

    def test_two_locators_are_finite_and_ordered(self):
        urls=['https://dropbox.com/SYNTHETIC_A','https://dropbox.com/SYNTHETIC_B']
        self.assertEqual(validate_descriptor(self.descriptor()|dict(source_urls=urls)),urls)
        for invalid in (None,urls[:1],urls+[urls[0]],urls[::-1][:1],
                        [urls[0],urls[0]],['https://example.invalid/x',urls[1]],
                        ['https://dropbox.com@evil.invalid/x',urls[1]]):
            with self.subTest(invalid=invalid),self.assertRaises(RuntimeError):
                validate_descriptor(self.descriptor()|dict(source_urls=invalid))
        # URLs carry no identity claim: reversed locator bytes fail per-piece fetch SHA.

    def test_prepare_joins_before_one_encode_and_preserves_shared_shape(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);store=Mock();store.source=HIGHKIN
            urls=['https://dropbox.com/SYNTHETIC_A','https://dropbox.com/SYNTHETIC_B']
            store.claim.return_value=urls
            store.require_owner.return_value={'recognition_mode':'resumable'}
            def fetched(url,path,piece):path.write_bytes(b'synthetic original')
            def joined(descriptor,paths,out):
                self.assertEqual([p.name for p in paths],[p.filename for p in HIGHKIN.pieces])
                out.write_bytes(b'synthetic PCM');return {'audio_sha256':'c'*64}
            def encoded(args,**kwargs):
                self.assertEqual(args.count('-i'),1)
                self.assertNotIn('-ss',args);self.assertNotIn('-t',args)
                self.assertTrue(Path(args[args.index('-i')+1]).exists())
                Path(args[-1]).write_bytes(b'synthetic MP3')
            with patch('worker.jobs.yoon_once.fetch',side_effect=fetched) as fetch, \
                 patch('worker.jobs.yoon_once.assemble_highkin',side_effect=joined) as assembly, \
                 patch('worker.jobs.yoon_once.subprocess.run',side_effect=encoded) as ffmpeg, \
                 patch('worker.jobs.yoon_once.shutil.disk_usage',return_value=Mock(free=13_000_000_000)), \
                 patch('audio_segmenter.AudioSegmenter.get_audio_duration_ffprobe',return_value=7200):
                prepare(store,root)
            self.assertEqual([c.args[2] for c in fetch.call_args_list],list(HIGHKIN.pieces))
            self.assertEqual(ffmpeg.call_count,1);self.assertEqual(assembly.call_count,1)
            self.assertEqual(store.write.call_args.args[0]['joined_pcm_sha256'],'c'*64)
            self.assertTrue((root/'audio'/'input.mp3').exists())
            self.assertFalse((root/'highkin-joined.wav').exists())
            self.assertTrue(all(not (root/p.filename).exists() for p in HIGHKIN.pieces))

    def test_prepare_download_failure_never_encodes_and_cleans_copies(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);store=Mock();store.source=HIGHKIN
            store.claim.return_value=['https://dropbox.com/SYNTHETIC_A','https://dropbox.com/SYNTHETIC_B']
            store.require_owner.return_value={'recognition_mode':'resumable'}
            def bad(url,path,piece):
                path.write_bytes(b'bad');raise RuntimeError('source_digest_mismatch')
            with patch('worker.jobs.yoon_once.fetch',side_effect=bad), \
                 patch('worker.jobs.yoon_once.subprocess.run') as ffmpeg, \
                 patch('worker.jobs.yoon_once.shutil.disk_usage',return_value=Mock(free=13_000_000_000)):
                with self.assertRaisesRegex(RuntimeError,'source_digest_mismatch'):prepare(store,root)
            ffmpeg.assert_not_called()
            self.assertEqual(store.write.call_args.args[0]['status'],'failed')
            self.assertFalse((root/'audio'/'input.mp3').exists())
            self.assertTrue(all(not (root/p.filename).exists() for p in HIGHKIN.pieces))

    def test_prepare_preexisting_original_is_not_overwritten_or_deleted(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);existing=root/HIGHKIN.pieces[0].filename
            existing.write_bytes(b'preserve original')
            store=Mock();store.source=HIGHKIN
            store.claim.return_value=['https://dropbox.com/SYNTHETIC_A','https://dropbox.com/SYNTHETIC_B']
            store.require_owner.return_value={'recognition_mode':'resumable'}
            with patch('worker.jobs.yoon_once.fetch') as fetch:
                with self.assertRaisesRegex(RuntimeError,'preparation_paths_not_fresh'):prepare(store,root)
            fetch.assert_not_called();self.assertEqual(existing.read_bytes(),b'preserve original')

    def test_real_claim_returns_legacy_or_ordered_highkin_locators(self):
        from worker.jobs.yoon_resume_store import ResumeStore
        from worker.jobs.yoon_resume_policy import initial_state
        from worker.jobs.yoon_sources import JACKSON, DONALD, HALO, GRISHA
        for source in (JACKSON,DONALD,HALO,GRISHA,HIGHKIN):
            with self.subTest(source=source.id):
                urls=['https://dropbox.com/SYNTHETIC_A','https://dropbox.com/SYNTHETIC_B']
                descriptor=dict(source.pins(),source_id=source.id,recognition_mode='resumable')
                descriptor.update(source_urls=urls) if source==HIGHKIN else descriptor.update(source_url=urls[0])
                state=initial_state(0)|dict(initialization_mode='fresh',provenance_seeded=source==JACKSON)
                row=dict(status='private_resume_pending',db_now=0,source_metadata={'yoon_fixed_input':descriptor})
                cur=Mock();cur.fetchone.side_effect=[{'marker':'private-recognition-retention-v1'},{'n':0},{'n':0},{'n':0}]
                @contextmanager
                def locked(**kwargs):yield cur,row,state
                store=ResumeStore('12345678-1234-1234-1234-123456789012','1','1',connect=Mock())
                store.source=source;store.locked=locked;store.save_state=Mock()
                self.assertEqual(store.claim(),urls if source==HIGHKIN else urls[0])
                store.save_state.assert_called_once()
                self.assertEqual(state['status'],'preparing')

    def fixture(self, root):
        # Preserve real duration/seam geometry at reduced sample rate, stereo 24-bit.
        paths=[];pieces=[];payloads=[]
        for i, (start,end) in enumerate(((92000,500000),(0,312000))):
            path=root/f'part{i}.wav'
            payload=b''.join((n%65536).to_bytes(3,'little')+((n+i+7)%65536).to_bytes(3,'little') for n in range(500000))
            with wave.open(str(path),'wb') as w:
                w.setparams((2,3,100,0,'NONE','not compressed'));w.writeframes(payload)
            data=path.read_bytes();paths.append(path);payloads.append(payload)
            pieces.append(Piece(path.name,hashlib.sha256(data).hexdigest(),len(data),start,end,500000,100,2,3))
        return JoinedSource('synthetic',tuple(pieces),'synthetic'),paths,payloads

    def test_pcm_seam_crossing_window_and_input_preservation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source,paths,payloads=self.fixture(root)
            before=[p.read_bytes() for p in paths];out=root/'joined.wav'
            result=_assemble(source,paths,out)
            with wave.open(str(out),'rb') as w:
                self.assertEqual(w.getnframes(),720000);actual=w.readframes(720000)
            expected=payloads[0][92000*6:]+payloads[1][:312000*6]
            self.assertEqual(actual,expected)
            self.assertEqual(actual[407999*6:408001*6],payloads[0][-6:]+payloads[1][:6])
            # Window 271 = 4065..4095 crosses the seam; 270/272 only touch it.
            self.assertEqual(actual[406500*6:409500*6],payloads[0][-1500*6:]+payloads[1][:1500*6])
            self.assertEqual([i for i in range(479) if i*15<4080<i*15+30],[271])
            self.assertEqual(result['expected_windows'],479)
            self.assertEqual(result['audio_sha256'],hashlib.sha256(out.read_bytes()).hexdigest())
            self.assertEqual([p.read_bytes() for p in paths],before)
            with self.assertRaisesRegex(RuntimeError,'destination_must_be_new'):_assemble(source,paths,out)

    def test_failure_cases_create_no_derivative(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source,paths,_=self.fixture(root);out=root/'out.wav'
            cases=[(source,paths[::-1]),(source,paths[:1]),(source,[paths[0],paths[0]])]
            for changes in (dict(sha256='0'*64),dict(bytes=1),dict(start_frame=-1),
                            dict(end_frame=500001),dict(sample_rate=101),dict(channels=1),
                            dict(sample_width=2),dict(total_frames=500001)):
                cases.append((replace(source,pieces=(replace(source.pieces[0],**changes),source.pieces[1])),paths))
            for spec,inputs in cases:
                with self.subTest(spec=spec),self.assertRaises(RuntimeError):_assemble(spec,inputs,out)
                self.assertFalse(out.exists())
            with self.assertRaises(RuntimeError):_assemble(source,paths,paths[0])
            # Failure after exclusive creation removes only the new derivative.
            with patch('wave.Wave_read.readframes',return_value=b''):
                with self.assertRaisesRegex(RuntimeError,'source_truncated'):_assemble(source,paths,out)
            self.assertFalse(out.exists())


if __name__ == '__main__': unittest.main()
