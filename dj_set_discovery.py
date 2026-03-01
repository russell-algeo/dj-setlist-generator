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
# Words too generic to distinguish between different events of the same type
# (e.g. two different Boiler Room sets, two different promo mixes).
_FORMAT_NOISE = {
    "dj", "set", "live", "b2b", "mix", "boiler", "room",
    "promo", "guest", "podcast", "recorded", "|", "@", "#", "&",
}
# Maps every month name variant to its integer (1–12) for normalised comparison.
_MONTH_NAMES_TO_NUM: dict[str, int] = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def _tokenize_title(title: str, artist_name: str) -> set[str]:
    """Tokenize title, removing artist name tokens and common stopwords."""
    artist_tokens = set(_normalize(artist_name).split())
    return set(_normalize(title).split()) - artist_tokens - _DEDUP_STOPWORDS


def _content_tokens(title: str, artist_name: str) -> set[str]:
    """Tokenize title, also stripping format-noise words.

    Used for the content-disjointness check: if both titles have non-empty,
    fully disjoint content token sets they describe different events.
    """
    return _tokenize_title(title, artist_name) - _FORMAT_NOISE


def _extract_title_months(title: str) -> set[int]:
    """Extract months (1–12) from a title via name or numeric date pattern.

    Handles named months ("January", "jan") and numeric date triplets produced
    after normalisation ("29 03 2024", "09 20 2024", "01 01 2020"):
      - A > 12 and 1 ≤ B ≤ 12  →  DD MM YYYY, month = B
      - 1 ≤ A ≤ 12 and B > 12  →  MM DD YYYY, month = A
      - both ≤ 12               →  ambiguous; add both as candidates
    """
    tokens = _normalize(title).split()
    months: set[int] = set()

    for tok in tokens:
        if tok in _MONTH_NAMES_TO_NUM:
            months.add(_MONTH_NAMES_TO_NUM[tok])

    years = _extract_title_years(title)
    for i in range(len(tokens) - 2):
        a_s, b_s, c_s = tokens[i], tokens[i + 1], tokens[i + 2]
        if not (a_s.isdigit() and b_s.isdigit() and c_s.isdigit()):
            continue
        if not re.match(r'(19|20)\d{2}$', c_s):
            continue
        a, b = int(a_s), int(b_s)
        if a > 12 and 1 <= b <= 12:
            months.add(b)
        elif b > 12 and 1 <= a <= 12:
            months.add(a)
        else:
            # Both ≤ 12: ambiguous format — add both candidates conservatively
            if 1 <= a <= 12:
                months.add(a)
            if 1 <= b <= 12:
                months.add(b)

    return months


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

    Rules applied in order:
      1. Duration window: both must have duration data and be within 5 minutes.
      2. Year conflict: if both titles contain 4-digit years and those years
         don't overlap, they are different editions → not duplicates.
      2.5. Month conflict: if both titles contain month names or numeric date
         patterns (e.g. "29.03.2024") and the detected months don't overlap,
         they are different sessions → not duplicates.
      3. Episode number conflict: if either title has a number immediately after
         an ordinal-prefix word (e.g. "episode 12") and those numbers differ,
         they are different episodes → not duplicates.
      3.5. Bare numeric series conflict: if the only tokens that differ between
         the two titles are non-year integers that don't match (e.g. "CruiseCast
         001" vs "CruiseCast 002"), they are different episodes → not duplicates.
         Zero-padded and plain numbers compare equal (001 == 1).
      4. Jaccard title similarity: after removing artist tokens and stopwords,
         similarity must be >= 0.25 to be considered a duplicate.
      5. Content token disjointness: after also stripping format-noise words
         (including "podcast"), if both titles have non-empty, fully disjoint
         token sets they describe different events → not duplicates.
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

    # Rule 2.5: month conflict (e.g. HÖR January session vs HÖR November session)
    months_a = _extract_title_months(a.title)
    months_b = _extract_title_months(b.title)
    if months_a and months_b and not (months_a & months_b):
        return False

    # Rule 3: episode number conflict — fires when either side has an episode
    # number and they differ (e.g. "Tribute Mix" vs "Tribute Mix Pt 2")
    ep_a = _extract_episode_numbers(a.title)
    ep_b = _extract_episode_numbers(b.title)
    if (ep_a or ep_b) and ep_a != ep_b:
        return False

    # Rule 3.5: bare numeric series conflict — fires when the ONLY tokens that
    # differ between two titles are non-year integers that don't match, e.g.
    # "CruiseCast 001" vs "CruiseCast 002" or "DIM 324" vs "DIM 325".
    # Zero-padded and plain numbers compare equal after int() conversion.
    tokens_a = _tokenize_title(a.title, artist_name)
    tokens_b = _tokenize_title(b.title, artist_name)
    diff_a = tokens_a - tokens_b
    diff_b = tokens_b - tokens_a
    if diff_a and diff_b:
        all_years = _extract_title_years(a.title) | _extract_title_years(b.title)
        if all(tok.isdigit() and int(tok) not in all_years for tok in diff_a | diff_b):
            if {int(t) for t in diff_a} != {int(t) for t in diff_b}:
                return False

    # Rule 4: Jaccard similarity on cleaned title tokens
    if _jaccard(tokens_a, tokens_b) < _DEDUP_JACCARD_THRESHOLD:
        return False

    # Rule 5: content token disjointness — if both titles still have non-empty,
    # fully disjoint tokens after stripping format noise, they describe different
    # events that merely share a common format (e.g. two different Boiler Room
    # sets, two different promo mixes).
    # If either side is empty, there's not enough meaningful signal to confirm
    # a duplicate — default to keeping both.
    content_a = _content_tokens(a.title, artist_name)
    content_b = _content_tokens(b.title, artist_name)
    if not content_a or not content_b:
        return False
    if not (content_a & content_b):
        return False

    return True


def _deduplicate_near_duplicates(
    sets: list[DiscoveredSet], artist_name: str
) -> list[DiscoveredSet]:
    """Remove near-duplicate sets, preferring SoundCloud over YouTube.

    Uses Union-Find to find candidate clusters, then applies a clique check:
    each non-winner member must directly match the winner to be dropped.
    Members that only match transitively (A~B, B~C but not A~C) are evicted
    back to singleton status, preventing false positives from transitive chains.
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
        w_plat = winner.platform.upper()[:2]

        # Clique check: only drop members that directly match the winner.
        # Members that reached this cluster only transitively are evicted back
        # to singleton status to prevent false-positive removals.
        dropped_count = 0
        for idx in members:
            if idx == winner_idx:
                continue
            candidate = sets[idx]
            plat = candidate.platform.upper()[:2]
            if _are_near_duplicates(candidate, winner, artist_name):
                removed_count += 1
                dropped_count += 1
                print(f"  [dedup] Dropped [{plat}] '{candidate.title}'")
            else:
                winners.append(candidate)
                print(f"  [dedup] Evicted [{plat}] '{candidate.title}' (transitive-only match)")

        print(f"  [dedup] Kept    [{w_plat}] '{winner.title}' (dropped {dropped_count} duplicate(s))")

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

