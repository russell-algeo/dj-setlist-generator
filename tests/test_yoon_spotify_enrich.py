import copy
import unittest
from unittest.mock import Mock
from worker.jobs.yoon_spotify_enrich import validate, digest, enrich, RUN

class PrivateEnrichmentTests(unittest.TestCase):
    def fixture(self):
        tracks=[dict(title='Unknown Track',artist='Unknown',start_time=i,end_time=i+1,
                     confidence='low',detection_count=0,shazam_track_id=None,isrc=None,
                     cluster_density=0,cluster_span=0,segment_indices=[]) for i in range(28)]
        row=dict(id=RUN,status='private_resume_complete',target_set_id='s',collection_id='c',
                 submission_id='u',requested_by='owner',source_metadata={'yoon_fixed_input':{}})
        state=dict(status='complete',valid_responses=479,clustered_setlist=tracks,used_owners=['1:1'])
        expected={k:str(row[k]) for k in ('target_set_id','collection_id','submission_id','requested_by')}
        expected.update(source_digest=digest({}),cluster_digest=digest(tracks))
        hits=[dict(segment_index=i,raw_data={'private_jackson_v2':dict(valid=True,in_flight=False,attempts=[dict(state='finished',workflow_run_id='1',run_attempt='1',diagnostic=dict(http_status=200,outcome='no_match'))],
              response=dict(timestamp=i*15,segment_index=i,track_title=None,artist=None,
              shazam_track_id=None,raw_data={'matches':[]},recognized=False,http_status=200))}) for i in range(479)]
        return row,state,hits,expected

    def test_valid_scope(self):
        args=self.fixture()
        self.assertEqual(len(validate(*args)),28)

    def test_reject_changed_scope_evidence(self):
        for mutate in [lambda r,s,h,e:r.update(status='running'),
                       lambda r,s,h,e:r.update(collection_id='other'),
                       lambda r,s,h,e:s.update(in_flight=True),
                       lambda r,s,h,e:s['clustered_setlist'][0].update(title='changed'),
                       lambda r,s,h,e:h.pop(),
                       lambda r,s,h,e:h[0]['raw_data']['private_jackson_v2']['response'].update(http_status=429),
                       lambda r,s,h,e:h[0]['raw_data']['private_jackson_v2'].update(in_flight=True)]:
            args=self.fixture();mutate(*args)
            with self.assertRaises(RuntimeError):validate(*args)

    def test_no_unverified_link(self):
        tracks=self.fixture()[1]['clustered_setlist'][:1];tracks[0]['title']='Synthetic'
        fake=Mock();fake.enrich_track.return_value={'spotify_url':'https://open.spotify.com/track/'+'A'*22}
        with self.assertRaises(RuntimeError):enrich(tracks,fake)

    def test_metadata_only_and_isrc_passed(self):
        tracks=self.fixture()[1]['clustered_setlist'][:1];tracks[0]['title']='Synthetic';tracks[0]['isrc']='GBXXX0000002'
        fake=Mock();fake.enrich_track.return_value={'spotify_url':None,'platform_matches':{'spotify':{'status':'unverified'}},'link_matching_version':1}
        result=enrich(tracks,fake)
        self.assertEqual(fake.enrich_track.call_args[0][0].isrc,'GBXXX0000002')
        self.assertNotIn('title',result[0]);self.assertEqual(result[0]['index'],0)

    def test_reservation_replay_and_uncertainty(self):
        from contextlib import contextmanager
        from worker.jobs.yoon_spotify_enrich import Store, KEY
        store=object.__new__(Store);store.expected={'pin':'x'};store.owner={'workflow_run_id':'1'}
        row={'source_metadata':{}}
        @contextmanager
        def locked():yield None,row,[]
        store.locked=locked
        store.write=lambda cur,value:row['source_metadata'].update({KEY:value})
        ticket,_=store.reserve()
        with self.assertRaises(RuntimeError):store.reserve()
        with self.assertRaises(RuntimeError):store.finish('wrong',[])
        store.finish(ticket,[])
        self.assertEqual(store.reserve(),(None,[]))
        row['source_metadata'][KEY]['results']=[{'changed':True}]
        with self.assertRaises(RuntimeError):store.reserve()

    def test_verified_result(self):
        tracks=self.fixture()[1]['clustered_setlist'][:1];tracks[0]['title']='Synthetic'
        url='https://open.spotify.com/track/'+'A'*22
        fake=Mock();fake.enrich_track.return_value={'spotify_url':url,
          'platform_matches':{'spotify':{'status':'matched','url':url,'reason':'isrc'}},
          'link_matching_version':2}
        self.assertEqual(enrich(tracks,fake)[0]['spotify_url'],url)

    def test_legacy_response_requires_diagnostic(self):
        args=self.fixture();args[2][0]['raw_data']['private_jackson_v2']['response'].pop('http_status')
        validate(*args)
        args[2][0]['raw_data']['private_jackson_v2']['attempts'][-1]['diagnostic']['http_status']=429
        with self.assertRaises(RuntimeError):validate(*args)

    def test_exact_origin_seed(self):
        row,state,hits,expected=self.fixture()
        pin=dict(run_id='original',metadata_sha256='hash',workflow_run_id='2',valid_windows=1)
        state['origin']=pin
        d=hits[0]['raw_data']['private_jackson_v2'];d['attempts']=[]
        d['response'].pop('http_status');d['origin']=dict(pin,segment_index=0)
        origin=dict(id='original',metadata_sha256='hash',source_metadata={'yoon_analysis':dict(
            workflow_run_id='2',status='partial',raw_recognitions=[copy.deepcopy(d['response'])],
            recognition_diagnostics={'attempts':[dict(segment_index=0,http_status=200)]})})
        validate(row,state,hits,expected,origin)
        origin['source_metadata']['yoon_analysis']['raw_recognitions'][0]['timestamp']=1
        with self.assertRaises(RuntimeError):validate(row,state,hits,expected,origin)

    def test_unknown_never_searches(self):
        fake=Mock();self.assertEqual(enrich(self.fixture()[1]['clustered_setlist'],fake),[])
        fake.enrich_track.assert_not_called()

    def test_workflow_excludes_all_other_jobs(self):
        from pathlib import Path
        text=Path('.github/workflows/process-set.yml').read_text()
        old=text.split('  private-enrichment:')[0]
        conditions=[line for line in old.splitlines() if line.startswith('    if:')]
        self.assertEqual(len(conditions),8)
        self.assertTrue(all("private_enrichment_only != 'true'" in line for line in conditions))
        job=text.split('  private-enrichment:')[1]
        self.assertNotIn('upload-artifact',job)
        self.assertNotIn('DISCOGS',job)
        self.assertNotIn('YOUTUBE',job)
        self.assertIn('>/dev/null 2>&1',job)

if __name__=='__main__':unittest.main()
