import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

if "dotenv" not in sys.modules:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_stub

if "shazamio" not in sys.modules:
    shazamio_stub = types.ModuleType("shazamio")

    class _Shazam:
        def __init__(self, *args, **kwargs):
            pass

    class _HTTPClient:
        def __init__(self, *args, **kwargs):
            pass

    shazamio_stub.Shazam = _Shazam
    shazamio_stub.HTTPClient = _HTTPClient
    sys.modules["shazamio"] = shazamio_stub

if "aiohttp_retry" not in sys.modules:
    aiohttp_retry_stub = types.ModuleType("aiohttp_retry")

    class _JitterRetry:
        def __init__(self, *args, **kwargs):
            pass

    aiohttp_retry_stub.JitterRetry = _JitterRetry
    sys.modules["aiohttp_retry"] = aiohttp_retry_stub

from config import Config
import setlist_builder
import false_positive_policy
from setlist_builder import SetlistBuilder, Track

from track_recognizer import Recognition


def _make_rec(
    segment_index,
    artist=None,
    title=None,
    shazam_track_id=None,
    recognized=True,
    timestamp=None,
):
    return SimpleNamespace(
        timestamp=float(segment_index * 15 if timestamp is None else timestamp),
        track_title=title,
        artist=artist,
        shazam_track_id=shazam_track_id,
        recognized=recognized,
        segment_index=segment_index,
    )


def _make_track(
    segment_indices,
    artist="Known Artist",
    title="Known Track",
    start_time=None,
    end_time=None,
    confidence="LOW",
    detection_count=None,
    shazam_track_id="known-track",
    cluster_density=0.5,
    cluster_span=None,
):
    segment_indices = list(segment_indices)
    if start_time is None:
        start_time = float(min(segment_indices) * 15) if segment_indices else 0.0
    if end_time is None:
        end_time = float(max(segment_indices) * 15 + 30) if segment_indices else 30.0
    if detection_count is None:
        detection_count = len(segment_indices)
    if cluster_span is None:
        cluster_span = (max(segment_indices) - min(segment_indices) + 1) if segment_indices else 0

    return Track(
        title=title,
        artist=artist,
        start_time=start_time,
        end_time=end_time,
        confidence=confidence,
        detection_count=detection_count,
        shazam_track_id=shazam_track_id,
        cluster_density=cluster_density,
        cluster_span=cluster_span,
        segment_indices=segment_indices,
    )


class SetlistBuilderFalsePositiveTests(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.rules_path = Path(self._tempdir.name) / "false_positive_rules.json"
        self._original_rules_path = false_positive_policy._RULES_PATH
        self._original_singleton = false_positive_policy._singleton_policy
        self._original_unknown_gap_size = Config.MIN_UNKNOWN_GAP_SIZE
        false_positive_policy._RULES_PATH = self.rules_path
        false_positive_policy._singleton_policy = None  # reset singleton so it reloads
        Config.MIN_UNKNOWN_GAP_SIZE = 3
        self._write_rules([])

    def tearDown(self):
        false_positive_policy._RULES_PATH = self._original_rules_path
        false_positive_policy._singleton_policy = self._original_singleton
        Config.MIN_UNKNOWN_GAP_SIZE = self._original_unknown_gap_size
        self._tempdir.cleanup()

    def _write_rules(self, rules):
        self.rules_path.write_text(json.dumps(rules), encoding="utf-8")
        false_positive_policy._singleton_policy = None  # reset singleton to pick up new rules

    def test_suppresses_false_positive_before_overlap_resolution(self):
        self._write_rules(
            [
                {
                    "id": "bad-track",
                    "reason": "Recurring false positive",
                    "shazam_track_id": "fp-1",
                }
            ]
        )

        builder = SetlistBuilder()
        recognitions = [
            _make_rec(0, "Bad Artist", "Bad Track", "fp-1"),
            _make_rec(1, "Bad Artist", "Bad Track", "fp-1"),
            _make_rec(2, "Bad Artist", "Bad Track", "fp-1"),
            _make_rec(3, "Bad Artist", "Bad Track", "fp-1"),
            _make_rec(1, "Real Artist", "Real Track", "real-1"),
            _make_rec(2, "Real Artist", "Real Track", "real-1"),
            _make_rec(3, "Real Artist", "Real Track", "real-1"),
        ]

        tracks = builder.build_setlist(recognitions)

        self.assertEqual(1, len(tracks))
        self.assertEqual("Real Artist", tracks[0].artist)
        self.assertEqual("Real Track", tracks[0].title)
        self.assertEqual(1, len(builder._last_suppressed_false_positives))
        self.assertEqual("bad-track", builder._last_suppressed_false_positives[0].rule_id)

    def test_suppressed_only_tracks_backfill_unknown_gap(self):
        self._write_rules(
            [
                {
                    "id": "bad-track",
                    "reason": "Recurring false positive",
                    "shazam_track_id": "fp-1",
                }
            ]
        )

        builder = SetlistBuilder()
        recognitions = [
            _make_rec(0, "Bad Artist", "Bad Track", "fp-1"),
            _make_rec(1, "Bad Artist", "Bad Track", "fp-1"),
            _make_rec(2, "Bad Artist", "Bad Track", "fp-1"),
        ]

        tracks = builder.build_setlist(recognitions)
        all_tracks = builder.add_unknown_tracks(tracks, recognitions)

        self.assertEqual([], tracks)
        self.assertEqual(1, len(all_tracks))
        self.assertEqual("Unknown", all_tracks[0].artist)
        self.assertEqual("Unknown Track", all_tracks[0].title)
        self.assertEqual([0, 1, 2], all_tracks[0].segment_indices)

    def test_high_confidence_false_positive_is_still_suppressed(self):
        self._write_rules(
            [
                {
                    "id": "bad-track",
                    "reason": "Recurring false positive",
                    "artist": "Bad Artist",
                    "title": "Bad Track",
                }
            ]
        )

        builder = SetlistBuilder()
        recognitions = [
            _make_rec(index, "Bad Artist", "Bad Track", "fp-1")
            for index in range(15)
        ]

        tracks = builder.build_setlist(recognitions)

        self.assertEqual([], tracks)
        self.assertEqual(1, len(builder._last_suppressed_false_positives))
        self.assertEqual(15, builder._last_suppressed_false_positives[0].detection_count)

    def test_checkpoint_resume_recognitions_are_filtered_the_same_way(self):
        self._write_rules(
            [
                {
                    "id": "bad-track",
                    "reason": "Recurring false positive",
                    "shazam_track_id": "fp-1",
                }
            ]
        )

        direct_builder = SetlistBuilder()
        checkpoint_builder = SetlistBuilder()

        direct_recognitions = [
            _make_rec(0, "Bad Artist", "Bad Track", "fp-1"),
            _make_rec(1, "Bad Artist", "Bad Track", "fp-1"),
            _make_rec(2, "Bad Artist", "Bad Track", "fp-1"),
            _make_rec(3, "Bad Artist", "Bad Track", "fp-1"),
            _make_rec(1, "Real Artist", "Real Track", "real-1"),
            _make_rec(2, "Real Artist", "Real Track", "real-1"),
            _make_rec(3, "Real Artist", "Real Track", "real-1"),
        ]

        checkpoint_payload = [
            {
                "timestamp": rec.timestamp,
                "track_title": rec.track_title,
                "artist": rec.artist,
                "shazam_track_id": rec.shazam_track_id,
                "raw_data": None,
                "recognized": rec.recognized,
                "segment_index": rec.segment_index,
                "extra_field": "ignored",
            }
            for rec in direct_recognitions
        ]
        checkpoint_recognitions = [
            Recognition.from_checkpoint(item)
            for item in checkpoint_payload
        ]

        direct_tracks = direct_builder.build_setlist(direct_recognitions)
        checkpoint_tracks = checkpoint_builder.build_setlist(checkpoint_recognitions)

        self.assertEqual(
            [(track.artist, track.title) for track in direct_tracks],
            [(track.artist, track.title) for track in checkpoint_tracks],
        )

    def test_unknown_gaps_skip_holes_inside_known_cluster_span(self):
        builder = SetlistBuilder()
        miles_hits = {739, 740, 747, 748, 754, 755, 761}
        hacker_hits = {820, 822, 824, 825, 826, 827, 828, 829, 830, 831, 832, 833}
        flesh_hits = {821, 823}
        recognitions = []

        for index in range(730, 834):
            if index in miles_hits:
                recognitions.append(_make_rec(index, "Miles Maeda", "Tell Me Why", "miles-1"))
            elif index in hacker_hits:
                recognitions.append(_make_rec(index, "The Hacker", "Sequenced Life", "hacker-1"))
            elif index in flesh_hits:
                recognitions.append(
                    _make_rec(index, "The Hacker", "Flesh & Bone (feat. Perspects)", "hacker-2")
                )
            else:
                recognitions.append(_make_rec(index, recognized=False))

        tracks = builder.build_setlist(recognitions)
        all_tracks = builder.add_unknown_tracks(tracks, recognitions)

        unknown_tracks = [track for track in all_tracks if track.artist == "Unknown"]

        self.assertFalse(
            any(track.start_time < 11445.0 and track.end_time > 11085.0 for track in unknown_tracks)
        )
        self.assertEqual(
            [11445.0],
            [track.start_time for track in unknown_tracks if track.start_time >= 11445.0],
        )
        self.assertEqual(
            [12300.0],
            [track.end_time for track in unknown_tracks if track.start_time >= 11445.0],
        )

    def test_known_cluster_span_breaks_unknown_gap_merge(self):
        builder = SetlistBuilder()
        track = _make_track(
            [3, 5, 7],
            artist="Known Artist",
            title="Known Track",
            start_time=45.0,
            end_time=135.0,
        )
        recognitions = [
            _make_rec(index, "Known Artist", "Known Track", "known-1")
            if index in {3, 5, 7}
            else _make_rec(index, recognized=False)
            for index in range(11)
        ]

        all_tracks = builder.add_unknown_tracks([track], recognitions)
        unknown_tracks = [item for item in all_tracks if item.artist == "Unknown"]

        self.assertEqual([[0, 1, 2], [8, 9, 10]], [track.segment_indices for track in unknown_tracks])

    def test_unknown_track_windows_are_clamped_to_neighboring_known_tracks(self):
        builder = SetlistBuilder()
        left_track = _make_track(
            [0, 1, 2],
            artist="Left Artist",
            title="Left Track",
            start_time=0.0,
            end_time=75.0,
        )
        right_track = _make_track(
            [7, 8, 9],
            artist="Right Artist",
            title="Right Track",
            start_time=105.0,
            end_time=165.0,
        )
        recognitions = [
            _make_rec(index, "Left Artist", "Left Track", "left-1")
            if index in {0, 1, 2}
            else _make_rec(index, "Right Artist", "Right Track", "right-1")
            if index in {7, 8, 9}
            else _make_rec(index, recognized=False)
            for index in range(10)
        ]

        all_tracks = builder.add_unknown_tracks([left_track, right_track], recognitions)
        unknown_tracks = [track for track in all_tracks if track.artist == "Unknown"]

        self.assertEqual(1, len(unknown_tracks))
        self.assertEqual([3, 4, 5, 6], unknown_tracks[0].segment_indices)
        self.assertEqual(75.0, unknown_tracks[0].start_time)
        self.assertEqual(105.0, unknown_tracks[0].end_time)
