"""DJ set discovery using yt-dlp direct search.

Searches YouTube and SoundCloud directly via yt-dlp to find all recorded
DJ sets by a given artist, returning structured URLs for processing.
"""

import json
import re
import subprocess
from dataclasses import dataclass, asdict
from typing import Optional
from config import Config


@dataclass
class DiscoveredSet:
    """A DJ set discovered via search."""
    url: str
    title: str
    platform: str
    event: Optional[str]
    year: Optional[str]
    duration_minutes: Optional[int]

    @classmethod
    def from_dict(cls, data: dict) -> 'DiscoveredSet':
        return cls(
            url=data["url"],
            title=data["title"],
            platform=data["platform"],
            event=data.get("event"),
            year=data.get("year"),
            duration_minutes=data.get("duration_minutes"),
        )


class DjSetDiscoverer:
    """Discover DJ sets for an artist using yt-dlp search."""

    def __init__(self, artist_manager):
        self._artist_name = artist_manager.artist_name
        self._cache_dir = artist_manager.checkpoint_dir

    def discover(self) -> list[DiscoveredSet]:
        """Discover DJ sets, print results, and return them.

        Applies Config.MAX_SETS_PER_ARTIST limit internally.
        Uses cached results in checkpoint_dir/discovery.json if present.
        """
        # Check for cached results
        cache_file = self._cache_dir / "discovery.json"
        if cache_file.exists():
            print(f"  Found cached discovery results: {cache_file}")
            with open(cache_file) as f:
                cached = json.load(f)
            print(f"  Loaded {len(cached['sets'])} previously discovered sets")
            sets = [DiscoveredSet.from_dict(s) for s in cached["sets"]]
            self._print_results(sets)
            return sets

        queries = _build_search_queries(self._artist_name)

        print(f"  Searching YouTube & SoundCloud for DJ sets by '{self._artist_name}'...")
        print(f"  Running {len(queries)} search queries...\n")

        seen_ids: set[str] = set()
        all_results: list[dict] = []

        for i, query in enumerate(queries, 1):
            print(f"  [{i}/{len(queries)}] {query}")
            results = _search_yt_dlp(query)
            for entry in results:
                entry_id = entry.get("id", "")
                if entry_id and entry_id not in seen_ids:
                    seen_ids.add(entry_id)
                    all_results.append(entry)
            print(f"           → {len(results)} results ({len(all_results)} unique total)")

        print(f"\n  Found {len(all_results)} unique results before filtering")

        sets = _filter_and_map(all_results, self._artist_name)
        print(f"  After filtering: {len(sets)} DJ sets")

        if not sets:
            print("  No DJ sets found matching criteria.")
            return []

        # Apply limit
        if Config.MAX_SETS_PER_ARTIST > 0 and len(sets) > Config.MAX_SETS_PER_ARTIST:
            print(f"  Limiting to {Config.MAX_SETS_PER_ARTIST} sets (found {len(sets)})")
            sets = sets[:Config.MAX_SETS_PER_ARTIST]

        # Cache results
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "w") as f:
            json.dump({"artist": self._artist_name, "sets": [asdict(s) for s in sets]}, f, indent=2)
        print(f"  Cached discovery results to {cache_file}")

        self._print_results(sets)
        return sets

    def _print_results(self, sets: list[DiscoveredSet]):
        """Print a formatted summary of discovered sets."""
        print(f"\n{'=' * 70}")
        print(f"DISCOVERED DJ SETS FOR: {self._artist_name.upper()}")
        print(f"{'=' * 70}")
        print(f"Found {len(sets)} sets\n")

        for i, s in enumerate(sets, 1):
            platform_icon = "YT" if s.platform == "youtube" else "SC"
            duration = f" ({s.duration_minutes}min)" if s.duration_minutes else ""
            event = f" @ {s.event}" if s.event else ""
            year = f" [{s.year}]" if s.year else ""
            print(f"  {i:2d}. [{platform_icon}] {s.title}{event}{year}{duration}")
            print(f"      {s.url}")

        yt_count = sum(1 for s in sets if s.platform == "youtube")
        sc_count = sum(1 for s in sets if s.platform == "soundcloud")
        print(f"\n  YouTube: {yt_count} | SoundCloud: {sc_count}")
        print()


# Title keywords that indicate a result is NOT a DJ set
_EXCLUDE_KEYWORDS = [
    "interview", "premiere", "panel", "review", "trailer", "reaction",
    "tutorial", "official video", "music video", "teaser",
    "behind the scenes", "unboxing", "podcast",
]



_YT_GENERIC_TERMS = ["DJ set", "live set", "mix"]
_YT_CHANNELS = [
    "Boiler Room", "HÖR Berlin", "Cercle",
    "Resident Advisor", "Dekmantel", "Mixmag",
]
_SC_TERMS = ["DJ set", "mix", "live"]


def _build_search_queries(artist_name: str) -> list[str]:
    """Build the list of yt-dlp search queries for an artist."""
    n = Config.DISCOVERY_RESULTS_PER_QUERY
    quoted = f'"{artist_name}"'

    yt_terms = [f"{quoted} {t}" for t in _YT_GENERIC_TERMS + _YT_CHANNELS]
    sc_terms = [f"{quoted} {t}" for t in _SC_TERMS]

    queries = [f"ytsearch{n}:{term}" for term in yt_terms]
    queries += [f"scsearch{n}:{term}" for term in sc_terms]
    return queries


def _search_yt_dlp(query: str) -> list[dict]:
    """Run a single yt-dlp search query and return parsed results.

    Uses --flat-playlist to get metadata without downloading.
    """
    cmd = [
        "yt-dlp",
        "--dump-json",
        "--flat-playlist",
        "--no-download",
        "--no-warnings",
        query,
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        print(f"           Search timed out")
        return []

    if result.returncode != 0:
        return []

    entries = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _normalize(text: str) -> str:
    """Normalize text for artist name matching.

    Replaces common separators with spaces, collapses whitespace, lowercases.
    """
    text = re.sub(r"[_\-.]", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _filter_and_map(raw_results: list[dict], artist_name: str) -> list[DiscoveredSet]:
    """Filter raw yt-dlp results and map to DiscoveredSet instances."""
    min_duration_seconds = Config.MIN_SET_DURATION_MINUTES * 60
    artist_norm = _normalize(artist_name)
    seen_titles: set[str] = set()
    sets: list[DiscoveredSet] = []

    for entry in raw_results:
        title = entry.get("title", "")
        channel = entry.get("channel") or ""
        uploader = entry.get("uploader") or ""
        duration = entry.get("duration")

        # Filter: artist name must appear in title, channel, or uploader
        if not any(
            artist_norm in _normalize(field)
            for field in (title, channel, uploader)
        ):
            continue

        # Filter by duration
        if duration is not None and duration < min_duration_seconds:
            continue

        # Filter by title keywords
        title_lower = title.lower()
        if any(kw in title_lower for kw in _EXCLUDE_KEYWORDS):
            continue

        # Build URL
        url = entry.get("webpage_url") or entry.get("url", "")
        if not url:
            continue

        # Cross-platform dedup by normalized title
        title_norm = _normalize(title)
        if title_norm in seen_titles:
            continue
        seen_titles.add(title_norm)

        # Extract year from upload_date (YYYYMMDD)
        upload_date = entry.get("upload_date") or ""
        year = upload_date[:4] if len(upload_date) >= 4 else None

        # Duration in minutes
        duration_minutes = round(duration / 60) if duration else None

        # Try to extract event/venue from uploader or channel
        event = entry.get("channel") or entry.get("uploader")

        sets.append(DiscoveredSet(
            url=url,
            title=title or "Unknown Set",
            platform=_detect_platform(url),
            event=event,
            year=year,
            duration_minutes=duration_minutes,
        ))

    return sets


def _detect_platform(url: str) -> str:
    """Detect platform from URL."""
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    elif "soundcloud.com" in url:
        return "soundcloud"
    return "unknown"

