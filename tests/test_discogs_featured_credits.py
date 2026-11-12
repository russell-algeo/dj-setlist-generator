"""Offline regression coverage for explicit title-to-track feature credits."""
import copy
import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from discogs_matching import validate_discogs_release


CASES = json.loads((Path(__file__).parent / 'data/discogs_seven_review_cases.json').read_text())['cases']


def release(title='Song', names=('Lead Artist', 'Guest Artist')):
    return {'id': 123, 'title': 'Album', 'artists': [{'name': 'Lead Artist'}],
            'formats': [{'name': 'CD', 'descriptions': ['Album']}],
            'tracklist': [{'position': '1', 'type_': 'track', 'title': title,
                          'artists': [{'name': name} for name in names]}]}


class DiscogsFeaturedCreditTests(unittest.TestCase):
    def test_provider_and_serializer_preserve_feature_evidence_and_source_identity(self):
        from metadata_enricher import MetadataEnricher
        from output_formatter import serialize_track

        case = next(case for case in CASES if case['accept'])
        source = SimpleNamespace(artist=case['artist'], title=case['title'], confidence='HIGH',
                                 start_time=0, end_time=30, detection_count=3,
                                 cluster_density=1, cluster_span=3)
        enricher = MetadataEnricher.__new__(MetadataEnricher)
        enricher.discogs_enabled = True
        enricher.spotify_enabled = enricher.youtube_enabled = False
        enricher._discogs_auth_header = lambda: 'synthetic-test-header'
        search, detail = MagicMock(status_code=200), MagicMock(status_code=200)
        search.json.return_value = {'results': [{'id': 9271783}]}
        detail.json.return_value = case['release']
        with patch('metadata_enricher._discogs_session.get', side_effect=[search, detail]) as get:
            metadata = enricher.enrich_track(source)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(metadata['discogs_url'], 'https://www.discogs.com/release/9271783')
        evidence = metadata['platform_matches']['discogs']
        self.assertEqual(evidence['credit_comparison'], 'explicit_featured_credit_from_title')
        saved = serialize_track({'track': source, 'metadata': metadata}, 1, '')
        self.assertEqual(saved['platform_matches']['discogs'], evidence)
        self.assertEqual(source.artist, case['artist'])
        self.assertEqual(source.title, case['title'])
        self.assertEqual(saved['artist'], case['artist'])
        self.assertEqual(saved['title'], case['title'])

    def test_real_seven_case_audit_only_accepts_verified_feature_credit(self):
        for case in CASES:
            with self.subTest(release=case['release']['id']):
                before = copy.deepcopy(case['release'])
                evidence = validate_discogs_release(case['artist'], case['title'], case['release'])
                self.assertEqual(bool(evidence), case['accept'])
                self.assertEqual(case['release'], before)
                if evidence:
                    self.assertEqual(evidence['release_id'], 9271783)
                    self.assertEqual(evidence['track_position'], '12')
                    self.assertEqual(evidence['artists'], ['Lay-Far', 'Sean McCabe'])
                    self.assertEqual(evidence['credit_comparison'], 'explicit_featured_credit_from_title')
                    self.assertEqual(evidence['featured_credit'], 'Sean McCabe')
                    self.assertEqual(evidence['requested_title'], case['title'])
                    self.assertEqual(evidence['requested_artist'], 'Lay-Far')
                    self.assertEqual(evidence['metadata_scope'], 'release')
                    self.assertFalse(evidence['original_release_verified'])

    def test_explicit_bracket_syntax(self):
        for title in ('Song (feat. Guest Artist)', 'Song (feat Guest Artist)',
                      'Song (featuring Guest Artist)', 'Song [FEAT. Guest Artist]',
                      'Song [Featuring Guest Artist]'):
            with self.subTest(title=title):
                self.assertIsNotNone(validate_discogs_release('Lead Artist', title, release()))

    def test_feature_credit_is_not_a_version_and_version_text_is_preserved(self):
        for suffix in ('Club Mix', 'Radio Edit', 'Dub', 'Other Remix', 'Mixed'):
            observed = f'Song ({suffix})'
            for expected in (f'Song (feat. Guest Artist) ({suffix})',
                             f'Song ({suffix}) (feat. Guest Artist)'):
                with self.subTest(expected=expected):
                    self.assertIsNotNone(validate_discogs_release('Lead Artist', expected, release(observed)))
                    self.assertIsNone(validate_discogs_release('Lead Artist', expected, release()))
                    self.assertIsNone(validate_discogs_release('Lead Artist', expected, release('Song (Different Remix)')))
        self.assertIsNone(validate_discogs_release('Lead Artist', 'Song (feat. Guest Artist)', release('Song (Club Mix)')))

    def test_original_mix_omission_is_existing_policy_only(self):
        evidence = validate_discogs_release('Lead Artist', 'Song (Original Mix) (feat. Guest Artist)', release())
        self.assertEqual(evidence['version_comparison'], 'original_suffix_omitted')

    def test_exact_artist_set_required(self):
        for names in (('Lead Artist',), ('Guest Artist',), ('Wrong Lead', 'Guest Artist'),
                      ('Lead Artist', 'Wrong Guest'), ('Lead Artist', 'Guest Artist', 'Other'),
                      ('Lead Artist', 'Guest Artist Remix')):
            with self.subTest(names=names):
                self.assertIsNone(validate_discogs_release('Lead Artist', 'Song (feat. Guest Artist)', release(names=names)))

    def test_all_multiple_featured_artists_required(self):
        title = 'Song (feat. Guest Artist & Other Guest)'
        self.assertIsNotNone(validate_discogs_release('Lead Artist', title,
                             release(names=('Lead Artist', 'Guest Artist', 'Other Guest'))))
        self.assertIsNone(validate_discogs_release('Lead Artist', title, release()))

    def test_explicit_anv_is_supported_without_invented_aliases(self):
        data = release(names=('Lead Artist', 'Different Legal Name'))
        self.assertIsNone(validate_discogs_release('Lead Artist', 'Song (feat. Guest Artist)', data))
        data['tracklist'][0]['artists'][1]['anv'] = 'Guest Artist'
        self.assertIsNotNone(validate_discogs_release('Lead Artist', 'Song (feat. Guest Artist)', data))

    def test_primary_credit_already_containing_guest_is_idempotent(self):
        self.assertIsNotNone(validate_discogs_release('Lead Artist & Guest Artist',
                             'Song (feat. Guest Artist)', release()))

    def test_extraartists_cannot_substitute_for_explicit_track_artists(self):
        for role in ('Featuring', 'Producer', 'Remix', 'Design', 'DJ Mix'):
            for location in ('release', 'track'):
                with self.subTest(role=role, location=location):
                    data = release(names=('Lead Artist',))
                    target = data if location == 'release' else data['tracklist'][0]
                    target['extraartists'] = [{'name': 'Guest Artist', 'role': role}]
                    self.assertIsNone(validate_discogs_release('Lead Artist', 'Song (feat. Guest Artist)', data))

    def test_release_or_parent_credit_is_not_promoted(self):
        for compilation in (False, True):
            data = release()
            data['artists'] = data['tracklist'][0].pop('artists')
            if compilation:
                data['formats'][0]['descriptions'] = ['Compilation']
            self.assertIsNone(validate_discogs_release('Lead Artist', 'Song (feat. Guest Artist)', data))
        data = release()
        data['tracklist'] = [{'type_': 'index', 'artists': data['tracklist'][0]['artists'],
                             'sub_tracks': [{'type_': 'track', 'title': 'Song'}]}]
        self.assertIsNone(validate_discogs_release('Lead Artist', 'Song (feat. Guest Artist)', data))

    def test_missing_malformed_empty_or_ambiguous_feature_syntax(self):
        for title in ('Song feat. Guest Artist', 'Song ft. Guest Artist',
                      'Song (ft. Guest Artist)', 'Song (with Guest Artist)',
                      'Song (Guest Artist)', 'Song (feat.)', 'Song (feat. &)',
                      'Song (feat. Guest Artist', 'Song [feat. Guest Artist)',
                      'Song ((feat. Guest Artist))', 'Song [(feat. Guest Artist)]',
                      'Song (feat. Guest Artist) (feat. Other Guest)',
                      '(feat. Guest Artist)'):
            with self.subTest(title=title):
                self.assertIsNone(validate_discogs_release('Lead Artist', title, release()))
        for artist in ('', None, '&'):
            self.assertIsNone(validate_discogs_release(artist, 'Song (feat. Guest Artist)', release()))
        for artists in (None, [], 'Guest Artist', [None], [{}], [{'anv': ''}]):
            data = release()
            data['tracklist'][0]['artists'] = artists
            self.assertIsNone(validate_discogs_release('Lead Artist', 'Song (feat. Guest Artist)', data))

    def test_ordinary_exact_match_evidence_is_unchanged(self):
        data = release(names=('Lead Artist',))
        evidence = validate_discogs_release('Lead Artist', 'Song', data)
        self.assertNotIn('credit_comparison', evidence)
        self.assertEqual(evidence['version_comparison'], 'exact_title_version')
        self.assertEqual(evidence['matching_version'], 1)

    def test_exact_title_with_feat_word_is_not_reinterpreted(self):
        title = 'Song (feat. Guest Artist)'
        data = release(title=title, names=('Lead Artist',))
        evidence = validate_discogs_release('Lead Artist', title, data)
        self.assertIsNotNone(evidence)
        self.assertNotIn('credit_comparison', evidence)


if __name__ == '__main__':
    unittest.main()
