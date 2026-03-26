"""Aggregation helpers for converting segment hits into a setlist."""

from __future__ import annotations

from setlist_builder import SetlistBuilder, Track
from worker.pipeline.models import Recognition


def recognitions_from_segment_hits(segment_hits: list[dict[str, object]]) -> list[Recognition]:
    return [
        Recognition(
            timestamp=float(row["timestamp_seconds"]),
            track_title=str(row["track_title"]) if row.get("track_title") else None,
            artist=str(row["artist"]) if row.get("artist") else None,
            shazam_track_id=str(row["shazam_track_id"]) if row.get("shazam_track_id") else None,
            raw_data=row.get("raw_data") if isinstance(row.get("raw_data"), dict) else None,
            recognized=bool(row.get("recognized")),
            segment_index=int(row["segment_index"]),
        )
        for row in segment_hits
    ]


def build_tracks_from_recognitions(recognitions: list[Recognition]) -> tuple[list[Track], SetlistBuilder]:
    builder = SetlistBuilder()
    tracks = builder.build_setlist(recognitions)
    tracks = builder.add_unknown_tracks(tracks, recognitions)
    return tracks, builder


__all__ = [
    "Recognition",
    "SetlistBuilder",
    "Track",
    "build_tracks_from_recognitions",
    "recognitions_from_segment_hits",
]
