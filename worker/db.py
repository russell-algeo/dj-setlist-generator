"""Lightweight Postgres helpers for worker jobs."""

from __future__ import annotations

from contextlib import contextmanager
import os
from typing import Any, Iterator

from psycopg import connect as pg_connect
from psycopg.rows import dict_row
from psycopg.types.json import Json

from worker.config import get_settings
from worker.isolation import validate_database_target

ACTIVE_SET_RUN_STATUSES = (
    "dispatched",
    "resolving",
    "recognizing",
    "aggregating",
    "enriching",
    "publishing",
    "cancelling",
)


def _database_url() -> str:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL_DIRECT or DATABASE_URL_MIGRATIONS is required for worker jobs")
    validate_database_target(settings.database_url)
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
        update ops.set_runs
        set status = %s, stage = %s, error_summary = coalesce(%s, error_summary),
            published_set_id = coalesce(%s, published_set_id), heartbeat_at = now(),
            completed_at = case when %s in ('completed', 'failed', 'cancelled') then now() else completed_at end,
            updated_at = now()
        where id = %s and cancel_requested_at is null
          and status not in ('cancelled', 'completed', 'cancelling')
          and stage is distinct from 'publishing_committed'
          and (%s::text is null or source_metadata->>'active_workflow_run_id' is null
               or source_metadata->>'active_workflow_run_id' = %s)
        returning *
        """,
        (status, stage, error_summary, published_set_id, status, set_run_id,
         os.getenv("GITHUB_RUN_ID"), os.getenv("GITHUB_RUN_ID")),
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
          and ((%s = 'completed' and coalesce(%s::uuid, published_set_id) is not null)
               or (cancel_requested_at is null and status not in ('cancelled', 'cancelling', 'completed')
                   and stage is distinct from 'publishing_committed'))
          and (%s::text is null or source_metadata->>'active_workflow_run_id' is null
               or source_metadata->>'active_workflow_run_id' = %s)
        """,
        (status, stage, error_summary, published_set_id, status, set_run_id,
         status, published_set_id, os.getenv("GITHUB_RUN_ID"), os.getenv("GITHUB_RUN_ID")),
    )


def cancel_set_run(set_run_id: str, *, workflow_run_id: str | None) -> dict[str, Any] | None:
    """Acknowledge cancellation once, without overwriting publication or new owners."""
    return fetch_one(
        """
        with cancelled as (
          update ops.set_runs
          set status = 'cancelled', stage = 'cancelled', completed_at = now(),
              heartbeat_at = now(), updated_at = now()
          where id = %s
            and (cancel_requested_at is not null or status = 'cancelling')
            and status <> 'cancelled'
            and published_set_id is null
            and stage is distinct from 'publishing_committed'
            and (%s::text is null or source_metadata->>'active_workflow_run_id' is null
                 or source_metadata->>'active_workflow_run_id' = %s)
          returning id, submission_id
        ), cancelled_leases as (
          update ops.set_run_leases
          set status = 'cancelled', completed_at = now(), updated_at = now()
          where set_run_id in (select id from cancelled)
            and status in ('pending', 'claimed')
        )
        select * from cancelled
        """,
        (set_run_id, workflow_run_id, workflow_run_id),
    )


def update_set_run_metadata(
    set_run_id: str,
    metadata: dict[str, Any],
    *,
    set_title: str | None = None,
    source_url: str | None = None,
    source_platform: str | None = None,
) -> None:
    execute(
        """
        update ops.set_runs
        set
          set_title = coalesce(%s, set_title),
          source_url = coalesce(%s, source_url),
          source_platform = coalesce(%s, source_platform),
          source_metadata = coalesce(source_metadata, '{}'::jsonb) || %s::jsonb,
          heartbeat_at = now(),
          updated_at = now()
        where id = %s
          and cancel_requested_at is null and status not in ('cancelled', 'cancelling')
          and (%s::text is null or source_metadata->>'active_workflow_run_id' is null
               or source_metadata->>'active_workflow_run_id' = %s)
          and coalesce(source_metadata->>'dispatch_generation', '') = %s
        """,
        (
            set_title,
            source_url,
            source_platform,
            json_value(metadata),
            set_run_id,
            *_worker_fence_params(),
        ),
    )


def claim_workflow_run(set_run_id: str, *, workflow_run_id: str, force: bool, dispatch_generation: str | None = None) -> dict[str, Any] | None:
    """Acquire the current attempt without reviving a retired workflow."""
    return fetch_one(
        """
        with current as (
          select id, source_metadata
          from ops.set_runs
          where id = %s and cancel_requested_at is null
            and status not in ('cancelled', 'completed', 'cancelling')
            and published_set_id is null and stage is distinct from 'publishing_committed'
          for update
        )
        update ops.set_runs run
        set source_metadata = coalesce(current.source_metadata, '{}'::jsonb)
              || jsonb_build_object('active_workflow_run_id', %s::text),
            updated_at = now(), heartbeat_at = now()
        from current
        where run.id = current.id
          and not (coalesce(current.source_metadata->'retired_workflow_run_ids', '[]'::jsonb) ? %s)
          and coalesce(current.source_metadata->>'dispatch_generation', '') = %s
          and (current.source_metadata->>'active_workflow_run_id' is null
               or current.source_metadata->>'active_workflow_run_id' = %s
               or (%s and current.source_metadata->>'active_workflow_run_id' = 'awaiting_dispatch'))
        returning current.source_metadata->>'active_workflow_run_id' as previous_workflow_run_id
        """,
        (set_run_id, workflow_run_id, workflow_run_id, dispatch_generation or "", workflow_run_id, force),
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


# Lock the run before touching its recognition rows. A preflight read alone can
# race cancellation/retry between the check and an INSERT/lease completion.
_WORKER_RUN_FENCE = """
    run.cancel_requested_at is null
    and run.status not in ('cancelled', 'cancelling', 'completed')
    and run.published_set_id is null
    and run.stage is distinct from 'publishing_committed'
    and (%s::text is null or run.source_metadata->>'active_workflow_run_id' is null
         or run.source_metadata->>'active_workflow_run_id' = %s)
    and coalesce(run.source_metadata->>'dispatch_generation', '') = %s
"""


def _worker_fence_params() -> tuple[str | None, str | None, str]:
    owner = os.getenv("GITHUB_RUN_ID")
    return owner, owner, os.getenv("SET_LIST_DISPATCH_GENERATION") or ""


def initialize_set_run_leases(
    set_run_id: str,
    *,
    total_segments: int,
    slot_count: int,
    lease_size: int,
) -> int:
    row = fetch_one(
        f"""
        with owned as (
          select run.id from ops.set_runs run
          where run.id = %s and {_WORKER_RUN_FENCE} for update
        )
        select ops.initialize_set_run_leases(id, %s, %s, %s) as lease_count from owned
        """,
        (set_run_id, *_worker_fence_params(), total_segments, slot_count, lease_size),
    )
    return int(row["lease_count"]) if row else 0


def claim_next_lease(set_run_id: str, *, slot_index: int, worker_name: str) -> dict[str, Any] | None:
    # Global work stealing is retained; the slot is diagnostic, not a filter.
    return fetch_one(
        f"""
        with owned as (
          select run.id from ops.set_runs run
          where run.id = %s and {_WORKER_RUN_FENCE} for update
        ), candidate as (
          select lease.id from ops.set_run_leases lease
          where lease.set_run_id in (select id from owned) and lease.status = 'pending'
          order by lease.segment_start_index asc, lease.id asc
          limit 1 for update skip locked
        )
        update ops.set_run_leases lease
        set status = 'claimed', claimed_by = %s, claimed_at = now(), updated_at = now()
        where lease.id in (select id from candidate)
        returning lease.*
        """,
        (set_run_id, *_worker_fence_params(), worker_name),
    )


def complete_lease(lease_id: str, *, success: bool, error_text: str | None = None) -> None:
    execute(
        f"""
        with owned as (
          select run.id from ops.set_runs run
          where run.id = (select set_run_id from ops.set_run_leases where id = %s)
            and {_WORKER_RUN_FENCE} for update
        )
        update ops.set_run_leases lease
        set status = case when %s then 'completed' else 'failed' end,
            completed_at = case when %s then now() else null end,
            error_text = %s, updated_at = now()
        where lease.id = %s and lease.status = 'claimed'
          and lease.set_run_id in (select id from owned)
        """,
        (lease_id, *_worker_fence_params(), success, success, error_text, lease_id),
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
        f"""
        with owned as (
          select run.id from ops.set_runs run
          where run.id = %s and {_WORKER_RUN_FENCE} for update
        )
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
        select id, %s, %s, %s, %s, %s, %s, %s, %s from owned
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
            *_worker_fence_params(),
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
          completed_at = case when %s in ('completed', 'partial', 'failed', 'cancelled') then now() else completed_at end,
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
          count(*) filter (where status = 'completed') as completed_count,
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

    completed = int(rollup["completed_count"] or 0)
    failed = int(rollup["failed_count"] or 0)
    cancelled = int(rollup["cancelled_count"] or 0)
    total = int(rollup["total_count"] or 0)

    if failed > 0 and completed > 0:
        mark_submission(submission_id, status="partial")
        return

    if failed > 0:
        mark_submission(submission_id, status="failed")
        return

    if cancelled == total:
        mark_submission(submission_id, status="cancelled")
        return

    mark_submission(submission_id, status="completed")
