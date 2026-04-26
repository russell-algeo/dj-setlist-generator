#!/usr/bin/env python3
"""Targeted dry-run/apply backfill for alternate set source links.

Default mode is read-only. Use --apply to persist accepted alternate links.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from source_link_matcher import MatchSource, score_source_match

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

load_dotenv(os.path.join(REPO_ROOT, ".env"), override=False)
load_dotenv(os.path.join(REPO_ROOT, "apps", "web", ".env.local"), override=False)

ACCEPTED = "accepted"
AMBIGUOUS = "ambiguous"
REJECTED = "rejected"
SUPPORTED_PLATFORMS = {"youtube", "soundcloud"}
IGNORED_ARTIST_TOKENS = {"dj", "de", "fr", "uk", "us", "usa", "live", "official"}
MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


@dataclass
class KnownSet:
    id: str
    slug: str
    title: str
    artist_name: str | None
    source_platform: str
    source_url: str
    duration_seconds: int | None
    uploader: str | None


@dataclass
class Candidate:
    platform: str
    url: str
    title: str
    duration_seconds: int | None
    uploader: str | None
    raw: dict[str, Any]


@dataclass
class ReviewedMatch:
    set_slug: str
    candidate: Candidate
    decision: dict[str, Any]


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (value or "").lower())).strip()


def detect_platform(url: str | None) -> str:
    value = (url or "").lower()
    if "soundcloud.com" in value:
        return "soundcloud"
    if "youtube.com" in value or "youtu.be" in value:
        return "youtube"
    return "unknown"


def title_similarity(left: str, right: str) -> float:
    return difflib.SequenceMatcher(None, normalize_text(left), normalize_text(right)).ratio()


def extract_years(value: str | None) -> set[int]:
    return {int(match.group(0)) for match in re.finditer(r"\b(?:19|20)\d{2}\b", value or "")}


def extract_part_markers(value: str | None) -> set[str]:
    text = normalize_text(value)
    markers = set()
    for match in re.finditer(r"\b(?:part|pt)\s+([0-9ivx]+)\b", text):
        markers.add(match.group(1))
    return markers


def normalize_year(value: str) -> int:
    year = int(value)
    if year < 100:
        return 2000 + year if year <= 68 else 1900 + year
    return year


def add_date(dates: set[str], year: int, month: int, day: int) -> None:
    try:
        dates.add(date(year, month, day).isoformat())
    except ValueError:
        return


def extract_dates(value: str | None) -> set[str]:
    text = value or ""
    dates: set[str] = set()

    for match in re.finditer(r"\b((?:19|20)\d{2})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})\b", text):
        year, month, day = normalize_year(match.group(1)), int(match.group(2)), int(match.group(3))
        add_date(dates, year, month, day)

    for match in re.finditer(r"\b(\d{1,2})\s*[-./]\s*(\d{1,2})\s*[-./]\s*((?:19|20)?\d{2})\b", text):
        first, second, year = int(match.group(1)), int(match.group(2)), normalize_year(match.group(3))
        add_date(dates, year, first, second)
        add_date(dates, year, second, first)

    month_pattern = "|".join(MONTHS)
    for match in re.finditer(
        rf"\b({month_pattern})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?[,]?\s+((?:19|20)?\d{{2}})\b",
        text,
        flags=re.IGNORECASE,
    ):
        add_date(dates, normalize_year(match.group(3)), MONTHS[match.group(1).lower().rstrip(".")], int(match.group(2)))
    for match in re.finditer(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_pattern})\.?[,]?\s+((?:19|20)?\d{{2}})\b",
        text,
        flags=re.IGNORECASE,
    ):
        add_date(dates, normalize_year(match.group(3)), MONTHS[match.group(2).lower().rstrip(".")], int(match.group(1)))

    return dates


def token_set(value: str | None) -> set[str]:
    return set(normalize_text(value).split())


def significant_artist_tokens(value: str | None) -> set[str]:
    return {token for token in token_set(value) if len(token) > 1 and token not in IGNORED_ARTIST_TOKENS}


def duration_diff_minutes(known: KnownSet, candidate: Candidate) -> float | None:
    if known.duration_seconds is None or candidate.duration_seconds is None:
        return None
    return abs(known.duration_seconds - candidate.duration_seconds) / 60


def score_candidate(known: KnownSet, candidate: Candidate) -> dict[str, Any]:
    return score_source_match(
        MatchSource(
            title=known.title,
            platform=known.source_platform,
            duration_seconds=known.duration_seconds,
            uploader=known.uploader,
        ),
        MatchSource(
            title=candidate.title,
            platform=candidate.platform,
            duration_seconds=candidate.duration_seconds,
            uploader=candidate.uploader,
        ),
        artist_names=[known.artist_name] if known.artist_name else [],
    )


def search_queries(known: KnownSet, per_query_limit: int) -> list[str]:
    target = "scsearch" if known.source_platform == "youtube" else "ytsearch"
    terms = [
        f"{known.artist_name or ''} {known.title}".strip(),
        known.title,
    ]
    if known.uploader:
        terms.append(f"{known.artist_name or ''} {known.uploader} {known.title}".strip())

    queries: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = normalize_text(term)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        queries.append(f"{target}{per_query_limit}:{term}")
    return queries


def ytdlp_command() -> list[str]:
    override = os.getenv("YT_DLP_BIN")
    if override:
        return [override]
    local_binary = os.path.join(REPO_ROOT, ".venv", "bin", "yt-dlp")
    if os.path.exists(local_binary):
        return [local_binary]
    path_binary = shutil.which("yt-dlp")
    if path_binary:
        return [path_binary]
    return [sys.executable, "-m", "yt_dlp"]


def run_search(query: str, timeout: int, retries: int, retry_sleep: float) -> tuple[list[Candidate], str | None]:
    cmd = [
        *ytdlp_command(),
        "--dump-json",
        "--flat-playlist",
        "--no-download",
        "--no-warnings",
        query,
    ]
    message = ""
    attempts = max(1, retries + 1)
    for attempt in range(1, attempts + 1):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            message = f"timed out after {timeout}s"
            if attempt < attempts:
                time.sleep(retry_sleep * attempt)
                continue
            return [], f"{query}: {message}"

        if result.returncode == 0:
            break

        message = (result.stderr or result.stdout).strip()
        is_retryable = "HTTP Error 403" in message or "Forbidden" in message or "timed out" in message.lower()
        if attempt < attempts and is_retryable:
            print(
                f"yt-dlp search retry {attempt}/{retries} for {query}: {message[-300:]}",
                file=sys.stderr,
            )
            time.sleep(retry_sleep * attempt)
            continue
        if message:
            print(f"yt-dlp search failed for {query}: {message[-500:]}", file=sys.stderr)
        return [], f"{query}: {message[-1000:]}"
    else:  # pragma: no cover - loop always returns or breaks.
        return [], f"{query}: {message}"

    candidates: list[Candidate] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        url = raw.get("webpage_url") or raw.get("url") or ""
        title = raw.get("title") or ""
        duration = raw.get("duration")
        candidates.append(
            Candidate(
                platform=detect_platform(url),
                url=url,
                title=title,
                duration_seconds=int(duration) if isinstance(duration, (int, float)) else None,
                uploader=raw.get("uploader") or raw.get("channel"),
                raw=raw,
            )
        )
    return candidates, None


def load_sets(args: argparse.Namespace) -> list[KnownSet]:
    from worker.db import fetch_all

    clauses = ["s.source_url is not null", "s.source_platform in ('youtube', 'soundcloud')"]
    params: list[Any] = []
    retry_error_slugs = slugs_with_search_errors(args.retry_errors_from) if getattr(args, "retry_errors_from", None) else []
    if getattr(args, "retry_errors_from", None) and not retry_error_slugs:
        return []
    if retry_error_slugs:
        clauses.append("s.slug = any(%s)")
        params.append(retry_error_slugs)
    if args.set_slug:
        clauses.append("s.slug = %s")
        params.append(args.set_slug)
    if args.artist:
        clauses.append("lower(a.name) = lower(%s)")
        params.append(args.artist)
    limit = args.sample or args.limit
    query = f"""
        select
          s.id,
          s.slug,
          s.title,
          s.source_platform,
          s.source_url,
          s.duration_seconds,
          s.uploader,
          a.name as artist_name
        from app.sets s
        left join lateral (
          select a.name
          from app.set_artists sa
          join app.artists a on a.id = sa.artist_id
          where sa.set_id = s.id and sa.role = 'primary'
          order by a.name asc
          limit 1
        ) a on true
        where {' and '.join(clauses)}
        order by s.updated_at desc, s.title asc
        {f'limit {int(limit)}' if limit else ''}
    """
    rows = fetch_all(query, tuple(params))
    return [
        KnownSet(
            id=str(row["id"]),
            slug=str(row["slug"]),
            title=str(row["title"]),
            artist_name=row.get("artist_name"),
            source_platform=str(row["source_platform"]),
            source_url=str(row["source_url"]),
            duration_seconds=row.get("duration_seconds"),
            uploader=row.get("uploader"),
        )
        for row in rows
    ]


def slugs_with_search_errors(path: str) -> list[str]:
    with open(path, encoding="utf-8") as handle:
        report = json.load(handle)
    if not isinstance(report, list):
        raise ValueError("--retry-errors-from must point at a JSON report array")

    slugs: list[str] = []
    seen: set[str] = set()
    for item in report:
        if not isinstance(item, dict) or not item.get("search_errors"):
            continue
        set_data = item.get("set")
        if not isinstance(set_data, dict):
            continue
        slug = set_data.get("slug")
        if isinstance(slug, str) and slug not in seen:
            seen.add(slug)
            slugs.append(slug)
    return slugs


def candidate_from_data(data: dict[str, Any]) -> Candidate:
    return Candidate(
        platform=str(data["platform"]),
        url=str(data["url"]),
        title=str(data.get("title") or ""),
        duration_seconds=data.get("duration_seconds"),
        uploader=data.get("uploader"),
        raw={},
    )


def load_reviewed_matches(path: str) -> list[ReviewedMatch]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, list):
        raise ValueError("--reviewed-input must be a JSON array of reviewed match objects")

    reviewed: list[ReviewedMatch] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"reviewed match #{index} must be an object")
        status = item.get("review_status") or item.get("status")
        if status != ACCEPTED:
            continue
        set_slug = item.get("set_slug") or item.get("slug")
        candidate_data = item.get("candidate")
        if not set_slug or not isinstance(candidate_data, dict):
            raise ValueError(f"accepted reviewed match #{index} must include set_slug and candidate")
        decision = item.get("decision") if isinstance(item.get("decision"), dict) else {}
        reviewed.append(
            ReviewedMatch(
                set_slug=str(set_slug),
                candidate=candidate_from_data(candidate_data),
                decision={
                    "status": ACCEPTED,
                    "score": decision.get("score", 1.0),
                    "reason": decision.get("reason", "manual_review"),
                    **decision,
                },
            )
        )
    return reviewed


def review_records_from_report(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for result in report:
        set_data = result["set"]
        for match in result["matches"]:
            status = match["decision"]["status"]
            if status not in {ACCEPTED, AMBIGUOUS}:
                continue
            records.append(
                {
                    "review_status": "pending",
                    "set_slug": set_data["slug"],
                    "set_title": set_data["title"],
                    "set_artist": set_data.get("artist_name"),
                    "source_platform": set_data["source_platform"],
                    "source_url": set_data["source_url"],
                    "candidate": match["candidate"],
                    "decision": match["decision"],
                }
            )
    records.sort(
        key=lambda item: (
            item["decision"]["status"] != ACCEPTED,
            -float(item["decision"].get("score", 0)),
            item["set_slug"],
        )
    )
    return records


def upsert_source_link(set_id: str, candidate: Candidate, decision: dict[str, Any]) -> None:
    from worker.db import execute, json_value

    execute(
        """
        insert into app.set_source_links (
          set_id,
          platform,
          url,
          title,
          duration_seconds,
          is_primary,
          match_confidence,
          metadata
        )
        values (%s, %s, %s, %s, %s, false, %s, %s)
        on conflict (set_id, platform, url) do update set
          title = excluded.title,
          duration_seconds = excluded.duration_seconds,
          match_confidence = excluded.match_confidence,
          metadata = excluded.metadata,
          updated_at = now()
        """,
        (
            set_id,
            candidate.platform,
            candidate.url,
            candidate.title,
            candidate.duration_seconds,
            decision["score"],
            json_value({"backfill": decision, "uploader": candidate.uploader}),
        ),
    )


def seed_canonical_source_link(known: KnownSet) -> None:
    from worker.db import execute, json_value

    execute(
        """
        insert into app.set_source_links (
          set_id,
          platform,
          url,
          title,
          duration_seconds,
          is_primary,
          match_confidence,
          metadata
        )
        values (%s, %s, %s, %s, %s, true, 1.0, %s)
        on conflict (set_id, platform, url) do update set
          title = excluded.title,
          duration_seconds = excluded.duration_seconds,
          is_primary = true,
          updated_at = now()
        """,
        (
            known.id,
            known.source_platform,
            known.source_url,
            known.title,
            known.duration_seconds,
            json_value({"source": "canonical_backfill"}),
        ),
    )


def evaluate_set(known: KnownSet, args: argparse.Namespace) -> dict[str, Any]:
    candidates_by_url: dict[str, Candidate] = {}
    search_errors: list[str] = []
    for query in search_queries(known, args.per_query_limit):
        candidates, error = run_search(query, args.timeout, args.search_retries, args.retry_sleep)
        if error:
            search_errors.append(error)
        for candidate in candidates:
            if candidate.url:
                candidates_by_url.setdefault(candidate.url, candidate)

    evaluated = []
    for candidate in candidates_by_url.values():
        decision = score_candidate(known, candidate)
        evaluated.append(
            {
                "candidate": {
                    "platform": candidate.platform,
                    "url": candidate.url,
                    "title": candidate.title,
                    "duration_seconds": candidate.duration_seconds,
                    "uploader": candidate.uploader,
                },
                "decision": decision,
            }
        )

    evaluated.sort(key=lambda item: (item["decision"]["status"] != ACCEPTED, -item["decision"]["score"]))
    return {
        "set": {
            "id": known.id,
            "slug": known.slug,
            "title": known.title,
            "artist_name": known.artist_name,
            "source_platform": known.source_platform,
            "source_url": known.source_url,
            "duration_seconds": known.duration_seconds,
        },
        "queries": search_queries(known, args.per_query_limit),
        "matches": evaluated,
        "search_errors": search_errors,
    }


def print_result(result: dict[str, Any]) -> None:
    set_data = result["set"]
    accepted = [match for match in result["matches"] if match["decision"]["status"] == ACCEPTED]
    ambiguous = [match for match in result["matches"] if match["decision"]["status"] == AMBIGUOUS]
    print(f"\n{set_data['slug']} [{set_data['source_platform']}] {set_data['title']}")
    print(f"  accepted={len(accepted)} ambiguous={len(ambiguous)} candidates={len(result['matches'])}")
    if result.get("search_errors"):
        print(f"  search_errors={len(result['search_errors'])}")
    for match in result["matches"][:3]:
        candidate = match["candidate"]
        decision = match["decision"]
        print(
            f"  {decision['status']:9} score={decision['score']:.4f} "
            f"sim={decision['title_similarity']:.2f} "
            f"dur={decision['duration_diff_minutes']}m "
            f"{candidate['platform']} {candidate['title']} {candidate['url']}"
        )


def evaluate_sets(known_sets: list[KnownSet], args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.workers <= 1:
        report = []
        for index, known in enumerate(known_sets, start=1):
            result = evaluate_set(known, args)
            report.append(result)
            print_result(result)
            print(f"  progress={index}/{len(known_sets)}")
        return report

    report_by_slug: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(evaluate_set, known, args): known for known in known_sets}
        for index, future in enumerate(as_completed(futures), start=1):
            known = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # pragma: no cover - defensive reporting for long CLI runs.
                print(f"\n{known.slug} [{known.source_platform}] {known.title}")
                print(f"  error={exc}", file=sys.stderr)
                result = {
                    "set": {
                        "id": known.id,
                        "slug": known.slug,
                        "title": known.title,
                        "artist_name": known.artist_name,
                        "source_platform": known.source_platform,
                        "source_url": known.source_url,
                        "duration_seconds": known.duration_seconds,
                    },
                    "queries": search_queries(known, args.per_query_limit),
                    "matches": [],
                    "search_errors": [],
                    "error": str(exc),
                }
            report_by_slug[known.slug] = result
            print_result(result)
            print(f"  progress={index}/{len(known_sets)}")

    return [report_by_slug[known.slug] for known in known_sets if known.slug in report_by_slug]


def apply_reviewed_matches(args: argparse.Namespace) -> None:
    if not args.reviewed_input:
        raise ValueError("--reviewed-input is required with --apply")

    load_args = argparse.Namespace(**vars(args))
    load_args.artist = None
    load_args.limit = None
    load_args.sample = None
    load_args.set_slug = None
    known_by_slug = {known.slug: known for known in load_sets(load_args)}
    reviewed = load_reviewed_matches(args.reviewed_input)
    missing_slugs = sorted({match.set_slug for match in reviewed if match.set_slug not in known_by_slug})
    if missing_slugs:
        raise ValueError(f"reviewed input references unknown set slug(s): {', '.join(missing_slugs[:5])}")

    print(f"Reviewed accepted matches: {len(reviewed)}")
    if not args.apply:
        print("Mode: dry-run reviewed input validation")
        return

    by_slug: dict[str, list[ReviewedMatch]] = {}
    for match in reviewed:
        by_slug.setdefault(match.set_slug, []).append(match)

    for set_slug, matches in by_slug.items():
        known = known_by_slug[set_slug]
        seed_canonical_source_link(known)
        for match in matches:
            upsert_source_link(known.id, match.candidate, match.decision)
        print(f"Applied {len(matches)} reviewed match(es) for {set_slug}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill alternate YouTube/SoundCloud set source links")
    parser.add_argument("--apply", action="store_true", help="Persist accepted matches")
    parser.add_argument("--dry-run", action="store_true", help="Inspect matches without writing; this is the default")
    parser.add_argument("--artist", help="Only inspect sets for this primary artist")
    parser.add_argument("--limit", type=int, help="Maximum sets to inspect")
    parser.add_argument("--per-query-limit", type=int, default=5)
    parser.add_argument("--report", help="Write full JSON report to this path")
    parser.add_argument("--review-candidates", help="Write accepted/ambiguous candidates for manual review")
    parser.add_argument("--reviewed-input", help="Read manually accepted candidates and apply only those with --apply")
    parser.add_argument("--retry-errors-from", help="Only inspect sets with search_errors in a prior JSON report")
    parser.add_argument("--sample", type=int, help="Inspect a small sample")
    parser.add_argument("--set-slug", help="Only inspect one set slug")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--workers", type=int, default=1, help="Number of sets to evaluate concurrently")
    parser.add_argument("--search-retries", type=int, default=3, help="Retries for transient yt-dlp search failures")
    parser.add_argument("--retry-sleep", type=float, default=5.0, help="Base seconds to sleep between search retries")
    args = parser.parse_args()

    if args.workers < 1:
        raise ValueError("--workers must be at least 1")

    if args.reviewed_input:
        apply_reviewed_matches(args)
        return

    if args.apply:
        raise ValueError("--apply requires --reviewed-input so writes are based on manually reviewed matches")

    known_sets = load_sets(args)
    report = evaluate_sets(known_sets, args)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)

    if args.review_candidates:
        with open(args.review_candidates, "w", encoding="utf-8") as handle:
            json.dump(review_records_from_report(report), handle, indent=2)

    print("\nMode:", "dry-run")
    print(f"Inspected {len(known_sets)} sets")


if __name__ == "__main__":
    main()
