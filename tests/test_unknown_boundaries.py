import numpy as np
import pytest

ub = pytest.importorskip("tools.unknown_boundaries")


def test_count_model():
    assert ub.estimate_track_count(60) == 0
    assert ub.estimate_track_count(180) == 1
    assert ub.estimate_track_count(9 * 60) == 2
    assert ub.estimate_track_count(20 * 60) == 5


def test_snaps_to_novelty_peak_and_keeps_inside_span():
    nov = np.zeros(2000)
    nov[1000 + 330] = 1.0  # clear change near the 1/3 point
    bounds = ub.place_boundaries(nov, 1000, 1900, 3)
    assert [b["start_seconds"] for b in bounds][0] == 1330
    assert bounds[0]["basis"] == "novelty_peak"
    assert all(1000 + ub.MIN_PART_SECONDS <= b["start_seconds"] <= 1900 - ub.MIN_PART_SECONDS for b in bounds)


def test_estimate_set_only_unknowns_and_leaves_known_entries():
    entries = [
        {"id": "a", "display_title": "Some Track", "track_id": "t1", "start_time_seconds": 0, "end_time_seconds": 1200},
        {"id": "u1", "display_title": "Unknown Track", "track_id": None, "start_time_seconds": 1200, "end_time_seconds": 1380},
        {"id": "u2", "display_title": "Unknown Track", "track_id": None, "start_time_seconds": 1380, "end_time_seconds": 2580},
    ]
    out = ub.estimate_set(entries, None)
    assert [o["entry_id"] for o in out] == ["u2"]
    assert out[0]["estimated_track_count"] == 5
    assert [b["start_seconds"] for b in out[0]["provisional_boundaries"]] == [1620, 1860, 2100, 2340]
    assert all(b["basis"] == "even_split" for b in out[0]["provisional_boundaries"])
