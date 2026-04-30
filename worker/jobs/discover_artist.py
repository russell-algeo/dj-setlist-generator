"""Discover artist jobs and persist queued set runs."""

from __future__ import annotations

import argparse
import requests

from checkpoint_manager import ArtistManager
from config import Config
from source_url_normalizer import resolve_canonical_source_url
from worker.config import get_settings
from worker.db import execute, fetch_one, finalize_submission_from_runs, insert_worker_event, json_value, mark_submission
from worker.providers.ytdlp import DjSetDiscoverer


def _dispatch_pending() -> None:
    settings = get_settings()
    if not settings.api_base_url or not settings.internal_secret:
        return

    requests.post(
        f"{settings.api_base_url}/api/internal/dispatch-pending",
        headers={"x-internal-secret": settings.internal_secret},
        timeout=30,
    ).raise_for_status()


def run(submission_id: str) -> None:
    submission = fetch_one(
        """
        select id, artist_name, artist_aliases, max_sets_override
        from ops.submissions
        where id = %s
        """,
        (submission_id,),
    )
    if not submission:
        raise RuntimeError(f"Submission {submission_id} was not found")

    artist_name = submission.get("artist_name")
    if not artist_name:
        raise RuntimeError(f"Submission {submission_id} is missing artist_name")
    artist_aliases = submission.get("artist_aliases") or []
    if not isinstance(artist_aliases, list):
        artist_aliases = []
    search_names = [artist_name, *[str(alias).strip() for alias in artist_aliases if str(alias).strip()]]

    insert_worker_event(
        submission_id=submission_id,
        event_type="submission.discovery.started",
        message=f"Starting discovery for {artist_name}",
    )
    mark_submission(submission_id, status="running")

    original_max_sets = Config.MAX_SETS_PER_ARTIST
    try:
        if submission.get("max_sets_override"):
            Config.MAX_SETS_PER_ARTIST = int(submission["max_sets_override"])

        artist_manager = ArtistManager(artist_name)
        sets = DjSetDiscoverer(artist_manager=artist_manager, search_names=search_names).discover()
        canonical_sets = []
        for candidate in sets:
            canonical_url = resolve_canonical_source_url(candidate.url)
            raw_source_links = candidate.source_links or [
                {
                    "url": candidate.url,
                    "platform": candidate.platform,
                    "title": candidate.title,
                    "duration_seconds": candidate.duration_minutes * 60 if candidate.duration_minutes else None,
                    "is_primary": True,
                    "metadata": {
                        "event": candidate.event,
                        "year": candidate.year,
                        "duration_minutes": candidate.duration_minutes,
                    },
                }
            ]
            canonical_source_links = []
            for source_link in raw_source_links:
                link_url = str(source_link.get("url") or candidate.url)
                canonical_source_links.append(
                    {
                        **dict(source_link),
                        "url": resolve_canonical_source_url(link_url),
                    }
                )
            canonical_sets.append((candidate, canonical_url, canonical_source_links))

        execute("delete from ops.discovery_candidates where submission_id = %s", (submission_id,))

        for candidate, canonical_url, source_links in canonical_sets:
            for source_link in source_links:
                is_primary = source_link.get("url") == canonical_url
                execute(
                    """
                    insert into ops.discovery_candidates (
                      submission_id,
                      source_url,
                      source_platform,
                      source_title,
                      duration_seconds,
                      status,
                      metadata
                    )
                    values (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        submission_id,
                        source_link.get("url") or canonical_url,
                        source_link.get("platform") or candidate.platform,
                        source_link.get("title") or candidate.title,
                        source_link.get("duration_seconds")
                        or (candidate.duration_minutes * 60 if candidate.duration_minutes else None),
                        "accepted" if is_primary else "alternate",
                        json_value(
                            {
                                **dict(source_link.get("metadata") or {}),
                                "primary_source_url": canonical_url,
                                "is_primary": is_primary,
                            }
                        ),
                    ),
                )

        if not sets:
            mark_submission(submission_id, status="failed", error_summary="No DJ sets discovered")
            insert_worker_event(
                submission_id=submission_id,
                event_type="submission.discovery.empty",
                message="No DJ sets discovered",
            )
            return

        for candidate, canonical_url, source_links in canonical_sets:
            execute(
                """
                insert into ops.set_runs (
                  submission_id,
                  requested_by,
                  status,
                  stage,
                  source_url,
                  source_platform,
                  set_title,
                  create_playlist,
                  source_metadata,
                  published_set_id,
                  completed_at
                )
                select
                  s.id,
                  s.requested_by,
                  case when pub.published_set_id is not null then 'completed' else 'queued' end,
                  case when pub.published_set_id is not null then 'deduped' else null end,
                  %s,
                  %s,
                  %s,
                  s.create_playlist,
                  %s,
                  pub.published_set_id,
                  case when pub.published_set_id is not null then now() else null end
                from ops.submissions s
                left join lateral (
                  select published_set_id
                  from ops.set_runs pub
                  where pub.source_url = %s
                    and pub.status = 'completed'
                    and pub.published_set_id is not null
                  limit 1
                ) pub on true
                where s.id = %s
                  and not exists (
                    select 1
                    from ops.set_runs existing
                    where existing.submission_id = s.id
                      and existing.source_url = %s
                  )
                """,
                (
                    canonical_url,
                    candidate.platform,
                    candidate.title,
                    json_value(
                        {
                            "event": candidate.event,
                            "year": candidate.year,
                            "duration_minutes": candidate.duration_minutes,
                            "source_links": source_links,
                        }
                    ),
                    canonical_url,
                    submission_id,
                    canonical_url,
                ),
            )

        insert_worker_event(
            submission_id=submission_id,
            event_type="submission.discovery.completed",
            message=f"Queued {len(sets)} discovered sets",
            details={"set_count": len(sets)},
        )

        # If all discovered sets were deduped (already published), finalise the submission
        # immediately — no worker will complete runs to trigger this otherwise.
        queued_count = fetch_one(
            """
            select count(*) as count
            from ops.set_runs
            where submission_id = %s and status = 'queued'
            """,
            (submission_id,),
        )
        if not queued_count or int(queued_count.get("count") or 0) == 0:
            finalize_submission_from_runs(submission_id)
        else:
            mark_submission(submission_id, status="running")
            _dispatch_pending()
    except Exception as exc:
        mark_submission(submission_id, status="failed", error_summary=str(exc))
        insert_worker_event(
            submission_id=submission_id,
            event_type="submission.discovery.failed",
            message=str(exc),
        )
        raise
    finally:
        Config.MAX_SETS_PER_ARTIST = original_max_sets


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover artist sets for a queued submission")
    parser.add_argument("--submission-id", required=True)
    args = parser.parse_args()
    run(args.submission_id)


if __name__ == "__main__":
    main()
