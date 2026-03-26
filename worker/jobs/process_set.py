"""Process a queued set run end-to-end and publish the output."""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
from pathlib import Path

import requests

from artist_summary import ArtistSummarizer
from checkpoint_manager import ArtistManager
from config import Config
from main import SetlistGenerator
from master_summary import generate_master_summary
from worker.config import REPO_ROOT, get_settings
from worker.db import (
    execute,
    fetch_one,
    finalize_submission_from_runs,
    insert_worker_event,
    mark_set_run,
    touch_set_run,
)


def _dispatch_pending() -> None:
    settings = get_settings()
    if not settings.api_base_url or not settings.internal_secret:
        return

    requests.post(
        f"{settings.api_base_url}/api/internal/dispatch-pending",
        headers={"x-internal-secret": settings.internal_secret},
        timeout=30,
    ).raise_for_status()


def _revalidate(paths: list[str]) -> None:
    settings = get_settings()
    if not settings.api_base_url or not settings.internal_secret:
        return

    requests.post(
        f"{settings.api_base_url}/api/internal/revalidate",
        headers={"x-internal-secret": settings.internal_secret},
        json={"paths": paths},
        timeout=30,
    ).raise_for_status()


def _latest_json_file(output_dir: str) -> Path:
    json_files = sorted(Path(output_dir).glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not json_files:
        raise RuntimeError(f"No JSON output found in {output_dir}")
    return json_files[0]


def _publish_generated_outputs(
    *,
    set_json_path: Path,
    artist_summary_path: Path | None,
    home_html_path: Path | None,
) -> None:
    env = os.environ.copy()
    env["IMPORT_SET_JSON"] = str(set_json_path)
    if artist_summary_path and artist_summary_path.exists():
        env["IMPORT_ARTIST_SUMMARY"] = str(artist_summary_path)
    if home_html_path and home_html_path.exists():
        env["IMPORT_HOME_HTML"] = str(home_html_path)

    subprocess.run(
        ["pnpm", "--filter", "web", "import:archive"],
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )


def _refresh_artist_outputs(artist_name: str, result: dict[str, str]) -> tuple[Path | None, Path | None]:
    artist_manager = ArtistManager(artist_name)
    ArtistSummarizer(artist_manager=artist_manager).generate([result])
    home_html = generate_master_summary(Config.OUTPUT_DIR)
    return artist_manager.output_dir / "artist_summary.html", home_html


async def _process_set(run_row: dict[str, object]) -> str | None:
    set_run_id = str(run_row["id"])
    submission_id = str(run_row["submission_id"])
    source_url = str(run_row["source_url"])
    artist_name = run_row.get("artist_name")

    touch_set_run(set_run_id, stage="bootstrapping", status="running")
    insert_worker_event(
        submission_id=submission_id,
        set_run_id=set_run_id,
        event_type="set_run.started",
        message=f"Processing {source_url}",
    )

    original_playlist_setting = Config.ENABLE_SPOTIFY_PLAYLISTS
    Config.ENABLE_SPOTIFY_PLAYLISTS = bool(run_row.get("create_playlist"))
    try:
        generator = SetlistGenerator()
        mix_name, output_dir, _ = await generator.generate(
            source_url,
            resume=False,
            artist_name=str(artist_name) if artist_name else None,
        )
        set_json_path = _latest_json_file(output_dir)

        artist_summary_path = None
        home_html_path = None
        if artist_name:
            artist_summary_path, home_html_path = _refresh_artist_outputs(
                str(artist_name),
                {
                    "url": source_url,
                    "status": "SUCCESS",
                    "mix_name": mix_name,
                    "output_dir": output_dir,
                },
            )

        _publish_generated_outputs(
            set_json_path=set_json_path,
            artist_summary_path=artist_summary_path,
            home_html_path=home_html_path,
        )

        published_row = fetch_one(
            """
            select id, legacy_path
            from app.sets
            where source_url = %s
            order by updated_at desc
            limit 1
            """,
            (source_url,),
        )

        published_set_id = str(published_row["id"]) if published_row else None
        mark_set_run(
            set_run_id,
            status="completed",
            stage="published",
            published_set_id=published_set_id,
        )
        finalize_submission_from_runs(submission_id)
        insert_worker_event(
            submission_id=submission_id,
            set_run_id=set_run_id,
            event_type="set_run.completed",
            message=f"Published {mix_name}",
            details={"published_set_id": published_set_id},
        )

        revalidate_paths = ["/", "/sets"]
        if published_row and published_row.get("legacy_path"):
            revalidate_paths.append(str(published_row["legacy_path"]))
        if artist_summary_path and artist_summary_path.exists():
            relative = "/" + str(artist_summary_path.relative_to(Config.OUTPUT_DIR)).replace(os.sep, "/")
            revalidate_paths.extend(["/artists", relative])
        _revalidate(revalidate_paths)

        return published_set_id
    except Exception as exc:
        mark_set_run(set_run_id, status="failed", stage="failed", error_summary=str(exc))
        finalize_submission_from_runs(submission_id)
        insert_worker_event(
            submission_id=submission_id,
            set_run_id=set_run_id,
            event_type="set_run.failed",
            message=str(exc),
        )
        raise
    finally:
        Config.ENABLE_SPOTIFY_PLAYLISTS = original_playlist_setting
        _dispatch_pending()


def run(set_run_id: str) -> str | None:
    run_row = fetch_one(
        """
        select
          r.id,
          r.submission_id,
          r.source_url,
          r.create_playlist,
          s.artist_name
        from ops.set_runs r
        inner join ops.submissions s on s.id = r.submission_id
        where r.id = %s
        """,
        (set_run_id,),
    )
    if not run_row:
        raise RuntimeError(f"Set run {set_run_id} was not found")
    return asyncio.run(_process_set(run_row))


def main() -> None:
    parser = argparse.ArgumentParser(description="Process a queued set run")
    parser.add_argument("--set-run-id", required=True)
    args = parser.parse_args()
    run(args.set_run_id)


if __name__ == "__main__":
    main()
