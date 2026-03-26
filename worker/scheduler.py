"""Scheduler tuning helpers for remote recognition workflows."""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass

from config import Config


AUTO_SENTINELS = {"", "auto", "default"}


@dataclass(frozen=True, slots=True)
class SchedulerPlan:
    slot_count: int
    lease_size: int
    lease_count: int
    segments_per_slot: float
    leases_per_slot: float
    requested_slot_count: int | None
    requested_lease_size: int | None
    mode: str

    def as_metadata(self) -> dict[str, object]:
        return asdict(self)


def _parse_requested_positive_int(raw_value: str | None) -> int | None:
    if raw_value is None:
        return None

    normalized = raw_value.strip().lower()
    if normalized in AUTO_SENTINELS:
        return None

    value = int(normalized)
    if value <= 0:
        raise ValueError(f"Expected a positive integer or 'auto', got {raw_value!r}")
    return value


def _requested_slot_count() -> int | None:
    raw_value = os.getenv("RECOGNITION_SLOT_COUNT_REQUESTED")
    if raw_value is None:
        raw_value = os.getenv("RECOGNITION_SLOT_COUNT")
    return _parse_requested_positive_int(raw_value)


def _requested_lease_size() -> int | None:
    raw_value = os.getenv("LEASE_SIZE_REQUESTED")
    if raw_value is None:
        raw_value = os.getenv("LEASE_SIZE")
    return _parse_requested_positive_int(raw_value)


def _auto_slot_count(total_segments: int) -> int:
    if total_segments <= 0:
        return 1

    return max(
        1,
        min(
            Config.AUTO_MAX_RECOGNITION_SLOTS,
            total_segments,
            math.ceil(total_segments / max(Config.AUTO_TARGET_SEGMENTS_PER_SLOT, 1)),
        ),
    )


def _auto_lease_size(total_segments: int, slot_count: int) -> int:
    if total_segments <= 0:
        return max(1, Config.AUTO_MIN_LEASE_SIZE)

    target_slots = max(1, slot_count)
    target_leases = max(Config.AUTO_TARGET_LEASES_PER_SLOT, 1.0)
    computed = math.ceil(total_segments / (target_slots * target_leases))
    return max(1, min(total_segments, max(Config.AUTO_MIN_LEASE_SIZE, computed)))


def _lease_count(total_segments: int, lease_size: int) -> int:
    if total_segments <= 0:
        return 0
    return math.ceil(total_segments / max(lease_size, 1))


def build_scheduler_plan(total_segments: int) -> SchedulerPlan:
    requested_slot_count = _requested_slot_count()
    requested_lease_size = _requested_lease_size()

    if total_segments <= 0:
        return SchedulerPlan(
            slot_count=1,
            lease_size=max(1, requested_lease_size or Config.AUTO_MIN_LEASE_SIZE),
            lease_count=0,
            segments_per_slot=0.0,
            leases_per_slot=0.0,
            requested_slot_count=requested_slot_count,
            requested_lease_size=requested_lease_size,
            mode="manual" if requested_slot_count or requested_lease_size else "auto",
        )

    if requested_slot_count is None:
        slot_count = _auto_slot_count(total_segments)
    else:
        slot_count = max(1, min(requested_slot_count, total_segments))

    if requested_lease_size is None:
        lease_size = _auto_lease_size(total_segments, slot_count)
    else:
        lease_size = max(1, min(requested_lease_size, total_segments))

    lease_count = _lease_count(total_segments, lease_size)

    # In auto mode, avoid spinning up idle slots when the lease size is coarser than expected.
    if requested_slot_count is None:
        slot_count = max(1, min(slot_count, lease_count))
        if requested_lease_size is None:
            lease_size = _auto_lease_size(total_segments, slot_count)
            lease_count = _lease_count(total_segments, lease_size)

    mode = (
        "manual"
        if requested_slot_count is not None and requested_lease_size is not None
        else "hybrid"
        if requested_slot_count is not None or requested_lease_size is not None
        else "auto"
    )

    return SchedulerPlan(
        slot_count=slot_count,
        lease_size=lease_size,
        lease_count=lease_count,
        segments_per_slot=round(total_segments / max(slot_count, 1), 2),
        leases_per_slot=round(lease_count / max(slot_count, 1), 2),
        requested_slot_count=requested_slot_count,
        requested_lease_size=requested_lease_size,
        mode=mode,
    )
