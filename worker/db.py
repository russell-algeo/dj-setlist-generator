"""Lightweight Postgres helpers for worker jobs."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from psycopg import connect as pg_connect
from psycopg.rows import dict_row
from psycopg.types.json import Json

from worker.config import get_settings

ACTIVE_SET_RUN_STATUSES = (
    "dispatched",
    "resolving",
    "recognizing",
    "aggregating",
    "enriching",
    "publishing",
    "running",
    "cancelling",
)


def _database_url() -> str:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL_DIRECT or DATABASE_URL_MIGRATIONS is required for worker jobs")
    return settings.database_url


@contextmanager
def connect() -> Iterator[Any]:
    with pg_connect(_database_url(), autocommit=True, row_factory=dict_row) as conn:
        yield conn


def fetch_one(query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchone()


def fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(query, params)
        return list(cur.fetchall())


def execute(query: str, params: tuple[Any, ...] = ()) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(query, params)


def json_value(value: Any) -> Json:
    return Json(value)


def insert_worker_event(
    *,
    event_type: str,
    message: str,
    submission_id: str | None = None,
    set_run_id: str | None = None,
    lease_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    execute(
        """
        insert into ops.worker_events (
          submission_id,
          set_run_id,
          lease_id,
          event_type,
          message,
          details
        )
        values (%s, %s, %s, %s, %s, %s)
        """,
        (
            submission_id,
            set_run_id,
            lease_id,
            event_type,
            message,
            json_value(details or {}),
        ),
    )


def touch_set_run(set_run_id: str, stage: str | None = None, status: str | None = None) -> None:
    execute(
        """
        update ops.set_runs
        set
          stage = coalesce(%s, stage),
          status = coalesce(%s, status),
          heartbeat_at = now(),
          updated_at = now()
        where id = %s
        """,
        (stage, status, set_run_id),
    )


def mark_run_stage(
    set_run_id: str,
    *,
    status: str,
    stage: str,
    error_summary: str | None = None,
    published_set_id: str | None = None,
) -> dict[str, Any] | None:
    return fetch_one(
        """
        select *
        from ops.mark_run_stage(%s, %s, %s, %s, %s)
        limit 1
        """,
        (set_run_id, status, stage, error_summary, published_set_id),
    )


def mark_set_run(
    set_run_id: str,
    *,
    status: str,
    stage: str | None = None,
    error_summary: str | None = None,
    published_set_id: str | None = None,
) -> None:
    execute(
        """
        update ops.set_runs
        set
          status = %s,
          stage = %s,
          error_summary = %s,
          published_set_id = coalesce(%s, published_set_id),
          heartbeat_at = now(),
          completed_at = case when %s in ('completed', 'failed', 'cancelled') then now() else completed_at end,
          updated_at = now()
        where id = %s
        """,
        (status, stage, error_summary, published_set_id, status, set_run_id),
    )


def update_set_run_metadata(
    set_run_id: str,
    metadata: dict[str, Any],
    *,
    set_title: str | None = None,
    source_platform: str | None = None,
) -> None:
    execute(
        """
        update ops.set_runs
        set
          set_title = coalesce(%s, set_title),
          source_platform = coalesce(%s, source_platform),
          source_metadata = coalesce(source_metadata, '{}'::jsonb) || %s::jsonb,
          heartbeat_at = now(),
          updated_at = now()
        where id = %s
        """,
        (
            set_title,
            source_platform,
            json_value(metadata),
            set_run_id,
        ),
    )


def get_active_workflow_run_id(set_run_id: str) -> str | None:
    row = fetch_one(
        """
        select source_metadata->>'active_workflow_run_id' as active_workflow_run_id
        from ops.set_runs
        where id = %s
        """,
        (set_run_id,),
    )
    if not row:
        return None

    value = row.get("active_workflow_run_id")
    return str(value) if value else None


def initialize_set_run_leases(
    set_run_id: str,
    *,
    total_segments: int,
    slot_count: int,
    lease_size: int,
) -> int:
    row = fetch_one(
        """
        select ops.initialize_set_run_leases(%s, %s, %s, %s) as lease_count
        """,
        (set_run_id, total_segments, slot_count, lease_size),
    )
    return int(row["lease_count"]) if row else 0


def claim_next_lease(set_run_id: str, *, slot_index: int, worker_name: str) -> dict[str, Any] | None:
    return fetch_one(
        """
        select *
        from ops.claim_next_lease(%s, %s, %s)
        limit 1
        """,
        (set_run_id, slot_index, worker_name),
    )


def complete_lease(lease_id: str, *, success: bool, error_text: str | None = None) -> None:
    execute(
        """
        select ops.complete_lease(%s, %s, %s)
        """,
        (lease_id, success, error_text),
    )


def upsert_segment_hit(
    *,
    set_run_id: str,
    lease_id: str | None,
    segment_index: int,
    timestamp_seconds: float,
    track_title: str | None,
    artist: str | None,
    shazam_track_id: str | None,
    recognized: bool,
    raw_data: dict[str, Any] | None,
) -> None:
    execute(
        """
        insert into ops.segment_hits (
          set_run_id,
          lease_id,
          segment_index,
          timestamp_seconds,
          track_title,
          artist,
          shazam_track_id,
          recognized,
          raw_data
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (set_run_id, segment_index)
        do update
        set
          lease_id = excluded.lease_id,
          timestamp_seconds = excluded.timestamp_seconds,
          track_title = excluded.track_title,
          artist = excluded.artist,
          shazam_track_id = excluded.shazam_track_id,
          recognized = excluded.recognized,
          raw_data = excluded.raw_data
        """,
        (
            set_run_id,
            lease_id,
            segment_index,
            timestamp_seconds,
            track_title,
            artist,
            shazam_track_id,
            recognized,
            json_value(raw_data) if raw_data is not None else None,
        ),
    )


def list_segment_hits(set_run_id: str) -> list[dict[str, Any]]:
    return fetch_all(
        """
        select *
        from ops.segment_hits
        where set_run_id = %s
        order by segment_index asc
        """,
        (set_run_id,),
    )


def get_lease_rollup(set_run_id: str) -> dict[str, Any] | None:
    return fetch_one(
        """
        select
          count(*) filter (where status = 'pending') as pending_count,
          count(*) filter (where status = 'claimed') as claimed_count,
          count(*) filter (where status = 'completed') as completed_count,
          count(*) filter (where status = 'failed') as failed_count,
          count(*) as total_count
        from ops.set_run_leases
        where set_run_id = %s
        """,
        (set_run_id,),
    )


def mark_submission(
    submission_id: str,
    *,
    status: str,
    error_summary: str | None = None,
) -> None:
    execute(
        """
        update ops.submissions
        set
          status = %s,
          error_summary = %s,
          completed_at = case when %s in ('completed', 'failed', 'cancelled') then now() else completed_at end,
          updated_at = now()
        where id = %s
        """,
        (status, error_summary, status, submission_id),
    )


def finalize_submission_from_runs(submission_id: str) -> None:
    rollup = fetch_one(
        """
        select
          count(*) filter (where status = 'queued' or status = any(%s)) as active_count,
          count(*) filter (where status = 'failed') as failed_count,
          count(*) filter (where status = 'cancelled') as cancelled_count,
          count(*) as total_count
        from ops.set_runs
        where submission_id = %s
        """,
        (list(ACTIVE_SET_RUN_STATUSES), submission_id),
    )

    if not rollup or int(rollup["total_count"] or 0) == 0:
        return

    if int(rollup["active_count"] or 0) > 0:
        mark_submission(submission_id, status="running")
        return

    if int(rollup["failed_count"] or 0) > 0:
        mark_submission(submission_id, status="failed")
        return

    if int(rollup["cancelled_count"] or 0) == int(rollup["total_count"] or 0):
        mark_submission(submission_id, status="cancelled")
        return

    mark_submission(submission_id, status="completed")
