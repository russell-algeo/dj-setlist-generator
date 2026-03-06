import json
import tempfile
import unittest
from pathlib import Path

from false_positive_policy import FalsePositivePolicy


class FalsePositivePolicyTests(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.rules_path = Path(self._tempdir.name) / "false_positive_rules.json"

    def tearDown(self):
        self._tempdir.cleanup()

    def _write_rules(self, rules):
        self.rules_path.write_text(json.dumps(rules), encoding="utf-8")

    def test_matches_by_shazam_track_id(self):
        self._write_rules(
            [
                {
                    "id": "fp-track-id",
                    "reason": "Known bad Shazam hit",
                    "shazam_track_id": "12345",
                }
            ]
        )

        policy = FalsePositivePolicy.load_from_path(self.rules_path)
        match = policy.match("Different Artist", "Different Title", "12345")

        self.assertIsNotNone(match)
        self.assertEqual("fp-track-id", match.rule.id)
        self.assertEqual("shazam_track_id", match.match_type)

    def test_matches_by_artist_title_fallback(self):
        self._write_rules(
            [
                {
                    "id": "fp-artist-title",
                    "reason": "Known bad fallback match",
                    "artist": "Andy Compton",
                    "title": "That Acid Track",
                }
            ]
        )

        policy = FalsePositivePolicy.load_from_path(self.rules_path)
        match = policy.match("andy  compton", "That Acid Track!", None)

        self.assertIsNotNone(match)
        self.assertEqual("fp-artist-title", match.rule.id)
        self.assertEqual("artist_title", match.match_type)

    def test_prefers_shazam_track_id_before_artist_title(self):
        self._write_rules(
            [
                {
                    "id": "fp-by-id",
                    "reason": "ID match should win",
                    "shazam_track_id": "abc123",
                    "artist": "Different Artist",
                    "title": "Different Title",
                },
                {
                    "id": "fp-by-name",
                    "reason": "Fallback artist/title rule",
                    "artist": "Known Artist",
                    "title": "Known Title",
                },
            ]
        )

        policy = FalsePositivePolicy.load_from_path(self.rules_path)
        match = policy.match("Known Artist", "Known Title", "abc123")

        self.assertIsNotNone(match)
        self.assertEqual("fp-by-id", match.rule.id)
        self.assertEqual("shazam_track_id", match.match_type)

    def test_rejects_duplicate_shazam_track_ids(self):
        self._write_rules(
            [
                {
                    "id": "fp-1",
                    "reason": "First rule",
                    "shazam_track_id": "dup-id",
                },
                {
                    "id": "fp-2",
                    "reason": "Second rule",
                    "shazam_track_id": "dup-id",
                },
            ]
        )

        with self.assertRaisesRegex(ValueError, "Duplicate false-positive shazam_track_id"):
            FalsePositivePolicy.load_from_path(self.rules_path)

    def test_rejects_duplicate_artist_title_rules(self):
        self._write_rules(
            [
                {
                    "id": "fp-1",
                    "reason": "First rule",
                    "artist": "Andy Compton",
                    "title": "That Acid Track",
                },
                {
                    "id": "fp-2",
                    "reason": "Second rule",
                    "artist": "andy-compton",
                    "title": "That acid track!",
                },
            ]
        )

        with self.assertRaisesRegex(ValueError, "Duplicate false-positive artist/title match"):
            FalsePositivePolicy.load_from_path(self.rules_path)
