"""Tests for Spotify track matching logic."""

import unittest

from spotify_matching import (
    score_artist_title_candidates,
    score_title_only_candidates,
    select_spotify_candidate,
)


class TestSpotifyMatching(unittest.TestCase):
    PRIMARY = [
        {"artist": "James McMurtry", "title": "Valley Road", "artist_genres": ["alt country"]},
        {"artist": "James Brown", "title": "Road of No Return", "artist_genres": ["funk"]},
    ]

    FALLBACK = [
        {"artist": "JTC", "title": "Valley Road (We Are 1)", "artist_genres": ["acid house"]},
        {"artist": "JTC", "title": "Valley Road (We Are 1) - DJ Qu Remix", "artist_genres": ["acid house"]},
        {"artist": "Bruce Hornsby", "title": "The Valley Road", "artist_genres": ["soft rock"]},
    ]

    JTC_DISCOGS = {
        "title": "JTC - Valley Road (We Are 1)",
        "genres": ["Electronic"],
        "styles": ["Deep House", "Tech House", "Techno"],
    }

    def test_artist_ratio_rejects_mcmurtry_primary_match(self):
        results = score_artist_title_candidates(
            "James T. Cotton",
            "Valley Road (We Are 1)",
            self.PRIMARY,
        )

        self.assertEqual(results, [])

    def test_title_only_fallback_finds_jtc_with_discogs_and_genres(self):
        match = select_spotify_candidate(
            "James T. Cotton",
            "Valley Road (We Are 1)",
            self.PRIMARY,
            self.FALLBACK,
            discogs_data=self.JTC_DISCOGS,
        )

        self.assertIsNotNone(match)
        self.assertEqual(match.item["artist"], "JTC")
        self.assertEqual(match.item["title"], "Valley Road (We Are 1)")

    def test_title_only_fallback_accepts_expected_artist_initials_without_discogs(self):
        match = select_spotify_candidate(
            "James T. Cotton",
            "Valley Road (We Are 1)",
            [],
            [{"artist": "JTC", "title": "Valley Road (We Are 1)"}],
        )

        self.assertIsNotNone(match)
        self.assertEqual(match.item["artist"], "JTC")

    def test_title_only_fallback_rejects_partial_title_match(self):
        results = score_title_only_candidates(
            "James T. Cotton",
            "Valley Road (We Are 1)",
            [{"artist": "Bruce Hornsby", "title": "The Valley Road"}],
            discogs_data=self.JTC_DISCOGS,
        )

        self.assertEqual(results, [])

    def test_title_only_fallback_accepts_version_suffix_with_corroboration(self):
        results = score_title_only_candidates(
            "James T. Cotton",
            "Valley Road (We Are 1)",
            [{"artist": "JTC", "title": "Valley Road (We Are 1) - DJ Qu Remix - Mixed"}],
            discogs_data=self.JTC_DISCOGS,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].item["artist"], "JTC")

    def test_title_only_fallback_is_not_used_when_primary_succeeds(self):
        primary_with_correct = [
            {"artist": "James T. Cotton", "title": "Valley Road (We Are 1)"},
            {"artist": "James McMurtry", "title": "Valley Road"},
        ]
        match = select_spotify_candidate(
            "James T. Cotton",
            "Valley Road (We Are 1)",
            primary_with_correct,
            self.FALLBACK,
            discogs_data=self.JTC_DISCOGS,
        )

        self.assertIsNotNone(match)
        self.assertEqual(match.item["artist"], "James T. Cotton")

    def test_title_only_fallback_skips_short_titles(self):
        match = select_spotify_candidate(
            "Unknown Artist",
            "Glue",
            [],
            [{"artist": "Bicep", "title": "Glue", "artist_genres": ["house"]}],
            discogs_data={"title": "Bicep - Glue", "styles": ["House"], "genres": ["Electronic"]},
        )

        self.assertIsNone(match)

    def test_normal_artist_title_match_unaffected(self):
        match = select_spotify_candidate(
            "Bicep",
            "Glue",
            [{"artist": "Bicep", "title": "Glue"}],
        )

        self.assertIsNotNone(match)
        self.assertEqual(match.item["artist"], "Bicep")

    def test_two_word_artist_requires_both_words(self):
        candidates = [
            {"artist": "James McMurtry", "title": "Levelland"},
            {"artist": "James Cotton", "title": "Levelland Blues"},
        ]
        results = score_artist_title_candidates("James Cotton", "Levelland Blues", candidates)

        self.assertTrue(all(result.item["artist"] == "James Cotton" for result in results))

    def test_three_word_artist_two_matches_accepted(self):
        candidates = [{"artist": "The Chemical Brothers", "title": "Block Rockin Beats"}]
        results = score_artist_title_candidates("Chemical Brothers", "Block Rockin Beats", candidates)

        self.assertEqual(len(results), 1)

    def test_korsakow_title_only_rejects_oh_land(self):
        match = select_spotify_candidate(
            "Korsakow",
            "Sun Of A Gun",
            [],
            [{"artist": "Oh Land", "title": "Sun of a Gun", "artist_genres": ["dansk pop"]}],
            discogs_data={
                "title": "Korsakow / Jan Mattheus - Sun Of A Gun / Rændstrøm",
                "genres": ["Electronic"],
                "styles": ["House", "Deep House"],
            },
        )

        self.assertIsNone(match)

    def test_genre_overlap_can_validate_title_only_when_artist_alias_is_unknown(self):
        match = select_spotify_candidate(
            "Unknown Shazam Alias",
            "Deep Channel",
            [],
            [{"artist": "Studio Alias", "title": "Deep Channel", "artist_genres": ["deep house"]}],
            discogs_data={
                "title": "Obscure Name - Deep Channel",
                "genres": ["Electronic"],
                "styles": ["Deep House"],
            },
        )

        self.assertIsNotNone(match)
        self.assertEqual(match.item["artist"], "Studio Alias")


if __name__ == "__main__":
    unittest.main()
