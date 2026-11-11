"""Finite corrected-source identities, predecessor preservation, fresh windows."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import tempfile
from worker.jobs.yoon_sources import CATALOG, VERSION_CATALOG, reviewed_source
from worker.jobs.yoon_highkin_source import JoinedSource
from worker.jobs.yoon_once import validate_descriptor, prepare
from worker.jobs.yoon_version_sources import VERSION_ENRICHMENT_RUNS
from worker.jobs.yoon_spotify_enrich import REGISTERED_ENRICHMENT_RUNS, REVIEWED_RUNS, validate, digest
from tests.test_yoon_enrichment_registrations import fixture

DATA = json.loads((Path(__file__).parent/'data/yoon_version_reviewed_sources.json').read_text())

def descriptor(source):
    return dict(source.pins(), source_id=source.id, recognition_mode='resumable',
        **({'source_urls':['https://dropbox.com/SYNTHETIC_A','https://dropbox.com/SYNTHETIC_B']}
           if isinstance(source,JoinedSource) else {'source_url':'https://dropbox.com/SYNTHETIC'}))

class VersionSourcesTests(unittest.TestCase):
    def test_all_27_predecessor_pins_unchanged(self):
        self.assertEqual(len(DATA['legacy_sources']),27)
        self.assertEqual({k:v.pins() for k,v in CATALOG.items() if k not in VERSION_CATALOG},DATA['legacy_sources'])
        self.assertEqual(len(CATALOG),37)
        self.assertEqual(len(VERSION_CATALOG),10)
        self.assertEqual(sum(x.windows for x in VERSION_CATALOG.values()),3830)
        self.assertEqual(sum(isinstance(x,JoinedSource) for x in VERSION_CATALOG.values()),3)

    def test_each_new_identity_and_exact_plan_pins(self):
        ids=[]
        for plan in DATA['plans']:
            source=VERSION_CATALOG[plan['source_id']]
            self.assertEqual(source.pins(),{k:v for k,v in plan['descriptor_without_private_locator'].items() if k not in ('source_id','recognition_mode')})
            proposed=plan['proposed_ids']; ids.extend(proposed.values())
            self.assertFalse(set(proposed.values()) & set(plan['predecessor_ids'].values()))
            self.assertEqual(VERSION_ENRICHMENT_RUNS[proposed['run_id']],dict(source_id=source.id,submission_id=proposed['submission_id'],target_set_id=proposed['set_id']))
        self.assertEqual(len(set(ids)),40)
        self.assertEqual(set(VERSION_ENRICHMENT_RUNS),{p['proposed_ids']['run_id'] for p in DATA['plans']})
        self.assertTrue(set(VERSION_ENRICHMENT_RUNS) <= REVIEWED_RUNS)

    def test_every_pin_and_type_required_and_no_unknown_keys(self):
        for source in VERSION_CATALOG.values():
            value=descriptor(source)
            self.assertIs(reviewed_source(value),source)
            validate_descriptor(value)
            for key,original in source.pins().items():
                changed=copy.deepcopy(value);changed.pop(key)
                with self.subTest(source=source.id,key=key),self.assertRaises(RuntimeError):reviewed_source(changed)
                changed=copy.deepcopy(value);changed[key]=str(original) if not isinstance(original,str) else original+'X'
                with self.assertRaises(RuntimeError):reviewed_source(changed)
            for patch_value in ({'unknown':True},{'recognition_mode':'full'},{'source_id':'arbitrary-mean-gaps-v2'}):
                with self.assertRaises(RuntimeError):reviewed_source(value|patch_value)
            if isinstance(source,JoinedSource):
                changed=copy.deepcopy(value);changed['source_parts'][0]['start_frame']=float(changed['source_parts'][0]['start_frame'])
                with self.assertRaises(RuntimeError):reviewed_source(changed)
                with self.assertRaises(RuntimeError):validate_descriptor(value|{'source_urls':['https://dropbox.com/SAME']*2})
            else:
                with self.assertRaises(RuntimeError):reviewed_source(value|{'source_start_frame':float(value['source_start_frame'])})

    def test_fresh_metadata_validation_no_v1_evidence_reuse(self):
        # Reuse the complete, synthetic finite-run fixture builder with the new
        # finite map, then prove its original source/identity cannot be relabeled.
        with patch('tests.test_yoon_enrichment_registrations.ADDITIONAL_ENRICHMENT_RUNS', REGISTERED_ENRICHMENT_RUNS):
            for plan in DATA['plans']:
                run=plan['proposed_ids']['run_id'];args=fixture(run)
                self.assertEqual(validate(*args),args[1]['clustered_setlist'])
                args[0]['source_metadata']['yoon_fixed_input']=descriptor(CATALOG[plan['source_id']])
                args[3]['source_digest']=digest(args[0]['source_metadata']['yoon_fixed_input'])
                self.assertEqual(validate(*args),args[1]['clustered_setlist'])
                for field in ('source_id','source_pins','origin','provenance_seeded'):
                    changed=copy.deepcopy(args)
                    changed[1][field]=({'valid_windows':3830} if field=='origin' else True if field=='provenance_seeded' else plan['predecessor_source_id'] if field=='source_id' else DATA['legacy_sources'][plan['predecessor_source_id']])
                    with self.subTest(run=run,field=field),self.assertRaises(RuntimeError):validate(*changed)

    def test_all_3830_physical_windows_change_and_conserve_samples(self):
        def spans(parts, index):
            start,end=index*15*44100,(index*15+30)*44100
            result=[];offset=0
            for name,left,right in parts:
                length=right-left; a,b=max(start,offset),min(end,offset+length)
                if a<b:result.append((name,left+a-offset,left+b-offset))
                offset+=length
            return result
        def parts(source, plan):
            if isinstance(source,JoinedSource):return [(p.filename,p.start_frame,p.end_frame) for p in source.pieces]
            return [(plan['parts'][0]['filename'],source.start_frame,source.end_frame)]
        count=0
        for plan in DATA['plans']:
            new=VERSION_CATALOG[plan['source_id']];old=CATALOG[plan['predecessor_source_id']]
            before,after=parts(old,plan),parts(new,plan)
            old_windows={tuple(spans(before,i)) for i in range(old.windows)}
            self.assertEqual(before[0][1]-after[0][1],2684062)
            self.assertEqual((new.duration,new.windows),(old.duration,old.windows))
            for i in range(new.windows):
                window=spans(after,i);count+=1
                self.assertEqual(sum(b-a for _,a,b in window),30*44100)
                self.assertNotIn(tuple(window),old_windows)
        self.assertEqual(count,3830)

    def test_half_frame_rule_and_exact_seven_single_crops(self):
        from fractions import Fraction
        from dataclasses import replace
        import shutil,subprocess,wave
        if not shutil.which('ffmpeg'):self.skipTest('ffmpeg unavailable')
        for plan in DATA['plans']:
            for part,exact in zip(plan['parts'],plan['exact_projected_endpoints']):
                for key,exact_key in [('start_frame','exact_start_frame'),('end_frame_exclusive','exact_end_frame_exclusive')]:
                    value=exact[exact_key];rational=Fraction(value['numerator'],value['denominator'])
                    self.assertEqual(part[key],(rational.numerator*2+rational.denominator)//(2*rational.denominator))
                    self.assertLessEqual(abs(part[key]-rational),Fraction(1,2))
            source=VERSION_CATALOG[plan['source_id']]
            if isinstance(source,JoinedSource):continue
            residual=source.start_frame%44100;spec=replace(source,start_frame=44100+residual,end_frame=88200+residual)
            with tempfile.TemporaryDirectory() as d:
                root=Path(d);master=root/'master.wav';out=root/'crop.wav'
                frames=b''.join((i%65536).to_bytes(2,'little') for i in range(4*44100))
                with wave.open(str(master),'wb') as w:w.setparams((1,2,44100,0,'NONE','not compressed'));w.writeframes(frames)
                subprocess.run(['ffmpeg','-nostdin','-v','error','-ss',str(spec.seek_seconds),'-i',str(master),*spec.crop_filter_args(),'-t','1','-acodec','pcm_s16le',str(out)],check=True,capture_output=True)
                with wave.open(str(out),'rb') as w:
                    self.assertEqual(w.getnframes(),44100)
                    self.assertEqual(w.readframes(44100),frames[spec.start_frame*2:spec.end_frame*2])

    def test_three_fixed_joins_one_encode_and_cleanup(self):
        for source in VERSION_CATALOG.values():
            if not isinstance(source,JoinedSource):continue
            with tempfile.TemporaryDirectory() as d:
                root=Path(d);store=Mock();store.source=source
                store.claim.return_value=descriptor(source)['source_urls']
                store.require_owner.return_value={'recognition_mode':'resumable'}
                def fetch(url,path,piece):path.write_bytes(b'synthetic')
                def assemble(desc,paths,dest,catalog):
                    self.assertIs(reviewed_source(desc),source)
                    self.assertIs(catalog,VERSION_CATALOG)
                    self.assertEqual([p.name for p in paths],[p.filename for p in source.pieces])
                    dest.write_bytes(b'joined');return {'audio_sha256':'c'*64}
                def transcode(args,**kwargs):Path(args[-1]).write_bytes(b'mp3')
                with patch('worker.jobs.yoon_once.fetch',side_effect=fetch) as fetched,patch('worker.jobs.yoon_once.assemble_version',side_effect=assemble) as assembled,patch('worker.jobs.yoon_once.subprocess.run',side_effect=transcode) as encoded,patch('worker.jobs.yoon_once.shutil.disk_usage',return_value=Mock(free=20_000_000_000)),patch('audio_segmenter.AudioSegmenter.get_audio_duration_ffprobe',return_value=source.duration):
                    prepare(store,root)
                self.assertEqual((fetched.call_count,assembled.call_count,encoded.call_count),(2,1,1))
                self.assertTrue((root/'audio/input.mp3').exists())
                self.assertFalse(any((root/p.filename).exists() for p in source.pieces))
                self.assertFalse((root/(source.id+'-joined.wav')).exists())

if __name__=='__main__':unittest.main()
