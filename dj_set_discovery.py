"""DJ set discovery using yt-dlp direct search.

Searches YouTube and SoundCloud directly via yt-dlp to find all recorded
DJ sets by a given artist, returning structured URLs for processing.
"""

import json
import re
import subprocess
from collections import defaultdict
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

        sets = _deduplicate_near_duplicates(sets, self._artist_name)

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
    "behind the scenes", "unboxing", "tribute"
]


_GENERIC_TERMS = ["DJ set", "live set", "mix", "guest mix", "b2b", "live", "podcast"]
_CHANNELS = [
    "Boiler Room", "HÖR Berlin", "Cercle",
    "Resident Advisor", "Dekmantel", "Mixmag",
    "themuddshow", "Dimensions Festival", "fabric",
    "XLR8R", "Rinse FM", "Robot Heart", "MEOKO", "Desert Hearts",
]


# ---------------------------------------------------------------------------
# Near-duplicate deduplication helpers
# ---------------------------------------------------------------------------

_DEDUP_DURATION_WINDOW_MINUTES = 5
_DEDUP_JACCARD_THRESHOLD = 0.25
_ORDINAL_PREFIX_WORDS = {
    "episode", "vol", "volume", "part", "pt", "installment", "chapter",
    "no", "nr", "number", "edition", "ed", "ep",
}
_DEDUP_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "at", "on", "for",
    "to", "by", "with", "from",
}


def _tokenize_title(title: str, artist_name: str) -> set[str]:
    """Tokenize title, removing artist name tokens and common stopwords."""
    artist_tokens = set(_normalize(artist_name).split())
    return set(_normalize(title).split()) - artist_tokens - _DEDUP_STOPWORDS


def _jaccard(a: set, b: set) -> float:
    """Jaccard similarity between two sets."""
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def _extract_title_years(title: str) -> set[int]:
    """Extract 4-digit years (19xx or 20xx) explicitly present in a title."""
    return {int(m.group()) for m in re.finditer(r'\b(19|20)\d{2}\b', title)}


def _extract_episode_numbers(title: str) -> set[int]:
    """Extract numbers immediately following ordinal-prefix words.

    For example: "Episode 12" → {12}, "Vol 3" → {3}, "Radio 1" → {} (radio
    is not an ordinal prefix).
    """
    tokens = _normalize(title).split()
    nums: set[int] = set()
    for i, tok in enumerate(tokens):
        if tok in _ORDINAL_PREFIX_WORDS and i + 1 < len(tokens):
            candidate = tokens[i + 1]
            if candidate.isdigit():
                nums.add(int(candidate))
    return nums


def _are_near_duplicates(a: DiscoveredSet, b: DiscoveredSet, artist_name: str) -> bool:
    """Return True if a and b are near-duplicates (same set, differently titled).

    Four rules, applied in order:
      1. Duration window: both must have duration data and be within 5 minutes.
      2. Year conflict: if both titles contain 4-digit years and those years
         don't overlap, they are different editions → not duplicates.
      3. Episode number conflict: if both titles have a number immediately after
         an ordinal-prefix word (e.g. "episode 12") and those numbers differ,
         they are different episodes → not duplicates.
      4. Jaccard title similarity: after removing artist tokens and stopwords,
         similarity must be >= 0.25 to be considered a duplicate.
    """
    # Rule 1: duration required and within window
    if a.duration_minutes is None or b.duration_minutes is None:
        return False
    if abs(a.duration_minutes - b.duration_minutes) > _DEDUP_DURATION_WINDOW_MINUTES:
        return False

    # Rule 2: year conflict (e.g. Essential Mix 2019 vs Essential Mix 2020)
    years_a = _extract_title_years(a.title)
    years_b = _extract_title_years(b.title)
    if years_a and years_b and not (years_a & years_b):
        return False

    # Rule 3: episode number conflict (e.g. installment 1 vs installment 12)
    ep_a = _extract_episode_numbers(a.title)
    ep_b = _extract_episode_numbers(b.title)
    if ep_a and ep_b and ep_a != ep_b:
        return False

    # Rule 4: Jaccard similarity on cleaned title tokens
    tokens_a = _tokenize_title(a.title, artist_name)
    tokens_b = _tokenize_title(b.title, artist_name)
    return _jaccard(tokens_a, tokens_b) >= _DEDUP_JACCARD_THRESHOLD


def _deduplicate_near_duplicates(
    sets: list[DiscoveredSet], artist_name: str
) -> list[DiscoveredSet]:
    """Remove near-duplicate sets, preferring SoundCloud over YouTube.

    Uses Union-Find to cluster all sets that are pairwise near-duplicates
    (handles transitive chains: A~B, B~C → all three merge). From each
    cluster, keeps the SoundCloud entry if one exists, otherwise the first
    by discovery order.
    """
    n = len(sets)
    if n < 2:
        return sets

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path-halving compression
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    for i in range(n):
        for j in range(i + 1, n):
            if _are_near_duplicates(sets[i], sets[j], artist_name):
                union(i, j)

    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        clusters[find(i)].append(i)

    winners: list[DiscoveredSet] = []
    removed_count = 0
    seen_roots: set[int] = set()

    for i in range(n):
        root = find(i)
        if root in seen_roots:
            continue
        seen_roots.add(root)

        members = clusters[root]
        if len(members) == 1:
            winners.append(sets[members[0]])
            continue

        # Prefer SoundCloud; otherwise keep first by original order
        sc_members = [idx for idx in members if sets[idx].platform == "soundcloud"]
        winner_idx = sc_members[0] if sc_members else members[0]
        winner = sets[winner_idx]
        winners.append(winner)

        removed_count += len(members) - 1
        for idx in members:
            if idx != winner_idx:
                dropped = sets[idx]
                plat = dropped.platform.upper()[:2]
                print(f"  [dedup] Dropped [{plat}] '{dropped.title}'")
        w_plat = winner.platform.upper()[:2]
        print(f"  [dedup] Kept    [{w_plat}] '{winner.title}' (cluster of {len(members)})")

    if removed_count:
        print(f"  Near-duplicate dedup removed {removed_count} set(s) → {len(winners)} unique")

    return winners


def _build_search_queries(artist_name: str) -> list[str]:
    """Build the list of yt-dlp search queries for an artist."""
    n = Config.DISCOVERY_RESULTS_PER_QUERY
    quoted = f'"{artist_name}"'

    terms = [f"{quoted} {t}" for t in _GENERIC_TERMS + _CHANNELS]

    queries = [f"ytsearch{n}:{term}" for term in terms]
    queries += [f"scsearch{n}:{term}" for term in terms]
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

