"""Tests for Spotify track matching logic in metadata_enricher.py."""
import unittest


def _artist_title_score(expected_artist_words, expected_title_words, candidates):
    """Score candidates using artist+title word overlap with artist ratio enforcement."""
    scored_results = []
    for item in candidates:
        observed_artist_words = set(w for w in item['artist'].lower().split() if len(w) > 2)
        observed_title_words = set(w for w in item['title'].lower().split() if len(w) > 2)

        artist_matches = len(expected_artist_words & observed_artist_words)
        title_matches = len(expected_title_words & observed_title_words)

        if artist_matches > 0 and title_matches > 0:
            artist_ratio = artist_matches / len(expected_artist_words)
            if artist_ratio < 0.6:
                continue
            scored_results.append((artist_matches + title_matches, item))

    scored_results.sort(key=lambda x: x[0], reverse=True)
    return scored_results


def _title_only_score(expected_title_words, candidates):
    """Score candidates using title word overlap only (fallback when artist name differs).
    Requires 100% of expected title words to appear in the observed title."""
    if len(expected_title_words) < 2:
        return []
    scored_results = []
    for item in candidates:
        observed_title_words = set(w for w in item['title'].lower().split() if len(w) > 2)
        title_matches = len(expected_title_words & observed_title_words)
        if title_matches == len(expected_title_words):
            scored_results.append((title_matches, item))
    scored_results.sort(key=lambda x: x[0], reverse=True)
    return scored_results


def search_spotify_fixed(expected_artist: str, expected_title: str,
                         primary_candidates: list, fallback_candidates: list = None) -> list:
    """
    Full fixed search logic:
    1. Try artist+title search with artist ratio filter.
    2. If no results, fall back to title-only search (handles Shazam vs Spotify artist name
       discrepancies, e.g. "James T. Cotton" on Shazam vs "JTC" on Spotify).
    """
    expected_artist_words = set(w for w in expected_artist.lower().split() if len(w) > 2)
    expected_title_words = set(w for w in expected_title.lower().split() if len(w) > 2)

    scored = _artist_title_score(expected_artist_words, expected_title_words, primary_candidates)
    if scored:
        return scored

    if fallback_candidates is not None:
        return _title_only_score(expected_title_words, fallback_candidates)
    return []


class TestSpotifyMatchingBug(unittest.TestCase):
    """
    Covers the bug where "Valley Road (We Are 1)" by James T. Cotton (Shazam name)
    was matched to "Valley Road" by James McMurtry, because:
    1. The correct track is on Spotify under artist "JTC", not "James T. Cotton"
    2. The artist-title query never found it
    3. McMurtry passed a too-lenient artist filter (only needs 1 shared word: "James")
    """

    # Primary search results (artist-title query): correct JTC track never appears
    PRIMARY = [
        {'artist': 'James McMurtry', 'title': 'Valley Road'},
        {'artist': 'James Brown', 'title': 'Road of No Return'},
    ]

    # Fallback search results (title-only query): JTC track is #1
    FALLBACK = [
        {'artist': 'JTC', 'title': 'Valley Road (We Are 1)'},
        {'artist': 'JTC', 'title': 'Valley Road (We Are 1) - DJ Qu Remix'},
        {'artist': 'Bruce Hornsby', 'title': 'The Valley Road'},
    ]

    # --- BUG: original behavior ---

    def test_bug_mcmurtry_passes_lenient_filter(self):
        """BUG: Original code accepts McMurtry because 'james' is the only artist match needed."""
        expected_artist_words = set(w for w in 'James T. Cotton'.lower().split() if len(w) > 2)
        expected_title_words = set(w for w in 'Valley Road (We Are 1)'.lower().split() if len(w) > 2)

        scored = []
        for item in self.PRIMARY:
            obs_artist = set(w for w in item['artist'].lower().split() if len(w) > 2)
            obs_title = set(w for w in item['title'].lower().split() if len(w) > 2)
            am = len(expected_artist_words & obs_artist)
            tm = len(expected_title_words & obs_title)
            if am > 0 and tm > 0:
                scored.append((am + tm, item))
        scored.sort(key=lambda x: x[0], reverse=True)

        self.assertTrue(len(scored) > 0)
        self.assertEqual(scored[0][1]['artist'], 'James McMurtry',
                         "BUG confirmed: McMurtry wins with only 'james' as artist match")

    # --- FIX part 1: artist ratio filter prevents McMurtry ---

    def test_fix_ratio_rejects_mcmurtry(self):
        """Artist ratio filter (>=0.6) rejects McMurtry: 1 of 2 expected words = 50%."""
        results = search_spotify_fixed(
            'James T. Cotton', 'Valley Road (We Are 1)',
            primary_candidates=self.PRIMARY,
        )
        self.assertEqual(len(results), 0,
                         "After ratio fix, no match should be returned from primary search")

    # --- FIX part 2: title-only fallback finds JTC ---

    def test_fix_fallback_finds_jtc(self):
        """Title-only fallback finds 'JTC - Valley Road (We Are 1)' when primary search fails."""
        results = search_spotify_fixed(
            'James T. Cotton', 'Valley Road (We Are 1)',
            primary_candidates=self.PRIMARY,
            fallback_candidates=self.FALLBACK,
        )
        self.assertTrue(len(results) > 0, "Fallback should find JTC track")
        self.assertEqual(results[0][1]['artist'], 'JTC')
        self.assertEqual(results[0][1]['title'], 'Valley Road (We Are 1)')

    def test_fix_fallback_rejects_partial_title_match(self):
        """Fallback requires 100% title word match: 'The Valley Road' (2/4 words) is rejected."""
        fallback_only = [{'artist': 'Bruce Hornsby', 'title': 'The Valley Road'}]
        results = search_spotify_fixed(
            'James T. Cotton', 'Valley Road (We Are 1)',
            primary_candidates=[],
            fallback_candidates=fallback_only,
        )
        self.assertEqual(len(results), 0)

    def test_fix_fallback_accepts_remix_with_extra_words(self):
        """Fallback accepts a Spotify title with extra words (remix suffix) as long as all expected words are present."""
        fallback_with_remix = [{'artist': 'JTC', 'title': 'Valley Road (We Are 1) - DJ Qu Remix - Mixed'}]
        results = search_spotify_fixed(
            'James T. Cotton', 'Valley Road (We Are 1)',
            primary_candidates=[],
            fallback_candidates=fallback_with_remix,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][1]['artist'], 'JTC')

    def test_fix_fallback_not_triggered_when_primary_succeeds(self):
        """Fallback is not used when primary search already found a valid match."""
        primary_with_correct = [
            {'artist': 'James T. Cotton', 'title': 'Valley Road (We Are 1)'},
            {'artist': 'James McMurtry', 'title': 'Valley Road'},
        ]
        results = search_spotify_fixed(
            'James T. Cotton', 'Valley Road (We Are 1)',
            primary_candidates=primary_with_correct,
            fallback_candidates=self.FALLBACK,
        )
        self.assertEqual(results[0][1]['artist'], 'James T. Cotton')

    def test_fix_fallback_skipped_for_short_titles(self):
        """Fallback requires at least 2 expected title words to avoid false positives on single-word titles."""
        results = search_spotify_fixed(
            'Unknown Artist', 'Glue',
            primary_candidates=[],
            fallback_candidates=[{'artist': 'Bicep', 'title': 'Glue'}],
        )
        self.assertEqual(len(results), 0,
                         "Single-word title fallback should be skipped")

    # --- Regression: normal matches still work ---

    def test_normal_artist_title_match_unaffected(self):
        """Standard matching still works for well-known artist names."""
        candidates = [{'artist': 'Bicep', 'title': 'Glue'}]
        results = search_spotify_fixed('Bicep', 'Glue', primary_candidates=candidates)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][1]['artist'], 'Bicep')

    def test_two_word_artist_requires_both_words(self):
        """Two-word artist: both words must match (ratio = 50% fails the 60% threshold)."""
        candidates = [
            {'artist': 'James McMurtry', 'title': 'Levelland'},
            {'artist': 'James Cotton', 'title': 'Levelland Blues'},
        ]
        results = search_spotify_fixed('James Cotton', 'Levelland Blues', primary_candidates=candidates)
        self.assertTrue(all(r[1]['artist'] == 'James Cotton' for r in results))

    def test_three_word_artist_two_matches_accepted(self):
        """For 3-word artist names, 2 of 3 matching (67%) passes the 60% threshold."""
        candidates = [{'artist': 'The Chemical Brothers', 'title': 'Block Rockin Beats'}]
        results = search_spotify_fixed('Chemical Brothers', 'Block Rockin Beats', primary_candidates=candidates)
        self.assertEqual(len(results), 1)


if __name__ == '__main__':
    unittest.main()
