import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import requests
from discogs_matching import (MAX_DISCOGS_CANDIDATES, artist_credit_matches,
    title_version_match, validate_discogs_release)
from metadata_enricher import MetadataEnricher
from output_formatter import OutputFormatter, serialize_track
from platform_matching import usable_platform_url, primary_track_platform

CASES = json.loads((Path(__file__).parent / 'data/discogs_tracklist_cases.json').read_text())['cases']
GOOD = CASES[-1]
URL = 'https://www.discogs.com/release/514557'

def response(data, status=200):
    result = MagicMock(status_code=status)
    result.json.return_value = data
    if status >= 400:
        result.raise_for_status.side_effect = requests.HTTPError(response=result)
    return result


def enricher():
    obj = MetadataEnricher.__new__(MetadataEnricher)
    obj.discogs_enabled = True
    obj.spotify_enabled = obj.youtube_enabled = False
    obj._discogs_auth_header = lambda: 'synthetic-test-header'
    return obj


def track():
    return SimpleNamespace(artist=GOOD['artist'], title=GOOD['title'], confidence='HIGH',
        start_time=0, end_time=30, detection_count=3, cluster_density=1, cluster_span=3)


class DiscogsIdentityTests(unittest.TestCase):
    def test_all_four_halo_regressions_and_legitimate_compilations(self):
        for case in CASES:
            with self.subTest(case['name']):
                match = validate_discogs_release(case['artist'], case['title'], case['release'])
                self.assertEqual(bool(match), case['accept'])
                if match:
                    self.assertEqual(match['metadata_scope'], 'release')
                    self.assertFalse(match['original_release_verified'])
                    self.assertEqual(match['release_id'], case['release']['id'])
                    self.assertIn('track_position', match)

    def test_exact_artist_no_substrings_initial_guesses_or_word_bags(self):
        for expected, observed in [('Hammer','Velvet Hammer'),('S.A.M.','Sam Smith'),
                ('The Mirror Boys','Mirror Boys'),('Fries & Bridges','Disco Fries & Dacia Bridges'),
                ('James T Cotton','JTC'),('A & B','A & B & C')]:
            with self.subTest(expected=expected,observed=observed):
                self.assertFalse(artist_credit_matches(expected,[{'name':observed}]))
        self.assertTrue(artist_credit_matches('S.A.M.',[{'name':'S.A.M. (4)'}]))
        self.assertTrue(artist_credit_matches('Hipp-E',[{'name':'Hip E','anv':'Hipp-E'}]))
        self.assertTrue(artist_credit_matches('DJ Garth & ETI',[{'name':'DJ Garth'},{'name':'ETI'}]))

    def test_versions_must_match_in_both_directions(self):
        for expected, observed in [('Inside Out (Original Mix)','Inside Out (Extended Mix)'),
                ('Inside Out','Inside Out (Radio Edit)'),('Inside Out (Dub)','Inside Out'),
                ('Fade Take','Fade (Palm Skin Productions Smooth Edit)'),
                ('Compound (M.I.R.K.O. Remix)','Compound (Other Remix)'),
                ('House Rallante (Hipp-E\'s Dub)','House Rallante (Original Mix)')]:
            self.assertIsNone(title_version_match(expected,observed))
        self.assertEqual(title_version_match('Falling Down (Original Mix)','Falling Down'),'original_suffix_omitted')
        self.assertEqual(title_version_match('See the Music (1 AM Mix)','See The Music (1AM Mix)'),'exact_title_version')

    def test_release_title_does_not_replace_tracklist_or_track_artist(self):
        rel=copy.deepcopy(GOOD['release']);rel['tracklist']=[];rel['title']='Checker'
        self.assertIsNone(validate_discogs_release('Tigerskin','Checker',rel))
        rel['tracklist']=[{'title':'Checker','artists':[{'name':'Unrelated Artist'}]}]
        self.assertIsNone(validate_discogs_release('Tigerskin','Checker',rel))
        rel['formats']=[{'descriptions':['Compilation']}];rel['tracklist']=[{'title':'Checker'}]
        self.assertIsNone(validate_discogs_release('Tigerskin','Checker',rel))

    def test_malformed_release_formats_never_inherit_dj_credit(self):
        for formats in [{'descriptions':['Compilation']}, [{'descriptions':'Compilation'}], None, []]:
            rel=copy.deepcopy(GOOD['release']);rel['formats']=formats
            rel['tracklist']=[{'title':'Checker'}]
            self.assertIsNone(validate_discogs_release('Tigerskin','Checker',rel))
            rel['tracklist'][0]['artists']=[{'name':'Tigerskin'}]
            self.assertIsNotNone(validate_discogs_release('Tigerskin','Checker',rel))

    def test_nested_track_artists_and_noncompilation_release_credit(self):
        rel=copy.deepcopy(GOOD['release']);rel['tracklist']=[{'title':'Checker'}]
        self.assertIsNotNone(validate_discogs_release('Tigerskin','Checker',rel))
        rel['artists']=[{'name':'Various'}]
        rel['tracklist']=[{'type_':'index','title':'Part One','artists':[{'name':'Tigerskin'}],
            'sub_tracks':[{'type_':'track','position':'1.1','title':'Checker'}]}]
        self.assertEqual(validate_discogs_release('Tigerskin','Checker',rel)['track_position'],'1.1')
        rel['tracklist']=[{'type_':'heading','title':'Checker','artists':[{'name':'Tigerskin'}]}]
        self.assertIsNone(validate_discogs_release('Tigerskin','Checker',rel))


class DiscogsProviderTests(unittest.TestCase):
    def test_skips_wrong_first_candidate_and_persists_release_evidence(self):
        wrong=CASES[0]['release']
        with patch('metadata_enricher._discogs_session.get',side_effect=[
                response({'results':[{'id':wrong['id']},{'id':514557}]}),response(wrong),response(GOOD['release'])]) as get:
            meta=enricher().enrich_track(track())
        self.assertEqual(get.call_count,3)
        self.assertEqual(get.call_args_list[0].kwargs['params']['per_page'],5)
        self.assertEqual(meta['discogs_url'],URL)
        self.assertEqual(meta['discogs_metadata_scope'],'release')
        self.assertEqual(meta['platform_matches']['discogs']['candidates_checked'],2)
        saved=serialize_track({'track':track(),'metadata':meta},1,'')
        self.assertEqual(saved['platform_matches']['discogs'],meta['platform_matches']['discogs'])
        self.assertEqual(saved['discogs_matching_version'],1)
        self.assertEqual(saved['discogs_label_url'],'https://www.discogs.com/label/123')

    def test_malformed_ancillary_fields_cannot_crash_or_contaminate_matched_release(self):
        rel=copy.deepcopy(GOOD['release'])
        rel.update(labels={'name':'malformed'},genres='Electronic',styles='House')
        with patch('metadata_enricher._discogs_session.get',side_effect=[
                response({'results':[{'id':514557}]}),response(rel)]):
            meta=enricher().enrich_track(track())
        self.assertEqual(meta['discogs_url'],URL)
        self.assertIsNone(meta['discogs_label']);self.assertEqual(meta['discogs_styles'],[])
        self.assertEqual(meta['discogs_genres'],[])
        rel.update(labels=[{'name':{'malformed':True},'id':'wrong'}],genres=[{},'Electronic'],styles=[1,'House'])
        with patch('metadata_enricher._discogs_session.get',side_effect=[
                response({'results':[{'id':514557}]}),response(rel)]):
            meta=enricher().enrich_track(track())
        self.assertIsNone(meta['discogs_label']);self.assertIsNone(meta['discogs_label_url'])
        self.assertEqual(meta['discogs_genres'],['Electronic']);self.assertEqual(meta['discogs_styles'],['House'])

    def test_maximum_five_details_and_fixed_api_hosts(self):
        candidates=[{'id':i,'resource_url':'https://untrusted.invalid/secret'} for i in range(1,9)]
        with patch('metadata_enricher._discogs_session.get',side_effect=[response({'results':candidates})]+
                [response({'id':i,'tracklist':[]}) for i in range(1,6)]) as get:
            result=enricher()._search_discogs_rich('Checker','Tigerskin')
        self.assertEqual(get.call_count,1+MAX_DISCOGS_CANDIDATES)
        self.assertEqual(result['match']['status'],'no_match')
        for call in get.call_args_list[1:]:self.assertTrue(call.args[0].startswith('https://api.discogs.com/releases/'))

    def test_unavailable_search_does_not_publish_or_corroborate(self):
        for failure in [requests.Timeout('synthetic'),response({},429),response({},503)]:
            with self.subTest(failure=type(failure).__name__),patch('metadata_enricher._discogs_session.get') as get:
                if isinstance(failure,Exception):get.side_effect=failure
                else:get.return_value=failure
                meta=enricher().enrich_track(track())
            self.assertIsNone(meta['discogs_url']);self.assertEqual(meta['discogs_genres'],[])
            self.assertEqual(meta['platform_matches']['discogs']['status'],'unavailable')

    def test_rate_limit_during_detail_stops_remaining_requests(self):
        with patch('metadata_enricher._discogs_session.get',side_effect=[
                response({'results':[{'id':1},{'id':2}]}),response({},429)]) as get:
            result=enricher()._search_discogs_rich('Checker','Tigerskin')
        self.assertEqual(get.call_count,2)
        self.assertEqual(result['match']['reason'],'rate_limited')

    def test_missing_details_duplicate_and_mismatched_release_ids(self):
        with patch('metadata_enricher._discogs_session.get',side_effect=[
                response({'results':[{'id':1},{'id':1},{'id':'bad'},{'id':2}]}),response({},404),response(GOOD['release'])]) as get:
            result=enricher()._search_discogs_rich('Checker','Tigerskin')
        self.assertEqual(get.call_count,3)
        self.assertEqual(result['match']['status'],'unavailable')
        self.assertNotIn('url',result)

    def test_missing_auth_and_disabled_unknown_tracks_have_no_evidence(self):
        obj=enricher();obj._discogs_auth_header=lambda:None
        self.assertEqual(obj.enrich_track(track())['platform_matches']['discogs']['status'],'unavailable')
        obj.discogs_enabled=False
        self.assertEqual(obj.enrich_track(track())['platform_matches']['discogs']['status'],'disabled')
        obj.discogs_enabled=True;t=track();t.title='Unknown Track'
        with patch('metadata_enricher._discogs_session.get') as get:obj.enrich_track(t)
        get.assert_not_called()

    def test_spotify_youtube_results_unchanged_by_discogs_failure(self):
        obj=enricher();obj.spotify_enabled=obj.youtube_enabled=True
        spotify={'url':'https://open.spotify.com/track/verified','match':{'status':'matched','url':'https://open.spotify.com/track/verified','reason':'isrc'},'artist_profile':{'genres':['house']}}
        youtube={'url':'https://www.youtube.com/watch?v=verified','match':{'status':'matched','url':'https://www.youtube.com/watch?v=verified','reason':'artist_title'}}
        obj._search_spotify_rich=MagicMock(return_value=spotify);obj._search_youtube=MagicMock(return_value=youtube)
        with patch('metadata_enricher._discogs_session.get',side_effect=requests.Timeout):meta=obj.enrich_track(track())
        self.assertEqual(meta['platform_matches']['spotify'],spotify['match'])
        self.assertEqual(meta['platform_matches']['youtube'],youtube['match'])
        self.assertIsNone(obj._search_spotify_rich.call_args.kwargs['discogs_data'])


class DiscogsPersistenceTests(unittest.TestCase):
    def test_legacy_links_remain_legacy_new_links_require_matching_evidence(self):
        for version in [None,2]:
            self.assertEqual(usable_platform_url({'discogs_url':URL,'link_matching_version':version},'discogs'),URL)
        meta={'discogs_url':URL,'discogs_matching_version':1}
        self.assertIsNone(usable_platform_url(meta,'discogs'))
        meta['platform_matches']={'discogs':{'status':'matched','url':URL}}
        self.assertEqual(primary_track_platform(meta),'discogs')
        meta['platform_matches']['discogs']['url']='wrong'
        self.assertIsNone(usable_platform_url(meta,'discogs'))
        saved=serialize_track({'track':track(),'metadata':dict(meta,discogs_label='Stale',discogs_styles=['Stale'])},1,'')
        self.assertIsNone(saved['discogs_url']);self.assertIsNone(saved['discogs_label']);self.assertEqual(saved['discogs_styles'],[])


class DiscogsMarkdownTests(unittest.TestCase):
    def render(self, metadata):
        with TemporaryDirectory() as directory:
            formatter = OutputFormatter(artist_manager=SimpleNamespace(output_dir=Path(directory)))
            path = formatter.save_setlist_markdown(
                [{'track': track(), 'metadata': {
                    'spotify_url': 'https://open.spotify.com/track/unchanged',
                    'youtube_url': 'https://www.youtube.com/watch?v=unchanged',
                    **metadata,
                }}], {'title': 'Synthetic set'}, 'synthetic')
            text = path.read_text()
        self.assertIn('[Spotify](https://open.spotify.com/track/unchanged)', text)
        self.assertIn('[YouTube](https://www.youtube.com/watch?v=unchanged)', text)
        return text

    def test_reviewed_rejection_is_not_linked(self):
        text = self.render({'discogs_url': URL, 'discogs_matching_version': 1,
            'platform_matches': {'discogs': {'status': 'no_match',
                'reason': 'reviewed_rejection', 'rejected_url': URL}}})
        self.assertNotIn('[Discogs]', text)
        self.assertNotIn(URL, text)

    def test_mismatched_evidence_is_not_linked(self):
        text = self.render({'discogs_url': URL, 'discogs_matching_version': 1,
            'platform_matches': {'discogs': {'status': 'matched',
                'url': 'https://www.discogs.com/release/514558'}}})
        self.assertNotIn('[Discogs]', text)
        self.assertNotIn(URL, text)

    def test_missing_versioned_evidence_is_not_linked(self):
        self.assertNotIn('[Discogs]', self.render({
            'discogs_url': URL, 'discogs_matching_version': 1}))

    def test_confirmed_link_is_preserved(self):
        text = self.render({'discogs_url': URL, 'discogs_matching_version': 1,
            'platform_matches': {'discogs': {'status': 'matched', 'url': URL}}})
        self.assertIn(f'[Discogs]({URL})', text)

    def test_unversioned_legacy_link_is_preserved(self):
        self.assertIn(f'[Discogs]({URL})', self.render({'discogs_url': URL}))


if __name__ == '__main__':
    unittest.main()
