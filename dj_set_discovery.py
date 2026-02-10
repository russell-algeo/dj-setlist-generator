"""DJ set discovery using Claude API with web search.

Uses Claude to intelligently search the web for all recorded DJ sets
by a given artist, returning structured URLs for processing.
"""

import json
import sys
from pathlib import Path
from config import Config

DISCOVERY_SYSTEM_PROMPT = """You are a DJ set research assistant. Your job is to find every publicly available recorded DJ set (audio or video) for a given artist on YouTube and SoundCloud.

You MUST use the web_search tool extensively to find sets. Perform MANY searches with different strategies:

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
{
  "url": "https://...",
  "title": "descriptive title of the set",
  "platform": "youtube" or "soundcloud",
  "event": "event or venue name if known, otherwise null",
  "year": "year if known, otherwise null",
  "duration_minutes": estimated duration in minutes if known, otherwise null
}

Be thorough. Search at least 8-10 different queries. The user wants EVERY available recorded set."""


def discover_dj_sets(artist_name: str, cache_dir: Path = None) -> list[dict]:
    """Discover DJ sets for an artist using Claude API with web search.

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

    if not Config.ANTHROPIC_API_KEY:
        print("\n❌ ANTHROPIC_API_KEY is required for DJ name discovery mode.")
        print("   Set it in your .env file or environment variables.")
        print("   Get an API key at: https://console.anthropic.com/")
        sys.exit(1)

    try:
        import anthropic
    except ImportError:
        print("\n❌ anthropic package not installed.")
        print("   Run: pip install anthropic")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

    print(f"  Searching the web for DJ sets by '{artist_name}'...")
    print(f"  Using model: {Config.DISCOVERY_MODEL}")
    print(f"  This may take a minute as Claude searches multiple platforms...\n")

    user_prompt = (
        f"Find every publicly available recorded DJ set by {artist_name}. "
        f"Search YouTube and SoundCloud thoroughly using many different search queries. "
        f"Return ONLY the JSON array of results, no other text."
    )

    response = client.messages.create(
        model=Config.DISCOVERY_MODEL,
        max_tokens=16000,
        system=DISCOVERY_SYSTEM_PROMPT,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 20}],
        messages=[{"role": "user", "content": user_prompt}],
    )

    # Extract the final text response (after all tool use)
    sets = _parse_discovery_response(response)

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


def _parse_discovery_response(response) -> list[dict]:
    """Extract the structured set list from Claude's response.

    Handles the response which may contain text blocks and tool_use blocks.
    The final text block should contain the JSON array.
    """
    # Collect all text content from the response
    text_content = ""
    for block in response.content:
        if hasattr(block, "text"):
            text_content = block.text  # Take the last text block

    if not text_content:
        return []

    # Try to parse JSON from the text
    # Handle case where JSON is wrapped in markdown code blocks
    text_content = text_content.strip()
    if text_content.startswith("```json"):
        text_content = text_content[7:]
    elif text_content.startswith("```"):
        text_content = text_content[3:]
    if text_content.endswith("```"):
        text_content = text_content[:-3]
    text_content = text_content.strip()

    try:
        sets = json.loads(text_content)
        if isinstance(sets, list):
            # Validate each entry has at minimum a url field
            validated = []
            for s in sets:
                if isinstance(s, dict) and "url" in s:
                    validated.append({
                        "url": s["url"],
                        "title": s.get("title", "Unknown Set"),
                        "platform": s.get("platform", _detect_platform(s["url"])),
                        "event": s.get("event"),
                        "year": s.get("year"),
                        "duration_minutes": s.get("duration_minutes"),
                    })
            return validated
    except json.JSONDecodeError:
        # Try to find JSON array in the text
        start = text_content.find("[")
        end = text_content.rfind("]")
        if start != -1 and end != -1:
            try:
                sets = json.loads(text_content[start:end + 1])
                if isinstance(sets, list):
                    return [
                        {
                            "url": s["url"],
                            "title": s.get("title", "Unknown Set"),
                            "platform": s.get("platform", _detect_platform(s["url"])),
                            "event": s.get("event"),
                            "year": s.get("year"),
                            "duration_minutes": s.get("duration_minutes"),
                        }
                        for s in sets
                        if isinstance(s, dict) and "url" in s
                    ]
            except json.JSONDecodeError:
                pass

    print("  ⚠ Could not parse discovery results from Claude's response.")
    return []


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
