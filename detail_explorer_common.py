"""Shared helpers and master-language styling for detail explorer pages."""

from __future__ import annotations

import json
import re
from html import escape
from urllib.parse import quote, urlparse, parse_qs


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

SUMMARY_FILES = {"artist_summary.json", "artist_summary.md", "artist_summary.html"}
"""Filenames that represent artist-level summaries (not per-set outputs)."""

EXCLUDED_GENRES = {"House"}
"""Genre names filtered out of top-genre displays (too broad to be useful)."""

CONFIDENCE_LEVELS = ("HIGH", "MEDIUM", "LOW", "UNCERTAIN")
"""Ordered confidence tiers for track recognition."""

CONFIDENCE_CSS_CLASSES = {
    "HIGH": "conf-high",
    "MEDIUM": "conf-medium",
    "LOW": "conf-low",
    "UNCERTAIN": "conf-uncertain",
}

CONFIDENCE_COLORS = {
    "HIGH": "#00e676",
    "MEDIUM": "#ffd740",
    "LOW": "#ff9100",
    "UNCERTAIN": "#757575",
}

ARTIST_PROFILE_FIELDS = (
    "artist_profile_name",
    "artist_profile_image",
    "artist_profile_url",
    "artist_profile_source",
    "artist_profile_confidence",
    "artist_profile_genre_overlap",
    "artist_profile_expected_genres",
    "artist_profile_provider_genres",
    "artist_profile_rejected_reason",
    "spotify_artist_profile_name",
    "spotify_artist_profile_image",
    "spotify_artist_profile_url",
    "spotify_artist_profile_genres",
    "discogs_artist_profile_name",
    "discogs_artist_profile_image",
    "discogs_artist_profile_url",
    "discogs_artist_profile_genres",
)
"""Fields copied from artist profile enrichment into per-set mix_info."""


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------


def normalize_confidence(value: str | None) -> str:
    """Normalize a raw confidence string to one of CONFIDENCE_LEVELS."""
    conf = str(value or "UNCERTAIN").upper()
    return conf if conf in CONFIDENCE_LEVELS else "UNCERTAIN"


def blank_confidence_counts() -> dict[str, int]:
    """Return a zeroed confidence-count dict keyed by CONFIDENCE_LEVELS."""
    return {level: 0 for level in CONFIDENCE_LEVELS}


def merge_confidence_counts(base: dict[str, int], extra: dict[str, int]) -> dict[str, int]:
    """Add extra confidence counts into base and return a new dict."""
    merged = {level: int(base.get(level, 0)) for level in CONFIDENCE_LEVELS}
    for level in CONFIDENCE_LEVELS:
        merged[level] += int(extra.get(level, 0))
    return merged


def primary_confidence(conf_counts: dict[str, int]) -> str:
    """Return the highest-count confidence level from a counts dict."""
    best = "UNCERTAIN"
    best_count = -1
    for level in CONFIDENCE_LEVELS:
        count = int(conf_counts.get(level, 0))
        if count > best_count:
            best = level
            best_count = count
    return best


def normalize_name(value: str) -> str:
    """Lowercase alphanumeric normalization for loose artist-name matching."""
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def is_valid_artist_image_url(url: str | None) -> bool:
    """Return True when image URL appears usable for artist-card artwork."""
    if not url:
        return False
    lower = str(url).strip().lower()
    if not lower.startswith("http"):
        return False
    if "spacer.gif" in lower:
        return False
    return True


def extract_youtube_id(url: str) -> str | None:
    """Extract YouTube video ID from a URL."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower().removeprefix("www.").removeprefix("m.")
        if host == "youtube.com":
            return parse_qs(parsed.query).get("v", [None])[0]
        if host == "youtu.be":
            return parsed.path.lstrip("/")
    except Exception:
        pass
    return None


def select_artist_hero_image(
    set_summaries: list[dict],
    track_info: dict[str, dict],
    artist_name: str,
) -> tuple[str, str | None, str | None, str | None]:
    """Pick the best artist image using a 3-tier priority cascade.

    Returns (image_url, source_label, profile_name, profile_url).
    All strings default to "" or None when unavailable.

    Priority:
    1. Set-level artist profile image (ranked: spotify > discogs)
    2. Spotify track-artist profile image matching the artist name
    3. First available set thumbnail
    """
    _SOURCE_RANK = {"spotify": 2, "discogs": 1}
    image = ""
    source_label: str | None = None
    profile_name: str | None = None
    profile_url: str | None = None

    # Tier 1: set-level artist profile images
    candidates = []
    for s in set_summaries:
        img = s.get("artist_profile_image")
        if not is_valid_artist_image_url(img):
            continue
        src = (s.get("artist_profile_source") or "").strip().lower()
        candidates.append((_SOURCE_RANK.get(src, 0), src, img,
                           s.get("artist_profile_name"), s.get("artist_profile_url")))
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        _, source_label, image, profile_name, profile_url = candidates[0]
        source_label = source_label or "set_artist_profile"

    # Tier 2: Spotify track-artist profile image (exact name match)
    normalized = normalize_name(artist_name)
    if not image and normalized:
        for info in track_info.values():
            pname = info.get("spotify_artist_name")
            img = info.get("spotify_artist_profile_image")
            if (
                is_valid_artist_image_url(img)
                and pname
                and normalize_name(pname) == normalized
            ):
                image = img
                profile_name = pname
                profile_url = info.get("spotify_artist_url")
                source_label = "spotify_artist_profile"
                break

    # Tier 3: first set thumbnail
    if not image:
        for s in set_summaries:
            thumb = s.get("thumbnail_url") or ""
            if thumb:
                image = thumb
                source_label = "thumbnail"
                break

    return image, source_label, profile_name, profile_url


def esc(value) -> str:
    """HTML-escape text."""
    return escape("" if value is None else str(value), quote=True)


def to_json(value) -> str:
    """Safe JSON serialization for inline script embedding."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def normalize_track_key(artist: str, title: str) -> str:
    """Stable lower-cased key for cross-set comparisons."""
    a = re.sub(r"\s+", " ", (artist or "").strip().lower())
    t = re.sub(r"\s+", " ", (title or "").strip().lower())
    return f"{a} - {t}".strip(" -")


def spotify_track_id(url: str | None) -> str | None:
    """Extract Spotify track id from an open.spotify URL."""
    if not url:
        return None
    parts = url.split("/")
    if "track" not in parts:
        return None
    idx = parts.index("track")
    if idx + 1 >= len(parts):
        return None
    track_id = parts[idx + 1].split("?")[0].strip()
    return track_id or None


def spotify_search_url(artist: str, title: str) -> str:
    query = quote(f"{artist} {title}".strip())
    return f"https://open.spotify.com/search/{query}"


def youtube_search_url(artist: str, title: str) -> str:
    query = quote(f"{artist} {title}".strip())
    return f"https://www.youtube.com/results?search_query={query}"


def discogs_search_url(artist: str, title: str) -> str:
    query = quote(f"{artist} {title}".strip())
    return f"https://www.discogs.com/search/?q={query}&type=all"


MASTER_DETAIL_BASE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Space+Mono:wght@400;700&display=swap');

:root {
  --bg: #0a0a0a;
  --paper: #111111;
  --paper-2: #161616;
  --ink: #f3f3f3;
  --muted: #ababab;
  --lime: #d8ff5a;
  --violet: #7f51ff;
  --line: #2c2c2c;
  --line-soft: #242424;
  --radius: 4px;
  --gutter: clamp(16px, 2vw, 28px);
  --section-pad: clamp(24px, 4.8vw, 72px);
  --section-pad-y: clamp(16px, 3.2vw, 44px);
}

* { box-sizing: border-box; }
html, body {
  margin: 0;
  padding: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: 'Manrope', sans-serif;
}
a { color: inherit; text-decoration: none; }

.topbar {
  position: sticky;
  top: 0;
  z-index: 40;
  background: rgba(10, 10, 10, 0.96);
  border-bottom: 1px solid var(--line-soft);
  backdrop-filter: blur(8px);
}

.topbar-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px var(--section-pad);
  margin: 0 auto;
  max-width: 1480px;
}

.brand {
  font-family: 'Space Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #d8d8d8;
  white-space: nowrap;
}

.topnav {
  display: flex;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
  font-family: 'Space Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.topnav a {
  color: #cfcfcf;
  border-bottom: 1px solid transparent;
  padding-bottom: 2px;
  transition: color 0.2s ease, border-color 0.2s ease;
}

.topnav a:hover {
  color: #fff;
  border-color: var(--lime);
}

.chip-btn {
  border: 1px solid var(--line);
  background: var(--paper);
  color: var(--muted);
  border-radius: var(--radius);
  padding: 7px 10px;
  font-size: 11px;
  font-family: 'Space Mono', monospace;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  cursor: pointer;
}

.chip-btn:hover {
  border-color: #fff;
  color: #fff;
}

.chip-btn.lime {
  border-color: var(--lime);
  color: var(--lime);
}

.shell {
  max-width: 1480px;
  margin: 0 auto;
  padding: 0 var(--gutter) 72px;
}

.section {
  border: 1px solid var(--line);
  background: var(--paper);
  margin-top: var(--gutter);
}

.section-inner {
  padding: var(--section-pad-y) var(--section-pad);
}

.section-head {
  display: grid;
  grid-template-columns: 1.5fr 1fr;
  gap: 20px;
  align-items: end;
  margin-bottom: 18px;
}

.section-head h2 {
  margin: 0;
  font-size: clamp(38px, 7.6vw, 82px);
  line-height: 0.88;
  letter-spacing: -0.04em;
  text-transform: uppercase;
  color: #fff;
}

.section-head p {
  margin: 0;
  justify-self: end;
  max-width: 460px;
  font-size: 13px;
  line-height: 1.6;
  color: #c0c0c0;
}

.kicker {
  display: inline-flex;
  border: 1px solid var(--line);
  padding: 5px 10px;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.09em;
  text-transform: uppercase;
  margin-bottom: 10px;
  color: #d8d8d8;
}

.title {
  margin: 10px 0 0;
  line-height: 0.92;
  font-size: clamp(28px, 5.8vw, 72px);
  text-transform: uppercase;
  letter-spacing: 0.01em;
}

.subtitle {
  margin-top: 10px;
  color: var(--muted);
  max-width: 82ch;
}

.stats-grid {
  margin-top: 18px;
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.stat {
  border: 1px solid var(--line);
  background: #0f0f0f;
  padding: 10px 12px;
}

.stats-grid > .stat:first-child {
  background: var(--lime);
  color: #090909;
  border-color: #bddd45;
}

.stats-grid > .stat:first-child .stat-value,
.stats-grid > .stat:first-child .stat-label {
  color: inherit;
}

.stats-grid > .stat:first-child .stat-label {
  opacity: 0.85;
}

.stat-value {
  display: block;
  color: var(--lime);
  font-size: 22px;
  font-weight: 800;
  line-height: 1;
}

.stat-label {
  display: block;
  margin-top: 6px;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
}

.cluster-row {
  margin-top: 14px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.cluster-pill {
  border: 1px solid var(--line);
  background: var(--paper-2);
  border-radius: 999px;
  padding: 5px 10px;
  font-family: 'Space Mono', monospace;
  font-size: 11px;
  color: var(--muted);
}

.cluster-pill.lime {
  border-color: var(--lime);
  color: var(--lime);
}

.split {
  display: grid;
  gap: 14px;
  grid-template-columns: minmax(340px, 0.9fr) minmax(440px, 1.1fr);
}

.panel {
  border: 1px solid var(--line);
  background: #101010;
  padding: 14px;
}

.panel-title {
  margin: 0;
  font-size: 18px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.panel-sub {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--muted);
}

.controls {
  margin-top: 12px;
  display: grid;
  gap: 8px;
}

.controls-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}

.input,
.select {
  width: 100%;
  border: 1px solid var(--line);
  background: #171717;
  color: var(--ink);
  border-radius: var(--radius);
  padding: 9px 10px;
  font-size: 13px;
  font-family: 'Space Mono', monospace;
}

.input::placeholder { color: #717171; }
.input:focus,
.select:focus {
  outline: none;
  border-color: var(--lime);
}

.btn {
  border: 1px solid var(--line);
  background: var(--paper-2);
  color: var(--muted);
  border-radius: var(--radius);
  padding: 7px 10px;
  font-size: 11px;
  font-family: 'Space Mono', monospace;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  cursor: pointer;
}

.btn:hover { border-color: #fff; color: #fff; }
.btn.active { border-color: var(--lime); color: var(--lime); background: #0f1210; }
.btn.warn { border-color: #ff6d6d; color: #ff6d6d; }
.btn.good { border-color: #1db954; color: #1db954; }
.btn.violet { border-color: var(--violet); color: var(--violet); }

.empty {
  margin-top: 12px;
  border: 1px dashed var(--line);
  color: var(--muted);
  padding: 12px;
  font-size: 13px;
}

.footer-note {
  margin-top: 20px;
  font-size: 11px;
  color: #8f8f8f;
  font-family: 'Space Mono', monospace;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

@media (max-width: 1120px) {
  .section-head { grid-template-columns: 1fr; }
  .section-head p { justify-self: start; max-width: 100%; }
  .stats-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .split { grid-template-columns: 1fr; }
}

@media (max-width: 720px) {
  .topbar-inner { padding-left: 14px; padding-right: 14px; }
  .topnav { gap: 10px; font-size: 10px; }
  .chip-btn { padding: 6px 8px; font-size: 10px; }
  .section-inner { padding: 14px; }
  .stats-grid { grid-template-columns: 1fr; }
  .title { font-size: clamp(24px, 11vw, 42px); }
  .section-head h2 { font-size: clamp(34px, 15vw, 58px); }
}
"""
