import json
import tempfile
import unittest

from scripts.backfill_set_source_links import (
    ACCEPTED,
    AMBIGUOUS,
    REJECTED,
    Candidate,
    KnownSet,
    load_reviewed_matches,
    score_candidate,
)


class BackfillSetSourceLinksTests(unittest.TestCase):
    def test_accepts_exact_opposite_platform_match(self):
        known = KnownSet(
            id="set-1",
            slug="channel-one-boiler-room",
            title="Channel One Boiler Room x Notting Hill Carnival 2017 DJ Set",
            artist_name="Channel One",
            source_platform="youtube",
            source_url="https://www.youtube.com/watch?v=abc",
            duration_seconds=4230,
            uploader="Boiler Room",
        )
        candidate = Candidate(
            platform="soundcloud",
            url="https://soundcloud.com/platform/channel-one-boiler-room-x-notting-hill-carnival-2017-dj-set",
            title="Channel One Boiler Room x Notting Hill Carnival 2017 DJ Set",
            duration_seconds=4232,
            uploader="Boiler Room",
            raw={},
        )

        decision = score_candidate(known, candidate)

        self.assertEqual(ACCEPTED, decision["status"])
        self.assertEqual("strong_title_duration_match", decision["reason"])

    def test_rejects_wrong_artist_weak_match(self):
        known = KnownSet(
            id="set-2",
            slug="lone-live-from-home",
            title="Lone DJ Set Live From His Home",
            artist_name="Lone",
            source_platform="youtube",
            source_url="https://www.youtube.com/watch?v=abc",
            duration_seconds=4956,
            uploader="DJ Mag",
        )
        candidate = Candidate(
            platform="soundcloud",
            url="https://soundcloud.com/exeatmusic/exeat-live-from-his-home-studio-audio",
            title="EXEAT LIVE FROM HIS HOME STUDIO 2021 [DJ SET]",
            duration_seconds=4249,
            uploader="EXEAT",
            raw={},
        )

        decision = score_candidate(known, candidate)

        self.assertEqual(REJECTED, decision["status"])

    def test_marks_plausible_but_not_strong_match_ambiguous(self):
        known = KnownSet(
            id="set-3",
            slug="test",
            title="DJ Test Live at Warehouse 2024",
            artist_name="DJ Test",
            source_platform="soundcloud",
            source_url="https://soundcloud.com/test/warehouse",
            duration_seconds=3600,
            uploader="Warehouse",
        )
        candidate = Candidate(
            platform="youtube",
            url="https://www.youtube.com/watch?v=abc",
            title="DJ Test Warehouse Session 2024",
            duration_seconds=3800,
            uploader="DJ Test",
            raw={},
        )

        decision = score_candidate(known, candidate)

        self.assertEqual(AMBIGUOUS, decision["status"])
        self.assertEqual("calibrated_duration_artist_match", decision["reason"])

    def test_rejects_same_series_with_different_artist(self):
        known = KnownSet(
            id="set-4",
            slug="yoyaku-djulz",
            title="Yoyaku instore session with D'Julz",
            artist_name="D'Julz",
            source_platform="youtube",
            source_url="https://www.youtube.com/watch?v=abc",
            duration_seconds=3600,
            uploader="Yoyaku",
        )
        candidate = Candidate(
            platform="soundcloud",
            url="https://soundcloud.com/yoyaku/yoyaku-instore-session-lunaludmila",
            title="Yoyaku Instore Session with Luna Ludmila",
            duration_seconds=3560,
            uploader="Yoyaku",
            raw={},
        )

        decision = score_candidate(known, candidate)

        self.assertEqual(REJECTED, decision["status"])
        self.assertEqual("missing_artist_overlap", decision["reason"])

    def test_rejects_shared_first_name_when_distinctive_artist_token_missing(self):
        known = KnownSet(
            id="set-5",
            slug="ben-ufo-boiler-room",
            title="Ben UFO Boiler Room London DJ Set",
            artist_name="Ben UFO",
            source_platform="youtube",
            source_url="https://www.youtube.com/watch?v=abc",
            duration_seconds=2803,
            uploader="Boiler Room",
        )
        candidate = Candidate(
            platform="soundcloud",
            url="https://soundcloud.com/platform/ben-sims",
            title="Ben Sims Boiler Room London DJ Set",
            duration_seconds=3594,
            uploader="Boiler Room",
            raw={},
        )

        decision = score_candidate(known, candidate)

        self.assertEqual(REJECTED, decision["status"])

    def test_rejects_same_series_title_when_artist_is_different(self):
        known = KnownSet(
            id="set-5b",
            slug="ben-ufo-dekmantel",
            title="Ben UFO Boiler Room x Dekmantel x IR DJ Set",
            artist_name="Ben UFO",
            source_platform="youtube",
            source_url="https://www.youtube.com/watch?v=abc",
            duration_seconds=3600,
            uploader="Boiler Room",
        )
        candidate = Candidate(
            platform="soundcloud",
            url="https://soundcloud.com/platform/dixon-dekmantel",
            title="Dixon Boiler Room x Dekmantel x IR DJ Set",
            duration_seconds=3605,
            uploader="Boiler Room",
            raw={},
        )

        decision = score_candidate(known, candidate)

        self.assertEqual(REJECTED, decision["status"])
        self.assertEqual("missing_artist_overlap", decision["reason"])

    def test_part_marker_mismatch_requires_manual_review(self):
        known = KnownSet(
            id="set-6",
            slug="daniel-bell-tresor",
            title="Daniel Bell, John Tejada, Luciano, Todd Bodine @ 13 Years Tresor, Berlin - 2004-03-13",
            artist_name="Daniel Bell",
            source_platform="soundcloud",
            source_url="https://soundcloud.com/example",
            duration_seconds=3600,
            uploader="Example",
        )
        candidate = Candidate(
            platform="youtube",
            url="https://www.youtube.com/watch?v=abc",
            title="Daniel Bell, John Tejada, Luciano, Todd Bodine @ 13 Years Tresor, Berlin - 2004-03-13 (Part 2)",
            duration_seconds=3600,
            uploader="Example",
            raw={},
        )

        decision = score_candidate(known, candidate)

        self.assertEqual(AMBIGUOUS, decision["status"])
        self.assertEqual("calibrated_exact_duration_series_match", decision["reason"])

    def test_rejects_same_series_different_explicit_date(self):
        known = KnownSet(
            id="set-7",
            slug="chez-damier-lot-radio",
            title="Chez Damier @TheLotRadio 08-01-2025",
            artist_name="Chez Damier",
            source_platform="youtube",
            source_url="https://www.youtube.com/watch?v=abc",
            duration_seconds=7200,
            uploader="The Lot Radio",
        )
        candidate = Candidate(
            platform="soundcloud",
            url="https://soundcloud.com/thelotradio/chez-damier-the-lot-radio-08",
            title="Chez Damier @ The Lot Radio 08-24-2025",
            duration_seconds=7316,
            uploader="The Lot Radio",
            raw={},
        )

        decision = score_candidate(known, candidate)

        self.assertEqual(REJECTED, decision["status"])
        self.assertEqual("date_conflict", decision["reason"])

    def test_rejects_same_year_different_month(self):
        known = KnownSet(
            id="set-7b",
            slug="black-loops-january",
            title="Harrison BDP b2b Black Loops - January 2022",
            artist_name="Black Loops",
            source_platform="youtube",
            source_url="https://www.youtube.com/watch?v=abc",
            duration_seconds=3597,
            uploader="Example",
        )
        candidate = Candidate(
            platform="soundcloud",
            url="https://soundcloud.com/example/black-loops-may",
            title="Aterral - Black Loops | HÖR - May 31 / 2022",
            duration_seconds=3339,
            uploader="HÖR BERLIN",
            raw={},
        )

        decision = score_candidate(known, candidate)

        self.assertEqual(REJECTED, decision["status"])
        self.assertEqual("month_conflict", decision["reason"])

    def test_accepts_same_date_written_differently(self):
        known = KnownSet(
            id="set-8",
            slug="chez-damier-lot-radio",
            title="Chez Damier @ The Lot Radio (June 2nd 2019)",
            artist_name="Chez Damier",
            source_platform="youtube",
            source_url="https://www.youtube.com/watch?v=abc",
            duration_seconds=7200,
            uploader="The Lot Radio",
        )
        candidate = Candidate(
            platform="soundcloud",
            url="https://soundcloud.com/thelotradio/chez-damier-the-lot-radio-06-02-2019",
            title="Chez Damier @ The Lot Radio 06 - 02 - 2019",
            duration_seconds=7201,
            uploader="The Lot Radio",
            raw={},
        )

        decision = score_candidate(known, candidate)

        self.assertEqual(ACCEPTED, decision["status"])

    def test_accepts_reviewed_positive_with_low_title_similarity_but_exact_duration(self):
        known = KnownSet(
            id="set-9",
            slug="ra-500-ben-ufo",
            title="RA.500 Ben UFO",
            artist_name="Ben UFO",
            source_platform="youtube",
            source_url="https://www.youtube.com/watch?v=abc",
            duration_seconds=7200,
            uploader="Resident Advisor",
        )
        candidate = Candidate(
            platform="soundcloud",
            url="https://soundcloud.com/resident-advisor/ra500-ben-ufo",
            title="Ben UFO - Resident Advisor 500 (28 December 2015)",
            duration_seconds=7200,
            uploader="Resident Advisor",
            raw={},
        )

        decision = score_candidate(known, candidate)

        self.assertEqual(ACCEPTED, decision["status"])
        self.assertEqual("near_exact_duration_context_match", decision["reason"])

    def test_rejects_high_similarity_numeric_series_conflict_without_duration(self):
        known = KnownSet(
            id="set-10",
            slug="raresh-epic-028",
            title="Raresh Rush - Epic 028 (Home Mix)",
            artist_name="Raresh",
            source_platform="youtube",
            source_url="https://www.youtube.com/watch?v=abc",
            duration_seconds=None,
            uploader="Resident Advisor",
        )
        candidate = Candidate(
            platform="soundcloud",
            url="https://soundcloud.com/example/raresh-rush-epic-021",
            title="Raresh Rush - EPIC 021 (Studio Mix)",
            duration_seconds=3678,
            uploader="Example",
            raw={},
        )

        decision = score_candidate(known, candidate)

        self.assertEqual(REJECTED, decision["status"])
        self.assertEqual("numeric_series_conflict", decision["reason"])

    def test_load_reviewed_matches_only_loads_manually_accepted_rows(self):
        payload = [
            {
                "review_status": ACCEPTED,
                "set_slug": "known-set",
                "candidate": {
                    "platform": "soundcloud",
                    "url": "https://soundcloud.com/example/set",
                    "title": "Known Set",
                    "duration_seconds": 3600,
                    "uploader": "Example",
                },
                "decision": {"score": 0.99, "reason": "manual_review"},
            },
            {
                "review_status": "pending",
                "set_slug": "ignored-set",
                "candidate": {
                    "platform": "youtube",
                    "url": "https://www.youtube.com/watch?v=abc",
                    "title": "Ignored Set",
                },
            },
        ]
        with tempfile.NamedTemporaryFile("w+", suffix=".json") as handle:
            json.dump(payload, handle)
            handle.flush()

            reviewed = load_reviewed_matches(handle.name)

        self.assertEqual(1, len(reviewed))
        self.assertEqual("known-set", reviewed[0].set_slug)
        self.assertEqual("https://soundcloud.com/example/set", reviewed[0].candidate.url)


if __name__ == "__main__":
    unittest.main()
