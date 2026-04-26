import unittest

from dj_set_discovery import (
    DiscoveredSet,
    _build_search_queries,
    _deduplicate_near_duplicates,
    _ensure_source_links,
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
        self.assertEqual(2, len(discovered_sets[0].source_links))
        self.assertEqual(
            {"soundcloud", "youtube"},
            {link["platform"] for link in discovered_sets[0].source_links},
        )

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
        self.assertEqual(2, len(deduped_sets[0].source_links))

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

    def test_near_duplicate_dedup_accepts_exact_duration_low_similarity_match(self):
        discovered_sets = [
            DiscoveredSet(
                url="https://www.youtube.com/watch?v=ra500",
                title="RA.500 Ben UFO",
                platform="youtube",
                event="Resident Advisor",
                year="2015",
                duration_minutes=120,
            ),
            DiscoveredSet(
                url="https://soundcloud.com/resident-advisor/ra500-ben-ufo",
                title="Ben UFO - Resident Advisor 500 (28 December 2015)",
                platform="soundcloud",
                event="Resident Advisor",
                year="2015",
                duration_minutes=120,
            ),
        ]

        deduped_sets = _deduplicate_near_duplicates(discovered_sets, ["Ben UFO"])

        self.assertEqual(1, len(deduped_sets))
        self.assertEqual("youtube", deduped_sets[0].platform)
        self.assertEqual(2, len(deduped_sets[0].source_links))
        alternate = next(link for link in deduped_sets[0].source_links if not link["is_primary"])
        self.assertEqual("near_exact_duration_context_match", alternate["metadata"]["discovery_match"]["reason"])

    def test_near_duplicate_dedup_keeps_manual_review_grade_false_positive_separate(self):
        discovered_sets = [
            DiscoveredSet(
                url="https://www.youtube.com/watch?v=epic028",
                title="Raresh Rush - Epic 028 (Home Mix)",
                platform="youtube",
                event="Resident Advisor",
                year=None,
                duration_minutes=None,
            ),
            DiscoveredSet(
                url="https://soundcloud.com/example/raresh-rush-epic-021",
                title="Raresh Rush - EPIC 021 (Studio Mix)",
                platform="soundcloud",
                event="Example",
                year=None,
                duration_minutes=61,
            ),
        ]

        deduped_sets = _deduplicate_near_duplicates(discovered_sets, ["Raresh"])
        _ensure_source_links(deduped_sets)

        self.assertEqual(2, len(deduped_sets))
        self.assertTrue(all(len(item.source_links) == 1 for item in deduped_sets))

    def test_near_duplicate_dedup_rejects_same_series_different_explicit_date(self):
        discovered_sets = [
            DiscoveredSet(
                url="https://www.youtube.com/watch?v=chez1",
                title="Chez Damier @TheLotRadio 08-01-2025",
                platform="youtube",
                event="The Lot Radio",
                year="2025",
                duration_minutes=120,
            ),
            DiscoveredSet(
                url="https://soundcloud.com/thelotradio/chez-damier-the-lot-radio-08",
                title="Chez Damier @ The Lot Radio 08-24-2025",
                platform="soundcloud",
                event="The Lot Radio",
                year="2025",
                duration_minutes=122,
            ),
        ]

        deduped_sets = _deduplicate_near_duplicates(discovered_sets, ["Chez Damier"])

        self.assertEqual(2, len(deduped_sets))

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
