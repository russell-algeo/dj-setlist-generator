"""Finite remaining catalog, exact pins, and synthetic joined preparation only."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import wave

from worker.jobs.yoon_sources import CATALOG, JACKSON, DONALD, HALO, GRISHA, HIGHKIN, DEEP_HOUSE, BRETT, SKY, reviewed_source
from worker.jobs.yoon_remaining_sources import JOINED_CATALOG, SINGLE_DEFINITIONS, assemble_remaining
from worker.jobs.yoon_highkin_source import Piece, JoinedSource, _assemble
from worker.jobs.yoon_once import prepare, validate_descriptor


def descriptor(source):
    result=dict(source.pins(),source_id=source.id,recognition_mode='resumable')
    result.update(source_urls=['https://dropbox.com/SYNTHETIC1','https://dropbox.com/SYNTHETIC2'] if source.id in JOINED_CATALOG else None)
    if source.id not in JOINED_CATALOG:
        result.pop('source_urls'); result['source_url']='https://dropbox.com/SYNTHETIC'
    return result


class RemainingSourceTests(unittest.TestCase):
    def test_exact_finite_inventory_and_existing_sources(self):
        self.assertEqual(len(CATALOG),27)
        self.assertEqual(len(SINGLE_DEFINITIONS),10)
        self.assertEqual(len(JOINED_CATALOG),9)
        self.assertEqual({CATALOG[x[0]].windows for x in SINGLE_DEFINITIONS},{359,479})
        self.assertEqual({x.windows for x in JOINED_CATALOG.values()},{359,479})
        self.assertEqual((SKY.duration,SKY.windows),(9000,599))
        for source in [JACKSON,DONALD,HALO,GRISHA,HIGHKIN,DEEP_HOUSE,BRETT,SKY]:
            self.assertIs(CATALOG[source.id],source)
        for forbidden in ['dylan-payne-sunday','kieran-ishimaru-sunday','christopher-mohn-monday','jake-mora-jackson-algeo-monday','arbitrary-source']:
            with self.assertRaises(RuntimeError):reviewed_source({'source_id':forbidden})
        self.assertEqual((DONALD.start,DONALD.end),(3371,10571))
        self.assertLess(DEEP_HOUSE.start,DONALD.end)

    def test_every_registered_pin_is_mandatory_and_exact(self):
        for source in [CATALOG[x[0]] for x in SINGLE_DEFINITIONS]+list(JOINED_CATALOG.values()):
            value=descriptor(source)
            with self.subTest(source=source.id):
                self.assertIs(reviewed_source(value),source)
                self.assertEqual(validate_descriptor(value),value.get('source_urls',value.get('source_url')))
                for key in source.pins():
                    bad=deepcopy(value);bad.pop(key)
                    with self.assertRaises(RuntimeError):reviewed_source(bad)
                for change in [dict(source_id='arbitrary-source'),dict(recognition_mode='full')]:
                    with self.assertRaises(RuntimeError):reviewed_source(value|change)
                if source.id in JOINED_CATALOG:
                    for key in source.pins()['source_parts'][0]:
                        bad=deepcopy(value);v=bad['source_parts'][0][key]
                        bad['source_parts'][0][key]=float(v) if isinstance(v,int) else v+'x'
                        with self.assertRaises(RuntimeError):reviewed_source(bad)
                    bad=deepcopy(value);bad['source_parts'].reverse()
                    with self.assertRaises(RuntimeError):reviewed_source(bad)
                    with self.assertRaises(RuntimeError):reviewed_source(value|{'arbitrary':True})
                    for urls in [[],['https://dropbox.com/A'],['https://dropbox.com/A']*2,['http://dropbox.com/A','https://dropbox.com/B'],['https://example.com/A','https://dropbox.com/B']]:
                        with self.assertRaises(RuntimeError):validate_descriptor(value|{'source_urls':urls})
                else:
                    for key in ['source_start_frame','source_end_frame','source_sample_rate']:
                        with self.assertRaises(RuntimeError):reviewed_source(value|{key:float(value[key])})

    def test_join_geometry_is_sample_conserving(self):
        for source in JOINED_CATALOG.values():
            with self.subTest(source=source.id):
                first,last=source.pieces
                self.assertEqual(first.end_frame,first.total_frames)
                self.assertEqual(last.start_frame,0)
                self.assertEqual(source.frames,source.duration*44100)
                for piece in source.pieces:
                    self.assertEqual((piece.sample_rate,piece.channels,piece.sample_width),(44100,2,3))
                    self.assertLess(piece.start_frame,piece.end_frame)
                    self.assertLessEqual(piece.end_frame,piece.total_frames)
        danny=JOINED_CATALOG['danny-daze-sunday']
        self.assertEqual(danny.pieces[-1].total_frames,309469824)

    def test_each_join_uses_exact_order_and_one_encode(self):
        for spec in JOINED_CATALOG.values():
            with self.subTest(source=spec.id),tempfile.TemporaryDirectory() as d:
                root=Path(d); store=Mock(); store.source=spec
                store.claim.return_value=descriptor(spec)['source_urls']
                store.require_owner.return_value={'recognition_mode':'resumable'}
                def fetch(url,path,piece):path.write_bytes(b'synthetic')
                def assemble(desc,paths,dest):
                    self.assertIs(reviewed_source(desc),spec)
                    self.assertEqual([p.name for p in paths],[p.filename for p in spec.pieces])
                    dest.write_bytes(b'joined');return {'audio_sha256':'c'*64}
                def transcode(args,**kwargs):Path(args[-1]).write_bytes(b'mp3')
                with patch('worker.jobs.yoon_once.fetch',side_effect=fetch) as fetched,patch('worker.jobs.yoon_once.assemble_remaining',side_effect=assemble) as assembled,patch('worker.jobs.yoon_once.subprocess.run',side_effect=transcode) as encoded,patch('worker.jobs.yoon_once.shutil.disk_usage',return_value=Mock(free=20_000_000_000)),patch('audio_segmenter.AudioSegmenter.get_audio_duration_ffprobe',return_value=spec.duration):
                    prepare(store,root)
                self.assertEqual(fetched.call_count,2);self.assertEqual(assembled.call_count,1);self.assertEqual(encoded.call_count,1)
                self.assertEqual([c.args[2] for c in fetched.call_args_list],list(spec.pieces))
                self.assertEqual(encoded.call_args.args[0][encoded.call_args.args[0].index('-i')+1],str(root/(spec.id+'-joined.wav')))
                self.assertTrue((root/'audio/input.mp3').exists())
                self.assertFalse(any((root/p.filename).exists() for p in spec.pieces))
                self.assertFalse((root/(spec.id+'-joined.wav')).exists())

    def test_pinned_reviewed_manifest_matches_all_sources(self):
        fixture=json.loads((Path(__file__).parent/'data/yoon_remaining_reviewed_spans.json').read_text())
        self.assertEqual(fixture['source_plan_sha256'],'88571c83552fd6031826c520639fe99e6fc64878d7af3ba1a9cae228ab6df326')
        self.assertEqual(fixture['timeline_sha256'],'f1cdc6c51c777725f202605d65e53dceeb05860a1fd1699705e411fdccea4d51')
        self.assertEqual(len(fixture['rows']),19)
        for r in fixture['rows']:
            spec=CATALOG[r['source_id']]
            with self.subTest(source=spec.id):
                self.assertEqual((spec.duration,spec.windows),(r['duration'],r['windows']))
                if spec.id in JOINED_CATALOG:
                    actual=[dict(filename=p.filename,sha256=p.sha256,bytes=p.bytes,start_frame=p.start_frame,end_frame=p.end_frame,total_frames=p.total_frames,sample_rate=p.sample_rate,channels=p.channels,bits=p.sample_width*8) for p in spec.pieces]
                else:
                    actual=[dict(filename=r['parts'][0]['filename'],sha256=spec.sha256,bytes=spec.bytes,start_frame=spec.start_frame,end_frame=spec.end_frame,total_frames=r['parts'][0]['total_frames'],sample_rate=spec.sample_rate,channels=2,bits=24)]
                self.assertEqual(actual,r['parts'])

    def test_join_failure_and_owner_loss_cleanup(self):
        spec=next(iter(JOINED_CATALOG.values()))
        for failure in ['download','assemble','encode','owner']:
            with self.subTest(phase=failure),tempfile.TemporaryDirectory() as d:
                root=Path(d);store=Mock();store.source=spec;store.claim.return_value=descriptor(spec)['source_urls']
                counter={'owners':0,'downloads':0}
                def owner():
                    counter['owners']+=1
                    if failure=='owner' and counter['owners']==3:raise RuntimeError('synthetic_owner_lost')
                    return {'recognition_mode':'resumable'}
                store.require_owner.side_effect=owner
                def fetch(url,path,piece):
                    counter['downloads']+=1;path.write_bytes(b'partial')
                    if failure=='download' and counter['downloads']==2:raise RuntimeError('synthetic_download')
                def assemble(desc,paths,dest):
                    dest.write_bytes(b'joined')
                    if failure=='assemble':raise RuntimeError('synthetic_assemble')
                    return {'audio_sha256':'c'*64}
                def encode(args,**kwargs):
                    Path(args[-1]).write_bytes(b'partial_mp3')
                    if failure=='encode':raise RuntimeError('synthetic_encode')
                with patch('worker.jobs.yoon_once.fetch',side_effect=fetch),patch('worker.jobs.yoon_once.assemble_remaining',side_effect=assemble),patch('worker.jobs.yoon_once.subprocess.run',side_effect=encode),patch('worker.jobs.yoon_once.shutil.disk_usage',return_value=Mock(free=20_000_000_000)),self.assertRaises(RuntimeError):
                    prepare(store,root)
                self.assertFalse(any((root/p.filename).exists() for p in spec.pieces))
                self.assertFalse((root/(spec.id+'-joined.wav')).exists());self.assertFalse((root/'audio/input.mp3').exists())
                self.assertEqual(store.write.call_args.args[0],{'status':'failed','reason':'preparation_failed'})

    def test_existing_path_is_preserved_and_never_fetched(self):
        spec=next(iter(JOINED_CATALOG.values()))
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/spec.pieces[0].filename;p.write_bytes(b'keep')
            store=Mock();store.source=spec;store.claim.return_value=descriptor(spec)['source_urls'];store.require_owner.return_value={'recognition_mode':'resumable'}
            with patch('worker.jobs.yoon_once.fetch') as fetch,self.assertRaisesRegex(RuntimeError,'preparation_paths_not_fresh'):prepare(store,root)
            fetch.assert_not_called();self.assertEqual(p.read_bytes(),b'keep')

    def test_sample_exact_pcm_seam_and_original_preservation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);originals=[];pieces=[];payloads=[]
            for i in range(2):
                path=root/f'synthetic-{i}.wav';payload=bytes((i*23+j)%256 for j in range(40*6));payloads.append(payload)
                with wave.open(str(path),'wb') as w:w.setparams((2,3,4,0,'NONE','not compressed'));w.writeframes(payload)
                originals.append(path);pieces.append(Piece(path.name,hashlib.sha256(path.read_bytes()).hexdigest(),path.stat().st_size,11 if i==0 else 0,40 if i==0 else 7,total_frames=40,sample_rate=4))
            before=[p.read_bytes() for p in originals];spec=JoinedSource('synthetic-only',tuple(pieces),'synthetic')
            result=_assemble(spec,originals,root/'joined.wav')
            with wave.open(str(root/'joined.wav'),'rb') as w:self.assertEqual(w.readframes(w.getnframes()),payloads[0][11*6:]+payloads[1][:7*6])
            self.assertEqual(result['frames'],36);self.assertEqual([p.read_bytes() for p in originals],before)
            with self.assertRaises(RuntimeError):assemble_remaining({'source_id':'synthetic-only'},originals,root/'forbidden.wav')
            self.assertFalse((root/'forbidden.wav').exists())
