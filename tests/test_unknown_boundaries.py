import unittest

try:
    import numpy as np
    import scipy  # noqa: F401
    from tools import unknown_boundaries as ub
except ImportError:  # offline tool; numpy/scipy are not worker dependencies
    ub = None


@unittest.skipIf(ub is None, "numpy/scipy not installed")
class UnknownBoundariesTest(unittest.TestCase):
    def test_count_model(self):
        self.assertEqual(ub.estimate_track_count(60), 0)
        self.assertEqual(ub.estimate_track_count(180), 1)
        self.assertEqual(ub.estimate_track_count(9 * 60), 2)
        self.assertEqual(ub.estimate_track_count(20 * 60), 5)

    def test_snaps_to_novelty_peak_and_keeps_inside_span(self):
        nov = np.zeros(2000)
        nov[1000 + 330] = 1.0  # clear change near the 1/3 point
        bounds = ub.place_boundaries(nov, 1000, 1900, 3)
        self.assertEqual(bounds[0]["start_seconds"], 1330)
        self.assertEqual(bounds[0]["basis"], "novelty_peak")
        for b in bounds:
            self.assertTrue(1000 + ub.MIN_PART_SECONDS <= b["start_seconds"] <= 1900 - ub.MIN_PART_SECONDS)

    def test_estimate_set_only_unknowns(self):
        entries = [
            {"id": "a", "display_title": "Some Track", "track_id": "t1", "start_time_seconds": 0, "end_time_seconds": 1200},
            {"id": "u1", "display_title": "Unknown Track", "track_id": None, "start_time_seconds": 1200, "end_time_seconds": 1380},
            {"id": "u2", "display_title": "Unknown Track", "track_id": None, "start_time_seconds": 1380, "end_time_seconds": 2580},
        ]
        out = ub.estimate_set(entries, None)
        self.assertEqual([o["entry_id"] for o in out], ["u2"])
        self.assertEqual(out[0]["estimated_track_count"], 5)
        self.assertEqual([b["start_seconds"] for b in out[0]["provisional_boundaries"]], [1620, 1860, 2100, 2340])


if __name__ == "__main__":
    unittest.main()
