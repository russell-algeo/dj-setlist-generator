import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from worker.jobs import yoon_partial_runner as base
from worker.jobs import yoon_sampling_compare as compare

RATE = base.RATE


def fragment(seconds, start=0, index=0):
    frames = seconds * RATE
    return {'index': index, 'frames': frames, 'startFrame': start,
            'parts': [{'file': 'm.wav', 'start': start, 'end': start + frames}]}


def hit(index, key=None):
    raw = {'matches': [{}], 'track': {'key': key, 'title': 'T' + key, 'subtitle': 'A'}} if key else {'matches': []}
    return {'index': index, 'response': {'recognized': key is not None, 'raw_data': raw}}


class StudyGridTests(unittest.TestCase):
    def test_twelve_second_hop_tiles_centred_analysis(self):
        grid = compare.study_windows([fragment(120)], compare.STUDY_HOP_FRAMES)
        self.assertEqual(len(grid), (120 - 30) // 12 + 1)
        centres = [(w['start_frame'] + 15 * RATE) / RATE for w in grid]
        for left, right in zip(centres, centres[1:]):
            self.assertEqual(right - 6, left + 6)  # contiguous 12 s analyses

    def test_hop_is_restored_and_arm_a_grid_unchanged(self):
        before = base.windows([fragment(120)])
        compare.study_windows([fragment(120)], compare.STUDY_HOP_FRAMES)
        self.assertEqual(base.HOP_FRAMES, 15 * RATE)
        self.assertEqual(base.windows([fragment(120)]), before)

    def test_windows_never_span_fragments(self):
        grid = compare.study_windows([fragment(40, 0, 0), fragment(50, 100 * RATE, 1)],
                                     compare.STUDY_HOP_FRAMES)
        for w in grid:
            self.assertEqual(len(w['parts']), 1)


class CountTests(unittest.TestCase):
    def test_identified_counts_clusters_and_distinct_tracks(self):
        grid = compare.study_windows([fragment(300)], compare.STUDY_HOP_FRAMES)
        hits = [hit(w['index'], 'k1' if w['index'] < 8 else 'k2' if w['index'] < 16 else None)
                for w in grid]
        result = compare.identified(grid, hits)
        self.assertEqual(result['windows'], len(grid))
        self.assertEqual(result['recognized_windows'], 16)
        self.assertEqual(result['distinct_tracks'], 2)
        self.assertEqual(result['identified_entries'], 2)


class FakeRecognizer:
    calls = 0

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    async def recognize_batch(self, segments, total_segments=None):
        FakeRecognizer.calls += len(segments)
        return [FakeRecognizer.results(s) for s in segments]

    async def close(self):
        pass


def result(status=200, recognized=False, raw=None):
    return SimpleNamespace(http_status=status, is_valid=status == 200, recognized=recognized,
                           raw_data=raw if raw is not None else ({'matches': []} if status == 200 else None))


class ArmBTests(unittest.TestCase):
    def run_arm(self, results, others=0):
        grid = compare.study_windows([fragment(90)], compare.STUDY_HOP_FRAMES)
        FakeRecognizer.calls = 0
        FakeRecognizer.results = results
        fake_module = SimpleNamespace(TrackRecognizer=FakeRecognizer)
        def fetch(url, first, last, path):
            path.write_bytes(b'\0' * (last - first + 1))
        with patch.dict('sys.modules', {'track_recognizer': fake_module}), \
                patch.object(base, 'fetch_range', fetch), \
                patch.object(compare, 'other_recognizing_runs', return_value=others), \
                patch.object(compare.asyncio, 'sleep', new_callable=AsyncMock):
            return grid, asyncio.run(compare.recognize_arm_b(grid, {'m.wav': 'https://example.invalid/m'}))

    def test_single_attempt_one_call_per_window(self):
        grid, hits = self.run_arm(lambda s: result())
        self.assertEqual(len(hits), len(grid))
        self.assertEqual(FakeRecognizer.calls, len(grid))

    def test_throttle_stops_immediately(self):
        with self.assertRaisesRegex(compare.Inconclusive, 'provider_throttled'):
            self.run_arm(lambda s: result(429))
        self.assertLessEqual(FakeRecognizer.calls, 10)

    def test_failed_attempt_is_inconclusive(self):
        with self.assertRaisesRegex(compare.Inconclusive, 'provider_attempt_failed'):
            self.run_arm(lambda s: result(500))

    def test_incomplete_identity_is_inconclusive(self):
        with self.assertRaisesRegex(compare.Inconclusive, 'provider_identity_incomplete'):
            self.run_arm(lambda s: result(200, True, {'matches': [{}], 'track': {'key': 'x'}}))

    def test_other_recognizing_run_stops_before_any_call(self):
        with self.assertRaisesRegex(compare.Inconclusive, 'other_recognizing_run_active'):
            self.run_arm(lambda s: result(), others=1)
        self.assertEqual(FakeRecognizer.calls, 0)


if __name__ == '__main__':
    unittest.main()
