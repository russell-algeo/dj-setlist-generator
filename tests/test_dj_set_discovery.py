import unittest

from dj_set_discovery import (
    DiscoveredSet,
    _build_search_queries,
    _deduplicate_near_duplicates,
    _filter_and_map,
    _should_reuse_cached_results,
)


class DjSetDiscoveryDedupTests(unittest.TestCase):
    def test_filter_and_map_prefers_youtube_on_exact_title_collision(self):
        raw_results = [
            {
                "title": "DJ Test Boiler Room NYC 2024",
                "channel": "DJ Test",
                "duration": 3600,
                "webpage_url": "https://soundcloud.com/dj-test/boiler-room-nyc-2024",
                "upload_date": "20240102",
            },
            {
                "title": "DJ Test Boiler Room NYC 2024",
                "channel": "DJ Test",
                "duration": 3600,
                "webpage_url": "https://www.youtube.com/watch?v=yt123",
                "upload_date": "20240103",
            },
        ]

        discovered_sets = _filter_and_map(raw_results, ["DJ Test"])

        self.assertEqual(1, len(discovered_sets))
        self.assertEqual("youtube", discovered_sets[0].platform)
        self.assertEqual("https://www.youtube.com/watch?v=yt123", discovered_sets[0].url)

    def test_near_duplicate_dedup_prefers_youtube_over_soundcloud(self):
        discovered_sets = [
            DiscoveredSet(
                url="https://soundcloud.com/dj-test/boiler-room-nyc-2024",
                title="DJ Test Boiler Room NYC 2024",
                platform="soundcloud",
                event="Boiler Room",
                year="2024",
                duration_minutes=60,
            ),
            DiscoveredSet(
                url="https://www.youtube.com/watch?v=yt123",
                title="DJ Test live at Boiler Room NYC 2024",
                platform="youtube",
                event="Boiler Room",
                year="2024",
                duration_minutes=61,
            ),
        ]

        deduped_sets = _deduplicate_near_duplicates(discovered_sets, ["DJ Test"])

        self.assertEqual(1, len(deduped_sets))
        self.assertEqual("youtube", deduped_sets[0].platform)
        self.assertEqual("https://www.youtube.com/watch?v=yt123", deduped_sets[0].url)

    def test_filter_and_map_accepts_alias_matches(self):
        raw_results = [
            {
                "title": "Danilo Plessow at Dekmantel 2024",
                "channel": "Dekmantel",
                "duration": 3600,
                "webpage_url": "https://www.youtube.com/watch?v=alias123",
                "upload_date": "20240801",
            },
        ]

        discovered_sets = _filter_and_map(raw_results, ["Motor City Drum Ensemble", "Danilo Plessow"])

        self.assertEqual(1, len(discovered_sets))
        self.assertEqual("https://www.youtube.com/watch?v=alias123", discovered_sets[0].url)

    def test_build_search_queries_includes_aliases(self):
        queries = _build_search_queries(["Motor City Drum Ensemble", "Danilo Plessow"])

        self.assertTrue(any('"Motor City Drum Ensemble"' in query for query in queries))
        self.assertTrue(any('"Danilo Plessow"' in query for query in queries))

    def test_near_duplicate_dedup_strips_alias_tokens(self):
        discovered_sets = [
            DiscoveredSet(
                url="https://soundcloud.com/mcde/live-from-lost-village",
                title="Live from Lost Village - Danilo Plessow [MCDE]",
                platform="soundcloud",
                event="Lost Village",
                year="2024",
                duration_minutes=60,
            ),
            DiscoveredSet(
                url="https://www.youtube.com/watch?v=mcde123",
                title="Motor City Drum Ensemble live from Lost Village",
                platform="youtube",
                event="Lost Village",
                year="2024",
                duration_minutes=61,
            ),
        ]

        deduped_sets = _deduplicate_near_duplicates(
            discovered_sets,
            ["Motor City Drum Ensemble", "Danilo Plessow", "MCDE"],
        )

        self.assertEqual(1, len(deduped_sets))
        self.assertEqual("youtube", deduped_sets[0].platform)

    def test_cache_reuse_rejects_alias_mismatches(self):
        self.assertTrue(
            _should_reuse_cached_results(
                ["Motor City Drum Ensemble", "Danilo Plessow"],
                ["Motor City Drum Ensemble", "Danilo Plessow"],
            )
        )
        self.assertFalse(
            _should_reuse_cached_results(
                ["Motor City Drum Ensemble"],
                ["Motor City Drum Ensemble", "Danilo Plessow"],
            )
        )
        self.assertFalse(_should_reuse_cached_results(None, ["Motor City Drum Ensemble"]))


if __name__ == "__main__":
    unittest.main()
