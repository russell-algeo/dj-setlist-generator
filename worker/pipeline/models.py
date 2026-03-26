"""Lightweight pipeline data models shared across worker phases."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Optional


@dataclass
class Recognition:
    """Recognition result from Shazam."""

    timestamp: float
    track_title: Optional[str]
    artist: Optional[str]
    shazam_track_id: Optional[str]
    raw_data: Optional[dict]
    recognized: bool
    segment_index: int
    was_rate_limited: bool = False
    error_type: Optional[str] = None
    error_details: Optional[str] = None

    @classmethod
    def from_checkpoint(cls, data: dict) -> "Recognition":
        """Create a Recognition from checkpoint data, ignoring unknown fields."""

        known = {field.name for field in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})
