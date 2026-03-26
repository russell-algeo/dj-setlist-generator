"""Remote-first CLI with local fallback."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from urllib import error as urllib_error
from urllib import request as urllib_request
from typing import Any

from worker.config import clear_auth, get_settings, save_auth


def _is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _require_remote_config(base_url: str | None = None) -> tuple[str, str]:
    settings = get_settings(base_url)
    if not settings.api_base_url:
        raise RuntimeError("Remote mode requires SET_LIST_API_BASE_URL, APP_BASE_URL, or a saved base URL")
    if not settings.api_token:
        raise RuntimeError("Remote mode requires a saved API token or SET_LIST_API_TOKEN")
    return settings.api_base_url, settings.api_token


def _auth_headers(base_url: str | None = None) -> tuple[str, dict[str, str]]:
    api_base_url, api_token = _require_remote_config(base_url)
    return api_base_url, {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}


def _print_submission(detail: dict[str, Any]) -> None:
    submission = detail["submission"]
    print("=" * 70)
    print(f"Submission: {submission['id']}")
    print(f"Mode:       {submission['mode']}")
    print(f"Status:     {submission['status']}")
    if submission.get("artistName"):
        print(f"Artist:     {submission['artistName']}")
    if submission.get("sourceUrl"):
        print(f"Source:     {submission['sourceUrl']}")
    print("=" * 70)

    runs = detail.get("runs") or []
    if runs:
        print("Set runs:")
        for run in runs:
            print(f"  - {run['status']:10s} {run.get('stage') or 'queued':12s} {run['sourceUrl']}")

    events = detail.get("events") or []
    if events:
        print("\nRecent events:")
        for event in events[:5]:
            print(f"  - {event['eventType']}: {event['message']}")


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    payload = None
    request_headers = dict(headers)
    if body is not None:
      payload = json.dumps(body).encode("utf8")
      request_headers.setdefault("Content-Type", "application/json")

    request = urllib_request.Request(
        url,
        data=payload,
        headers=request_headers,
        method=method,
    )

    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib_error.HTTPError as exc:
        details = exc.read().decode("utf8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: {exc.code} {details}") from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc.reason}") from exc

    if not raw:
        return {}

    return json.loads(raw.decode("utf8"))


def _poll_submission(submission_id: str, *, base_url: str | None, interval: int) -> dict[str, Any]:
    api_base_url, headers = _auth_headers(base_url)
    terminal_states = {"completed", "failed", "cancelled"}

    while True:
        detail = _request_json(
            "GET",
            f"{api_base_url}/api/jobs/{submission_id}",
            headers=headers,
        )
        _print_submission(detail)
        if detail["submission"]["status"] in terminal_states:
            return detail
        time.sleep(interval)


def _submit_remote(payload: dict[str, Any], *, wait: bool, base_url: str | None, interval: int) -> dict[str, Any]:
    api_base_url, headers = _auth_headers(base_url)
    detail = _request_json(
        "POST",
        f"{api_base_url}/api/jobs",
        headers=headers,
        body=payload,
    )
    submission_id = detail["submissionId"]
    print(f"Queued submission {submission_id}")
    if wait:
        return _poll_submission(submission_id, base_url=base_url, interval=interval)
    return detail


def _status_remote(submission_id: str, *, wait: bool, base_url: str | None, interval: int) -> dict[str, Any]:
    if wait:
        return _poll_submission(submission_id, base_url=base_url, interval=interval)

    api_base_url, headers = _auth_headers(base_url)
    detail = _request_json(
        "GET",
        f"{api_base_url}/api/jobs/{submission_id}",
        headers=headers,
    )
    _print_submission(detail)
    return detail


async def _run_local(args: argparse.Namespace) -> None:
    from main import process_artist, process_curated_artist, process_urls

    if args.artist and args.sets:
        await process_curated_artist(args.artist, args.sets, resume=not args.no_resume)
        return

    targets = args.targets
    urls = [target for target in targets if _is_url(target)]
    artists = [target for target in targets if not _is_url(target)]

    if urls:
        await process_urls(urls, resume=not args.no_resume)
        return

    if artists:
        for artist_name in artists:
            await process_artist(artist_name, resume=not args.no_resume)
        return

    raise RuntimeError("No local targets were provided")


def _build_auth_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage saved CLI auth")
    parser.set_defaults(subcommand="auth")
    subparsers = parser.add_subparsers(dest="auth_command", required=True)

    login_parser = subparsers.add_parser("login", help="Save an API token locally")
    login_parser.add_argument("--token", required=True)
    login_parser.add_argument("--base-url")

    subparsers.add_parser("logout", help="Remove the saved API token")
    return parser


def _build_main_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Remote-first CLI for the DJ set deployment")
    parser.set_defaults(subcommand=None)
    parser.add_argument("targets", nargs="*")
    parser.add_argument("--artist")
    parser.add_argument("--sets", nargs="+")
    parser.add_argument("--status")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--base-url")
    return parser


def _parse_args(argv: list[str]) -> argparse.Namespace:
    if argv and argv[0] == "auth":
        return _build_auth_parser().parse_args(argv[1:])

    return _build_main_parser().parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])

    if args.subcommand == "auth":
        if args.auth_command == "login":
            save_auth(args.token, args.base_url)
            print("Saved API token for remote CLI use")
            return 0
        if args.auth_command == "logout":
            clear_auth()
            print("Cleared saved API token")
            return 0

    if args.status:
        _status_remote(args.status, wait=args.wait, base_url=args.base_url, interval=args.interval)
        return 0

    if args.local:
        asyncio.run(_run_local(args))
        return 0

    if args.artist and args.sets:
        _submit_remote(
            {
                "mode": "curated_artist",
                "artistName": args.artist,
                "sourceUrls": args.sets,
            },
            wait=args.wait,
            base_url=args.base_url,
            interval=args.interval,
        )
        return 0

    if not args.targets:
        raise RuntimeError("Provide a URL, artist name, --artist with --sets, or --status")

    urls = [target for target in args.targets if _is_url(target)]
    artists = [target for target in args.targets if not _is_url(target)]

    if urls and artists:
        raise RuntimeError("Do not mix URLs and artist names in the same command")

    if urls:
        for url in urls:
            _submit_remote(
                {
                    "mode": "url",
                    "sourceUrl": url,
                },
                wait=args.wait,
                base_url=args.base_url,
                interval=args.interval,
            )
        return 0

    for artist_name in artists:
        _submit_remote(
            {
                "mode": "artist",
                "artistName": artist_name,
            },
            wait=args.wait,
            base_url=args.base_url,
            interval=args.interval,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
