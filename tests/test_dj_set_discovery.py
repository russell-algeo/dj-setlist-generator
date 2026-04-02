import unittest

from dj_set_discovery import DiscoveredSet, _deduplicate_near_duplicates, _filter_and_map


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

        discovered_sets = _filter_and_map(raw_results, "DJ Test")

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

        deduped_sets = _deduplicate_near_duplicates(discovered_sets, "DJ Test")

        self.assertEqual(1, len(deduped_sets))
        self.assertEqual("youtube", deduped_sets[0].platform)
        self.assertEqual("https://www.youtube.com/watch?v=yt123", deduped_sets[0].url)


if __name__ == "__main__":
    unittest.main()
