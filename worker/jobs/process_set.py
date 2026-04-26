"""Phase-based processing for queued set runs."""

from __future__ import annotations

import argparse
import asyncio
import os
import socket

from psycopg.errors import ForeignKeyViolation

from config import Config
from worker.config import get_settings
from worker.db import (
    claim_next_lease,
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


class PublishSetRunPartialError(RuntimeError):
    """Raised when publish writes set data but fails a later server-side step."""

    def __init__(self, message: str, *, published_row: dict[str, object]) -> None:
        super().__init__(message)
        self.published_row = published_row


def _dispatch_pending() -> None:
    import requests

    settings = get_settings()
    if not settings.api_base_url or not settings.internal_secret:
        return

    requests.post(
        f"{settings.api_base_url}/api/internal/dispatch-pending",
        headers={"x-internal-secret": settings.internal_secret},
        timeout=30,
    ).raise_for_status()


def _revalidate(paths: list[str], tags: list[str] | None = None) -> None:
    import requests

    settings = get_settings()
    if not settings.api_base_url or not settings.internal_secret:
        return

    requests.post(
        f"{settings.api_base_url}/api/internal/revalidate",
        headers={"x-internal-secret": settings.internal_secret},
        json={"paths": paths, "tags": tags or []},
        timeout=30,
    ).raise_for_status()


def _publish_set_run_payload(
    *,
    set_run_id: str,
    payload: dict[str, object],
) -> dict[str, object]:
    import requests

    settings = get_settings()
    if not settings.api_base_url or not settings.internal_secret:
        raise RuntimeError("APP_BASE_URL and INTERNAL_WORKER_SHARED_SECRET are required for publish")

    response = requests.post(
        f"{settings.api_base_url}/api/internal/publish-set-run",
        headers={"x-internal-secret": settings.internal_secret},
        json={
            "setRunId": set_run_id,
            "payload": payload,
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
    if "soundcloud.com" in source_url:
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

    previous_workflow_run_id = get_active_workflow_run_id(set_run_id)
    if previous_workflow_run_id == workflow_run_id:
        return previous_workflow_run_id
    if previous_workflow_run_id and not force:
        return previous_workflow_run_id

    update_set_run_metadata(
        set_run_id,
        {"active_workflow_run_id": workflow_run_id},
    )
    return previous_workflow_run_id


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


def _record_stage_change(
    run_row: dict[str, object],
    *,
    status: str,
    stage: str,
    event_type: str = "set_run.stage_changed",
    message: str | None = None,
    details: dict[str, object] | None = None,
) -> None:
    mark_run_stage(str(run_row["id"]), status=status, stage=stage)
    insert_worker_event(
        submission_id=str(run_row["submission_id"]),
        set_run_id=str(run_row["id"]),
        event_type=event_type,
        message=message or f"{status}:{stage}",
        details=details,
    )


def _mark_failed(run_row: dict[str, object], error: Exception | str, *, stage: str = "failed") -> None:
    message = str(error)
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


async def bootstrap_phase(set_run_id: str) -> dict[str, object]:
    from worker.pipeline.recognize import prepare_set_context, serialize_prepared_context

    run_row = _load_run(set_run_id)
    _claim_workflow_ownership(set_run_id, force=True)
    _record_stage_change(
        run_row,
        status="resolving",
        stage="resolving",
        event_type="set_run.bootstrap.started",
        message=f"Bootstrapping {run_row['source_url']}",
    )

    try:
        context = prepare_set_context(
            str(run_row["source_url"]),
            artist_name=str(run_row["artist_name"]) if run_row.get("artist_name") else None,
        )
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
            source_platform=_detect_source_platform(str(run_row["source_url"])),
        )

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
    except Exception as error:
        _mark_failed(run_row, error, stage="bootstrap_failed")
        raise


async def recognize_phase(set_run_id: str, *, slot_index: int) -> dict[str, int]:
    from worker.pipeline.recognize import recognize_segment_range, restore_set_context

    run_row = _load_run(set_run_id)
    _assert_workflow_ownership(set_run_id)
    source_metadata = dict(run_row.get("source_metadata") or {})
    context = restore_set_context(
        str(run_row["source_url"]),
        artist_name=str(run_row["artist_name"]) if run_row.get("artist_name") else None,
        source_metadata=source_metadata,
    )

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
            _assert_workflow_ownership(set_run_id)
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
                _assert_workflow_ownership(set_run_id)
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
                await recognize_segment_range(
                    context,
                    start_index=start_index,
                    end_index=end_index,
                    on_result=persist_result,
                )
                _assert_workflow_ownership(set_run_id)
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
            except WorkflowSupersededError:
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


async def publish_phase(set_run_id: str) -> str | None:
    from worker.pipeline.aggregate import build_tracks_from_recognitions, recognitions_from_segment_hits
    from worker.pipeline.enrich import build_set_payload, enrich_tracks
    from worker.pipeline.recognize import restore_set_context

    run_row = _load_run(set_run_id)
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
    if total_segments > 0 and len(segment_hits) != total_segments:
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
            str(run_row["source_url"]),
            artist_name=str(run_row["artist_name"]) if run_row.get("artist_name") else None,
            source_metadata=source_metadata,
            require_audio=False,
        )

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

        _assert_workflow_ownership(set_run_id)
        set_payload = build_set_payload(
            enriched_tracks=enriched_tracks,
            mix_info=mix_info,
        )
        published_row = _publish_set_run_payload(
            set_run_id=set_run_id,
            payload=set_payload,
        )
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


def finalize_phase(
    set_run_id: str,
    *,
    bootstrap_result: str,
    recognize_result: str,
    publish_result: str,
) -> None:
    run_row = _load_run(set_run_id)
    terminal_status = str(run_row["status"])

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
    main()
