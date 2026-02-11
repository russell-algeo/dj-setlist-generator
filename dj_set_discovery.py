"""DJ set discovery using Claude CLI with web search.

Uses `claude -p` to intelligently search the web for all recorded DJ sets
by a given artist, returning structured URLs for processing.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from config import Config

DISCOVERY_PROMPT = """You are a DJ set research assistant. Your job is to find every publicly available recorded DJ set (audio or video) for a given artist on YouTube and SoundCloud.

Search the web extensively for sets. Perform MANY searches with different strategies:

1. Direct searches:
   - "{artist}" DJ set
   - "{artist}" live set
   - "{artist}" mix

2. Known DJ set platforms/channels:
   - "{artist}" Boiler Room
   - "{artist}" HÖR Berlin
   - "{artist}" Cercle
   - "{artist}" Resident Advisor
   - "{artist}" fabric
   - "{artist}" Dekmantel
   - "{artist}" Mixmag
   - "{artist}" DJ Mag
   - "{artist}" Possession
   - "{artist}" HATE
   - "{artist}" Nuits Sonores

3. Platform-specific:
   - site:youtube.com "{artist}" DJ set
   - site:soundcloud.com "{artist}" DJ set
   - site:youtube.com "{artist}" live
   - site:soundcloud.com "{artist}" mix

4. Event/festival searches:
   - "{artist}" festival set
   - "{artist}" club set
   - "{artist}" warehouse

5. If the artist has known aliases or alternate names, search those too.

IMPORTANT RULES:
- Only include URLs from youtube.com or soundcloud.com
- Only include actual DJ sets/mixes (NOT interviews, track premieres, music videos, or short clips)
- DJ sets are typically 30+ minutes long
- Deduplicate: if the same set appears on multiple channels, prefer the official/highest quality one
- For each result, extract: URL, title, platform, approximate duration if visible, event/venue name, year

Return your results as a JSON array. Each entry must have these fields:
{{
  "url": "https://...",
  "title": "descriptive title of the set",
  "platform": "youtube" or "soundcloud",
  "event": "event or venue name if known, otherwise null",
  "year": "year if known, otherwise null",
  "duration_minutes": estimated duration in minutes if known, otherwise null
}}

Be thorough. Search at least 8-10 different queries. The user wants EVERY available recorded set.

Find every publicly available recorded DJ set by {artist}. Search YouTube and SoundCloud thoroughly using many different search queries. Return ONLY the JSON array of results, no other text."""


def discover_dj_sets(artist_name: str, cache_dir: Path = None) -> list[dict]:
    """Discover DJ sets for an artist using the Claude CLI with web search.

    Args:
        artist_name: Name of the DJ/artist to search for.
        cache_dir: Directory to cache discovery results. If discovery.json
                   exists here, returns cached results.

    Returns:
        List of dicts with keys: url, title, platform, event, year, duration_minutes
    """
    # Check for cached discovery results
    if cache_dir:
        cache_file = cache_dir / "discovery.json"
        if cache_file.exists():
            print(f"  Found cached discovery results: {cache_file}")
            with open(cache_file) as f:
                cached = json.load(f)
            print(f"  Loaded {len(cached['sets'])} previously discovered sets")
            return cached["sets"]

    if not shutil.which("claude"):
        print("\n❌ 'claude' CLI not found on PATH.")
        print("   Install Claude Code: https://docs.anthropic.com/en/docs/claude-code")
        sys.exit(1)

    prompt = DISCOVERY_PROMPT.replace("{artist}", artist_name)

    print(f"  Searching the web for DJ sets by '{artist_name}'...")
    print(f"  Using model: {Config.DISCOVERY_MODEL}")
    print(f"  This may take a minute as Claude searches multiple platforms...\n")

    cmd = [
        "claude", "-p", prompt,
        "--model", Config.DISCOVERY_MODEL,
        "--allowedTools", "WebSearch,WebFetch",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        print(f"  ❌ claude CLI returned exit code {result.returncode}")
        if result.stderr:
            print(f"  stderr: {result.stderr[:500]}")
        return []

    sets = _parse_response_text(result.stdout)

    if not sets:
        print("  ⚠ No DJ sets found. Claude may need more specific search terms.")
        return []

    # Apply max sets limit
    if Config.MAX_SETS_PER_ARTIST > 0 and len(sets) > Config.MAX_SETS_PER_ARTIST:
        print(f"  Limiting to {Config.MAX_SETS_PER_ARTIST} sets (found {len(sets)})")
        sets = sets[:Config.MAX_SETS_PER_ARTIST]

    # Cache results
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "discovery.json"
        with open(cache_file, "w") as f:
            json.dump({"artist": artist_name, "sets": sets}, f, indent=2)
        print(f"  💾 Cached discovery results to {cache_file}")

    return sets


def _parse_response_text(text: str) -> list[dict]:
    """Extract the structured set list from Claude's text output."""
    text = text.strip()
    if not text:
        return []

    # Strip markdown code fences if present
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # Try direct parse first
    parsed = _try_parse_json_array(text)
    if parsed is not None:
        return parsed

    # Try to find a JSON array embedded in surrounding text
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        parsed = _try_parse_json_array(text[start:end + 1])
        if parsed is not None:
            return parsed

    print("  ⚠ Could not parse discovery results from Claude's response.")
    return []


def _try_parse_json_array(text: str) -> list[dict] | None:
    """Try to parse text as a JSON array of set dicts. Returns None on failure."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, list):
        return None

    validated = []
    for entry in data:
        if isinstance(entry, dict) and "url" in entry:
            validated.append({
                "url": entry["url"],
                "title": entry.get("title", "Unknown Set"),
                "platform": entry.get("platform", _detect_platform(entry["url"])),
                "event": entry.get("event"),
                "year": entry.get("year"),
                "duration_minutes": entry.get("duration_minutes"),
            })
    return validated


def _detect_platform(url: str) -> str:
    """Detect platform from URL."""
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    elif "soundcloud.com" in url:
        return "soundcloud"
    return "unknown"


def print_discovery_results(sets: list[dict], artist_name: str):
    """Print a formatted summary of discovered sets."""
    print(f"\n{'=' * 70}")
    print(f"DISCOVERED DJ SETS FOR: {artist_name.upper()}")
    print(f"{'=' * 70}")
    print(f"Found {len(sets)} sets\n")

    for i, s in enumerate(sets, 1):
        platform_icon = "🎬" if s["platform"] == "youtube" else "🔊"
        duration = f" ({s['duration_minutes']}min)" if s.get("duration_minutes") else ""
        event = f" @ {s['event']}" if s.get("event") else ""
        year = f" [{s['year']}]" if s.get("year") else ""
        print(f"  {i:2d}. {platform_icon} {s['title']}{event}{year}{duration}")
        print(f"      {s['url']}")

    yt_count = sum(1 for s in sets if s["platform"] == "youtube")
    sc_count = sum(1 for s in sets if s["platform"] == "soundcloud")
    print(f"\n  YouTube: {yt_count} | SoundCloud: {sc_count}")
    print()
