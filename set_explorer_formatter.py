"""Independent set-level explorer renderer."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from detail_explorer_common import (
    MASTER_DETAIL_BASE_CSS,
    discogs_search_url,
    esc,
    spotify_search_url,
    spotify_track_id,
    to_json,
    youtube_search_url,
)
from output_formatter import format_time, serialize_track


def _detect_platform(source_url: str) -> tuple[str, str]:
    """Detect source platform and return `(platform, embed_id_or_url)`."""
    if not source_url:
        return ("unknown", "")
    try:
        parsed = urlparse(source_url)
    except Exception:
        return ("unknown", "")
    host = parsed.netloc.lower()
    if "youtube.com" in host:
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        return ("youtube", video_id or "")
    if "youtu.be" in host:
        return ("youtube", parsed.path.lstrip("/"))
    if "soundcloud.com" in host:
        return ("soundcloud", source_url.split("#")[0])
    return ("unknown", "")


def _first_nonempty(*values: str) -> str:
    """Return first non-empty string from values."""
    for value in values:
        s = str(value or "").strip()
        if s:
            return s
    return ""


def _set_cover_fallback_from_other_sets(
    output_dir: Path,
    exclude_images: set[str] | None = None,
) -> str:
    """
    Pick a fallback set cover from existing generated data.

    Search order:
    1) same-artist `artist_summary.json`
    2) global `output/explorer_data.json`
    """
    exclude = {str(x).strip() for x in (exclude_images or set()) if str(x or "").strip()}

    def _from_artist_summary() -> str:
        parent = output_dir.parent
        summary_path = parent / "artist_summary.json"
        if not summary_path.exists():
            return ""
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        for item in payload.get("sets", []):
            thumb = str(item.get("thumbnail_url") or "").strip()
            if thumb and thumb not in exclude:
                return thumb
        return ""

    def _find_output_root(start: Path) -> Path | None:
        cur = start.resolve()
        for candidate in (cur, *cur.parents):
            if candidate.name == "output":
                return candidate
        return None

    def _from_explorer_data() -> str:
        start = output_dir
        out_root = _find_output_root(start)
        if not out_root:
            return ""
        data_path = out_root / "explorer_data.json"
        if not data_path.exists():
            return ""
        try:
            payload = json.loads(data_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""

        for item in payload.get("all_sets", []):
            thumb = str(item.get("thumbnail_url") or "").strip()
            if thumb and thumb not in exclude:
                return thumb
        for artist in payload.get("artists", []):
            for item in artist.get("sets", []):
                thumb = str(item.get("thumbnail_url") or "").strip()
                if thumb and thumb not in exclude:
                    return thumb
        return ""

    return _first_nonempty(_from_artist_summary(), _from_explorer_data())


def _set_css() -> str:
    return (
        MASTER_DETAIL_BASE_CSS
        + """
.detail-shell { padding-top: 12px; }

.topbar-right {
  margin-left: auto;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 14px;
}

.set-hero {
  margin-top: 10px;
  border: 1px solid var(--line);
  background: #101010;
  padding: 10px;
}

.set-hero-grid {
  display: grid;
  grid-template-columns: 1.6fr 1fr;
  gap: 12px;
  align-items: stretch;
}

.set-hero-main {
  position: relative;
  border: 1px solid var(--line);
  background: #0d0d0d;
  height: clamp(340px, 40vw, 560px);
  overflow: hidden;
}

.set-hero-main::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.72) 0%, rgba(0, 0, 0, 0.2) 50%, rgba(0, 0, 0, 0.04) 100%);
  pointer-events: none;
  z-index: 1;
}

.set-hero-main img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center 24%;
  display: block;
  filter: grayscale(18%);
}

.set-hero-main-empty {
  width: 100%;
  height: 100%;
  display: grid;
  place-items: center;
  color: #888;
  font-family: 'Space Mono', monospace;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
}

.set-hero-title-overlay {
  position: absolute;
  left: clamp(12px, 2.6vw, 30px);
  bottom: clamp(12px, 2.2vw, 24px);
  margin: 0;
  max-width: min(94%, 1120px);
  font-size: clamp(42px, 9vw, 132px);
  line-height: 0.9;
  text-transform: uppercase;
  letter-spacing: -0.025em;
  word-break: break-word;
  text-wrap: balance;
  color: #fff;
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.52);
  font-weight: 800;
  opacity: 1;
  z-index: 3;
  pointer-events: none;
}

.set-hero-title-overlay.long {
  font-size: clamp(32px, 6.6vw, 96px);
  line-height: 0.92;
}

.set-hero-title-overlay.xlong {
  font-size: clamp(22px, 4.9vw, 64px);
  line-height: 0.96;
  letter-spacing: -0.015em;
}

.set-hero-caption {
  position: absolute;
  left: 12px;
  right: 12px;
  bottom: 12px;
  border: 1px solid #2f2f2f;
  background: rgba(0, 0, 0, 0.76);
  color: #f3f3f3;
  padding: 7px 8px;
  display: grid;
  gap: 3px;
  backdrop-filter: blur(1.6px);
  z-index: 3;
}

.set-hero-caption-kicker {
  margin: 0;
  font-family: 'Space Mono', monospace;
  font-size: 9px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #d8ff5a;
}

.set-hero-caption-sub {
  margin: 0;
  font-size: 12px;
  color: #efefef;
}

.set-hero-side {
  position: relative;
  border: 1px solid var(--line);
  background: #0f0f0f;
  height: clamp(360px, 38vw, 560px);
  overflow: hidden;
}

.set-hero-side::before,
.set-hero-side::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  height: 42px;
  pointer-events: none;
  z-index: 4;
}

.set-hero-side::before {
  top: 0;
  background: linear-gradient(to bottom, rgba(12, 12, 12, 0.88), rgba(12, 12, 12, 0));
}

.set-hero-side::after {
  bottom: 0;
  background: linear-gradient(to top, rgba(12, 12, 12, 0.9), rgba(12, 12, 12, 0));
}

.set-hero-side-viewport {
  height: 100%;
  overflow: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
  position: relative;
  z-index: 2;
}

.set-hero-side-viewport::-webkit-scrollbar {
  display: none;
}

.set-hero-side-track {
  display: grid;
  gap: 10px;
  padding: 10px;
}

.set-hero-card {
  border: 1px solid var(--line);
  background: #0f0f0f;
  width: 100%;
  min-height: 0;
  height: clamp(192px, 21vw, 244px);
  display: block;
  text-align: left;
  position: relative;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.25s ease, border-color 0.25s ease, box-shadow 0.25s ease;
}

.set-hero-card:hover {
  border-color: #f0f0f0;
  transform: translateY(-2px);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.38);
}

.set-hero-card.active {
  border-color: var(--lime);
  box-shadow: 0 0 0 1px rgba(216, 255, 90, 0.26), 0 10px 24px rgba(0, 0, 0, 0.36);
}

.set-hero-card-media {
  width: 100%;
  height: 100%;
  min-height: 0;
  border: 0;
  background: #0a0a0a;
  overflow: hidden;
  display: grid;
  place-items: center;
}

.set-hero-card-media img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  filter: grayscale(16%);
  display: block;
  transition: transform 0.35s ease, filter 0.35s ease;
}

.set-hero-card:hover .set-hero-card-media img {
  transform: scale(1.035);
  filter: grayscale(4%);
}

.set-hero-card-media-empty {
  font-size: 14px;
  color: #686868;
}

.set-hero-card-meta {
  position: absolute;
  left: 8px;
  right: 8px;
  bottom: 8px;
  border: 1px solid #2f2f2f;
  background: rgba(0, 0, 0, 0.74);
  color: #f3f3f3;
  padding: 5px 7px;
  display: grid;
  gap: 2px;
  min-width: 0;
  backdrop-filter: blur(1.4px);
  opacity: 1;
  transform: translateY(0);
  transition: none;
  pointer-events: none;
}

.set-hero-card-artist {
  margin: 0;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #d8ff5a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.set-hero-card-title {
  margin: 0;
  font-size: 11px;
  line-height: 1.25;
  color: #f5f5f5;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
}

.set-hero-side-empty {
  height: 100%;
  display: grid;
  place-items: center;
  color: #afafaf;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.timeline-wrap {
  margin-top: 4px;
  border: 1px solid var(--line);
  background: #0f0f0f;
  padding: 8px;
}

.source-player-panel {
  margin-top: 8px;
}

.source-player-frame {
  margin-top: 6px;
  border: 1px solid var(--line);
  background: #090909;
  min-height: 130px;
  overflow: hidden;
}

.source-player-frame iframe {
  width: 100%;
  height: 100%;
  border: 0;
  display: block;
}

.source-player-frame.is-youtube {
  aspect-ratio: 16 / 9;
  max-height: 58vh;
}

.source-player-frame.is-youtube iframe {
  height: 100%;
}

.source-player-frame.is-youtube-error,
.source-player-frame.is-embed-error {
  aspect-ratio: auto;
  min-height: 74px;
  max-height: none;
  display: flex;
  align-items: center;
  padding: 10px 12px;
}

.source-player-frame.is-soundcloud {
  height: 166px;
  aspect-ratio: auto;
}

.source-player-frame.is-fallback {
  min-height: 120px;
}

.source-player-error-note {
  width: 100%;
  color: #b8b8b8;
  font-size: 12px;
  line-height: 1.35;
  text-align: center;
}

.source-player-open {
  margin-top: 6px;
  display: inline-flex;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: #d8ff5a;
  text-decoration: none;
}

.source-player-open:hover {
  text-decoration: underline;
}

.source-player-fallback {
  height: 100%;
  display: grid;
  place-items: center;
  padding: 12px;
  color: var(--muted);
  font-size: 12px;
  text-align: center;
  line-height: 1.4;
}

.source-player-fallback a {
  color: #d8ff5a;
}

.timeline-journey-panel {
  margin-top: 6px;
}

.timeline-bar {
  position: relative;
  height: 20px;
  border: 1px solid var(--line);
  background: #0b0b0b;
  overflow: hidden;
}

.timeline-segment {
  position: absolute;
  top: 0;
  height: 100%;
  border: 0;
  border-right: 1px solid rgba(10, 10, 10, 0.85);
  opacity: 0.92;
  cursor: pointer;
  transition: opacity 0.12s ease, filter 0.12s ease;
}

.timeline-segment:hover { filter: brightness(1.15); }
.timeline-segment.dim { opacity: 0.18; }
.timeline-segment.active { outline: 2px solid #fff; z-index: 2; opacity: 1; }
.timeline-segment.hover { outline: 2px solid #9a9a9a; z-index: 1; opacity: 1; }

.timeline-segment.conf-high { background: #6fffa4; }
.timeline-segment.conf-medium { background: #ffd166; }
.timeline-segment.conf-low { background: #ffa55a; }
.timeline-segment.conf-uncertain { background: #7b7b7b; }

.timeline-ticks {
  margin-top: 3px;
  display: flex;
  justify-content: space-between;
  gap: 4px;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.05em;
  color: var(--muted);
}

#tl-tooltip,
#journey-tooltip {
  position: fixed;
  z-index: 40;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.12s ease;
  min-width: 200px;
  max-width: 340px;
  border: 1px solid var(--line);
  background: rgba(10, 10, 10, 0.98);
  padding: 10px;
  font-size: 12px;
  color: #ddd;
  line-height: 1.45;
}

#tl-tooltip.visible,
#journey-tooltip.visible { opacity: 1; }

#tl-tooltip .tt-title,
#journey-tooltip .jt-title {
  color: #fff;
  font-weight: 700;
  margin-bottom: 2px;
}

#tl-tooltip .tt-sub,
#journey-tooltip .jt-value {
  color: var(--muted);
  font-size: 11px;
}

#tl-tooltip .tt-badge {
  margin-top: 6px;
  display: inline-flex;
  border: 1px solid var(--line);
  border-radius: 999px;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.03em;
  padding: 2px 8px;
}

.journey-panel {
  border: 1px solid var(--line);
  background: #0f0f0f;
  padding: 14px;
}

.journey-inline {
  margin-top: 8px;
  border: 1px solid var(--line);
  background: #0f0f0f;
  padding: 8px;
}

.journey-toggle-btn {
  padding: 4px 8px;
  font-size: 10px;
  font-family: 'Space Mono', monospace;
  letter-spacing: 0.05em;
}

.journey-toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.journey-toolbar-note {
  font-size: 10px;
  color: var(--muted);
  font-family: 'Space Mono', monospace;
}

.journey-body {
  margin-top: 8px;
}

.journey-body[hidden] { display: none; }

.journey-controls {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.journey-chart-wrap {
  margin-top: 8px;
  border: 1px solid var(--line);
  background: #0a0a0a;
  min-height: 240px;
  position: relative;
}

.journey-empty {
  padding: 22px;
  color: var(--muted);
  font-size: 13px;
}

#journeySvg {
  width: 100%;
  height: 260px;
  display: block;
}

.journey-legend {
  margin-top: 8px;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 11px;
  font-family: 'Space Mono', monospace;
  color: var(--muted);
}

.journey-key {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.journey-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  display: inline-block;
}

.journey-point {
  stroke: #1a1a1a;
  stroke-width: 1.5;
  cursor: pointer;
}

.journey-point.active {
  stroke: #fff;
  stroke-width: 2.4;
}

.signals-grid {
  display: grid;
  gap: 6px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.signal-card {
  border: 1px solid var(--line);
  background: #0f0f0f;
  padding: 8px;
}

.signal-value {
  display: block;
  color: var(--lime);
  font-size: 18px;
  font-weight: 800;
  line-height: 1;
}

.signal-label {
  display: block;
  margin-top: 4px;
  color: var(--muted);
  font-size: 11px;
  font-family: 'Space Mono', monospace;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.track-explorer-panel {
  margin-top: 0;
}

.track-head {
  margin-top: 0;
  display: grid;
  gap: 8px;
}

.timeline-track-atlas {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--line);
}

.timeline-track-atlas > .panel-title {
  font-size: 14px;
  letter-spacing: 0.03em;
}

.timeline-track-atlas > .panel-sub {
  margin-top: 1px;
  font-size: 11px;
}

.tracklist {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.track-card {
  border: 1px solid var(--line);
  background: #111;
  padding: 8px 10px;
  position: relative;
  cursor: pointer;
  transition: border-color 0.18s ease, background 0.18s ease;
}

.track-card:hover {
  border-color: #f0f0f0;
  background: #151515;
}

.track-card.active {
  border-color: var(--lime);
  background: #0f1210;
}

.track-card.hash-hit {
  outline: 2px solid var(--lime);
  outline-offset: 2px;
}

.track-grid {
  display: grid;
  grid-template-columns: 28px 58px max-content minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.track-index {
  font-family: 'Space Mono', monospace;
  font-size: 12px;
  color: var(--muted);
  padding-top: 2px;
}

.track-time-col {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.track-art {
  width: 58px;
  height: 58px;
  border: 1px solid var(--line);
  background: #0d0d0d;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.track-art img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.track-art--empty {
  font-size: 16px;
  color: #6e6e6e;
}

.track-time-link {
  color: var(--lime);
  font-family: 'Space Mono', monospace;
  font-size: 11px;
  text-decoration: underline;
  text-decoration-color: #2a2a2a;
}

.track-main {
  min-width: 0;
}

.track-title-row {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  align-items: baseline;
  font-size: 13px;
  line-height: 1.2;
}

.track-artist {
  font-weight: 700;
}

.track-sep { color: #686868; }
.track-title { color: #d8d8d8; }

.track-meta {
  margin-top: 3px;
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.pill {
  border: 1px solid var(--line);
  background: #151515;
  color: var(--muted);
  border-radius: 999px;
  padding: 1px 6px;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.03em;
}

.pill.conf-high { border-color: #6fffa4; color: #6fffa4; }
.pill.conf-medium { border-color: #ffd166; color: #ffd166; }
.pill.conf-low { border-color: #ffa55a; color: #ffa55a; }
.pill.conf-uncertain { border-color: #8c8c8c; color: #8c8c8c; }

.pill-link {
  color: #ff855d;
  border-color: #ff855d;
}

.btn {
  border: 1px solid var(--line);
  background: #171717;
  color: #f0f0f0;
  border-radius: 0;
  padding: 2px 6px;
  font-size: 9px;
  font-family: 'Space Mono', monospace;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  min-height: 20px;
  line-height: normal;
}

.btn {
  cursor: pointer;
}

.btn:hover {
  border-color: #fff;
  color: #fff;
}

.btn.active {
  border-color: var(--lime);
  color: var(--lime);
  background: #0f1210;
}

.action-link {
  border: 1px dashed #2d2d2d;
  background: transparent;
  color: #bdbdbd;
  border-radius: 0;
  padding: 2px 6px;
  font-size: 9px;
  font-family: 'Space Mono', monospace;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  min-height: 20px;
  line-height: normal;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
}

.action-link:hover {
  border-color: #fff;
  color: #fff;
}

body.yt-embed-blocked .js-track-play,
body.yt-embed-blocked .js-track-play.active,
body.yt-embed-blocked .js-track-play.source-jump {
  border-color: #ff4d4d;
  color: #ff4d4d;
  background: rgba(72, 10, 10, 0.45);
}

body.yt-embed-blocked .js-track-play:hover {
  border-color: #ff8f8f;
  color: #ff8f8f;
}

.track-actions {
  display: flex;
  gap: 3px;
  flex-wrap: nowrap;
  justify-content: flex-end;
  overflow-x: auto;
  scrollbar-width: thin;
}

.track-external-links {
  display: inline-flex;
  gap: 3px;
  flex-wrap: nowrap;
}

.track-external-links.in-details {
  display: flex;
  flex-wrap: wrap;
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--line);
}

.track-tool-btn {
  border-style: solid;
  border-color: #4a4a4a;
  background: #1b1b1b;
  color: #efefef;
}

.track-tool-btn:hover {
  border-color: #fff;
}

.track-tool-btn.embed-btn {
  border-color: #1db954;
  color: #1db954;
  background: rgba(12, 48, 24, 0.45);
}

.action-link.spotify { border-color: #1db954; color: #1db954; }
.action-link.youtube { border-color: #ff5757; color: #ff5757; }
.action-link.discogs { border-color: #ff855d; color: #ff855d; }
.action-link.fallback { border-style: dashed; opacity: 0.85; }

.track-details,
.spotify-inline {
  margin-top: 6px;
  border: 1px solid var(--line);
  background: #0f0f0f;
  padding: 8px;
}

.track-details[hidden],
.spotify-inline[hidden] { display: none; }

.details-grid {
  display: grid;
  gap: 6px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.detail-item {
  border: 1px solid var(--line);
  background: #111;
  padding: 6px;
}

.detail-density-bar {
  margin-top: 6px;
  border: 1px solid var(--line);
  background: #141414;
  height: 8px;
  position: relative;
}

.detail-density-fill {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 0;
  background: var(--lime);
}

.detail-k {
  display: block;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.07em;
}

.detail-v {
  display: block;
  margin-top: 3px;
  color: #d8d8d8;
  font-size: 13px;
}

.no-results {
  margin-top: 12px;
  border: 1px dashed var(--line);
  color: var(--muted);
  padding: 12px;
  display: none;
}

.dock {
  position: fixed;
  left: 50%;
  bottom: 14px;
  transform: translateX(-50%);
  z-index: 20;
  width: min(1080px, calc(100vw - 18px));
  border: 1px solid var(--line);
  background: rgba(14, 14, 14, 0.97);
  border-radius: 10px;
  padding: 10px 12px;
  --dock-now-width: clamp(290px, 30vw, 340px);
}

.dock-grid {
  display: grid;
  gap: 8px;
  grid-template-columns: var(--dock-now-width) minmax(0, 1fr) auto;
  align-items: center;
}

.dock-now {
  display: grid;
  grid-template-columns: 68px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  width: var(--dock-now-width);
  min-width: 0;
}

.dock-now > div:last-child {
  min-width: 0;
}

.dock-art-frame {
  width: 64px;
  height: 64px;
  border: 1px solid var(--line);
  background: #101010;
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

.dock-art {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: none;
}

.dock-art.visible { display: block; }

.dock-art-fallback {
  font-size: 18px;
  color: #606060;
}

.dock-art-fallback.hidden {
  display: none;
}

.dock-track {
  font-size: 13px;
  color: #f2f2f2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-weight: 700;
}

.dock-artist {
  margin-top: 2px;
  font-size: 12px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dock-center {
  min-width: 0;
  width: 100%;
}

.dock-main-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  justify-content: flex-start;
}

.dock-primary-controls {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  flex: 0 0 auto;
}

.dock-mini-btn {
  border: 1px solid var(--line);
  background: #151515;
  color: #bbb;
  border-radius: 999px;
  min-width: 34px;
  height: 26px;
  padding: 0 8px;
  font-size: 10px;
  font-family: 'Space Mono', monospace;
  letter-spacing: 0.04em;
  cursor: pointer;
}

.dock-mini-btn:hover {
  border-color: #666;
  color: #f0f0f0;
}

.dock-nav-btn {
  border: 0;
  background: transparent;
  color: #d0d0d0;
  width: 26px;
  height: 26px;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
}

.dock-nav-btn:hover {
  color: #fff;
}

.dock-play-btn {
  width: 38px;
  height: 38px;
  border: 0;
  border-radius: 999px;
  background: #1db954;
  color: #08120a;
  font-size: 18px;
  font-weight: 800;
  line-height: 1;
  cursor: pointer;
}

.dock-play-btn:hover {
  filter: brightness(1.08);
}

.dock-play-btn:active {
  transform: scale(0.96);
}

.dock-actions {
  display: inline-flex;
  justify-content: flex-end;
}

.dock-progress {
  border: 1px solid var(--line);
  background: #141414;
  height: 10px;
  position: relative;
  cursor: pointer;
}

.dock-progress-fill {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 0%;
  background: var(--lime);
}

.dock-time {
  margin-top: 6px;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  color: var(--muted);
  display: flex;
  justify-content: space-between;
}

.dock-range {
  flex: 1 1 auto;
  min-width: 0;
}

.dock-controls {
  display: none;
}

@media (max-width: 1180px) {
  .signals-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .topbar-right { gap: 10px; }
  .set-hero-grid { grid-template-columns: 1fr; }
  .set-hero-main {
    height: clamp(280px, 62vw, 430px);
  }
  .set-hero-side {
    height: clamp(250px, 54vw, 360px);
  }
}

@media (max-width: 860px) {
  .topbar-right {
    width: 100%;
    justify-content: space-between;
    margin-left: 0;
  }
  .set-hero-title-overlay {
    font-size: clamp(24px, 8.6vw, 56px);
    bottom: clamp(10px, 3.6vw, 18px);
  }
  .set-hero-title-overlay.long {
    font-size: clamp(22px, 7.4vw, 46px);
  }
  .set-hero-title-overlay.xlong {
    font-size: clamp(20px, 6.6vw, 40px);
  }
  .set-hero-card { height: 148px; }
  .set-hero-card-media { min-height: 0; }
  .source-player-frame { min-height: 150px; }
  .source-player-frame.is-youtube { max-height: none; }
  .source-player-frame.is-youtube-error,
  .source-player-frame.is-embed-error { min-height: 74px; }
  .source-player-frame.is-soundcloud { height: 166px; }
  .track-grid {
    grid-template-columns: 28px 40px minmax(0, 1fr);
    gap: 6px;
  }
  .track-time-col { grid-column: 3; }
  .track-actions {
    grid-column: 1 / -1;
    justify-content: flex-start;
    flex-wrap: wrap;
  }
  .track-art {
    width: 40px;
    height: 40px;
  }
  .details-grid {
    grid-template-columns: 1fr;
  }
  .dock-grid {
    grid-template-columns: 1fr;
  }
  .dock-main-row {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
  }
  .dock-now {
    grid-template-columns: 58px minmax(0, 1fr);
    width: 100%;
  }
  .dock-art-frame { width: 54px; height: 54px; }
  .dock-actions { justify-content: flex-start; }
  .dock-primary-controls {
    gap: 6px;
    justify-content: flex-start;
    flex-wrap: wrap;
  }
  .dock-play-btn { width: 34px; height: 34px; font-size: 16px; }
}
"""
    )


def save_set_explorer_html(
    output_dir: Path,
    enriched_tracks: list,
    mix_info: dict,
    filename: str | None = None,
) -> Path:
    """Render and save the set-level explorer page."""
    if not filename:
        filename = f"setlist_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_path = output_dir / f"{filename}.html"

    source_url = str(mix_info.get("url") or "")
    total_duration = float(mix_info.get("duration") or 0.0)
    if total_duration <= 0:
        total_duration = 1.0

    platform, embed_id = _detect_platform(source_url)
    rows: list[dict] = []
    for i, item in enumerate(enriched_tracks, 1):
        track = serialize_track(item, i, source_url)
        end_time = track["end_time"] if track["end_time"] is not None else total_duration
        genres = []
        for g in (track.get("discogs_styles") or []) + (track.get("discogs_genres") or []) + (track.get("spotify_genres") or []):
            gn = str(g or "").strip()
            if gn and gn not in genres:
                genres.append(gn)
        search_blob = f"{track.get('artist','')} {track.get('title','')} {' '.join(genres)}".lower()
        label = (track.get("discogs_label") or "").strip()
        track["track_key"] = f"{track.get('artist','Unknown')} - {track.get('title','Unknown Track')}"
        track["end_time"] = end_time
        track["end_time_formatted"] = format_time(end_time)
        track["start_pct"] = (track["start_time"] / total_duration * 100.0) if total_duration else 0.0
        track["width_pct"] = max(0.5, ((end_time - track["start_time"]) / total_duration * 100.0)) if total_duration else 0.0
        track["genres"] = genres
        track["label"] = label
        track["search_blob"] = search_blob
        track["spotify_track_id"] = spotify_track_id(track.get("spotify_url"))
        track["spotify_search_url"] = spotify_search_url(track.get("artist", ""), track.get("title", ""))
        track["youtube_search_url"] = youtube_search_url(track.get("artist", ""), track.get("title", ""))
        track["discogs_search_url"] = discogs_search_url(track.get("artist", ""), track.get("title", ""))
        rows.append(track)

    counts = Counter((r.get("confidence") or "UNCERTAIN") for r in rows)
    total_tracks = len(rows)
    identified_tracks = sum(1 for r in rows if (r.get("title") or "") != "Unknown Track")
    id_rate = round((identified_tracks / total_tracks) * 100.0, 1) if total_tracks else 0.0
    confidence_rate = round(((counts.get("HIGH", 0) + counts.get("MEDIUM", 0)) / total_tracks) * 100.0, 1) if total_tracks else 0.0

    track_cards_html: list[str] = []
    timeline_segments_html: list[str] = []
    journey_points = []
    conf_class_map = {
        "HIGH": "conf-high",
        "MEDIUM": "conf-medium",
        "LOW": "conf-low",
        "UNCERTAIN": "conf-uncertain",
    }
    conf_color_map = {
        "HIGH": "#6fffa4",
        "MEDIUM": "#ffd166",
        "LOW": "#ffa55a",
        "UNCERTAIN": "#7b7b7b",
    }

    for row in rows:
        conf = (row.get("confidence") or "UNCERTAIN").upper()
        conf_cls = conf_class_map.get(conf, "conf-uncertain")
        conf_color = conf_color_map.get(conf, "#7b7b7b")
        display_artist = row.get("artist") or "Unknown"
        display_title = row.get("title") or "Unknown Track"
        direct_spotify_url = row.get("spotify_url") or ""
        direct_youtube_url = row.get("youtube_url") or ""
        direct_discogs_url = row.get("discogs_url") or ""
        spotify_url = direct_spotify_url or row["spotify_search_url"]
        youtube_url = direct_youtube_url or row["youtube_search_url"]
        discogs_url = direct_discogs_url or row["discogs_search_url"]
        spotify_link_label = "Spotify" if direct_spotify_url else "Search Spotify"
        youtube_link_label = "YouTube" if direct_youtube_url else "Search YouTube"
        discogs_link_label = "Discogs" if direct_discogs_url else "Search Discogs"
        start_fmt = row.get("start_time_formatted") or format_time(row["start_time"])
        end_fmt = row.get("end_time_formatted") or format_time(row["end_time"])
        time_range = f"{start_fmt} - {end_fmt}"
        density_pct = float(row.get("cluster_density") or 0.0) * 100.0
        preview_url = row.get("spotify_preview_url") or ""
        album_art_url = row.get("spotify_album_art") or ""

        timeline_segments_html.append(
            f'<button class="timeline-segment {conf_cls}" data-track-idx="{row["position"]}" '
            f'data-start="{row["start_time"]:.3f}" data-end="{row["end_time"]:.3f}" '
            f'data-artist="{esc(display_artist)}" data-title="{esc(display_title)}" '
            f'data-time="{esc(time_range)}" data-conf="{esc(conf)}" data-color="{esc(conf_color)}" '
            f'style="left:{row["start_pct"]:.4f}%;width:{row["width_pct"]:.4f}%;" '
            f'title="{esc(display_artist)} — {esc(display_title)}"></button>'
        )

        bpm = row.get("bpm")
        energy = row.get("energy")
        dance = row.get("danceability")
        if any(val is not None for val in (bpm, energy, dance)):
            journey_points.append(
                {
                    "idx": row["position"],
                    "start": row["start_time"],
                    "artist": display_artist,
                    "title": display_title,
                    "bpm": bpm,
                    "energy": energy,
                    "dance": dance,
                }
            )

        details_blocks = [
            ("Detections", str(row.get("detection_count", 0))),
            ("Density", f"{density_pct:.0f}%"),
            ("Cluster Span", f'{row.get("cluster_span", 0)} seg'),
            ("Window", time_range),
        ]
        if bpm is not None:
            details_blocks.append(("BPM", f"{float(bpm):.1f}"))
        if row.get("genres"):
            details_blocks.append(("Genres", ", ".join(str(g) for g in row.get("genres", []) if str(g).strip())))
        if row.get("label"):
            details_blocks.append(("Label", str(row["label"])))
        if row.get("key"):
            details_blocks.append(("Key", str(row["key"])))
        if energy is not None:
            details_blocks.append(("Energy", f"{float(energy):.2f}"))
        if dance is not None:
            details_blocks.append(("Dance", f"{float(dance):.2f}"))

        details_html = "".join(
            f'<div class="detail-item"><span class="detail-k">{esc(k)}</span><span class="detail-v">{esc(v)}</span></div>'
            for k, v in details_blocks
        )
        details_html += (
            f'<div class="detail-item"><span class="detail-k">Density Bar</span>'
            f'<div class="detail-density-bar"><div class="detail-density-fill" style="width:{density_pct:.1f}%;"></div></div></div>'
        )
        art_html = (
            f'<img src="{esc(album_art_url)}" alt="" loading="lazy" />'
            if album_art_url
            else '<span class="track-art--empty">♪</span>'
        )
        has_embed = bool(row.get("spotify_track_id"))
        spotify_external_link_html = (
            f'<a class="action-link spotify{" fallback" if not direct_spotify_url else ""}" href="{esc(spotify_url)}" target="_blank" rel="noopener">{spotify_link_label}</a>'
        )
        youtube_discogs_links_html = (
            f'<a class="action-link youtube{" fallback" if not direct_youtube_url else ""}" href="{esc(youtube_url)}" target="_blank" rel="noopener">{youtube_link_label}</a>'
            f'<a class="action-link discogs{" fallback" if not direct_discogs_url else ""}" href="{esc(discogs_url)}" target="_blank" rel="noopener">{discogs_link_label}</a>'
        )
        external_links_html = spotify_external_link_html + youtube_discogs_links_html
        if has_embed:
            track_actions_html = (
                f'<button class="btn track-tool-btn embed-btn js-spotify-embed" data-track-id="{esc(row["spotify_track_id"])}">Spotify</button>'
                '<button class="btn track-tool-btn details-btn js-details-toggle">Details</button>'
            )
            details_external_links_html = f'<div class="track-external-links in-details">{external_links_html}</div>'
        else:
            track_actions_html = (
                f'<div class="track-external-links">{spotify_external_link_html}</div>'
                '<button class="btn track-tool-btn details-btn js-details-toggle">Details</button>'
            )
            details_external_links_html = f'<div class="track-external-links in-details">{youtube_discogs_links_html}</div>'

        track_cards_html.append(
            f"""
<article class="track-card" id="track-{row["position"]}" data-track-idx="{row["position"]}" data-conf="{esc(conf)}"
  data-search="{esc(row["search_blob"])}" data-artist="{esc(display_artist.lower())}" data-title="{esc(display_title.lower())}"
  data-start="{row["start_time"]:.3f}" data-bpm="{esc(row.get("bpm") or '')}" data-preview-url="{esc(preview_url)}">
  <div class="track-grid">
    <div class="track-index">{row["position"]}</div>
    <div class="track-art">{art_html}</div>
    <div class="track-time-col">
      <button class="btn js-track-play" data-time="{row["start_time"]:.3f}" title="Play / pause at this track">▶</button>
      <a class="track-time-link js-track-time" href="#" data-time="{row["start_time"]:.3f}" title="Jump to this timestamp">{esc(start_fmt)}</a>
    </div>
    <div class="track-main">
      <div class="track-title-row">
        <span class="track-artist">{esc(display_artist)}</span>
        <span class="track-sep">—</span>
        <span class="track-title">{esc(display_title)}</span>
      </div>
      <div class="track-meta">
        <span class="pill {conf_cls}">{esc(conf)}</span>
      </div>
    </div>
    <div class="track-actions">
      {track_actions_html}
    </div>
  </div>
  <div class="spotify-inline" hidden></div>
  <div class="track-details" hidden>
    {details_external_links_html}
    <div class="details-grid">
      {details_html}
    </div>
  </div>
</article>
"""
        )

    conf_filter_buttons = ['<button class="btn active js-conf-filter" data-conf="all">All</button>']
    for conf in ("HIGH", "MEDIUM", "LOW", "UNCERTAIN"):
        count = counts.get(conf, 0)
        if count:
            conf_filter_buttons.append(
                f'<button class="btn js-conf-filter" data-conf="{conf}">{conf} ({count})</button>'
            )

    ticks_html = "".join(
        f"<span>{esc(format_time(total_duration * pct / 100.0))}</span>" for pct in (0, 25, 50, 75, 100)
    )

    set_payload = {
        "duration": total_duration,
        "platform": platform,
        "embedId": embed_id,
        "sourceUrl": source_url,
        "tracks": [
            {
                "idx": r["position"],
                "artist": r.get("artist") or "Unknown",
                "title": r.get("title") or "Unknown Track",
                "start": float(r.get("start_time") or 0.0),
                "end": float(r.get("end_time") or total_duration),
                "startFmt": r.get("start_time_formatted") or format_time(r.get("start_time") or 0.0),
                "endFmt": r.get("end_time_formatted") or format_time(r.get("end_time") or total_duration),
                "conf": (r.get("confidence") or "UNCERTAIN").upper(),
                "albumArt": r.get("spotify_album_art") or "",
                "previewUrl": r.get("spotify_preview_url") or "",
                "bpm": r.get("bpm"),
                "energy": r.get("energy"),
                "dance": r.get("danceability"),
            }
            for r in rows
        ],
        "journeyPoints": journey_points,
    }

    title_raw = str(mix_info.get("title") or "").strip() or "Untitled Set"
    title = esc(title_raw)
    title_len = len(title_raw)
    if title_len >= 68:
        hero_title_size_class = "xlong"
        hero_title_min_size = 20
    elif title_len >= 44:
        hero_title_size_class = "long"
        hero_title_min_size = 22
    else:
        hero_title_size_class = ""
        hero_title_min_size = 24
    hero_title_class_attr = "set-hero-title-overlay" + (
        f" {hero_title_size_class}" if hero_title_size_class else ""
    )
    artist_display = (
        str(mix_info.get("artist") or "").strip()
        or str(mix_info.get("artist_name") or "").strip()
        or str(mix_info.get("uploader") or "").strip()
        or "Set Artist"
    )
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    duration_fmt = esc(format_time(total_duration))
    known_artists = len({(r.get("artist") or "").strip().lower() for r in rows if (r.get("artist") or "").strip() and r.get("artist") != "Unknown"})
    bpm_values = [float(r["bpm"]) for r in rows if r.get("bpm") is not None]
    tempo_span = f"{min(bpm_values):.0f} - {max(bpm_values):.0f} BPM" if bpm_values else "Tempo unavailable"

    set_image_source = ""
    for key in (
        "thumbnail_url",
        "thumbnail",
        "image_url",
        "cover_image",
        "poster_url",
    ):
        candidate = str(mix_info.get(key) or "").strip()
        if candidate:
            set_image_source = candidate
            break
    if not set_image_source and platform == "youtube" and embed_id:
        set_image_source = f"https://i.ytimg.com/vi/{embed_id}/hqdefault.jpg"

    artist_image_source = ""
    for key in (
        "artist_profile_image",
        "spotify_artist_profile_image",
        "discogs_artist_profile_image",
    ):
        candidate = str(mix_info.get(key) or "").strip()
        if candidate:
            artist_image_source = candidate
            break

    fallback_other_set_image = _set_cover_fallback_from_other_sets(
        output_dir,
        exclude_images={set_image_source, artist_image_source},
    )
    hero_image_source = _first_nonempty(
        set_image_source,
        artist_image_source,
        fallback_other_set_image,
    )
    if not hero_image_source:
        hero_image_source = next(
            (str(r.get("spotify_album_art") or "").strip() for r in rows if str(r.get("spotify_album_art") or "").strip()),
            "",
        )

    if platform == "youtube" and embed_id:
        source_player_frame_class = "source-player-frame is-youtube"
        source_player_inner_html = (
            f'<iframe id="ytSourcePlayer" src="https://www.youtube-nocookie.com/embed/{esc(embed_id)}?enablejsapi=1&rel=0&modestbranding=1&iv_load_policy=3&playsinline=1" '
            'title="Set source player" '
            'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" '
            'allowfullscreen loading="lazy"></iframe>'
        )
    elif platform == "soundcloud" and source_url:
        source_player_frame_class = "source-player-frame is-soundcloud"
        soundcloud_src = (
            "https://w.soundcloud.com/player/?url="
            f"{quote(source_url, safe='')}"
            "&color=%23111111&auto_play=false&hide_related=false&show_comments=false"
            "&show_user=true&show_reposts=false&show_teaser=false&visual=false"
        )
        source_player_inner_html = (
            f'<iframe id="scSourceWidget" src="{esc(soundcloud_src)}" title="Set source player" '
            'allow="autoplay" loading="lazy"></iframe>'
        )
    elif source_url:
        source_player_frame_class = "source-player-frame is-fallback"
        source_player_inner_html = (
            '<div class="source-player-fallback">Embedded playback is unavailable for this source.<br/>'
            f'<a href="{esc(source_url)}" target="_blank" rel="noopener">Open original source</a>.</div>'
        )
    else:
        source_player_frame_class = "source-player-frame is-fallback"
        source_player_inner_html = '<div class="source-player-fallback">No source URL available for this set.</div>'

    source_player_open_link_html = (
        f'<a class="source-player-open" href="{esc(source_url)}" target="_blank" rel="noopener">Open Source</a>'
        if source_url
        else ""
    )
    hero_track_rows = [
        r
        for r in rows
        if str(r.get("spotify_album_art") or "").strip()
    ][:12]

    hero_cards: list[str] = []
    for row in hero_track_rows:
        hero_artist = row.get("artist") or "Unknown"
        hero_title = row.get("title") or "Unknown Track"
        hero_art = str(row.get("spotify_album_art") or "").strip()
        if not hero_art:
            continue
        hero_art_html = f'<img src="{esc(hero_art)}" alt="" loading="lazy" />'
        hero_cards.append(
            f"""
<button class="set-hero-card js-hero-jump" type="button" data-track-idx="{row["position"]}" data-time="{row["start_time"]:.3f}" title="Jump to track {row["position"]}">
  <div class="set-hero-card-media">{hero_art_html}</div>
  <div class="set-hero-card-meta">
    <p class="set-hero-card-artist">{esc(hero_artist)}</p>
    <p class="set-hero-card-title">{esc(hero_title)}</p>
  </div>
</button>
"""
        )

    if hero_cards:
        hero_loop = "".join(hero_cards)
        hero_side_html = f"""
<div class="set-hero-side-viewport" id="setHeroSideViewport">
  <div class="set-hero-side-track" id="setHeroSideTrack">
    {hero_loop}
    {hero_loop}
  </div>
</div>"""
    else:
        hero_side_html = '<div class="set-hero-side-empty">No track cards available.</div>'

    hero_main_media_html = (
        f'<img src="{esc(hero_image_source)}" alt="{title} cover image" loading="eager" />'
        if hero_image_source
        else '<div class="set-hero-main-empty">No set image available</div>'
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title} — Set Explorer</title>
  <style>{_set_css()}</style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand">[SET SIGNAL ARCHIVE]</div>
      <div class="topbar-right">
        <nav class="topnav">
          <a href="#overview">Overview</a>
          <a href="#timeline">Timeline</a>
          <a href="#journey">Journey</a>
          <a href="#tracks">Track Atlas</a>
        </nav>
      </div>
    </div>
  </header>

  <main class="shell detail-shell">
    <section class="section" id="overview">
      <div class="section-inner">
        <div class="kicker">Set Intelligence Deck</div>
        <div class="set-hero">
          <div class="set-hero-grid">
            <div class="set-hero-main">
              {hero_main_media_html}
              <h2 class="{hero_title_class_attr}" data-min-size="{hero_title_min_size}">{title}</h2>
            </div>
            <div class="set-hero-side" id="setHeroSide">
              {hero_side_html}
            </div>
          </div>
        </div>
        <div class="stats-grid">
          <div class="stat"><span class="stat-value">{total_tracks}</span><span class="stat-label">Tracks</span></div>
          <div class="stat"><span class="stat-value">{id_rate:.0f}%</span><span class="stat-label">Identified</span></div>
          <div class="stat"><span class="stat-value">{confidence_rate:.0f}%</span><span class="stat-label">High / Medium</span></div>
          <div class="stat"><span class="stat-value">{known_artists}</span><span class="stat-label">Distinct Artists</span></div>
        </div>
        <div class="cluster-row">
          <span class="cluster-pill">{duration_fmt}</span>
          <span class="cluster-pill">{esc(tempo_span)}</span>
          <span class="cluster-pill">Generated {esc(generated)}</span>
        </div>
        <div class="panel timeline-journey-panel" id="timeline">
          <div class="{source_player_frame_class}" id="sourcePlayerFrame">
            {source_player_inner_html}
          </div>
          <div class="timeline-wrap">
            <div class="timeline-bar" id="timelineBar">
              {''.join(timeline_segments_html)}
            </div>
            <div class="timeline-ticks">{ticks_html}</div>
          </div>
          {source_player_open_link_html}
          <div class="journey-inline" id="journey">
            <div class="journey-toolbar">
              <button class="btn journey-toggle-btn" id="journeyToggleBtn" type="button" aria-expanded="false" aria-controls="journeyBody">Show Journey Lens</button>
            </div>
            <div class="journey-body" id="journeyBody" hidden>
              <div class="journey-controls">
                <button class="btn active js-journey-metric" data-metric="bpm">BPM</button>
                <button class="btn active js-journey-metric" data-metric="energy">Energy</button>
                <button class="btn active js-journey-metric" data-metric="dance">Dance</button>
              </div>
              <div class="journey-chart-wrap" id="journeyWrap">
                <svg id="journeySvg" viewBox="0 0 1000 260" preserveAspectRatio="none"></svg>
                <div class="journey-empty" id="journeyEmpty" hidden>No track metrics available for this set.</div>
              </div>
              <div class="journey-legend">
                <span class="journey-key"><span class="journey-dot" style="background:#6fffa4"></span>BPM</span>
                <span class="journey-key"><span class="journey-dot" style="background:#ffcf5c"></span>Energy</span>
                <span class="journey-key"><span class="journey-dot" style="background:#7dc3ff"></span>Dance</span>
              </div>
            </div>
          </div>
          <div class="timeline-track-atlas" id="tracks">
            <h2 class="panel-title">Track Atlas</h2>
            <p class="panel-sub">Search, slice, and inspect evidence for each detected track.</p>
            <div class="track-explorer-panel">
          <div class="track-head">
            <div class="controls">
              <input class="input" id="trackSearchInput" type="search" placeholder="Search by artist or title..." />
              <div class="controls-row">{''.join(conf_filter_buttons)}</div>
            </div>
          </div>
          <div class="tracklist" id="tracklist">{''.join(track_cards_html)}</div>
          <div class="no-results" id="noResults">No tracks match the active filters.</div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <div class="footer-note">Generated {esc(generated)} · Set Signal Explorer</div>
  </main>

  <div class="dock" id="playerDock">
    <div class="dock-grid">
      <div class="dock-now">
        <div class="dock-art-frame">
          <img class="dock-art" id="dockArt" src="" alt="" loading="lazy" />
          <div class="dock-art-fallback" id="dockArtFallback">&#9835;</div>
        </div>
        <div>
          <div class="dock-track" id="dockTrack">No active track</div>
          <div class="dock-artist" id="dockArtist">—</div>
        </div>
      </div>
      <div class="dock-center">
        <div class="dock-main-row">
          <div class="dock-primary-controls">
            <button class="dock-mini-btn" id="dockBack" title="Back 15 seconds">-15</button>
            <button class="dock-nav-btn" id="dockPrev" title="Previous track">&#9198;</button>
            <button class="dock-play-btn" id="dockPlay" title="Play / pause">&#9654;</button>
            <button class="dock-nav-btn" id="dockNext" title="Next track">&#9197;</button>
            <button class="dock-mini-btn" id="dockFwd" title="Forward 15 seconds">+15</button>
          </div>
          <div class="dock-range">
            <div class="dock-progress" id="dockProgress"><div class="dock-progress-fill" id="dockProgressFill"></div></div>
            <div class="dock-time"><span id="dockCurrentTime">0:00</span><span>{duration_fmt}</span></div>
          </div>
        </div>
      </div>
      <div class="dock-actions">
        <button class="btn" id="dockToTrack">Track</button>
      </div>
    </div>
  </div>
  <div id="tl-tooltip" aria-hidden="true">
    <div class="tt-title"></div>
    <div class="tt-sub"></div>
    <div class="tt-badge"></div>
  </div>
  <div id="journey-tooltip" aria-hidden="true">
    <div class="jt-title"></div>
    <div class="jt-value"></div>
  </div>

  <script>
    const SET_DATA = {to_json(set_payload)};
  </script>
  <script>
(() => {{
  const STATE = {{
    query: '',
    conf: 'all',
    activeIdx: null,
    currentTime: 0,
    isPlaying: false,
    metrics: new Set(['bpm', 'energy', 'dance']),
    journeyOpen: false,
  }};

  const trackListEl = document.getElementById('tracklist');
  const noResultsEl = document.getElementById('noResults');
  const searchEl = document.getElementById('trackSearchInput');
  const confBtns = Array.from(document.querySelectorAll('.js-conf-filter'));
  const cards = Array.from(document.querySelectorAll('.track-card'));
  const segs = Array.from(document.querySelectorAll('.timeline-segment'));
  const dock = document.getElementById('playerDock');
  const dockTrack = document.getElementById('dockTrack');
  const dockArtist = document.getElementById('dockArtist');
  const dockArt = document.getElementById('dockArt');
  const dockArtFallback = document.getElementById('dockArtFallback');
  const dockPlay = document.getElementById('dockPlay');
  const dockProgress = document.getElementById('dockProgress');
  const dockProgressFill = document.getElementById('dockProgressFill');
  const dockCurrentTime = document.getElementById('dockCurrentTime');
  const sourcePlayerFrame = document.getElementById('sourcePlayerFrame');
  const tlTooltip = document.getElementById('tl-tooltip');
  const tlTitle = tlTooltip ? tlTooltip.querySelector('.tt-title') : null;
  const tlSub = tlTooltip ? tlTooltip.querySelector('.tt-sub') : null;
  const tlBadge = tlTooltip ? tlTooltip.querySelector('.tt-badge') : null;
  const journeyTooltip = document.getElementById('journey-tooltip');
  const journeyTitle = journeyTooltip ? journeyTooltip.querySelector('.jt-title') : null;
  const journeyValue = journeyTooltip ? journeyTooltip.querySelector('.jt-value') : null;
  const journeyBody = document.getElementById('journeyBody');
  const journeyToggleBtn = document.getElementById('journeyToggleBtn');
  const heroCards = Array.from(document.querySelectorAll('.set-hero-card[data-track-idx]'));
  const setHeroViewport = document.getElementById('setHeroSideViewport');
  const setHeroTrack = document.getElementById('setHeroSideTrack');
  const setHeroMain = document.querySelector('.set-hero-main');
  const setHeroTitle = document.querySelector('.set-hero-title-overlay');
  const setHeroCaption = document.querySelector('.set-hero-caption');

  const PLAYER_PLATFORM = String(SET_DATA.platform || '').toLowerCase();
  const PLAYER_EMBED_ID = String(SET_DATA.embedId || '');
  const PLAYER_SOURCE_URL = String(SET_DATA.sourceUrl || '');
  const byIdx = new Map(SET_DATA.tracks.map(t => [String(t.idx), t]));
  let currentPreviewAudio = null;
  let currentPreviewBtn = null;
  let setHeroRailRaf = 0;
  let setHeroRailLastTs = 0;
  let setHeroResizeTimer = null;
  let ytPlayer = null;
  let scWidget = null;
  let playerReady = false;
  let playerPoll = null;
  let fallbackTick = null;
  let seekLockUntil = 0;
  let pendingSeek = null;
  let pendingAutoplay = false;
  let prevTrackPressTs = 0;
  let ytEmbedBlocked = false;
  let scEmbedBlocked = false;

  function fmtTime(seconds) {{
    seconds = Math.max(0, Math.floor(seconds || 0));
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h > 0) return `${{h}}:${{String(m).padStart(2,'0')}}:${{String(s).padStart(2,'0')}}`;
    return `${{m}}:${{String(s).padStart(2,'0')}}`;
  }}

  function isInteractiveElement(el) {{
    return !!el.closest('a,button,input,select,textarea,.js-track-time,.js-track-play,.js-details-toggle,.js-spotify-embed,.js-preview');
  }}

  function updatePlayButtons() {{
    const sourceJumpMode = ytEmbedBlocked && PLAYER_PLATFORM === 'youtube';
    cards.forEach(card => {{
      const btn = card.querySelector('.js-track-play');
      if (!btn) return;
      const isActive = String(card.dataset.trackIdx || '') === String(STATE.activeIdx || '');
      btn.textContent = sourceJumpMode ? 'YT' : (isActive && STATE.isPlaying ? '❚❚' : '▶');
      btn.classList.toggle('active', !sourceJumpMode && isActive);
      btn.classList.toggle('source-jump', sourceJumpMode);
      btn.title = sourceJumpMode ? 'Open source on YouTube at this timestamp' : 'Play / pause at this track';
    }});
  }}

  function setHeroActive(idx) {{
    const sid = idx != null ? String(idx) : null;
    heroCards.forEach(card => {{
      card.classList.toggle('active', !!sid && card.dataset.trackIdx === sid);
    }});
  }}

  function fitHeroTitle() {{
    if (!setHeroMain || !setHeroTitle) return;
    const computed = window.getComputedStyle(setHeroTitle);
    if (!setHeroTitle.dataset.baseSize) {{
      const base = parseFloat(computed.fontSize || '0');
      if (base > 0) setHeroTitle.dataset.baseSize = String(base);
    }}
    const baseSize = parseFloat(setHeroTitle.dataset.baseSize || computed.fontSize || '0') || 56;
    const minSize = Math.max(16, parseFloat(setHeroTitle.dataset.minSize || '24') || 24);
    let size = baseSize;
    setHeroTitle.style.fontSize = `${{size}}px`;

    const fits = () => {{
      const mainRect = setHeroMain.getBoundingClientRect();
      const titleRect = setHeroTitle.getBoundingClientRect();
      const topClear = titleRect.top >= mainRect.top + 6;
      const bottomLimit = setHeroCaption
        ? setHeroCaption.getBoundingClientRect().top - 6
        : mainRect.bottom - 8;
      return topClear && titleRect.bottom <= bottomLimit;
    }};

    let guard = 0;
    while (!fits() && size > minSize && guard < 50) {{
      size -= 1;
      setHeroTitle.style.fontSize = `${{size}}px`;
      guard += 1;
    }}
  }}

  function stopSetHeroRail() {{
    if (setHeroRailRaf) {{
      cancelAnimationFrame(setHeroRailRaf);
      setHeroRailRaf = 0;
    }}
    setHeroRailLastTs = 0;
  }}

  function startSetHeroRail() {{
    stopSetHeroRail();
    if (!setHeroViewport || !setHeroTrack) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    if (window.matchMedia('(max-width: 1180px)').matches) return;

    const cycleHeight = setHeroTrack.scrollHeight / 2;
    if (!Number.isFinite(cycleHeight) || cycleHeight <= setHeroViewport.clientHeight + 4) return;

    if (!setHeroViewport.dataset.bound) {{
      setHeroViewport.addEventListener('mouseenter', () => stopSetHeroRail());
      setHeroViewport.addEventListener('mouseleave', () => startSetHeroRail());
      setHeroViewport.dataset.bound = '1';
    }}

    let scrollPos = setHeroViewport.scrollTop % cycleHeight;
    setHeroViewport.scrollTop = scrollPos;
    const pxPerSecond = 14;

    const tick = (ts) => {{
      if (!setHeroRailRaf) return;
      if (!setHeroRailLastTs) setHeroRailLastTs = ts;
      const dt = (ts - setHeroRailLastTs) / 1000;
      setHeroRailLastTs = ts;
      scrollPos += pxPerSecond * dt;
      if (scrollPos >= cycleHeight) {{
        scrollPos -= cycleHeight;
      }}
      setHeroViewport.scrollTop = scrollPos;
      setHeroRailRaf = requestAnimationFrame(tick);
    }};

    setHeroRailRaf = requestAnimationFrame(tick);
  }}

  function stopPreview() {{
    if (!currentPreviewAudio) return;
    currentPreviewAudio.pause();
    currentPreviewAudio = null;
    if (currentPreviewBtn) {{
      currentPreviewBtn.textContent = 'Preview';
      currentPreviewBtn.classList.remove('active');
      currentPreviewBtn = null;
    }}
  }}

  function setJourneyActive(idx) {{
    const sid = idx != null ? String(idx) : null;
    const points = document.querySelectorAll('.journey-point');
    points.forEach(dot => {{
      dot.classList.toggle('active', !!sid && dot.dataset.trackIdx === sid);
    }});
  }}

  function findTrackByTime(seconds) {{
    const t = Math.max(0, seconds || 0);
    let best = null;
    SET_DATA.tracks.forEach(tr => {{
      if (t >= tr.start && t < tr.end) {{
        if (!best || tr.start > best.start) best = tr;
      }}
    }});
    return best || SET_DATA.tracks[SET_DATA.tracks.length - 1] || null;
  }}

  function setActiveTrack(idx, scroll = false) {{
    const sid = String(idx ?? '');
    if (!sid) return;
    STATE.activeIdx = sid;
    cards.forEach(card => card.classList.toggle('active', card.dataset.trackIdx === sid));
    segs.forEach(seg => seg.classList.toggle('active', seg.dataset.trackIdx === sid));
    setHeroActive(sid);
    const tr = byIdx.get(sid);
    if (!tr) return;
    dockTrack.textContent = tr.title || 'Unknown Track';
    dockArtist.textContent = tr.artist || 'Unknown';
    if (dockArt) {{
      if (tr.albumArt) {{
        dockArt.src = tr.albumArt;
        dockArt.classList.add('visible');
        if (dockArtFallback) dockArtFallback.classList.add('hidden');
      }} else {{
        dockArt.src = '';
        dockArt.classList.remove('visible');
        if (dockArtFallback) dockArtFallback.classList.remove('hidden');
      }}
    }}
    if (scroll) {{
      const card = document.querySelector(`.track-card[data-track-idx="${{sid}}"]`);
      if (card) card.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
    }}
    setJourneyActive(sid);
    updatePlayButtons();
  }}

  function clearActiveTrack() {{
    STATE.activeIdx = null;
    cards.forEach(card => card.classList.remove('active'));
    segs.forEach(seg => seg.classList.remove('active'));
    setHeroActive(null);
    setJourneyActive(null);
    updatePlayButtons();
  }}

  function updateProgress() {{
    const duration = Math.max(0.001, SET_DATA.duration || 0);
    const safeCurrent = Math.max(0, Math.min(SET_DATA.duration || 0, STATE.currentTime || 0));
    const pct = Math.max(0, Math.min(100, (safeCurrent / duration) * 100));
    dockProgressFill.style.width = `${{pct}}%`;
    dockCurrentTime.textContent = fmtTime(safeCurrent);
  }}

  function updateFromTime(seconds, scroll = false) {{
    const duration = Math.max(0, SET_DATA.duration || 0);
    STATE.currentTime = Math.max(0, Math.min(duration, seconds || 0));
    const tr = findTrackByTime(STATE.currentTime);
    if (tr) setActiveTrack(tr.idx, scroll);
    updateProgress();
  }}

  function applyFilters() {{
    const q = (STATE.query || '').trim().toLowerCase();
    let visibleCount = 0;
    cards.forEach(card => {{
      const matchQuery = !q || (card.dataset.search || '').includes(q);
      const matchConf = STATE.conf === 'all' || card.dataset.conf === STATE.conf;
      const show = matchQuery && matchConf;
      card.hidden = !show;
      if (show) visibleCount += 1;
    }});
    noResultsEl.style.display = visibleCount ? 'none' : 'block';
    segs.forEach(seg => {{
      const card = document.querySelector(`.track-card[data-track-idx="${{seg.dataset.trackIdx}}"]`);
      seg.classList.toggle('dim', !!card && card.hidden);
    }});
  }}

  function positionTooltip(tooltipEl, x, y) {{
    if (!tooltipEl) return;
    const offset = 14;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const tw = tooltipEl.offsetWidth || 220;
    const th = tooltipEl.offsetHeight || 90;
    let left = x + offset;
    let top = y + offset;
    if (left + tw > vw - 8) left = x - tw - offset;
    if (top + th > vh - 8) top = y - th - offset;
    tooltipEl.style.left = `${{Math.max(8, left)}}px`;
    tooltipEl.style.top = `${{Math.max(8, top)}}px`;
  }}

  function showTimelineTooltip(seg, x, y) {{
    if (!tlTooltip) return;
    if (tlTitle) tlTitle.textContent = `Track #${{seg.dataset.trackIdx || ''}} · ${{seg.dataset.artist || 'Unknown'}} — ${{seg.dataset.title || 'Unknown Track'}}`;
    if (tlSub) tlSub.textContent = seg.dataset.time || '';
    if (tlBadge) {{
      tlBadge.textContent = seg.dataset.conf || '';
      tlBadge.style.color = seg.dataset.color || '#888';
      tlBadge.style.borderColor = seg.dataset.color || '#888';
    }}
    positionTooltip(tlTooltip, x, y);
    tlTooltip.classList.add('visible');
  }}

  function hideTimelineTooltip() {{
    if (tlTooltip) tlTooltip.classList.remove('visible');
  }}

  function showJourneyTooltip(dot, x, y) {{
    if (!journeyTooltip) return;
    const idx = String(dot.dataset.trackIdx || '');
    const tr = byIdx.get(idx);
    const metric = dot.dataset.metric || '';
    const rawValue = parseFloat(dot.dataset.value || '0');
    const valueLabel = metric === 'bpm'
      ? `BPM ${{rawValue.toFixed(1)}}`
      : `${{metric === 'energy' ? 'Energy' : 'Dance'}} ${{rawValue.toFixed(2)}}`;
    if (journeyTitle) journeyTitle.textContent = `${{tr?.artist || 'Unknown'}} — ${{tr?.title || 'Unknown Track'}}`;
    if (journeyValue) journeyValue.textContent = valueLabel;
    positionTooltip(journeyTooltip, x, y);
    journeyTooltip.classList.add('visible');
  }}

  function hideJourneyTooltip() {{
    if (journeyTooltip) journeyTooltip.classList.remove('visible');
  }}

  searchEl.addEventListener('input', () => {{
    STATE.query = searchEl.value || '';
    applyFilters();
  }});

  confBtns.forEach(btn => btn.addEventListener('click', () => {{
    STATE.conf = btn.dataset.conf || 'all';
    confBtns.forEach(b => b.classList.toggle('active', b === btn));
    applyFilters();
  }}));

  segs.forEach(seg => {{
    seg.addEventListener('mouseenter', ev => {{
      showTimelineTooltip(seg, ev.clientX, ev.clientY);
      if (String(seg.dataset.trackIdx || '') !== String(STATE.activeIdx || '')) {{
        seg.classList.add('hover');
      }}
    }});
    seg.addEventListener('mousemove', ev => showTimelineTooltip(seg, ev.clientX, ev.clientY));
    seg.addEventListener('mouseleave', () => {{
      hideTimelineTooltip();
      seg.classList.remove('hover');
    }});
    seg.addEventListener('click', ev => {{
      ev.stopPropagation();
      const idx = String(seg.dataset.trackIdx || '');
      const start = parseFloat(seg.dataset.start || '0');
      if (!idx) return;
      if (idx === String(STATE.activeIdx || '')) {{
        clearActiveTrack();
        return;
      }}
      // In YouTube blocked mode, timeline selection should also scroll to the card.
      const blockedYt = ytEmbedBlocked && PLAYER_PLATFORM === 'youtube';
      jumpTo(start, blockedYt, true);
    }});
  }});

  cards.forEach(card => {{
    card.addEventListener('mouseenter', () => {{
      const idx = String(card.dataset.trackIdx || '');
      if (!idx || idx === String(STATE.activeIdx || '')) return;
      const seg = document.querySelector(`.timeline-segment[data-track-idx="${{idx}}"]`);
      if (seg) seg.classList.add('hover');
    }});
    card.addEventListener('mouseleave', () => {{
      const idx = String(card.dataset.trackIdx || '');
      if (!idx || idx === String(STATE.activeIdx || '')) return;
      const seg = document.querySelector(`.timeline-segment[data-track-idx="${{idx}}"]`);
      if (seg) seg.classList.remove('hover');
    }});
    card.addEventListener('click', ev => {{
      if (isInteractiveElement(ev.target)) return;
      const start = parseFloat(card.dataset.start || '0');
      jumpTo(start, false, true);
    }});
  }});

  document.addEventListener('click', ev => {{
    const heroJump = ev.target.closest('.js-hero-jump');
    if (heroJump) {{
      ev.preventDefault();
      const start = parseFloat(heroJump.dataset.time || '0');
      jumpTo(start, true, true);
      return;
    }}
    const timeLink = ev.target.closest('.js-track-time');
    if (timeLink) {{
      ev.preventDefault();
      const start = parseFloat(timeLink.dataset.time || '0');
      jumpTo(start, true, true);
      return;
    }}
    const playBtn = ev.target.closest('.js-track-play');
    if (playBtn) {{
      ev.preventDefault();
      const card = playBtn.closest('.track-card');
      const idx = String(card?.dataset.trackIdx || '');
      const start = parseFloat(playBtn.dataset.time || '0');
      if (ytEmbedBlocked && PLAYER_PLATFORM === 'youtube') {{
        jumpTo(start, true, false);
        openSourceAt(start);
        return;
      }}
      if (idx && idx === String(STATE.activeIdx || '')) {{
        togglePlay();
      }} else {{
        jumpTo(start, true, true);
      }}
      return;
    }}
    const detBtn = ev.target.closest('.js-details-toggle');
    if (detBtn) {{
      const card = detBtn.closest('.track-card');
      const panel = card?.querySelector('.track-details');
      if (panel) {{
        panel.hidden = !panel.hidden;
        detBtn.classList.toggle('active', !panel.hidden);
      }}
      return;
    }}
    const spBtn = ev.target.closest('.js-spotify-embed');
    if (spBtn) {{
      const card = spBtn.closest('.track-card');
      const wrap = card?.querySelector('.spotify-inline');
      if (!wrap) return;
      if (!wrap.hidden) {{
        wrap.hidden = true;
        wrap.innerHTML = '';
        spBtn.classList.remove('active');
        return;
      }}
      const id = spBtn.dataset.trackId || '';
      if (!id) return;
      wrap.hidden = false;
      wrap.innerHTML = `<iframe style="border-radius:0" src="https://open.spotify.com/embed/track/${{id}}?utm_source=generator&theme=0" width="100%" height="80" frameBorder="0" allow="autoplay; clipboard-write; encrypted-media" loading="lazy"></iframe>`;
      spBtn.classList.add('active');
      return;
    }}
    const previewBtn = ev.target.closest('.js-preview');
    if (previewBtn) {{
      const url = previewBtn.dataset.preview || '';
      if (!url) return;
      if (currentPreviewBtn === previewBtn && currentPreviewAudio) {{
        stopPreview();
        return;
      }}
      stopPreview();
      const audio = new Audio(url);
      currentPreviewAudio = audio;
      currentPreviewBtn = previewBtn;
      previewBtn.textContent = 'Stop';
      previewBtn.classList.add('active');
      audio.play().catch(() => {{
        stopPreview();
      }});
      audio.onended = () => {{
        stopPreview();
      }};
      return;
    }}
  }});

  // Journey rendering
  const journeySvg = document.getElementById('journeySvg');
  const journeyEmpty = document.getElementById('journeyEmpty');
  const journeyBtns = Array.from(document.querySelectorAll('.js-journey-metric'));
  const journeyColors = {{
    bpm: '#6fffa4',
    energy: '#ffcf5c',
    dance: '#7dc3ff',
  }};
  function renderJourney() {{
    const points = SET_DATA.journeyPoints || [];
    if (!points.length) {{
      journeySvg.innerHTML = '';
      journeyEmpty.hidden = false;
      return;
    }}
    journeyEmpty.hidden = true;
    const w = 1000;
    const h = 260;
    const pad = 22;
    const total = SET_DATA.duration || 1;
    const activeMetrics = Array.from(STATE.metrics);
    const layers = [];
    activeMetrics.forEach(metric => {{
      const vals = points.map(p => p[metric]).filter(v => v !== null && v !== undefined);
      if (!vals.length) return;
      const min = Math.min(...vals);
      const max = Math.max(...vals);
      const range = Math.max(0.0001, max - min);
      const coords = points
        .filter(p => p[metric] !== null && p[metric] !== undefined)
        .map(p => {{
          const x = pad + (Math.max(0, p.start) / total) * (w - pad * 2);
          const norm = (p[metric] - min) / range;
          const y = h - pad - norm * (h - pad * 2);
          return {{ x, y, p }};
        }});
      if (!coords.length) return;
      const path = coords.map((c, i) => `${{i ? 'L' : 'M'}}${{c.x.toFixed(2)}} ${{c.y.toFixed(2)}}`).join(' ');
      layers.push(`<path d="${{path}}" fill="none" stroke="${{journeyColors[metric]}}" stroke-width="2"/>`);
      coords.forEach(c => {{
        layers.push(
          `<circle cx="${{c.x.toFixed(2)}}" cy="${{c.y.toFixed(2)}}" r="4" fill="${{journeyColors[metric]}}" data-track-idx="${{c.p.idx}}" data-metric="${{metric}}" data-value="${{Number(c.p[metric]).toFixed(3)}}" class="journey-point"/>`
        );
      }});
    }});
    journeySvg.innerHTML = layers.join('');
    journeySvg.querySelectorAll('.journey-point').forEach(dot => {{
      dot.addEventListener('mouseenter', e => showJourneyTooltip(dot, e.clientX, e.clientY));
      dot.addEventListener('mousemove', e => showJourneyTooltip(dot, e.clientX, e.clientY));
      dot.addEventListener('mouseleave', hideJourneyTooltip);
      dot.addEventListener('click', e => {{
        e.stopPropagation();
        const idx = dot.getAttribute('data-track-idx');
        const tr = byIdx.get(String(idx));
        // Master parity: journey click seeks/activates without scrolling to the card.
        if (tr) jumpTo(tr.start, false, true);
      }});
    }});
    setJourneyActive(STATE.activeIdx);
  }}

  journeyToggleBtn?.addEventListener('click', () => {{
    setJourneyOpen(!STATE.journeyOpen);
  }});

  journeyBtns.forEach(btn => btn.addEventListener('click', () => {{
    const metric = btn.dataset.metric;
    if (!metric) return;
    if (STATE.metrics.has(metric)) STATE.metrics.delete(metric);
    else STATE.metrics.add(metric);
    btn.classList.toggle('active', STATE.metrics.has(metric));
    renderJourney();
  }}));

  // Playback
  function setPlaying(playing) {{
    STATE.isPlaying = !!playing;
    if (dockPlay) {{
      dockPlay.innerHTML = STATE.isPlaying ? '&#10074;&#10074;' : '&#9654;';
      dockPlay.setAttribute('aria-label', STATE.isPlaying ? 'Pause' : 'Play');
    }}
    updatePlayButtons();
  }}

  function setDockVisible(visible) {{
    if (!dock) return;
    dock.hidden = !visible;
  }}

  function setJourneyOpen(open) {{
    STATE.journeyOpen = !!open;
    if (journeyBody) journeyBody.hidden = !STATE.journeyOpen;
    if (journeyToggleBtn) {{
      journeyToggleBtn.textContent = STATE.journeyOpen ? 'Hide Journey Lens' : 'Show Journey Lens';
      journeyToggleBtn.setAttribute('aria-expanded', STATE.journeyOpen ? 'true' : 'false');
    }}
    if (!STATE.journeyOpen) hideJourneyTooltip();
  }}

  function hasEmbeddedController() {{
    return (PLAYER_PLATFORM === 'youtube' && !!PLAYER_EMBED_ID) || (PLAYER_PLATFORM === 'soundcloud' && !!PLAYER_SOURCE_URL);
  }}

  function startFallbackTick() {{
    if (fallbackTick || hasEmbeddedController()) return;
    fallbackTick = setInterval(() => {{
      if (!STATE.isPlaying) return;
      const duration = SET_DATA.duration || 0;
      const next = Math.min(duration, (STATE.currentTime || 0) + 1);
      updateFromTime(next, false);
      if (next >= duration) {{
        setPlaying(false);
        stopFallbackTick();
      }}
    }}, 1000);
  }}

  function stopFallbackTick() {{
    if (!fallbackTick) return;
    clearInterval(fallbackTick);
    fallbackTick = null;
  }}

  function updateFromPolledTime(seconds) {{
    const duration = Math.max(0, SET_DATA.duration || 0);
    const safe = Math.max(0, Math.min(duration, seconds || 0));
    STATE.currentTime = safe;
    updateProgress();
    if (Date.now() < seekLockUntil) return;
    const tr = findTrackByTime(safe);
    if (!tr) return;
    if (String(tr.idx) !== String(STATE.activeIdx || '')) {{
      setActiveTrack(tr.idx, false);
    }}
  }}

  function pollPlayerTime() {{
    if (!hasEmbeddedController() || !playerReady) return;
    if (PLAYER_PLATFORM === 'youtube' && ytPlayer && ytPlayer.getCurrentTime) {{
      const current = ytPlayer.getCurrentTime();
      if (Number.isFinite(current)) updateFromPolledTime(current);
      return;
    }}
    if (PLAYER_PLATFORM === 'soundcloud' && scWidget && scWidget.getPosition) {{
      scWidget.getPosition(ms => {{
        const seconds = Number(ms) / 1000;
        if (Number.isFinite(seconds)) updateFromPolledTime(seconds);
      }});
    }}
  }}

  function startPlayerPoll() {{
    if (playerPoll) return;
    playerPoll = setInterval(() => {{
      if (!STATE.isPlaying) return;
      pollPlayerTime();
    }}, 1000);
    pollPlayerTime();
  }}

  function stopPlayerPoll() {{
    if (!playerPoll) return;
    clearInterval(playerPoll);
    playerPoll = null;
  }}

  function loadScript(src) {{
    return new Promise((resolve, reject) => {{
      const existing = document.querySelector(`script[src="${{src}}"]`);
      if (existing) {{
        if (existing.dataset.loaded === '1') {{
          resolve();
          return;
        }}
        existing.addEventListener('load', () => resolve(), {{ once: true }});
        existing.addEventListener('error', () => reject(new Error(`Failed to load ${{src}}`)), {{ once: true }});
        return;
      }}
      const script = document.createElement('script');
      script.src = src;
      script.async = true;
      script.addEventListener('load', () => {{
        script.dataset.loaded = '1';
        resolve();
      }}, {{ once: true }});
      script.addEventListener('error', () => reject(new Error(`Failed to load ${{src}}`)), {{ once: true }});
      document.head.appendChild(script);
    }});
  }}

  function flushPendingSeek() {{
    if (pendingSeek === null) return;
    const target = pendingSeek;
    const autoplay = pendingAutoplay;
    pendingSeek = null;
    pendingAutoplay = false;
    seekPlayer(target, false, autoplay);
  }}

  function buildSourceLinkAt(seconds) {{
    const safe = Math.max(0, Math.floor(seconds || 0));
    if (PLAYER_PLATFORM === 'youtube') {{
      if (PLAYER_EMBED_ID) return `https://www.youtube.com/watch?v=${{encodeURIComponent(PLAYER_EMBED_ID)}}&t=${{safe}}s`;
      if (!PLAYER_SOURCE_URL) return '';
      try {{
        const url = new URL(PLAYER_SOURCE_URL);
        url.searchParams.set('t', `${{safe}}s`);
        return url.toString();
      }} catch (_err) {{
        return PLAYER_SOURCE_URL;
      }}
    }}
    return PLAYER_SOURCE_URL || '';
  }}

  function openSourceAt(seconds) {{
    const link = buildSourceLinkAt(seconds);
    if (!link) return;
    window.open(link, '_blank', 'noopener');
  }}

  function showYouTubeBlockedFallback() {{
    if (!sourcePlayerFrame) return;
    ytEmbedBlocked = true;
    document.body.classList.add('yt-embed-blocked');
    sourcePlayerFrame.classList.remove('is-youtube');
    sourcePlayerFrame.classList.add('is-youtube-error');
    sourcePlayerFrame.innerHTML = '<div class="source-player-error-note">Embedded player is prevented by the video uploader.</div>';
    setPlaying(false);
    setDockVisible(false);
    stopPlayerPoll();
    pendingSeek = null;
    pendingAutoplay = false;
  }}

  function showSoundCloudBlockedFallback() {{
    if (!sourcePlayerFrame) return;
    scEmbedBlocked = true;
    sourcePlayerFrame.classList.remove('is-soundcloud');
    sourcePlayerFrame.classList.add('is-embed-error');
    sourcePlayerFrame.innerHTML = '<div class="source-player-error-note">SoundCloud embedded player requires validation in this browser. Use Open Source to continue.</div>';
    setPlaying(false);
    setDockVisible(false);
    stopPlayerPoll();
    pendingSeek = null;
    pendingAutoplay = false;
  }}

  function initYouTubePlayer() {{
    const target = document.getElementById('ytSourcePlayer');
    if (!target || !PLAYER_EMBED_ID) return;
    loadScript('https://www.youtube.com/iframe_api').then(() => {{
      const boot = () => {{
        if (!window.YT || !window.YT.Player) return;
        ytPlayer = new window.YT.Player('ytSourcePlayer', {{
          events: {{
            onReady: () => {{
              playerReady = true;
              flushPendingSeek();
            }},
            onStateChange: (event) => {{
              const state = event?.data;
              const playing = state === window.YT.PlayerState.PLAYING;
              if (playing) {{
                setPlaying(true);
                startPlayerPoll();
                pollPlayerTime();
                return;
              }}
              const paused = state === window.YT.PlayerState.PAUSED || state === window.YT.PlayerState.ENDED || state === window.YT.PlayerState.CUED;
              if (paused) {{
                setPlaying(false);
                stopPlayerPoll();
                pollPlayerTime();
              }}
            }},
            onError: () => {{
              playerReady = false;
              stopPlayerPoll();
              showYouTubeBlockedFallback();
            }},
          }},
        }});
      }};
      if (window.YT && window.YT.Player) {{
        boot();
        return;
      }}
      const prevReady = window.onYouTubeIframeAPIReady;
      window.onYouTubeIframeAPIReady = () => {{
        if (typeof prevReady === 'function') prevReady();
        boot();
      }};
    }}).catch(() => {{
      playerReady = false;
      showYouTubeBlockedFallback();
    }});
  }}

  function initSoundCloudPlayer() {{
    const target = document.getElementById('scSourceWidget');
    if (!target || !PLAYER_SOURCE_URL) return;
    let readyTimeout = null;
    loadScript('https://w.soundcloud.com/player/api.js').then(() => {{
      if (!window.SC || !window.SC.Widget) {{
        showSoundCloudBlockedFallback();
        return;
      }}
      scWidget = window.SC.Widget(target);
      readyTimeout = setTimeout(() => {{
        if (!playerReady) showSoundCloudBlockedFallback();
      }}, 9000);
      scWidget.bind(window.SC.Widget.Events.READY, () => {{
        if (readyTimeout) {{
          clearTimeout(readyTimeout);
          readyTimeout = null;
        }}
        playerReady = true;
        flushPendingSeek();
      }});
      scWidget.bind(window.SC.Widget.Events.PLAY, () => {{
        setPlaying(true);
        startPlayerPoll();
      }});
      scWidget.bind(window.SC.Widget.Events.PAUSE, () => {{
        setPlaying(false);
        stopPlayerPoll();
        pollPlayerTime();
      }});
      scWidget.bind(window.SC.Widget.Events.FINISH, () => {{
        setPlaying(false);
        stopPlayerPoll();
        pollPlayerTime();
      }});
    }}).catch(() => {{
      playerReady = false;
      showSoundCloudBlockedFallback();
    }});
  }}

  function initEmbeddedPlayer() {{
    if (!hasEmbeddedController()) {{
      setDockVisible(false);
      playerReady = false;
      return;
    }}
    setDockVisible(true);
    if (PLAYER_PLATFORM === 'youtube') {{
      initYouTubePlayer();
      return;
    }}
    if (PLAYER_PLATFORM === 'soundcloud') {{
      initSoundCloudPlayer();
      return;
    }}
    playerReady = false;
  }}

  function seekPlayer(seconds, scroll = false, autoplay = true) {{
    const safe = Math.max(0, Math.min(SET_DATA.duration || 0, seconds || 0));
    updateFromTime(safe, scroll);
    seekLockUntil = Date.now() + 1500;

    if (PLAYER_PLATFORM === 'youtube' && PLAYER_EMBED_ID) {{
      if (ytEmbedBlocked) {{
        setPlaying(false);
        return;
      }}
      if (ytPlayer && playerReady && ytPlayer.seekTo) {{
        ytPlayer.seekTo(safe, true);
        if (autoplay && ytPlayer.playVideo) ytPlayer.playVideo();
        if (!autoplay && ytPlayer.pauseVideo) ytPlayer.pauseVideo();
      }} else {{
        pendingSeek = safe;
        pendingAutoplay = !!autoplay;
      }}
      if (autoplay) setPlaying(true);
      return;
    }}

    if (PLAYER_PLATFORM === 'soundcloud' && PLAYER_SOURCE_URL) {{
      if (scEmbedBlocked) {{
        setPlaying(false);
        return;
      }}
      if (scWidget && playerReady && scWidget.seekTo) {{
        scWidget.seekTo(safe * 1000);
        if (autoplay && scWidget.play) scWidget.play();
        if (!autoplay && scWidget.pause) scWidget.pause();
      }} else {{
        pendingSeek = safe;
        pendingAutoplay = !!autoplay;
      }}
      if (autoplay) setPlaying(true);
      return;
    }}

    if (autoplay) {{
      setPlaying(true);
      startFallbackTick();
    }} else {{
      setPlaying(false);
      stopFallbackTick();
    }}
  }}

  function playPlayer() {{
    if (PLAYER_PLATFORM === 'youtube' && PLAYER_EMBED_ID) {{
      if (ytEmbedBlocked) {{
        setPlaying(false);
        return;
      }}
      if (ytPlayer && playerReady && ytPlayer.playVideo) ytPlayer.playVideo();
      else pendingAutoplay = true;
      setPlaying(true);
      return;
    }}
    if (PLAYER_PLATFORM === 'soundcloud' && PLAYER_SOURCE_URL) {{
      if (scEmbedBlocked) {{
        setPlaying(false);
        return;
      }}
      if (scWidget && playerReady && scWidget.play) scWidget.play();
      else pendingAutoplay = true;
      setPlaying(true);
      return;
    }}
    setPlaying(true);
    startFallbackTick();
  }}

  function pausePlayer() {{
    if (PLAYER_PLATFORM === 'youtube' && ytPlayer && playerReady && ytPlayer.pauseVideo) {{
      ytPlayer.pauseVideo();
      return;
    }}
    if (PLAYER_PLATFORM === 'soundcloud' && scWidget && playerReady && scWidget.pause) {{
      scWidget.pause();
      return;
    }}
    setPlaying(false);
    stopFallbackTick();
  }}

  function jumpTo(seconds, scroll = false, autoplay = true) {{
    seekPlayer(seconds, scroll, autoplay);
  }}

  function togglePlay() {{
    if (STATE.isPlaying) {{
      pausePlayer();
      return;
    }}
    if ((SET_DATA.duration || 0) > 0 && STATE.currentTime >= (SET_DATA.duration || 0)) {{
      seekPlayer(0, false, true);
      return;
    }}
    playPlayer();
  }}

  function nextTrack() {{
    const sorted = [...SET_DATA.tracks].sort((a, b) => a.start - b.start);
    const next = sorted.find(t => t.start > (STATE.currentTime || 0) + 1);
    if (next) {{
      jumpTo(next.start, false, true);
    }}
  }}

  function prevTrack() {{
    const sorted = [...SET_DATA.tracks].sort((a, b) => a.start - b.start);
    const now = Date.now();
    const current = [...sorted].reverse().find(t => t.start <= (STATE.currentTime || 0));
    if (current && now - prevTrackPressTs < 2000) {{
      const prev = [...sorted].reverse().find(t => t.start < current.start);
      if (prev) jumpTo(prev.start, false, true);
    }} else if (current) {{
      jumpTo(current.start, false, true);
    }} else {{
      jumpTo(0, false, true);
    }}
    prevTrackPressTs = now;
  }}

  document.getElementById('dockPlay')?.addEventListener('click', togglePlay);
  document.getElementById('dockPrev')?.addEventListener('click', prevTrack);
  document.getElementById('dockNext')?.addEventListener('click', nextTrack);
  document.getElementById('dockBack')?.addEventListener('click', () => jumpTo((STATE.currentTime || 0) - 15, false, true));
  document.getElementById('dockFwd')?.addEventListener('click', () => jumpTo((STATE.currentTime || 0) + 15, false, true));
  document.getElementById('dockToTrack')?.addEventListener('click', () => {{
    if (!STATE.activeIdx) return;
    const card = document.querySelector(`.track-card[data-track-idx="${{STATE.activeIdx}}"]`);
    if (card) card.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
  }});

  dockProgress?.addEventListener('click', e => {{
    const rect = dockProgress.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    jumpTo(frac * (SET_DATA.duration || 0), false, true);
  }});

  window.addEventListener('resize', () => {{
    if (setHeroResizeTimer) clearTimeout(setHeroResizeTimer);
    setHeroResizeTimer = setTimeout(() => {{
      fitHeroTitle();
      startSetHeroRail();
    }}, 120);
  }});

  document.addEventListener('visibilitychange', () => {{
    if (document.hidden) stopSetHeroRail();
    else startSetHeroRail();
  }});

  window.jumpTo = jumpTo;

  // Hash deep-link support
  function handleHash() {{
    const hash = window.location.hash || '';
    if (!hash.startsWith('#track-')) return;
    const card = document.querySelector(hash);
    if (!card) return;
    const idx = card.getAttribute('data-track-idx');
    if (idx) {{
      const tr = byIdx.get(String(idx));
      if (tr) updateFromTime(tr.start || 0, false);
      else setActiveTrack(idx);
    }}
    setTimeout(() => {{
      card.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
      card.classList.add('hash-hit');
      setTimeout(() => card.classList.remove('hash-hit'), 1800);
    }}, 120);
  }}

  applyFilters();
  renderJourney();
  setJourneyOpen(false);
  updateFromTime(0, false);
  setPlaying(false);
  initEmbeddedPlayer();
  fitHeroTitle();
  startSetHeroRail();
  handleHash();
}})();
  </script>
</body>
</html>
"""

    output_path.write_text(html, encoding="utf-8")
    print(f"Saved set explorer HTML: {output_path}")
    return output_path
