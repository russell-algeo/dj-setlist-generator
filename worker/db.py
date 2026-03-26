"""Lightweight Postgres helpers for worker jobs."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from psycopg import connect as pg_connect
from psycopg.rows import dict_row
from psycopg.types.json import Json

from worker.config import get_settings


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
          count(*) filter (where status in ('queued', 'running', 'cancelling')) as active_count,
          count(*) filter (where status = 'failed') as failed_count,
          count(*) filter (where status = 'cancelled') as cancelled_count,
          count(*) as total_count
        from ops.set_runs
        where submission_id = %s
        """,
        (submission_id,),
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

