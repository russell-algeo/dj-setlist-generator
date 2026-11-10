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

    http_status: Optional[int] = None
    retry_after_seconds: Optional[float] = None
    retry_after_format: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        """Only provider responses, including genuine no-match, are completed work."""
        return (not self.error_type and not self.was_rate_limited
                and self.http_status in (None, 200)
                and isinstance(self.raw_data, dict)
                and isinstance(self.raw_data.get('matches'), list)
                and ('track' not in self.raw_data or isinstance(self.raw_data['track'], dict))
                and (not self.raw_data['matches'] or isinstance(self.raw_data.get('track'), dict)))

    @classmethod
    def from_checkpoint(cls, data: dict) -> "Recognition":
        """Create a Recognition from checkpoint data, ignoring unknown fields."""

        known = {field.name for field in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})


def valid_checkpoint_coverage(saved, total, step):
    """Return ordered validated responses, or None for incomplete/ambiguous coverage."""
    if total <= 0 or not isinstance(saved, list) or len(saved) != total:
        return None
    rows = {}
    try:
        for data in saved:
            result = Recognition.from_checkpoint(data)
            index = result.segment_index
            if (type(index) is not int or index < 0 or index >= total or index in rows
                    or not result.is_valid or result.timestamp != index * step):
                return None
            rows[index] = result
    except (TypeError, ValueError, KeyError, AttributeError):
        return None
    return [rows[index] for index in range(total)]
