import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

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
    instances = []

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        FakeRecognizer.instances.append(self)

    async def recognize_batch(self, segments, total_segments=None):
        out = []
        for s in segments:
            FakeRecognizer.calls += 1
            r = FakeRecognizer.results(s, FakeRecognizer.calls)
            # Mirror the production path: report each throttled attempt, then the final one.
            for _ in range(getattr(r, 'throttles', 0)):
                self.kwargs['on_attempt'](result(429), None, 5.0)
            self.kwargs['on_attempt'](r, None, 0)
            out.append(r)
        return out

    async def close(self):
        pass


def result(status=200, recognized=False, raw=None, throttles=0):
    return SimpleNamespace(http_status=status, is_valid=status == 200, recognized=recognized,
                           throttles=throttles,
                           raw_data=raw if raw is not None else ({'matches': []} if status == 200 else None))


class ArmBTests(unittest.TestCase):
    def run_arm(self, results, deadline=7800):
        grid = compare.study_windows([fragment(90)], compare.STUDY_HOP_FRAMES)
        FakeRecognizer.calls = 0
        FakeRecognizer.instances = []
        FakeRecognizer.results = results
        stats = {'attempts': 0, 'throttled': 0, 'backoff_seconds': 0.0, 'passes': 0}
        fake_module = SimpleNamespace(TrackRecognizer=FakeRecognizer)
        def fetch(url, first, last, path):
            path.write_bytes(b'\0' * (last - first + 1))
        with patch.dict('sys.modules', {'track_recognizer': fake_module}), \
                patch.object(base, 'fetch_range', fetch), \
                patch.object(compare, 'STUDY_DEADLINE_SECONDS', deadline):
            hits = asyncio.run(compare.recognize_arm_b(grid, {'m.wav': 'https://example.invalid/m'}, stats))
        return grid, hits, stats

    def test_every_window_recognized_through_production_retry_path(self):
        grid, hits, stats = self.run_arm(lambda s, n: result())
        self.assertEqual([h['index'] for h in hits], [w['index'] for w in grid])
        recognizer = FakeRecognizer.instances[0]
        self.assertNotIn('single_attempt', recognizer.kwargs)
        self.assertGreater(recognizer.kwargs['max_retry_seconds'], 0)
        self.assertEqual(stats['passes'], 1)

    def test_throttling_is_survived_and_counted(self):
        grid, hits, stats = self.run_arm(lambda s, n: result(throttles=3 if n == 1 else 0))
        self.assertEqual(len(hits), len(grid))
        self.assertEqual(stats['throttled'], 3)
        self.assertEqual(stats['backoff_seconds'], 15.0)

    def test_unresolved_windows_are_retried_in_another_pass(self):
        grid, hits, stats = self.run_arm(lambda s, n: result(429) if n == 2 else result())
        self.assertEqual(len(hits), len(grid))
        self.assertEqual(stats['passes'], 2)
        self.assertEqual(FakeRecognizer.calls, len(grid) + 1)

    def test_deadline_reports_unresolved_windows(self):
        with self.assertRaisesRegex(compare.Inconclusive, 'deadline_with_'):
            self.run_arm(lambda s, n: result(429), deadline=0)

    def test_incomplete_identity_is_inconclusive(self):
        with self.assertRaisesRegex(compare.Inconclusive, 'provider_identity_incomplete'):
            self.run_arm(lambda s, n: result(200, True, {'matches': [{}], 'track': {'key': 'x'}}))


class SourceLinkTests(unittest.TestCase):
    progress = {'released': True, 'fragments': [fragment(60)]}

    def test_released_family_uses_secret_map_only_for_needed_masters(self):
        links = '{"links": [{"name": "m.wav", "href": "https://x/m"}, {"name": "o.wav", "href": "https://x/o"}]}'
        with patch.dict(os.environ, {'SAMPLING_SOURCE_LINKS': links}):
            self.assertEqual(compare.source_links('s', self.progress), {'m.wav': 'https://x/m'})

    def test_released_family_without_secret_stops(self):
        with patch.dict(os.environ, {'SAMPLING_SOURCE_LINKS': ''}):
            with self.assertRaises(SystemExit):
                compare.source_links('s', self.progress)

    def test_missing_master_stops_without_naming_it(self):
        with patch.dict(os.environ, {'SAMPLING_SOURCE_LINKS': '{"links": []}'}):
            with self.assertRaisesRegex(SystemExit, '^1 master link'):
                compare.source_links('s', self.progress)

    def test_open_family_uses_database_links(self):
        with patch.object(base, 'call', return_value={'m.wav': 'db'}) as call:
            self.assertEqual(compare.source_links('s', {'released': False}), {'m.wav': 'db'})
        call.assert_called_once_with('yoon_partial_sources_for', 's')


if __name__ == '__main__':
    unittest.main()
