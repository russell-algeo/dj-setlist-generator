import unittest

from platform_matching import primary_track_platform, select_youtube_candidate


YOUTUBE_URL = "https://www.youtube.com/watch?v=R2bda4X9v4E"
DISCOGS = {"title": "U.S. Collective - Midnight Luv / So Right", "styles": ["Deep House"]}


class PlatformMatchingTests(unittest.TestCase):
    def test_actual_youtube_result_is_corroborated_by_release(self):
        result = select_youtube_candidate("S.I. Collective", "So Right", [
            {"id": "wrong", "title": "Northern Collective - Right in Front of Me, Was You"},
            {"id": "R2bda4X9v4E", "title": "U.S. Collective - So Right"},
        ], discogs_data=DISCOGS)
        self.assertEqual(result["url"], YOUTUBE_URL)
        self.assertEqual(result["match"]["reason"], "discogs_artist_title")

    def test_youtube_first_hit_is_not_automatically_confirmed(self):
        self.assertIsNone(select_youtube_candidate("S.I. Collective", "So Right", [
            {"id": "wrong", "title": "Northern Collective - Right in Front of Me, Was You"}]))

    def test_artist_disagreement_needs_corroboration(self):
        video = [{"id": "R2bda4X9v4E", "title": "U.S. Collective - So Right"}]
        self.assertIsNone(select_youtube_candidate("S.I. Collective", "So Right", video))
        self.assertIsNone(select_youtube_candidate("S.I. Collective", "So Right", video,
                          discogs_data={"title": "U.S. Collective - Different Track"}))

    def test_unknown_legacy_spotify_does_not_outrank_confirmed_youtube(self):
        metadata = {"spotify_url": "https://open.spotify.com/track/legacy", "youtube_url": YOUTUBE_URL,
                    "platform_matches": {"youtube": {"status": "matched", "url": YOUTUBE_URL}}}
        self.assertEqual(primary_track_platform(metadata), "youtube")

    def test_rejected_or_missing_evidence_cannot_be_a_primary_link(self):
        for matches in [{}, {"spotify": {"status": "unverified"}},
                        {"spotify": {"status": "matched", "url": "different"}}]:
            self.assertIsNone(primary_track_platform({"spotify_url": "https://open.spotify.com/track/wrong",
                                                      "link_matching_version": 2, "platform_matches": matches}))

    def test_existing_legacy_links_are_not_relabelled_as_confirmed(self):
        self.assertEqual(primary_track_platform({"spotify_url": "https://open.spotify.com/track/legacy"}), "spotify")


if __name__ == "__main__":
    unittest.main()
