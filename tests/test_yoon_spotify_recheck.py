import copy
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from worker.jobs import yoon_spotify_recheck as subject
from worker.jobs.yoon_spotify_enrich import Store, KEY, DONALD_RUN, digest
from tests.test_yoon_spotify_enrich import PrivateEnrichmentTests


class RecheckTests(unittest.TestCase):
    def fixture(self):
        tracks = PrivateEnrichmentTests().fixture()[1]['clustered_setlist']
        for track in tracks:
            track['title'] = 'Synthetic'
        indices = list(subject.INDICES) + [i for i in range(28) if i not in subject.INDICES][:12]
        results = [dict(index=i, spotify_url=None if i in subject.INDICES else 'verified') for i in sorted(indices)]
        expected = dict(pin='synthetic')
        prior = dict(status='complete', input=expected, results=results, results_digest=digest(results))
        return dict(id=DONALD_RUN,source_metadata={KEY:prior}), tracks, expected

    def test_guard_preserves_prior_and_scope(self):
        row, tracks, expected = self.fixture()
        original = copy.deepcopy(row)
        with patch.object(subject, 'PRIOR_DIGEST', row['source_metadata'][KEY]['results_digest']):
            subject.validate_prior(row, tracks, expected)
            for mutate in [lambda r: r.update(id='other'),
                           lambda r: r['source_metadata'][KEY].update(status='reserved'),
                           lambda r: r['source_metadata'][KEY].update(input={}),
                           lambda r: r['source_metadata'][KEY]['results'][0].update(spotify_url='new')]:
                bad = copy.deepcopy(row); mutate(bad)
                with self.assertRaises(RuntimeError):
                    subject.validate_prior(bad, tracks, expected)
        self.assertEqual(row, original)

    def test_one_shot_replay_and_no_overwrite(self):
        row, tracks, expected = self.fixture(); original = copy.deepcopy(row['source_metadata'][KEY])
        store = object.__new__(subject.RecheckStore)
        store.expected=expected;store.owner={'workflow_run_id':'2','run_attempt':'1'}
        @contextmanager
        def locked(): yield None,row,tracks
        store.locked=locked
        store.write=lambda cur,value:row['source_metadata'].update({store.key:value})
        store.run_id='synthetic-run'
        row['target_set_id']='synthetic-set'
        admission=patch('worker.jobs.yoon_admission.check')
        admission.start();self.addCleanup(admission.stop)
        ticket,_=store.reserve()
        with self.assertRaises(RuntimeError):store.reserve()
        with self.assertRaises(RuntimeError):store.finish(ticket,[])
        results=[{'index':i} for i in subject.INDICES]
        store.finish(ticket,results)
        self.assertEqual(store.reserve(),(None,tracks))
        self.assertEqual(row['source_metadata'][KEY],original)
        row['source_metadata'][subject.RECHECK_KEY]['results'][0]['index']=99
        with self.assertRaises(RuntimeError):store.reserve()

    def test_only_seven_tracks_rechecked(self):
        _,tracks,_=self.fixture();fake=Mock()
        fake.enrich_track.return_value={'spotify_url':None,'platform_matches':{'spotify':{'status':'unverified'}}}
        fake.last_spotify_diagnostic={'status':'no_verified_candidate','searches':[]}
        results=subject.enrich_selected(tracks,fake)
        self.assertEqual([r['index'] for r in results],list(subject.INDICES))
        self.assertEqual(fake.enrich_track.call_count,7)
        self.assertTrue(all(r['diagnostic']['status']=='no_verified_candidate' for r in results))
        with self.assertRaises(RuntimeError):subject.RecheckStore({},'1','1','arbitrary')

    def test_store_writes_only_selected_receipt(self):
        store=object.__new__(subject.RecheckStore);store.run_id=DONALD_RUN;cur=Mock()
        store.write(cur,{'status':'reserved'})
        sql,params=cur.execute.call_args.args
        self.assertEqual(params[0],[subject.RECHECK_KEY]);self.assertNotIn(KEY,sql)


class DiagnosticTests(unittest.TestCase):
    def engine(self):
        from metadata_enricher import MetadataEnricher
        engine=object.__new__(MetadataEnricher);engine.spotify=Mock()
        return engine

    def test_no_candidates_is_not_error(self):
        engine=self.engine();engine.spotify.search.return_value={'tracks':{'items':[]}}
        self.assertIsNone(engine._search_spotify_rich('Synthetic','Artist',isrc='USAAA0000001'))
        self.assertEqual(engine.last_spotify_diagnostic,{'status':'no_verified_candidate','searches':[
            {'kind':'isrc','count':0},{'kind':'artist_title','count':0},{'kind':'title','count':0}]})

    def test_http_error_sanitized_and_not_no_match(self):
        from spotipy.exceptions import SpotifyException
        engine=self.engine();engine.spotify.search.side_effect=SpotifyException(429,-1,'private source and secret')
        self.assertIsNone(engine._search_spotify_rich('Synthetic','Artist'))
        d=engine.last_spotify_diagnostic
        self.assertEqual(d['status'],'error');self.assertEqual(d['http_status'],429)
        self.assertNotIn('private',str(d));self.assertNotIn('secret',str(d))

    def test_matched_isrc_unchanged(self):
        engine=self.engine();url='https://open.spotify.com/track/'+'A'*22
        engine.spotify.search.return_value={'tracks':{'items':[dict(name='Synthetic',artists=[{'name':'Artist'}],
          external_ids={'isrc':'USAAA0000001'},external_urls={'spotify':url})]}}
        result=engine._search_spotify_rich('Synthetic','Artist',isrc='USAAA0000001')
        self.assertEqual(result['url'],url);self.assertEqual(result['match']['reason'],'isrc')
        self.assertEqual(engine.last_spotify_diagnostic['status'],'matched_isrc')

    def test_artist_profile_error_is_not_catalog_absence(self):
        from spotipy.exceptions import SpotifyException
        engine=self.engine();engine._artist_cache={}
        candidate={'id':'candidate','name':'Synthetic','artists':[{'id':'artist','name':'Different'}]}
        engine.spotify.search.side_effect=[{'tracks':{'items':[]}}, {'tracks':{'items':[candidate]}}]
        engine.spotify.artist.side_effect=SpotifyException(503,-1,'private diagnostic detail')
        with patch('metadata_enricher.select_spotify_candidate',return_value=None):
            self.assertIsNone(engine._search_spotify_rich('Synthetic','Artist'))
        d=engine.last_spotify_diagnostic
        self.assertEqual(d['status'],'incomplete_provider_error')
        self.assertEqual(d['profile_errors'],[{'http_status':503,'error_type':'SpotifyException'}])
        self.assertNotIn('private',str(d))

    def test_disabled_and_malformed_response(self):
        engine=self.engine();engine.spotify=None
        self.assertIsNone(engine._search_spotify_rich('Synthetic','Artist'))
        self.assertEqual(engine.last_spotify_diagnostic['status'],'unavailable')
        engine.spotify=Mock();engine.spotify.search.return_value={'malformed':True}
        self.assertIsNone(engine._search_spotify_rich('Synthetic','Artist'))
        self.assertEqual(engine.last_spotify_diagnostic['status'],'error')

if __name__=='__main__':unittest.main()
