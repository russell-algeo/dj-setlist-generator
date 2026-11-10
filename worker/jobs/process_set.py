"""Phase-based processing for queued set runs."""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
from contextlib import suppress

from psycopg.errors import ForeignKeyViolation

from config import Config
from worker.callbacks import post_callback
from worker.config import get_settings
from worker.db import (
    cancel_set_run,
    claim_next_lease,
    claim_workflow_run,
    complete_lease,
    fetch_one,
    finalize_submission_from_runs,
    get_active_workflow_run_id,
    get_lease_rollup,
    insert_worker_event,
    initialize_set_run_leases,
    list_segment_hits,
    mark_run_stage,
    mark_set_run,
    upsert_segment_hit,
    update_set_run_metadata,
)
from worker.scheduler import build_scheduler_plan


class WorkflowSupersededError(RuntimeError):
    """Raised when a newer workflow run takes ownership of the set run."""


class RunCancelledError(RuntimeError):
    """Raised when the owner requests cancellation before publication commits."""


class PublishSetRunPartialError(RuntimeError):
    """Raised when publish writes set data but fails a later server-side step."""

    def __init__(self, message: str, *, published_row: dict[str, object]) -> None:
        super().__init__(message)
        self.published_row = published_row


def _dispatch_pending() -> None:
    settings = get_settings()
    if not settings.api_base_url or not settings.internal_secret:
        return

    post_callback(
        settings,
        "/api/internal/dispatch-pending",
        timeout=30,
    ).raise_for_status()


def _revalidate(paths: list[str], tags: list[str] | None = None) -> None:
    settings = get_settings()
    if not settings.api_base_url or not settings.internal_secret:
        return

    post_callback(
        settings,
        "/api/internal/revalidate",
        json={"paths": paths, "tags": tags or []},
        timeout=30,
    ).raise_for_status()


def _publish_set_run_payload(
    *,
    set_run_id: str,
    payload: dict[str, object],
) -> dict[str, object]:
    settings = get_settings()
    if not settings.api_base_url or not settings.internal_secret:
        raise RuntimeError("APP_BASE_URL and INTERNAL_WORKER_SHARED_SECRET are required for publish")

    response = post_callback(
        settings,
        "/api/internal/publish-set-run",
        json={
            "setRunId": set_run_id,
            "payload": payload,
            **({"workflowRunId": _workflow_run_id()} if _workflow_run_id() else {}),
        },
        timeout=120,
    )

    response_payload: dict[str, object] | None = None
    try:
        parsed_payload = response.json()
        if isinstance(parsed_payload, dict):
            response_payload = dict(parsed_payload)
    except ValueError:
        response_payload = None

    if response.status_code == 409 and response_payload:
        if response_payload.get("errorCode") == "run_cancelled":
            raise RunCancelledError("Cancellation accepted before publication")
        if response_payload.get("errorCode") == "workflow_superseded":
            raise WorkflowSupersededError("Publication rejected for a superseded workflow")

    if response.ok:
        return response_payload or {}

    if response_payload and response_payload.get("setId"):
        error_message = (
            str(response_payload.get("error"))
            if response_payload.get("error")
            else f"Publish failed with HTTP {response.status_code}"
        )
        raise PublishSetRunPartialError(error_message, published_row=response_payload)

    response.raise_for_status()
    raise RuntimeError("Publish failed without a response body")


def _detect_source_platform(source_url: str) -> str:
    if "soundcloud.com" in source_url or "snd.sc" in source_url:
        return "soundcloud"
    if "youtu" in source_url:
        return "youtube"
    return "unknown"


def _load_run(set_run_id: str) -> dict[str, object]:
    run_row = fetch_one(
        """
        select
          r.id,
          r.submission_id,
          r.requested_by,
          r.status,
          r.stage,
          r.source_url,
          r.source_platform,
          r.set_title,
          r.create_playlist,
          r.cancel_requested_at,
          r.published_set_id,
          r.source_metadata,
          s.artist_name
        from ops.set_runs r
        inner join ops.submissions s on s.id = r.submission_id
        where r.id = %s
        """,
        (set_run_id,),
    )
    if not run_row:
        raise RuntimeError(f"Set run {set_run_id} was not found")
    return run_row


def _workflow_run_id() -> str | None:
    value = os.getenv("GITHUB_RUN_ID")
    return value.strip() if value else None


def _resume_mode() -> str | None:
    value = os.getenv("SET_LIST_RESUME_MODE")
    return value.strip() if value else None


def _claim_workflow_ownership(set_run_id: str, *, force: bool = False) -> str | None:
    workflow_run_id = _workflow_run_id()
    if not workflow_run_id:
        return None

    claimed = claim_workflow_run(
        set_run_id, workflow_run_id=workflow_run_id, force=force,
        dispatch_generation=os.getenv("SET_LIST_DISPATCH_GENERATION") or None,
    )
    if claimed is None:
        _assert_not_cancelled(set_run_id)
        raise WorkflowSupersededError("This workflow attempt is retired or no longer eligible")
    previous = claimed.get("previous_workflow_run_id")
    return str(previous) if previous else None


def _workflow_superseded(set_run_id: str) -> bool:
    workflow_run_id = _workflow_run_id()
    if not workflow_run_id:
        return False

    active_workflow_run_id = get_active_workflow_run_id(set_run_id)
    return bool(active_workflow_run_id and active_workflow_run_id != workflow_run_id)


def _assert_workflow_ownership(set_run_id: str) -> None:
    if _workflow_superseded(set_run_id):
        raise WorkflowSupersededError(
            f"Workflow run {_workflow_run_id()} is no longer the active owner for {set_run_id}",
        )


def _assert_not_cancelled(set_run_id: str) -> None:
    run = _load_run(set_run_id)
    generation = (run.get("source_metadata") or {}).get("dispatch_generation") or ""
    if generation != (os.getenv("SET_LIST_DISPATCH_GENERATION") or ""):
        raise WorkflowSupersededError("This dispatch generation is no longer current")
    if run.get("cancel_requested_at") or run.get("status") in {"cancelling", "cancelled"}:
        raise RunCancelledError(f"Cancellation requested for {set_run_id}")


def _assert_run_active(set_run_id: str) -> None:
    _assert_workflow_ownership(set_run_id)
    _assert_not_cancelled(set_run_id)


def _finish_cancelled(set_run_id: str) -> None:
    # Compare-and-set in the DB prevents a late/superseded slot from overwriting
    # an already committed publication or a newer workflow's state.
    run = cancel_set_run(set_run_id, workflow_run_id=_workflow_run_id())
    if not run:
        current = _load_run(set_run_id)
        if current.get("status") == "cancelled" and not _workflow_superseded(set_run_id):
            finalize_submission_from_runs(str(current["submission_id"]))
        return
    if run:
        finalize_submission_from_runs(str(run["submission_id"]))
        insert_worker_event(
            submission_id=str(run["submission_id"]), set_run_id=set_run_id,
            event_type="set_run.cancelled", message="Worker stopped after cancellation was requested",
        )


async def _recognize_with_cancellation(set_run_id: str, recognition) -> None:
    task = asyncio.create_task(recognition)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=2)
            _assert_run_active(set_run_id)
            if done:
                await task
                return
    finally:
        if not task.done():
            task.cancel()
        # Always retrieve the result/exception; no orphaned recognition work.
        with suppress(asyncio.CancelledError, Exception):
            await task


def _record_stage_change(
    run_row: dict[str, object],
    *,
    status: str,
    stage: str,
    event_type: str = "set_run.stage_changed",
    message: str | None = None,
    details: dict[str, object] | None = None,
) -> None:
    _assert_run_active(str(run_row["id"]))
    if not mark_run_stage(str(run_row["id"]), status=status, stage=stage):
        _assert_run_active(str(run_row["id"]))
        raise RuntimeError("Set run cannot enter a new phase after publication or completion")
    insert_worker_event(
        submission_id=str(run_row["submission_id"]),
        set_run_id=str(run_row["id"]),
        event_type=event_type,
        message=message or f"{status}:{stage}",
        details=details,
    )


def _mark_failed(run_row: dict[str, object], error: Exception | str, *, stage: str = "failed") -> None:
    message = str(error)
    current = _load_run(str(run_row["id"]))
    if current.get("stage") == "publishing_committed" and not current.get("published_set_id"):
        insert_worker_event(
            submission_id=str(run_row["submission_id"]), set_run_id=str(run_row["id"]),
            event_type="set_run.publish.uncertain",
            message="Publication was admitted; preserve its boundary pending reconciliation",
        )
        return
    mark_set_run(
        str(run_row["id"]),
        status="failed",
        stage=stage,
        error_summary=message,
    )
    finalize_submission_from_runs(str(run_row["submission_id"]))
    insert_worker_event(
        submission_id=str(run_row["submission_id"]),
        set_run_id=str(run_row["id"]),
        event_type="set_run.failed",
        message=message,
    )


def _mark_published_with_errors(
    run_row: dict[str, object],
    error: Exception | str,
    *,
    published_row: dict[str, object] | None = None,
    published_set_id: str | None = None,
) -> str | None:
    message = str(error)
    resolved_published_set_id = published_set_id
    if not resolved_published_set_id and published_row:
        resolved_published_set_id = str(published_row.get("setId") or "") or None

    try:
        mark_set_run(
            str(run_row["id"]),
            status="completed",
            stage="published_with_errors",
            error_summary=message,
            published_set_id=resolved_published_set_id,
        )
    except Exception:
        pass

    if published_row:
        try:
            update_set_run_metadata(
                str(run_row["id"]),
                {
                    "published": {
                        "set_id": published_row.get("setId"),
                        "slug": published_row.get("slug"),
                    }
                },
            )
        except Exception:
            pass

    try:
        finalize_submission_from_runs(str(run_row["submission_id"]))
    except Exception:
        pass

    details: dict[str, object] | None = None
    if published_row:
        details = {
            "published_set_id": resolved_published_set_id,
            "slug": published_row.get("slug"),
        }
    elif resolved_published_set_id:
        details = {"published_set_id": resolved_published_set_id}

    try:
        insert_worker_event(
            submission_id=str(run_row["submission_id"]),
            set_run_id=str(run_row["id"]),
            event_type="set_run.post_publish_error",
            message=message,
            details=details,
        )
    except Exception:
        pass

    return resolved_published_set_id


async def _bootstrap_phase(set_run_id: str) -> dict[str, object]:
    from worker.pipeline.recognize import prepare_set_context, serialize_prepared_context

    run_row = _load_run(set_run_id)
    _assert_not_cancelled(set_run_id)
    _claim_workflow_ownership(set_run_id, force=True)
    _record_stage_change(
        run_row,
        status="resolving",
        stage="resolving",
        event_type="set_run.bootstrap.started",
        message=f"Bootstrapping {run_row['source_url']}",
    )

    from worker.jobs.shared_recognition import RecognitionStore, RecognitionPause
    durable_store = None
    durable_state = None
    try:
        durable_store = RecognitionStore(set_run_id)
        durable_state = durable_store.begin()
        context = prepare_set_context(
            str(run_row["source_url"]),
            artist_name=str(run_row["artist_name"]) if run_row.get("artist_name") else None,
        )
        _assert_run_active(set_run_id)
        scheduler_plan = build_scheduler_plan(context.total_segments)

        metadata_patch = serialize_prepared_context(
            context,
            slot_count=scheduler_plan.slot_count,
            lease_size=scheduler_plan.lease_size,
        )
        metadata_patch["scheduler_plan"] = scheduler_plan.as_metadata()
        update_set_run_metadata(
            set_run_id,
            metadata_patch,
            set_title=str(context.mix_info.get("title") or ""),
            source_url=str(context.source_url),
            source_platform=_detect_source_platform(str(context.source_url)),
        )

        if durable_state is not None:
            lease_count = durable_store.prepared(context, slot_count=scheduler_plan.slot_count,
                                                  lease_size=scheduler_plan.lease_size)
        else:
            lease_count = initialize_set_run_leases(
                set_run_id,
                total_segments=context.total_segments,
                slot_count=scheduler_plan.slot_count,
                lease_size=scheduler_plan.lease_size,
            )

        _record_stage_change(
            run_row,
            status="recognizing",
            stage="queued_recognition",
            event_type="set_run.bootstrap.completed",
            message=f"Prepared {context.total_segments} segments across {lease_count} leases",
            details={
                "segment_count": context.total_segments,
                "lease_count": lease_count,
                "slot_count": scheduler_plan.slot_count,
                "lease_size": scheduler_plan.lease_size,
                "audio_file": str(context.audio_file),
            },
        )

        return {
            "segment_count": context.total_segments,
            "lease_count": lease_count,
            "slot_count": scheduler_plan.slot_count,
            "lease_size": scheduler_plan.lease_size,
            "audio_file": context.audio_file,
        }
    except RunCancelledError:
        raise
    except RecognitionPause:
        # Durable reason/cooldown survives; the existing finalizer requeues only
        # when due and budgets permit, without erasing completed evidence.
        raise
    except Exception:
        _assert_run_active(set_run_id)
        if durable_state is not None:
            durable_store.pause('preparation_failed')
        else:
            _mark_failed(run_row, 'bootstrap_failed', stage="bootstrap_failed")
        raise


async def _recognize_phase(set_run_id: str, *, slot_index: int) -> dict[str, int]:
    from worker.pipeline.recognize import recognize_segment_range, restore_set_context

    run_row = _load_run(set_run_id)
    _assert_run_active(set_run_id)
    source_metadata = dict(run_row.get("source_metadata") or {})
    context = restore_set_context(
        str(run_row["source_url"]),
        artist_name=str(run_row["artist_name"]) if run_row.get("artist_name") else None,
        source_metadata=source_metadata,
    )

    if (source_metadata.get("shared_recognition") or {}).get("version") == 1:
        from worker.jobs.shared_recognition import RecognitionStore, recognize_continuation
        result = {}
        async def run_continuation():
            nonlocal result
            result = await recognize_continuation(RecognitionStore(set_run_id), context,
                                                   check_active=lambda: _assert_run_active(set_run_id), slot_index=slot_index)
        await _recognize_with_cancellation(set_run_id, run_continuation())
        return result

    worker_name = (
        f"{socket.gethostname()}-slot-{slot_index}-"
        f"{os.getenv('GITHUB_RUN_ID', 'local')}-{os.getpid()}"
    )

    claimed = 0
    recognized = 0
    _record_stage_change(
        run_row,
        status="recognizing",
        stage=f"slot_{slot_index}_recognizing",
        event_type="set_run.recognition.started",
        message=f"Slot {slot_index} is claiming leases",
    )

    try:
        while True:
            _assert_run_active(set_run_id)
            lease = claim_next_lease(set_run_id, slot_index=slot_index, worker_name=worker_name)
            if not lease:
                break

            claimed += 1
            lease_id = str(lease["id"])
            start_index = int(lease["segment_start_index"])
            end_index = int(lease["segment_end_index"])

            insert_worker_event(
                submission_id=str(run_row["submission_id"]),
                set_run_id=set_run_id,
                lease_id=lease_id,
                event_type="lease.claimed",
                message=f"Slot {slot_index} claimed segments {start_index}-{end_index}",
            )

            def persist_result(result) -> None:
                nonlocal recognized
                _assert_run_active(set_run_id)
                if result.error_type or result.was_rate_limited or not isinstance(result.raw_data, dict):
                    raise RuntimeError("recognition_provider_error")
                if result.recognized:
                    recognized += 1
                try:
                    upsert_segment_hit(
                        set_run_id=set_run_id,
                        lease_id=lease_id,
                        segment_index=result.segment_index,
                        timestamp_seconds=result.timestamp,
                        track_title=result.track_title,
                        artist=result.artist,
                        shazam_track_id=result.shazam_track_id,
                        recognized=result.recognized,
                        raw_data=result.raw_data,
                    )
                except ForeignKeyViolation as error:
                    if _workflow_superseded(set_run_id):
                        raise WorkflowSupersededError(
                            f"Lease {lease_id} was superseded by a newer workflow run",
                        ) from error
                    raise

            try:
                await _recognize_with_cancellation(set_run_id, recognize_segment_range(
                    context,
                    start_index=start_index,
                    end_index=end_index,
                    on_result=persist_result,
                ))
                _assert_run_active(set_run_id)
                complete_lease(lease_id, success=True)
                insert_worker_event(
                    submission_id=str(run_row["submission_id"]),
                    set_run_id=set_run_id,
                    lease_id=lease_id,
                    event_type="lease.completed",
                    message=f"Completed segments {start_index}-{end_index}",
                )
                mark_run_stage(
                    set_run_id,
                    status="recognizing",
                    stage=f"slot_{slot_index}_recognizing",
                )
            except (WorkflowSupersededError, RunCancelledError):
                raise
            except Exception as error:
                complete_lease(lease_id, success=False, error_text=str(error))
                insert_worker_event(
                    submission_id=str(run_row["submission_id"]),
                    set_run_id=set_run_id,
                    lease_id=lease_id,
                    event_type="lease.failed",
                    message=str(error),
                )
                raise

        insert_worker_event(
            submission_id=str(run_row["submission_id"]),
            set_run_id=set_run_id,
            event_type="set_run.recognition.completed",
            message=f"Slot {slot_index} completed {claimed} leases",
            details={"slot_index": slot_index, "lease_count": claimed, "recognized_count": recognized},
        )
        return {"lease_count": claimed, "recognized_count": recognized}
    except WorkflowSupersededError as error:
        insert_worker_event(
            submission_id=str(run_row["submission_id"]),
            set_run_id=set_run_id,
            event_type="set_run.workflow_superseded",
            message=str(error),
            details={"slot_index": slot_index, "lease_count": claimed, "recognized_count": recognized},
        )
        return {"lease_count": claimed, "recognized_count": recognized}
    except Exception:
        # Let the finalize phase decide the terminal run state after the workflow result is known.
        raise


async def _publish_phase(set_run_id: str) -> str | None:
    from source_url_normalizer import resolve_canonical_source_url
    from worker.pipeline.aggregate import build_tracks_from_recognitions, recognitions_from_segment_hits
    from worker.pipeline.enrich import build_set_payload, enrich_tracks
    from worker.pipeline.recognize import restore_set_context

    run_row = _load_run(set_run_id)
    _assert_not_cancelled(set_run_id)
    if _resume_mode() == "publish_only":
        previous_workflow_run_id = _claim_workflow_ownership(set_run_id, force=True)
        current_workflow_run_id = _workflow_run_id()
        if previous_workflow_run_id and previous_workflow_run_id != current_workflow_run_id:
            insert_worker_event(
                submission_id=str(run_row["submission_id"]),
                set_run_id=set_run_id,
                event_type="set_run.workflow_reclaimed",
                message="Publish-only retry reclaimed workflow ownership",
                details={
                    "phase": "publish",
                    "resume_mode": "publish_only",
                    "previous_workflow_run_id": previous_workflow_run_id,
                    "workflow_run_id": current_workflow_run_id,
                },
            )
    _assert_workflow_ownership(set_run_id)
    canonical_source_url = resolve_canonical_source_url(str(run_row["source_url"]))
    if canonical_source_url != str(run_row["source_url"]):
        update_set_run_metadata(
            set_run_id,
            {},
            source_url=canonical_source_url,
            source_platform=_detect_source_platform(canonical_source_url),
        )

    # If this run already has a published_set_id the data is already in the DB (a prior attempt
    # published successfully but post-publish bookkeeping failed). Skip all the expensive work
    # and only retry the non-fatal bookkeeping steps.
    existing_published_set_id = str(run_row.get("published_set_id") or "") or None
    if existing_published_set_id:
        insert_worker_event(
            submission_id=str(run_row["submission_id"]),
            set_run_id=set_run_id,
            event_type="set_run.publish.bookkeeping_retry",
            message="Set already published; retrying post-publish bookkeeping only",
            details={"published_set_id": existing_published_set_id},
        )
        try:
            finalize_submission_from_runs(str(run_row["submission_id"]))
            insert_worker_event(
                submission_id=str(run_row["submission_id"]),
                set_run_id=set_run_id,
                event_type="set_run.completed",
                message="Post-publish bookkeeping retry completed",
                details={"published_set_id": existing_published_set_id},
            )
            _revalidate(["/", "/archive-preview"], ["archive:home", "archive:lists"])
            mark_set_run(set_run_id, status="completed", stage="published")
        except Exception as bookkeeping_error:
            _mark_published_with_errors(
                run_row,
                bookkeeping_error,
                published_set_id=existing_published_set_id,
            )
        return existing_published_set_id

    source_metadata = dict(run_row.get("source_metadata") or {})
    rollup = get_lease_rollup(set_run_id)

    if not rollup or int(rollup["total_count"] or 0) == 0:
        insert_worker_event(
            submission_id=str(run_row["submission_id"]),
            set_run_id=set_run_id,
            event_type="set_run.publish.deferred",
            message="Publish skipped because no segment leases were available",
        )
        return None
    if int(rollup["pending_count"] or 0) > 0 or int(rollup["claimed_count"] or 0) > 0:
        insert_worker_event(
            submission_id=str(run_row["submission_id"]),
            set_run_id=set_run_id,
            event_type="set_run.publish.deferred",
            message="Publish skipped because recognition leases are still incomplete",
            details={
                "pending_count": int(rollup["pending_count"] or 0),
                "claimed_count": int(rollup["claimed_count"] or 0),
            },
        )
        return None
    if int(rollup["failed_count"] or 0) > 0:
        insert_worker_event(
            submission_id=str(run_row["submission_id"]),
            set_run_id=set_run_id,
            event_type="set_run.publish.deferred",
            message="Publish skipped because one or more recognition leases failed",
            details={"failed_count": int(rollup["failed_count"] or 0)},
        )
        return None

    total_segments = int(source_metadata.get("segment_count") or 0)
    segment_hits = list_segment_hits(set_run_id)
    from worker.jobs.shared_recognition import valid_coverage
    shared_state = source_metadata.get("shared_recognition") or {}
    geometry = shared_state.get("geometry") or {}
    step = geometry.get("segment_duration", 0) - geometry.get("segment_overlap", 0)
    if not valid_coverage(segment_hits, total_segments,
                          versioned=shared_state.get("version") == 1, step=step if geometry else None):
        insert_worker_event(
            submission_id=str(run_row["submission_id"]),
            set_run_id=set_run_id,
            event_type="set_run.publish.deferred",
            message="Publish skipped because segment hit coverage is incomplete",
            details={
                "segment_count": total_segments,
                "segment_hit_count": len(segment_hits),
            },
        )
        return None

    _record_stage_change(
        run_row,
        status="aggregating",
        stage="aggregating",
        event_type="set_run.aggregate.started",
        message="Building setlist from segment hits",
        details={
            "segment_hits": len(segment_hits),
            "lease_rollup": {
                "total_count": int(rollup["total_count"] or 0),
                "completed_count": int(rollup["completed_count"] or 0),
            },
        },
    )

    recognitions = recognitions_from_segment_hits(segment_hits)
    tracks, _ = build_tracks_from_recognitions(recognitions)

    _record_stage_change(
        run_row,
        status="enriching",
        stage="enriching",
        event_type="set_run.enrich.started",
        message="Enriching recognized tracks",
    )

    original_playlist_setting = Config.ENABLE_SPOTIFY_PLAYLISTS
    Config.ENABLE_SPOTIFY_PLAYLISTS = bool(run_row.get("create_playlist"))
    try:
        context = restore_set_context(
            canonical_source_url,
            artist_name=str(run_row["artist_name"]) if run_row.get("artist_name") else None,
            source_metadata=source_metadata,
            require_audio=False,
        )
        context.mix_info["url"] = canonical_source_url
        context.mix_info["source_links"] = source_metadata.get("source_links") or []

        enriched_tracks, mix_info = enrich_tracks(
            tracks,
            mix_info=context.mix_info,
            artist_name=str(run_row["artist_name"]) if run_row.get("artist_name") else None,
        )

        _record_stage_change(
            run_row,
            status="publishing",
            stage="publishing",
            event_type="set_run.publish.started",
            message="Publishing canonical set data",
        )

        _assert_run_active(set_run_id)
        set_payload = build_set_payload(
            enriched_tracks=enriched_tracks,
            mix_info=mix_info,
        )
        published_row = _publish_set_run_payload(
            set_run_id=set_run_id,
            payload=set_payload,
        )
    except RunCancelledError:
        raise
    except PublishSetRunPartialError as error:
        _mark_published_with_errors(run_row, error, published_row=error.published_row)
        raise
    except WorkflowSupersededError as error:
        insert_worker_event(
            submission_id=str(run_row["submission_id"]),
            set_run_id=set_run_id,
            event_type="set_run.workflow_superseded",
            message=str(error),
            details={"phase": "publish"},
        )
        return None
    except Exception as error:
        _assert_run_active(set_run_id)
        _mark_failed(run_row, error, stage="publish_failed")
        raise
    finally:
        Config.ENABLE_SPOTIFY_PLAYLISTS = original_playlist_setting

    # Data is now in the DB. Mark the run completed immediately so the row self-describes
    # as having published data, before any post-publish step that could fail.
    published_set_id = str(published_row["setId"]) if published_row.get("setId") else None
    mark_set_run(
        set_run_id,
        status="completed",
        stage="published",
        published_set_id=published_set_id,
    )

    # Post-publish bookkeeping — non-fatal. Failures are logged but do not change run status
    # or published_set_id, so the run remains self-describing.
    try:
        update_set_run_metadata(
            set_run_id,
            {
                "published": {
                    "set_id": published_row.get("setId"),
                    "slug": published_row.get("slug"),
                }
            },
        )
        finalize_submission_from_runs(str(run_row["submission_id"]))
        insert_worker_event(
            submission_id=str(run_row["submission_id"]),
            set_run_id=set_run_id,
            event_type="set_run.completed",
            message=f"Published {mix_info.get('title') or run_row['source_url']}",
            details={
                "published_set_id": published_set_id,
                "slug": published_row.get("slug"),
            },
        )

        revalidate_paths = [
            "/",
            "/archive-preview",
        ]
        revalidate_tags = ["archive:home", "archive:lists"]
        if published_row.get("slug"):
            slug = str(published_row["slug"])
            revalidate_paths.extend([
                f"/sets/{slug}",
                f"/archive-preview/sets/{slug}",
            ])
            revalidate_tags.append(f"archive:set:{slug}")
        for artist_slug in published_row.get("affectedArtistSlugs", []) or []:
            revalidate_paths.extend([
                f"/artists/{artist_slug}",
                f"/archive-preview/artists/{artist_slug}",
            ])
            revalidate_tags.append(f"archive:artist:{artist_slug}")
        _revalidate(sorted(set(revalidate_paths)), sorted(set(revalidate_tags)))
    except Exception as bookkeeping_error:
        _mark_published_with_errors(run_row, bookkeeping_error, published_row=published_row)

    return published_set_id


async def bootstrap_phase(set_run_id: str) -> dict[str, object]:
    try:
        return await _bootstrap_phase(set_run_id)
    except RunCancelledError:
        _finish_cancelled(set_run_id)
        return {}


async def recognize_phase(set_run_id: str, *, slot_index: int) -> dict[str, int]:
    try:
        return await _recognize_phase(set_run_id, slot_index=slot_index)
    except RunCancelledError:
        _finish_cancelled(set_run_id)
        return {"lease_count": 0, "recognized_count": 0}


async def publish_phase(set_run_id: str) -> str | None:
    try:
        return await _publish_phase(set_run_id)
    except RunCancelledError:
        _finish_cancelled(set_run_id)
        return None


def finalize_phase(
    set_run_id: str,
    *,
    bootstrap_result: str,
    recognize_result: str,
    publish_result: str,
) -> None:
    run_row = _load_run(set_run_id)
    if (run_row.get("cancel_requested_at") or run_row.get("status") in {"cancelling", "cancelled"}) and not run_row.get("published_set_id"):
        _finish_cancelled(set_run_id)
        return
    terminal_status = str(run_row["status"])
    if (run_row.get("source_metadata", {}).get("shared_recognition") or {}).get("version") == 1:
        # Workflow finalization is the app's existing fenced callback. A local
        # finalize invocation must not convert a clean cooldown to terminal failure.
        return

    if terminal_status not in {"completed", "failed", "cancelled"}:
        job_results = {
            "bootstrap": bootstrap_result,
            "recognize": recognize_result,
            "publish": publish_result,
        }
        if any(result not in {"success", "skipped"} for result in job_results.values()):
            _mark_failed(
                run_row,
                f"Workflow failed before completion: {job_results}",
                stage="workflow_failed",
            )
        else:
            _mark_failed(
                run_row,
                "Workflow finished without publishing a terminal set run state",
                stage="workflow_incomplete",
            )

    finalize_submission_from_runs(str(run_row["submission_id"]))


async def run_phase(set_run_id: str) -> str | None:
    bootstrap_result = await bootstrap_phase(set_run_id)
    slot_count = int(bootstrap_result.get("slot_count") or 1)
    for slot_index in range(slot_count):
        await recognize_phase(set_run_id, slot_index=slot_index)
    published_set_id = await publish_phase(set_run_id)
    finalize_phase(
        set_run_id,
        bootstrap_result="success",
        recognize_result="success",
        publish_result="success",
    )
    return published_set_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Process a queued set run")
    parser.add_argument("--set-run-id", required=True)
    parser.add_argument(
        "--phase",
        choices=["bootstrap", "recognize", "publish", "finalize", "run"],
        default="run",
    )
    parser.add_argument("--slot-index", type=int)
    parser.add_argument("--bootstrap-result", default="success")
    parser.add_argument("--recognize-result", default="success")
    parser.add_argument("--publish-result", default="success")
    args = parser.parse_args()

    if args.phase == "bootstrap":
        asyncio.run(bootstrap_phase(args.set_run_id))
        return

    if args.phase == "recognize":
        if args.slot_index is None:
            raise SystemExit("--slot-index is required for recognize phase")
        asyncio.run(recognize_phase(args.set_run_id, slot_index=args.slot_index))
        return

    if args.phase == "publish":
        asyncio.run(publish_phase(args.set_run_id))
        return

    if args.phase == "finalize":
        finalize_phase(
            args.set_run_id,
            bootstrap_result=args.bootstrap_result,
            recognize_result=args.recognize_result,
            publish_result=args.publish_result,
        )
        return

    asyncio.run(run_phase(args.set_run_id))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Driver/provider exceptions can contain SQL values or URLs. Durable
        # state and allowlisted worker events carry the actionable reason.
        raise SystemExit("Worker phase failed; inspect run status") from None
