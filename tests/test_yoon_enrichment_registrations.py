"""Strict finite registration validation with synthetic complete recognition."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from worker.jobs.yoon_enrichment_registrations import ADDITIONAL_ENRICHMENT_RUNS
from worker.jobs.yoon_sources import CATALOG
from worker.jobs.yoon_spotify_enrich import validate, digest, Store, REVIEWED_RUNS, DONALD_SCOPE, DONALD_MEMBERS
from worker.jobs.yoon_spotify_enrich import RUN, DONALD_RUN, HALO_RUN, GRISHA_RUN, HIGHKIN_RUN, DEEP_HOUSE_RUN, BRETT_RUN


def fixture(run):
    spec=ADDITIONAL_ENRICHMENT_RUNS[run]; source=CATALOG[spec['source_id']]
    descriptor=dict(source.pins(),source_id=source.id,recognition_mode='resumable')
    scope=dict(DONALD_SCOPE,target_set_id=spec['target_set_id'],submission_id=spec['submission_id'])
    row=dict(scope,id=run,status='private_resume_complete',source_metadata={'yoon_fixed_input':descriptor})
    tracks=[dict(title='Synthetic',artist='Synthetic',start_time=0,end_time=60,confidence='HIGH',
                 detection_count=3,shazam_track_id='1',isrc=None,cluster_density=1,cluster_span=3,segment_indices=[0])]
    state=dict(status='complete',valid_responses=source.windows,clustered_setlist=tracks,used_owners=['1:1'],
        initialization_mode='fresh',fresh_source_initialized=True,source_id=source.id,source_pins=source.pins(),
        members=copy.deepcopy(DONALD_MEMBERS),audio_sha256='a'*64,expected_audio_sha256='a'*64)
    hits=[dict(segment_index=i,raw_data={'private_jackson_v2':dict(valid=True,in_flight=False,
        attempts=[dict(state='finished',workflow_run_id='1',run_attempt='1',diagnostic=dict(http_status=200,outcome='no_match'))],
        response=dict(timestamp=i*15,segment_index=i,track_title=None,artist=None,shazam_track_id=None,
                      raw_data={'matches':[]},recognized=False,http_status=200))}) for i in range(source.windows)]
    expected=dict(scope,source_digest=digest(descriptor),cluster_digest=digest(tracks))
    return row,state,hits,expected


class FiniteRegistrationTests(unittest.TestCase):
    def test_identities_match_reviewed_seed_manifest(self):
        fixture_path=Path(__file__).parent/'data/yoon_enrichment_reviewed_identities.json'
        rows=json.loads(fixture_path.read_text())['rows']
        self.assertEqual(set(ADDITIONAL_ENRICHMENT_RUNS),{r['run_id'] for r in rows})
        for row in rows:
            self.assertEqual(ADDITIONAL_ENRICHMENT_RUNS[row['run_id']],
                {k:row[k] for k in ('source_id','target_set_id','submission_id')})
            self.assertEqual(CATALOG[row['source_id']].windows,row['windows'])

    def test_exact_allowlist_and_all_windows(self):
        old={RUN,DONALD_RUN,HALO_RUN,GRISHA_RUN,HIGHKIN_RUN,DEEP_HOUSE_RUN,BRETT_RUN}
        self.assertEqual(len(ADDITIONAL_ENRICHMENT_RUNS),20)
        self.assertFalse(old & ADDITIONAL_ENRICHMENT_RUNS.keys())
        self.assertEqual(REVIEWED_RUNS,old | ADDITIONAL_ENRICHMENT_RUNS.keys())
        for run in ADDITIONAL_ENRICHMENT_RUNS:
            with self.subTest(run=run):
                args=fixture(run);self.assertEqual(validate(*args),args[1]['clustered_setlist'])
                self.assertEqual(Store(args[3],'1','1',run).run_id,run)

    def test_all_identity_source_window_mutations_rejected(self):
        for run in ADDITIONAL_ENRICHMENT_RUNS:
            args=fixture(run)
            for field in ('target_set_id','submission_id','collection_id','requested_by'):
                with self.subTest(run=run,field=field):
                    r,s,h,e=copy.deepcopy(args);r[field]=e[field]='00000000-0000-4000-8000-000000000000'
                    with self.assertRaises(RuntimeError):validate(r,s,h,e)
            mutations=[lambda r,s,h,e:r.update(id='unknown'),lambda r,s,h,e:s.update(source_id='other'),
                lambda r,s,h,e:s['source_pins'].update(duration=1),lambda r,s,h,e:s.update(members=[]),
                lambda r,s,h,e:s.update(audio_sha256='b'*64),lambda r,s,h,e:s.update(origin={'valid_windows':0}),
                lambda r,s,h,e:s.update(provenance_seeded=True),lambda r,s,h,e:s.update(fresh_source_initialized=False),
                lambda r,s,h,e:s.update(valid_responses=s['valid_responses']+1),lambda r,s,h,e:h.pop(),
                lambda r,s,h,e:h[0].update(segment_index=1),
                lambda r,s,h,e:h[0]['raw_data']['private_jackson_v2']['response'].update(timestamp=1),
                lambda r,s,h,e:h[0]['raw_data']['private_jackson_v2']['response'].update(http_status=None),
                lambda r,s,h,e:h[0]['raw_data']['private_jackson_v2']['attempts'][0]['diagnostic'].update(http_status=429),
                lambda r,s,h,e:e.update(source_id='caller-source'),lambda r,s,h,e:e.update(windows=s['valid_responses']),
                lambda r,s,h,e:e.update(rich_metadata=False)]
            for i,mutate in enumerate(mutations):
                with self.subTest(run=run,mutation=i):
                    changed=copy.deepcopy(args);mutate(*changed)
                    with self.assertRaises(RuntimeError):validate(*changed)
            for key,value in [('unknown',True),('source_id','caller-source'),('duration',1),('recognition_mode','other'),('windows',1)]:
                with self.subTest(run=run,descriptor=key):
                    r,s,h,e=copy.deepcopy(args);r['source_metadata']['yoon_fixed_input'][key]=value
                    e['source_digest']=digest(r['source_metadata']['yoon_fixed_input'])
                    with self.assertRaises(RuntimeError):validate(r,s,h,e)

    def test_catalog_and_environment_do_not_authorize_unknown_run(self):
        arbitrary='00000000-0000-4000-8000-000000000000'
        with patch.dict('os.environ',{'PRIVATE_RUN_ID':arbitrary,'YOON_SOURCE_ID':'choice-friday'}):
            with self.assertRaises(RuntimeError):Store({},'1','1',arbitrary)

    def test_all_expected_shapes_and_source_pin_keys_fail_closed(self):
        from worker.jobs.yoon_remaining_sources import JOINED_CATALOG
        for run,registration in ADDITIONAL_ENRICHMENT_RUNS.items():
            row,state,hits,expected=fixture(run)
            with self.subTest(run=run,rich=True):
                self.assertEqual(validate(row,state,hits,dict(expected,rich_metadata=True)),state['clustered_setlist'])
            for key in expected:
                changed=dict(expected);changed.pop(key)
                with self.subTest(run=run,missing=key),self.assertRaises(RuntimeError):validate(row,state,hits,changed)
            for changed in (None,[],True,'caller-config'):
                with self.subTest(run=run,shape=type(changed)),self.assertRaises(RuntimeError):validate(row,state,hits,changed)
            source=CATALOG[registration['source_id']]
            for key in source.pins():
                changed=copy.deepcopy(row);changed['source_metadata']['yoon_fixed_input'][key]=None
                pins=dict(expected,source_digest=digest(changed['source_metadata']['yoon_fixed_input']))
                with self.subTest(run=run,pin=key),self.assertRaises(RuntimeError):validate(changed,state,hits,pins)
            opposite='source_url' if source.id in JOINED_CATALOG else 'source_urls'
            changed=copy.deepcopy(row);changed['source_metadata']['yoon_fixed_input'][opposite]='synthetic'
            pins=dict(expected,source_digest=digest(changed['source_metadata']['yoon_fixed_input']))
            with self.subTest(run=run,opposite=opposite),self.assertRaises(RuntimeError):validate(changed,state,hits,pins)
