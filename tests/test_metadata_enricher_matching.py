import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from metadata_enricher import MetadataEnricher
from output_formatter import serialize_track
from platform_matching import primary_track_platform
from set_explorer_formatter import render_set_explorer_html


SPOTIFY_URL = "https://open.spotify.com/track/3cuhpRVEXe8tGKDGsYZrR0"
YOUTUBE_URL = "https://www.youtube.com/watch?v=R2bda4X9v4E"
DISCOGS = {"url": "https://www.discogs.com/release/437605-US-Collective-Midnight-Luv-So-Right",
           "title": "U.S. Collective - Midnight Luv / So Right", "styles": ["Deep House"]}
# Unit-test provider stub already validated; the live matcher is covered separately.
DISCOGS["match"] = {"status": "matched", "url": DISCOGS["url"], "matching_version": 1}


def spotify_item(artist="Northern Collective", title="Right in Front of Me, Was You", isrc=None):
    return {"name": title, "artists": [{"name": artist, "id": "artist"}],
            "external_urls": {"spotify": SPOTIFY_URL}, "external_ids": {"isrc": isrc}}


def enricher():
    obj = MetadataEnricher.__new__(MetadataEnricher)
    obj.spotify_enabled = obj.youtube_enabled = obj.discogs_enabled = True
    obj.spotify = MagicMock()
    obj._get_artist_profile = MagicMock(return_value={"genres": ["deep house"]})
    obj._search_discogs_rich = MagicMock(return_value=DISCOGS)
    return obj


def track():
    return SimpleNamespace(title="So Right", artist="S.I. Collective", isrc=None,
                           confidence="LOW", start_time=1995, end_time=2250, detection_count=8,
                           cluster_density=0.5, cluster_span=16)


class MetadataEnricherMatchingTests(unittest.TestCase):
    def test_reported_case_through_enrichment_serialization_and_html(self):
        obj = enricher()
        obj.spotify.search.return_value = {"tracks": {"items": [spotify_item()]}}
        with patch("metadata_enricher.yt_dlp.YoutubeDL") as youtube:
            youtube.return_value.__enter__.return_value.extract_info.return_value = {"entries": [
                {"id": "wrong", "title": "Northern Collective - Right in Front of Me, Was You"},
                {"id": "R2bda4X9v4E", "title": "U.S. Collective - So Right"},
            ]}
            metadata = obj.enrich_track(track())
        self.assertIsNone(metadata["spotify_url"])
        self.assertEqual(metadata["youtube_url"], YOUTUBE_URL)
        self.assertEqual(metadata["platform_matches"]["spotify"]["status"], "unverified")
        self.assertEqual(primary_track_platform(metadata), "youtube")
        item = {"track": track(), "metadata": metadata}
        serialized = json.loads(json.dumps(serialize_track(item, 9, "")))
        self.assertEqual(serialized["link_matching_version"], 2)
        self.assertEqual(serialized["platform_matches"]["youtube"]["artists"], ["U.S. Collective"])
        self.assertEqual(serialized["platform_matches"]["youtube"]["corroboration"]["url"], DISCOGS["url"])
        html = render_set_explorer_html(Path("/tmp/nonexistent-setlist-fixture"), [item],
                 {"title": "Fred Everything - DJ Set 01 [2001]", "duration": 4408}, "fixture")
        self.assertIn(f'href="{YOUTUBE_URL}"', html)
        self.assertNotIn('data-track-id="3cuhpRVEXe8tGKDGsYZrR0"', html)
        self.assertNotIn(SPOTIFY_URL, html)

    def test_valid_spotify_fallback_is_retained_with_identity_evidence(self):
        obj = enricher()
        obj.spotify.search.side_effect = [{"tracks": {"items": [spotify_item()]}},
                                          {"tracks": {"items": [spotify_item("U.S. Collective", "So Right")]}}]
        result = obj._search_spotify_rich("So Right", "S.I. Collective", discogs_data=DISCOGS)
        self.assertEqual(result["match"]["status"], "matched")
        self.assertEqual(result["match"]["title"], "So Right")
        self.assertEqual(result["match"]["artists"], ["U.S. Collective"])
        self.assertEqual(result["match"]["corroboration"]["title"], DISCOGS["title"])

    def test_isrc_search_result_must_actually_carry_the_requested_isrc(self):
        obj = enricher()
        obj.spotify.search.return_value = {"tracks": {"items": [spotify_item(isrc="GBXXX0000001")]}}
        self.assertIsNone(obj._search_spotify_rich("So Right", "S.I. Collective", isrc="GBXXX0000002"))
        obj.spotify.search.return_value = {"tracks": {"items": [spotify_item("U.S. Collective", "So Right", isrc="GBXXX0000002")]}}
        self.assertEqual(obj._search_spotify_rich("Alias", "Alias", isrc="GBXXX0000002")["match"]["reason"], "isrc")

    def test_provider_failure_leaves_no_confirmed_link(self):
        obj = enricher()
        obj.spotify.search.side_effect = RuntimeError("offline")
        with patch("metadata_enricher.yt_dlp.YoutubeDL", side_effect=RuntimeError("offline")):
            metadata = obj.enrich_track(track())
        self.assertIsNone(metadata["spotify_url"])
        self.assertIsNone(metadata["youtube_url"])
        self.assertEqual(metadata["platform_matches"]["youtube"]["status"], "unverified")


if __name__ == "__main__":
    unittest.main()
