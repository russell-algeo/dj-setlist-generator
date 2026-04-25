"""Independent artist-level explorer renderer."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re
from urllib.parse import quote

from detail_explorer_common import (
    CONFIDENCE_COLORS,
    CONFIDENCE_LEVELS,
    MASTER_DETAIL_BASE_CSS,
    discogs_search_url,
    esc,
    is_valid_artist_image_url as _is_valid_artist_image_url,
    normalize_confidence as _normalize_confidence,
    normalize_name as _normalize_name,
    normalize_track_key,
    primary_confidence as _primary_confidence,
    select_artist_hero_image,
    spotify_search_url,
    spotify_track_id,
    to_json,
    youtube_search_url,
)


def _fmt_duration(seconds: int) -> str:
    seconds = max(0, int(seconds or 0))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


_EXTERNAL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
_FRAGMENT_ID_RE = re.compile(r"^[A-Za-z][\w:-]*$")


def _encode_local_href(href: str | None) -> str:
    raw = str(href or "").strip()
    if not raw:
        return ""
    if _EXTERNAL_SCHEME_RE.match(raw) or raw.startswith("//"):
        return raw

    base = raw
    fragment = ""
    hash_index = raw.rfind("#")
    if hash_index >= 0:
        tail = raw[hash_index + 1 :]
        if _FRAGMENT_ID_RE.fullmatch(tail):
            base = raw[:hash_index]
            fragment = f"#{tail}"

    return quote(base, safe="/%") + fragment


def _artist_css() -> str:
    return (
        MASTER_DETAIL_BASE_CSS
        + """
body.artist-page {
  min-height: 100vh;
}

body.artist-page::before {
  content: '';
  position: fixed;
  inset: 0;
  background-image:
    linear-gradient(180deg, rgba(8, 8, 8, 0.8) 0%, rgba(8, 8, 8, 0.92) 40%, rgba(8, 8, 8, 0.98) 100%),
    var(--artist-page-bg-image, none);
  background-size: cover;
  background-position: center 22%;
  background-repeat: no-repeat;
  filter: grayscale(24%) saturate(0.92);
  z-index: -2;
  pointer-events: none;
}

body.artist-page::after {
  content: '';
  position: fixed;
  inset: 0;
  background: radial-gradient(70% 50% at 50% 0%, rgba(216, 255, 90, 0.05), transparent 68%);
  z-index: -1;
  pointer-events: none;
}

.artist-shell {
  padding-top: 12px;
  position: relative;
  z-index: 0;
}

.topbar {
  z-index: 40;
  background: rgba(10, 10, 10, 0.96);
  border-bottom: 1px solid var(--line-soft);
  backdrop-filter: blur(8px);
}

.topbar-inner {
  max-width: 1480px;
  gap: 16px;
  padding: 14px var(--section-pad);
}

.brand {
  font-size: 11px;
  letter-spacing: 0.12em;
  color: #d8d8d8;
}

.topnav {
  gap: 16px;
  font-family: 'Space Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.topnav a {
  border: 0;
  background: transparent;
  color: #cfcfcf;
  padding: 0 0 2px;
  border-bottom: 1px solid transparent;
}

.topnav a:hover,
.topnav a:focus-visible {
  color: #fff;
  border-color: var(--lime);
}

.artist-hero {
  margin-top: 10px;
  display: grid;
  grid-template-columns: 1.8fr 1fr;
  gap: 12px;
  align-items: start;
}

.artist-hero-main {
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  min-height: 0;
}

.artist-hero-visual {
  height: clamp(500px, 58vh, 680px);
  min-height: 0;
  position: relative;
  border: 1px solid var(--line);
  background: #0d0d0d;
  overflow: hidden;
}

.artist-hero-visual::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.62) 0%, rgba(0, 0, 0, 0.16) 52%, rgba(0, 0, 0, 0.05) 100%);
  pointer-events: none;
  z-index: 1;
}

.artist-hero-visual img,
.artist-hero-image-fallback {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.artist-hero-visual img {
  filter: grayscale(20%);
}

.artist-hero-image-fallback {
  background: linear-gradient(140deg, #111 0%, #1d1d1d 55%, #121212 100%);
}

.artist-hero-title {
  position: absolute;
  left: clamp(14px, 3vw, 36px);
  bottom: clamp(14px, 3vw, 34px);
  margin: 0;
  max-width: calc(100% - clamp(22px, 4vw, 68px));
  font-size: var(--artist-hero-title-fit-size, clamp(52px, 11.8vw, 170px));
  line-height: 0.86;
  text-transform: uppercase;
  letter-spacing: -0.05em;
  color: #fff;
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.52);
  font-weight: 800;
  z-index: 3;
  pointer-events: none;
  word-break: normal;
  overflow-wrap: normal;
}

.artist-hero-title span {
  display: block;
  white-space: nowrap;
}

.artist-hero-stats {
  margin-top: 8px;
}

.artist-hero-side {
  position: relative;
  border: 1px solid var(--line);
  background: #0f0f0f;
  min-height: 0;
  height: clamp(500px, 38vw, 640px);
  overflow: hidden;
}

.artist-hero-side::before,
.artist-hero-side::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  height: 44px;
  pointer-events: none;
  z-index: 6;
}

.artist-hero-side::before {
  top: 0;
  background: linear-gradient(to bottom, rgba(12, 12, 12, 0.86), rgba(12, 12, 12, 0));
}

.artist-hero-side::after {
  bottom: 0;
  background: linear-gradient(to top, rgba(12, 12, 12, 0.9), rgba(12, 12, 12, 0));
}

.artist-hero-side-viewport {
  height: 100%;
  overflow: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
  position: relative;
  z-index: 2;
}

.artist-hero-side-viewport::-webkit-scrollbar {
  display: none;
}

.artist-hero-side-track {
  display: grid;
  gap: 10px;
  padding: 10px;
}

.artist-hero-card {
  border: 1px solid var(--line);
  background: #0f0f0f;
  min-height: 180px;
  display: block;
  color: inherit;
  text-decoration: none;
  position: relative;
  overflow: hidden;
  transition: transform 0.25s ease, border-color 0.25s ease, box-shadow 0.25s ease;
}

.artist-hero-card img,
.artist-hero-card-fallback {
  width: 100%;
  height: 100%;
  object-fit: cover;
  filter: grayscale(18%);
  display: block;
}

.artist-hero-card-fallback {
  background: linear-gradient(140deg, #141414 0%, #1f1f1f 55%, #121212 100%);
}

.artist-hero-card:hover {
  border-color: #f0f0f0;
  transform: translateY(-2px);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.38);
}

.artist-hero-card-meta {
  position: absolute;
  left: 10px;
  right: 10px;
  bottom: 10px;
  border: 1px solid #2f2f2f;
  background: rgba(0, 0, 0, 0.76);
  color: #f3f3f3;
  padding: 7px 8px;
  display: grid;
  gap: 4px;
  backdrop-filter: blur(1.6px);
}

.artist-hero-card-match {
  margin: 0;
  font-family: 'Space Mono', monospace;
  font-size: 9px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #d8ff5a;
}

.artist-hero-card-title {
  margin: 0;
  font-size: 12px;
  line-height: 1.25;
  color: #f5f5f5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
}

.artist-hero-card-sub {
  margin: 0;
  font-family: 'Space Mono', monospace;
  font-size: 9px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #d0d0d0;
}

.artist-hero-empty {
  position: absolute;
  left: 12px;
  bottom: 12px;
  border: 1px solid #313131;
  background: rgba(0, 0, 0, 0.72);
  padding: 6px 8px;
  color: #ececec;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.overview-grid {
  margin-top: 16px;
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.overview-card {
  border: 1px solid var(--line);
  background: #0f0f0f;
  padding: 12px;
}

.overview-card h3 {
  margin: 0 0 8px;
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.chip-cloud {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.chip {
  border: 1px solid var(--line);
  background: #171717;
  border-radius: 999px;
  padding: 4px 9px;
  font-size: 11px;
  font-family: 'Space Mono', monospace;
  color: var(--muted);
}

.chip.lime {
  border-color: var(--lime);
  color: var(--lime);
}

/* Recurring cards (index-like language) */
#recurring-section .section-head h2.recurring-heading {
  white-space: nowrap;
  font-size: clamp(24px, 9vw, 82px);
  letter-spacing: -0.03em;
}

.recurring-controls {
  margin-top: 12px;
  display: grid;
  gap: 8px;
}

.recurring-grid {
  margin-top: 12px;
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: calc((100% - 24px) / 5);
  overflow-x: auto;
  overflow-y: visible;
  padding-bottom: 6px;
  gap: 6px;
}

.recurring-grid .track-body {
  padding: 6px;
  gap: 5px;
}

.recurring-grid .track-title {
  font-size: 12px;
  line-height: 1.2;
}

.recurring-grid .actions {
  gap: 4px;
}

.recurring-grid .actions a,
.recurring-grid .actions button {
  font-size: 9px;
  padding: 3px 5px;
}

.track-card {
  border: 1px solid var(--line);
  background: #0f0f0f;
  overflow: hidden;
}

.track-art {
  aspect-ratio: 1 / 1;
  border-bottom: 1px solid var(--line);
  background: #141414;
  position: relative;
  overflow: hidden;
}

.track-art img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  filter: grayscale(18%);
}

.track-body {
  padding: 10px;
  display: grid;
  gap: 8px;
  position: relative;
}

.track-title {
  margin: 0;
  font-size: 16px;
  line-height: 1.25;
  color: #fff;
}

.muted {
  margin: 0;
  color: #bdbdbd;
  font-size: 12px;
  line-height: 1.45;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.actions a,
.actions button {
  border: 1px solid var(--line);
  background: #171717;
  color: #f0f0f0;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 5px 8px;
  cursor: pointer;
  text-decoration: none;
}

.actions a:hover,
.actions button:hover { border-color: #fff; }

.actions .spotify {
  border-color: #1db954;
  color: #1db954;
}

.source-panel {
  border-top: 1px solid var(--line);
  margin-top: 8px;
  padding-top: 8px;
  display: none;
  gap: 8px;
}

.source-panel.open { display: grid; }

.source-group {
  border: 1px solid var(--line);
  background: #151515;
  padding: 8px;
  display: grid;
  gap: 6px;
}

.source-group h5 {
  margin: 0;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: #d8d8d8;
  font-family: 'Space Mono', monospace;
}

.source-group h5 a {
  color: inherit;
  text-decoration: underline;
  text-decoration-color: #343434;
  text-underline-offset: 2px;
}

.source-list {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 4px;
}

.source-list li {
  color: #d8d8d8;
  font-size: 12px;
  line-height: 1.35;
}

.source-list li::marker {
  color: var(--lime);
}

.source-list a {
  color: #efefef;
  text-decoration: underline;
  text-decoration-color: #343434;
  text-underline-offset: 2px;
}

.spotify-embed {
  margin-top: 8px;
  border-top: 1px solid var(--line);
  padding-top: 8px;
}

/* Set Atlas (master artist-atlas language) */
.atlas-layout {
  margin-top: 12px;
  display: grid;
  grid-template-columns: minmax(240px, 0.55fr) minmax(620px, 1.45fr);
  gap: 12px;
  align-items: start;
  height: auto;
  width: 100%;
  max-width: 100%;
  margin-left: auto;
  margin-right: auto;
}

.artist-stack {
  border: 1px solid var(--line);
  background: #101010;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
  height: auto;
  max-height: none;
  align-self: start;
  overflow: hidden;
}

.artist-grid {
  --artist-card-height: 160px;
  --artist-card-overlap: 114px;
  --artist-card-step: calc(var(--artist-card-height) - var(--artist-card-overlap));
  --artist-cards-visible: 10;
  display: flex;
  flex-direction: column;
  flex: 0 0 auto;
  min-height: 0;
  height: calc(var(--artist-card-height) + (var(--artist-cards-visible) - 1) * var(--artist-card-step));
  max-height: calc(var(--artist-card-height) + (var(--artist-cards-visible) - 1) * var(--artist-card-step));
  overflow: auto;
  overscroll-behavior: contain;
  padding: 2px 10px 80px 2px;
  scroll-snap-type: y proximity;
}

/* Set-atlas stack cards need more reveal depth than artist cards so titles stay readable. */
.atlas-set-grid {
  --artist-card-overlap: 84px;
  --artist-cards-visible: 7;
}

.artist-card {
  border: 1px solid var(--line);
  background: #0f0f0f;
  height: var(--artist-card-height);
  margin-top: calc(-1 * var(--artist-card-overlap));
  flex: 0 0 auto;
  overflow: hidden;
  position: relative;
  cursor: pointer;
  transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
  will-change: transform;
  scroll-snap-align: start;
}

.artist-card:first-child {
  margin-top: 0;
}

.artist-card,
.artist-grid:hover .artist-card,
.artist-card:hover,
.artist-card.hover-latched {
  opacity: 1 !important;
}

.artist-card:hover,
.artist-card.hover-latched {
  transform: translateY(12px);
  border-color: #fff;
  z-index: 400 !important;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
}

.artist-card.focus {
  border-color: var(--lime);
  outline: 2px solid var(--lime);
  outline-offset: -2px;
}

.artist-card.selected {
  border-color: var(--lime);
  box-shadow: inset 0 0 0 1px var(--lime);
}

@media (hover: hover) and (pointer: fine) {
  .artist-grid.selected-dock .artist-card.selected {
    transform: none;
    box-shadow: inset 0 0 0 1px var(--lime);
  }
}

.set-card-fallback {
  width: 100%;
  height: 100%;
  background: linear-gradient(140deg, #121212 0%, #1f1f1f 55%, #151515 100%);
}

.artist-card img,
.set-card-fallback {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  filter: grayscale(14%);
}

.artist-detail {
  position: absolute;
  left: 8px;
  right: 8px;
  bottom: 8px;
  background: rgba(38, 38, 38, 0.82);
  border: 1px solid #585858;
  padding: 8px;
  display: grid;
  gap: 4px;
  opacity: 1;
  transform: none;
  transition: border-color 0.2s ease, background 0.2s ease;
  pointer-events: auto;
  backdrop-filter: blur(1.4px);
}

.artist-card:hover .artist-detail,
.artist-card.hover-latched .artist-detail {
  border-color: #d0d0d0;
  background: rgba(46, 46, 46, 0.86);
}

.artist-card.focus .artist-detail {
  border-color: var(--lime);
}

.artist-card.selected .artist-detail {
  border-color: var(--lime);
}

.artist-detail h3 {
  margin: 0;
  font-size: 20px;
  line-height: 0.92;
  letter-spacing: -0.02em;
  text-transform: uppercase;
  color: #fff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.artist-detail p {
  margin: 0;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #d3d3d3;
  white-space: nowrap;
}

.artist-meta-row {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 6px;
  min-width: 0;
}

.artist-card .card-actions {
  display: flex;
  justify-content: flex-start;
  gap: 4px;
  flex: 0 0 auto;
  flex-wrap: nowrap;
}

.artist-card .card-actions .chip-btn {
  white-space: nowrap;
  font-size: 9px;
  padding: 3px 6px;
}

.artist-card .card-actions .chip-btn.active {
  border-color: var(--line);
  color: #f1f1f1;
}

/* Tighten set-card detail density so collapsed rows still show title text. */
.atlas-set-card .artist-detail {
  left: 6px;
  right: 6px;
  bottom: 6px;
  padding: 6px;
  gap: 3px;
}

.atlas-set-card .artist-detail h3 {
  font-size: 14px;
  line-height: 1.05;
  letter-spacing: -0.01em;
}

.atlas-set-card .artist-detail p {
  font-size: 9px;
}

.atlas-set-card .card-actions .chip-btn {
  font-size: 8px;
  padding: 2px 4px;
}

.chip-btn {
  border: 1px solid var(--line);
  background: #171717;
  color: #f1f1f1;
  border-radius: 0;
  font-size: 10px;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  padding: 5px 8px;
  font-family: 'Space Mono', monospace;
  cursor: pointer;
}

.chip-btn:hover { border-color: #fff; }
.chip-btn.active { border-color: var(--violet); color: var(--violet); }
.chip-btn.lime { border-color: var(--lime); color: var(--lime); }

.atlas-panel {
  border: 1px solid var(--line);
  background: #0f0f0f;
  padding: 12px;
  display: grid;
  gap: 10px;
  align-content: start;
  min-height: 0;
  height: auto;
  overflow: visible;
}

.focus-header {
  border: 1px solid var(--line);
  background: #101010;
  padding: 10px;
  display: grid;
  gap: 8px;
}

.focus-names {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: flex-end;
}

.focus-names.single {
  display: block;
  min-width: 0;
}

.focus-names.single .focus-name {
  display: grid;
  grid-template-rows: auto auto;
  align-content: start;
  row-gap: 0;
  min-width: 0;
  width: 100%;
  margin: 0;
  font-size: clamp(22px, 3.2vw, 46px);
  line-height: 0.9;
  letter-spacing: -0.03em;
  text-transform: uppercase;
  color: #fff;
  border: none;
  background: transparent;
  padding: 0;
}

.focus-names.single .focus-name .focus-line {
  display: block;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.focus-names.single.focus-title-lg .focus-name {
  font-size: clamp(28px, 4.1vw, 56px);
}

.focus-names.single.focus-title-md .focus-name {
  font-size: clamp(24px, 3.5vw, 48px);
}

.focus-names.single.focus-title-sm .focus-name {
  font-size: clamp(20px, 3vw, 40px);
}

.focus-names.single.focus-title-xs .focus-name {
  font-size: clamp(17px, 2.4vw, 32px);
}

.focus-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.focus-mode {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.focus-summary {
  margin: 0;
  font-size: 12px;
  color: #bbbbbb;
  line-height: 1.45;
}

.focus-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.focus-tile {
  border: 1px solid var(--line);
  background: #0f0f0f;
  padding: 8px;
}

.focus-tile p {
  margin: 0 0 6px;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: #bdbdbd;
}

.focus-tile h4 {
  margin: 0;
  font-size: 18px;
  line-height: 1;
  letter-spacing: -0.02em;
}

.taxonomy-panel,
.evidence-panel {
  border: 1px solid var(--line);
  background: #101010;
  padding: 10px;
}

.taxonomy-workbench {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
  align-items: start;
}

.evidence-panel {
  display: none;
}

.evidence-panel.open {
  display: block;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.panel-title {
  margin: 0;
  font-size: 18px;
  text-transform: uppercase;
  letter-spacing: -0.01em;
}

.panel-copy {
  margin: 0;
  font-size: 12px;
  color: #bababa;
  line-height: 1.45;
}

.lens-tabs,
.pill-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.taxonomy-controls-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: nowrap;
  overflow-x: auto;
  overflow-y: hidden;
  margin-top: 6px;
  padding-bottom: 4px;
  margin-bottom: 6px;
  border-bottom: 1px solid #2a2a2a;
}

.taxonomy-head {
  flex-wrap: nowrap;
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 2px;
}

.taxonomy-head .panel-title {
  flex: 0 0 auto;
}

.taxonomy-head .lens-tabs {
  flex: 1 1 auto;
  flex-wrap: nowrap;
  justify-content: flex-end;
}

.taxonomy-head .chip-btn {
  white-space: nowrap;
  flex: 0 0 auto;
}

.taxonomy-controls-bar .pill-row {
  flex-wrap: nowrap;
  flex: 0 0 auto;
  gap: 4px;
}

.taxonomy-controls-bar .chip-btn {
  white-space: nowrap;
  flex: 0 0 auto;
  padding: 3px 6px;
  font-size: 9px;
}

.threshold-stepper {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex: 0 0 auto;
}

.threshold-stepper .threshold-arrow {
  width: 20px;
  min-width: 20px;
  padding: 3px 0;
  text-align: center;
  line-height: 1;
  font-size: 10px;
}

.threshold-stepper .threshold-value {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 84px;
  border-color: #3a3a3a;
  color: #f0f0f0;
  pointer-events: none;
  cursor: default;
}

.threshold-stepper .threshold-arrow:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.taxonomy-controls-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: nowrap;
  margin-left: auto;
  flex: 0 0 auto;
  min-width: 0;
}

.taxonomy-search-control {
  flex: 0 0 clamp(170px, 24vw, 260px);
  min-width: 0;
}

.taxonomy-controls-row .control {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 0 0 clamp(120px, 16vw, 170px);
}

.taxonomy-controls-bar .control input,
.taxonomy-controls-bar .control select {
  height: 18px;
  min-height: 18px;
  padding: 0 6px;
  font-size: 10px;
  line-height: 18px;
}

.taxonomy-controls-row input,
.taxonomy-controls-row select {
  height: 18px;
  padding: 0 6px;
  font-size: 10px;
}

.taxonomy-sort-icon {
  color: #c6c6c6;
  font-family: 'Space Mono', monospace;
  font-size: 12px;
  line-height: 1;
  flex: 0 0 auto;
  user-select: none;
}

.control {
  display: grid;
  gap: 5px;
}

.control label {
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: #c3c3c3;
}

.control input,
.control select {
  border: 1px solid var(--line);
  background: #171717;
  color: #f0f0f0;
  height: 34px;
  padding: 6px 8px;
  font-size: 13px;
  border-radius: 0;
  width: 100%;
}

.control input:focus,
.control select:focus {
  outline: none;
  border-color: var(--lime);
}

.rows {
  display: grid;
  gap: 6px;
  max-height: none;
  overflow: visible;
  padding-right: 0;
}

.quant-row {
  border: 1px solid var(--line);
  background: #131313;
  padding: 5px 7px;
  display: grid;
  gap: 4px;
  cursor: default;
}

.quant-row:hover { border-color: #f0f0f0; }
.quant-row.active { border-color: var(--lime); }

.row-hit {
  border: 0;
  background: transparent;
  padding: 0;
  margin: 0;
  width: 100%;
  text-align: left;
  color: inherit;
  display: block;
  cursor: pointer;
  font: inherit;
}

.row-line {
  display: grid;
  grid-template-columns: clamp(120px, 16vw, 180px) minmax(0, 1fr) auto;
  align-items: center;
  gap: 6px;
}

.row-name {
  font-size: 13px;
  line-height: 1.1;
  color: #fff;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.row-count {
  font-family: 'Space Mono', monospace;
  font-size: 11px;
  color: #cfcfcf;
  letter-spacing: 0.05em;
}

.bar {
  height: 6px;
  border: 1px solid #2e2e2e;
  background: #0d0d0d;
  position: relative;
  overflow: hidden;
}

.bar > span {
  position: absolute;
  inset: 0 auto 0 0;
  background: var(--lime);
  width: 0;
}

.inline-evidence {
  margin-top: 8px;
  border-top: 1px solid #2f3b1a;
  padding-top: 8px;
  display: grid;
  gap: 8px;
  background: #0f1210;
  border: 1px solid #273122;
  padding: 8px;
}

.inline-evidence .evidence-grid {
  grid-auto-columns: calc((100% - 24px) / 5);
  gap: 6px;
}

.inline-evidence .track-body {
  padding: 6px;
  gap: 5px;
}

.inline-evidence .track-title {
  font-size: 12px;
  line-height: 1.2;
}

.inline-evidence .muted {
  font-size: 10px;
  line-height: 1.35;
}

.inline-evidence .chip {
  font-size: 9px;
  padding: 2px 4px;
}

.inline-evidence .actions {
  gap: 4px;
}

.inline-evidence .actions a,
.inline-evidence .actions button {
  font-size: 9px;
  padding: 3px 5px;
}

.inline-evidence .inline-head {
  margin: 0;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #bfc5b2;
}

.inline-evidence .inline-head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  flex-wrap: wrap;
}

.inline-evidence .inline-head-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.inline-evidence .inline-head-actions a {
  border: 1px solid var(--line);
  background: #171717;
  color: #f0f0f0;
  font-family: 'Space Mono', monospace;
  font-size: 9px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 3px 5px;
  text-decoration: none;
}

.inline-evidence .inline-head-actions a:hover {
  border-color: #fff;
}

.inline-evidence .inline-head-actions a.discogs {
  border-color: #7db8f2;
  color: #7db8f2;
}

.pager {
  margin-top: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.pager .info {
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  color: #bdbdbd;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.pager button {
  border: 1px solid var(--line);
  background: #171717;
  color: #ececec;
  height: 30px;
  padding: 0 10px;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  cursor: pointer;
}

.pager button:hover { border-color: #fff; }

.evidence-grid {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(260px, 330px);
  overflow-x: auto;
  overflow-y: visible;
  padding-bottom: 6px;
  gap: 10px;
}

.track-card .track-body .spotify-embed {
  display: none;
  margin: 0;
  height: 100%;
  position: relative;
  overflow: hidden;
}

.track-card.embed-open .track-body .spotify-embed {
  display: block;
  padding: 0;
  width: 100%;
  height: var(--open-embed-height, 91.2px);
  display: flex;
  align-items: flex-start;
}

.track-card.embed-open,
.track-card.sources-open {
  width: calc(200% + 10px);
  height: var(--open-card-height, auto);
  overflow: hidden;
  z-index: 40;
}

.track-card.embed-open .track-art,
.track-card.sources-open .track-art {
  aspect-ratio: auto;
  height: var(--open-art-height, 260px);
}

.track-card.embed-open .track-body {
  height: var(--open-body-height, auto);
  padding: 0;
  overflow: hidden;
  display: grid;
  grid-template-rows: auto var(--open-embed-height, 91.2px);
  gap: 0;
  align-content: start;
}

.track-card.sources-open .track-body {
  height: var(--open-body-height, auto);
  padding: 0;
  overflow: hidden;
  display: grid;
  grid-template-rows: auto var(--open-source-height, 91.2px);
  gap: 0;
  align-content: start;
}

.track-card.embed-open .track-body > .track-title,
.track-card.embed-open .track-body > .muted,
.track-card.embed-open .track-body > .source-panel {
  display: none;
}

.track-card.sources-open .track-body > .track-title,
.track-card.sources-open .track-body > .muted {
  display: none;
}

.track-card.embed-open .track-body > .actions,
.track-card.sources-open .track-body > .actions {
  margin: 0;
  padding: 6px 6px 4px;
  border-bottom: 1px solid var(--line);
  background: #0f0f0f;
  gap: 6px;
  flex-wrap: nowrap;
  overflow-x: auto;
  z-index: 3;
}

.track-card.sources-open .track-body .source-panel {
  display: none;
}

.track-card.sources-open .track-body .source-panel.open {
  display: grid;
  margin: 0;
  padding: 6px;
  border-top: 0;
  width: 100%;
  height: var(--open-source-height, 91.2px);
  overflow-y: auto;
  overflow-x: hidden;
  gap: 6px;
  align-content: start;
  box-sizing: border-box;
}

.evidence-grid .track-card.embed-open:nth-child(even),
.evidence-grid .track-card.sources-open:nth-child(even) {
  margin-left: calc(-100% - 10px);
}

.track-card.embed-open .track-body .spotify-embed iframe {
  width: 100%;
  height: var(--open-embed-height, 91.2px);
  display: block;
  margin: 0;
  border-radius: 0;
}

/* Set explorer */
.set-panel {
  border: 1px solid var(--line);
  background: #101010;
  padding: 10px;
}

.controls-grid {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.controls-grid .control {
  min-width: 0;
}

.set-controls-inline {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: nowrap;
}

.set-controls-inline .control {
  display: flex;
  align-items: center;
  min-width: 0;
}

.set-controls-inline .control label {
  display: none;
}

.set-controls-inline .control:first-child {
  flex: 1 1 auto;
}

.set-controls-inline .control:last-child {
  flex: 0 0 clamp(118px, 13vw, 156px);
}

.set-controls-inline .control input,
.set-controls-inline .control select {
  height: 30px;
  min-height: 30px;
  padding: 4px 8px;
  font-size: 12px;
}

.set-grid {
  margin-top: 12px;
  column-count: 4;
  column-gap: 10px;
}

.set-card {
  border: 1px solid var(--line);
  background: #0f0f0f;
  display: inline-block;
  width: 100%;
  margin: 0 0 10px;
  break-inside: avoid;
  vertical-align: top;
  position: relative;
  overflow: visible;
}

.set-card.selected {
  border-color: var(--lime);
  background: #0f1210;
}

.set-thumb {
  aspect-ratio: 16 / 9;
  width: 100%;
  position: relative;
  overflow: hidden;
  border-bottom: 1px solid var(--line);
  background: #0b0b0b;
}

.set-thumb.empty {
  display: grid;
  place-items: center;
  color: #707070;
  font-family: 'Space Mono', monospace;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
}

.set-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center;
  display: block;
  filter: grayscale(18%);
}

.set-thumb a {
  display: block;
  width: 100%;
  height: 100%;
}

.set-body {
  padding: 10px;
  display: grid;
  gap: 8px;
}

.set-title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  line-height: 1.25;
}

.set-title a {
  color: inherit;
  text-decoration: none;
  border-bottom: 1px solid transparent;
}

.set-title a:hover {
  border-color: var(--lime);
}

.set-mini {
  border: 1px solid var(--line);
  background: #0a0a0a;
  height: 14px;
  position: relative;
  overflow: hidden;
}

.set-mini-seg {
  position: absolute;
  top: 0;
  height: 100%;
  border-right: 1px solid rgba(10, 10, 10, 0.9);
}

.set-mini-seg.high { background: #6fffa4; }
.set-mini-seg.medium { background: #ffd166; }
.set-mini-seg.low { background: #ffa55a; }
.set-mini-seg.uncertain { background: #7b7b7b; }

.set-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.set-pill {
  border: 1px solid #2c2c2c;
  background: #171717;
  color: #dcdcdc;
  font-size: 10px;
  font-family: 'Space Mono', monospace;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 4px 6px;
}

.set-tracklist {
  position: absolute;
  left: 0;
  width: 100%;
  top: 100%;
  border: 1px solid var(--line);
  background: #101010;
  box-shadow: 0 18px 36px rgba(0, 0, 0, 0.45);
  padding: 10px;
  display: none;
  gap: 6px;
  max-height: 260px;
  overflow: auto;
  padding-right: 2px;
  z-index: 40;
  box-sizing: border-box;
}

.set-tracklist.open { display: grid; }

.set-track {
  border: 1px solid var(--line);
  background: #161616;
  padding: 6px;
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 6px;
  align-items: center;
  font-size: 12px;
}

.set-track.shared {
  border-color: var(--lime);
  background: #11170e;
}

.set-track-time {
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  color: #cbcbcb;
  min-width: 48px;
}

.set-track-conf {
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  padding: 2px 5px;
  border: 1px solid #333;
  color: #cfcfcf;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.compare-panel {
  margin-top: 12px;
  border: 1px solid var(--line);
  background: #0f0f0f;
  padding: 12px;
}

.compare-grid {
  margin-top: 10px;
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.compare-card {
  border: 1px solid var(--line);
  background: #111;
  padding: 8px;
}

.compare-value {
  display: block;
  color: var(--lime);
  font-size: 18px;
  font-weight: 800;
  line-height: 1;
}

.compare-label {
  display: block;
  margin-top: 5px;
  font-size: 10px;
  color: var(--muted);
  font-family: 'Space Mono', monospace;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.status-list {
  margin-top: 12px;
  display: grid;
  gap: 8px;
}

.status-item {
  border: 1px solid var(--line);
  background: #101010;
  padding: 9px;
}

.status-url {
  color: #d8d8d8;
  font-size: 12px;
  word-break: break-word;
}

.status-err {
  margin-top: 6px;
  color: #ff8484;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.no-results {
  margin-top: 12px;
  border: 1px dashed var(--line);
  color: var(--muted);
  padding: 12px;
  display: none;
}

@media (max-width: 1320px) {
  .artist-hero {
    grid-template-columns: 1fr;
  }
  .artist-hero-side {
    height: 320px;
  }
  .overview-grid { grid-template-columns: 1fr; }
  .taxonomy-workbench { grid-template-columns: 1fr; }
  .focus-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .set-grid { column-count: 2; }
}

@media (max-width: 980px) {
  .atlas-layout { grid-template-columns: 1fr; align-items: start; height: auto; }
  .artist-stack,
  .atlas-panel { height: auto; }
  .atlas-panel { overflow: visible; }
  .artist-grid { max-height: 210px; }
  .compare-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .set-grid { column-count: 2; }
}

@media (max-width: 760px) {
  .artist-grid {
    --artist-card-height: 132px;
    --artist-card-overlap: 74px;
  }
  .set-grid { column-count: 1; }
  .recurring-grid {
    grid-auto-columns: minmax(240px, 82vw);
  }
  .evidence-grid {
    grid-auto-columns: minmax(240px, 82vw);
  }
  .controls-grid { grid-template-columns: 1fr; }
  .set-controls-inline {
    display: flex;
    flex-wrap: nowrap;
  }
  .set-controls-inline .control:first-child {
    flex: 1 1 auto;
  }
  .set-controls-inline .control:last-child {
    flex: 0 0 124px;
  }
  .compare-grid { grid-template-columns: 1fr; }
}
"""
    )


def save_artist_explorer_html(
    output_dir: Path,
    artist_name,
    set_summaries,
    track_counter,
    track_info,
    successful,
    failed,
) -> Path:
    """Render and save the artist-level explorer page."""
    output_path = output_dir / "artist_summary.html"
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    unique_tracks = len(track_counter)
    total_appearances = int(sum(track_counter.values()))
    recurring_tracks = int(sum(1 for c in track_counter.values() if c > 1))

    genre_focus: Counter = Counter()
    label_focus: Counter = Counter()
    track_artist_focus: Counter = Counter()

    # Recurring track records + lookup map
    recurring_records = []
    recurring_map = {}
    for key, count in sorted(track_counter.items(), key=lambda kv: (kv[1], kv[0]), reverse=True):
        info = track_info.get(key, {})
        artist = info.get("artist") or "Unknown"
        title = info.get("title") or "Unknown Track"
        genres = [g for g in (info.get("genres") or []) if g]
        label = info.get("discogs_label") or ""
        spotify_url = info.get("spotify_url") or spotify_search_url(artist, title)
        spotify_id = spotify_track_id(spotify_url)
        youtube_url = info.get("youtube_url") or youtube_search_url(artist, title)
        discogs_url = info.get("discogs_url") or info.get("discogs_label_url") or discogs_search_url(artist, title)
        album_art = info.get("spotify_album_art") or ""
        appearances = info.get("appearances") or []

        for g in genres:
            genre_focus[g] += count
        if label:
            label_focus[label] += count
        if artist and artist.lower() != "unknown":
            track_artist_focus[artist] += count

        app_rows = []
        rec_conf_counts = {level: 0 for level in CONFIDENCE_LEVELS}
        for app in appearances:
            set_html = app.get("set_html_rel") or ""
            track_position = app.get("track_position")
            set_anchor = _encode_local_href(
                f"{set_html}#track-{track_position}" if set_html and track_position else set_html
            )
            confidence = _normalize_confidence(app.get("confidence"))
            rec_conf_counts[confidence] = int(rec_conf_counts.get(confidence, 0)) + 1
            app_rows.append(
                {
                    "set_title": app.get("set_title") or "Unknown set",
                    "time_range": app.get("time_range") or "",
                    "source_deep_link": app.get("source_deep_link") or "",
                    "set_anchor": set_anchor,
                    "confidence": confidence,
                }
            )
        rec_conf_levels = [level for level in ("HIGH", "MEDIUM", "LOW") if int(rec_conf_counts.get(level, 0)) > 0]

        record = {
            "track_key": key,
            "artist": artist,
            "title": title,
            "count": int(count),
            "spotify_url": spotify_url,
            "spotify_track_id": spotify_id or "",
            "youtube_url": youtube_url,
            "discogs_url": discogs_url,
            "discogs_label": label,
            "genres": genres,
            "album_art": album_art,
            "appearances": app_rows,
            "confidence": _primary_confidence(rec_conf_counts),
            "confidence_counts": rec_conf_counts,
            "confidence_levels": rec_conf_levels,
            "search": f"{artist} {title} {' '.join(genres)} {label}".lower(),
        }
        recurring_records.append(record)
        recurring_map[key] = record

    # Set explorer cards + set-atlas payload
    set_cards_html = []
    atlas_set_cards_html = []
    hero_set_cards_html = []
    set_atlas_sets = []
    all_atlas_tracks = []
    for idx, s in enumerate(set_summaries):
        title = s.get("title") or "Untitled Set"
        set_html_rel = s.get("set_html_rel") or ""
        set_html_href = _encode_local_href(set_html_rel)
        source_url = s.get("url") or ""
        set_href = set_html_href or source_url or "#"
        source_href = source_url or set_html_href or "#"
        total_tracks = int(s.get("total_tracks") or 0)
        recognition_rate = float(s.get("recognition_rate") or 0.0)
        duration = int(s.get("duration") or 0)
        data_search = f"{title} {s.get('track_search_text') or ''}".lower()
        thumb = s.get("thumbnail_url") or ""
        conf_counts = s.get("confidence_counts") or {}
        high = int(conf_counts.get("HIGH", 0))
        medium = int(conf_counts.get("MEDIUM", 0))
        low = int(conf_counts.get("LOW", 0))
        uncertain = int(conf_counts.get("UNCERTAIN", 0))

        mini_tl = "".join(
            f'<span class="set-mini-seg {(seg.get("confidence") or "UNCERTAIN").lower()}" '
            f'style="left:{float(seg.get("start_pct") or 0):.3f}%;width:{float(seg.get("width_pct") or 0):.3f}%"></span>'
            for seg in (s.get("mini_timeline") or [])
        )

        track_keys_norm = []
        track_rows = []
        atlas_tracks = []

        for pos, t in enumerate((s.get("tracks") or []), start=1):
            artist = t.get("artist") or "Unknown"
            track_title = t.get("title") or "Unknown Track"
            key_raw = t.get("track_key") or normalize_track_key(artist, track_title)
            key_norm = normalize_track_key(artist, track_title)
            if key_norm:
                track_keys_norm.append(key_norm)

            info = track_info.get(key_raw, {})
            genres = [g for g in (info.get("genres") or []) if g]
            label = info.get("discogs_label") or ""
            spotify_url = t.get("spotify_url") or info.get("spotify_url") or spotify_search_url(artist, track_title)
            spotify_id = spotify_track_id(spotify_url)
            youtube_url = info.get("youtube_url") or youtube_search_url(artist, track_title)
            discogs_url = info.get("discogs_url") or info.get("discogs_label_url") or discogs_search_url(artist, track_title)
            album_art = info.get("spotify_album_art") or ""
            confidence_upper = _normalize_confidence(t.get("confidence"))
            conf_color = CONFIDENCE_COLORS.get(confidence_upper, "#757575")

            source_deep_link = ""
            time_range = t.get("start_time_formatted") or ""
            for app in (info.get("appearances") or []):
                if (app.get("set_title") or "") != title:
                    continue
                source_deep_link = app.get("source_deep_link") or source_deep_link
                time_range = app.get("time_range") or time_range
                if app.get("track_position") == pos:
                    break

            set_anchor = _encode_local_href(f"{set_html_rel}#track-{pos}") if set_html_rel else ""
            track_href = set_anchor or source_deep_link or spotify_url or ""
            track_rows.append(
                f"""
<div class="set-track" data-track-key="{esc(key_norm)}">
  <span class="set-track-time">{esc(t.get("start_time_formatted") or "")}</span>
  <span>{f'<a href="{esc(track_href)}" target="_blank" rel="noopener">{esc(artist)} - {esc(track_title)}</a>' if track_href else esc(f"{artist} - {track_title}")}</span>
  <span class="set-track-conf" style="border-color:{conf_color}; color:{conf_color};">{esc(confidence_upper)}</span>
</div>
"""
            )

            atlas_track_entry = {
                "idx": pos,
                "track_key": key_raw,
                "artist": artist,
                "title": track_title,
                "confidence": confidence_upper,
                "time": t.get("start_time_formatted") or "",
                "genres": genres,
                "label": label,
                "label_url": info.get("discogs_label_url") or "",
                "spotify_url": spotify_url,
                "spotify_track_id": spotify_id or "",
                "youtube_url": youtube_url,
                "discogs_url": discogs_url,
                "album_art": album_art,
                "set_anchor": set_anchor,
                "source_deep_link": source_deep_link,
                "time_range": time_range,
                "set_title": title,
            }
            atlas_tracks.append(atlas_track_entry)
            all_atlas_tracks.append(atlas_track_entry)

        thumb_html = (
            f'<div class="set-thumb"><a href="{esc(set_href)}" target="_blank" rel="noopener"><img src="{esc(thumb)}" alt="{esc(title)}" loading="lazy" /></a></div>'
            if thumb
            else '<div class="set-thumb empty">No Image</div>'
        )

        set_cards_html.append(
            f"""
<article class="set-card" data-card-idx="{idx}" data-search="{esc(data_search)}"
  data-tracks="{total_tracks}" data-rate="{recognition_rate:.2f}" data-duration="{duration}"
  data-track-keys="{esc('|'.join(track_keys_norm))}">
  {thumb_html}
  <div class="set-body">
    <h4 class="set-title"><a href="{esc(set_href)}" target="_blank" rel="noopener">{esc(title)}</a></h4>
    <div class="set-mini">{mini_tl}</div>
    <div class="set-meta">
      <span class="set-pill">{total_tracks} tracks</span>
      <span class="set-pill">{recognition_rate:.0f}% match</span>
      <span class="set-pill">{esc(_fmt_duration(duration))}</span>
      <span class="set-pill">H:{high} M:{medium} L:{low} U:{uncertain}</span>
    </div>
    <div class="actions">
      {f'<a href="{esc(set_html_href)}" target="_blank" rel="noopener">Open Set Page</a>' if set_html_href else ''}
      {f'<a href="{esc(source_url)}" target="_blank" rel="noopener">Source</a>' if source_url else ''}
      <button class="js-set-compare">Compare</button>
      <button class="js-tracklist-toggle">Show Tracklist</button>
    </div>
    <div class="set-tracklist">
      {''.join(track_rows) if track_rows else '<div class="empty">No identified tracks in this set.</div>'}
    </div>
  </div>
</article>
"""
        )

        # Hero side rail is image-first: only include sets with real set thumbnails.
        if thumb:
            hero_set_cards_html.append(
                f"""
<a class="artist-hero-card" href="{esc(set_href)}" target="_blank" rel="noopener">
  <img src="{esc(thumb)}" alt="{esc(title)}" loading="lazy" />
  <div class="artist-hero-card-meta">
    <p class="artist-hero-card-match">{recognition_rate:.0f}% match</p>
    <p class="artist-hero-card-title">{esc(title)}</p>
    <p class="artist-hero-card-sub">{total_tracks} tracks · {esc(_fmt_duration(duration))}</p>
  </div>
</a>
"""
            )

        atlas_set_cards_html.append(
            f"""
<article class="artist-card atlas-set-card{' focus selected' if idx == 0 else ''}" data-atlas-set-idx="{idx}" data-search="{esc(data_search)}"
  data-tracks="{total_tracks}" data-rate="{recognition_rate:.2f}" data-duration="{duration}" data-title="{esc(title.lower())}">
  {f'<img src="{esc(thumb)}" alt="{esc(title)}" loading="lazy" />' if thumb else '<div class="set-card-fallback" aria-hidden="true"></div>'}
  <div class="artist-detail">
    <div class="artist-meta-row">
      <div class="card-actions">
        <button class="chip-btn {'active' if idx == 0 else ''}" data-action="set-atlas-toggle" data-atlas-set-idx="{idx}">{'In Scope' if idx == 0 else 'Add to Scope'}</button>
        <a class="chip-btn" href="{esc(set_href)}" target="_blank" rel="noopener">Set Page</a>
        <a class="chip-btn" href="{esc(source_href)}" target="_blank" rel="noopener">Source</a>
      </div>
    </div>
    <h3>{esc(title)}</h3>
    <p>{total_tracks} tracks · {recognition_rate:.0f}% match · {esc(_fmt_duration(duration))}</p>
  </div>
</article>
"""
        )

        set_atlas_sets.append(
            {
                "idx": idx,
                "title": title,
                "search": data_search,
                "tracks_count": total_tracks,
                "recognition_rate": recognition_rate,
                "duration": duration,
                "set_href": set_href,
                "source_href": source_href,
                "set_html_rel": set_html_rel,
                "thumbnail_url": thumb,
                "tracks": atlas_tracks,
            }
        )

    hero_image, _, _, _ = select_artist_hero_image(set_summaries, track_info, artist_name)

    hero_image_html = (
        f'<img src="{esc(hero_image)}" alt="{esc(artist_name)} artist image" loading="eager" />'
        if hero_image
        else '<div class="artist-hero-image-fallback" aria-hidden="true"></div>'
    )

    name_parts = [part for part in str(artist_name or "").split() if part]
    if not name_parts:
        hero_name_primary = "Artist"
        hero_name_secondary = ""
    elif len(name_parts) == 1:
        hero_name_primary = name_parts[0]
        hero_name_secondary = ""
    elif len(name_parts) == 2:
        hero_name_primary = name_parts[0]
        hero_name_secondary = name_parts[1]
    else:
        mid = (len(name_parts) + 1) // 2
        hero_name_primary = " ".join(name_parts[:mid])
        hero_name_secondary = " ".join(name_parts[mid:])
    hero_name_secondary_html = f"<span>{esc(hero_name_secondary)}</span>" if hero_name_secondary else ""
    artist_body_style = f' style="--artist-page-bg-image: url(\'{esc(hero_image)}\');"' if hero_image else ""

    hero_cards_markup = "".join(hero_set_cards_html)
    hero_side_html = (
        f'<div class="artist-hero-side-viewport" id="artistHeroSideViewport"><div class="artist-hero-side-track" id="artistHeroSideTrack">{hero_cards_markup}{hero_cards_markup}</div></div>'
        if hero_cards_markup
        else '<div class="artist-hero-empty">No set previews available.</div>'
    )

    # Recurring cards in index-like component language
    recurring_cards_html = []
    for rec in recurring_records:
        set_count = rec["count"]
        conf_counts = rec.get("confidence_counts") or {}
        high_count = int(conf_counts.get("HIGH", 0))
        medium_count = int(conf_counts.get("MEDIUM", 0))
        low_count = int(conf_counts.get("LOW", 0))

        set_links_by_conf: dict[str, list[dict[str, str]]] = {
            "ALL": [],
            "HIGH": [],
            "MEDIUM": [],
            "LOW": [],
        }
        seen_by_conf: dict[str, set[tuple[str, str]]] = {key: set() for key in set_links_by_conf}
        for app in rec.get("appearances", []):
            set_title = str(app.get("set_title") or "Unknown set")
            set_anchor = str(app.get("set_anchor") or "").strip()
            if not set_anchor:
                continue
            app_conf = _normalize_confidence(app.get("confidence"))
            dedupe_key = (set_anchor, set_title.lower())
            if dedupe_key not in seen_by_conf["ALL"]:
                seen_by_conf["ALL"].add(dedupe_key)
                set_links_by_conf["ALL"].append({"title": set_title, "href": set_anchor})
            if app_conf in ("HIGH", "MEDIUM", "LOW") and dedupe_key not in seen_by_conf[app_conf]:
                seen_by_conf[app_conf].add(dedupe_key)
                set_links_by_conf[app_conf].append({"title": set_title, "href": set_anchor})

        set_links_count = len(set_links_by_conf["ALL"])
        all_set_links_html = "".join(
            f'<li><a href="{esc(item.get("href") or "")}" target="_blank" rel="noopener">{esc(item.get("title") or "Unknown set")}</a></li>'
            for item in set_links_by_conf["ALL"]
        )
        source_panel_html = (
            f'<ul class="source-list">{all_set_links_html}</ul>'
            if all_set_links_html
            else '<div class="empty">No set links available.</div>'
        )
        set_links_json = esc(json.dumps(set_links_by_conf, ensure_ascii=True))

        rec_art = rec.get("album_art") or ""
        rec_art_html = f'<img src="{esc(rec_art)}" alt="{esc(rec["title"])}" loading="lazy" />' if rec_art else ""
        spotify_embed_btn = (
            f'<button data-action="spotify-embed" data-track-id="{esc(rec["spotify_track_id"])}" '
            f'data-closed-label="Spotify" data-open-label="Hide Spotify">Spotify</button>'
            if rec.get("spotify_track_id")
            else ""
        )

        recurring_cards_html.append(
            f"""
<article class="track-card rec-card" data-count="{set_count}" data-count-all="{set_count}" data-count-high="{high_count}" data-count-medium="{medium_count}" data-count-low="{low_count}" data-set-links="{set_links_json}" data-search="{esc(rec['search'])}" data-track-key="{esc(rec['track_key'])}" data-conf="{esc(rec.get('confidence') or 'UNCERTAIN')}" data-conf-levels="{esc('|'.join(rec.get('confidence_levels') or []))}">
  <div class="track-art">{rec_art_html}</div>
  <div class="track-body">
    <h4 class="track-title">{esc(rec['artist'])} - {esc(rec['title'])}</h4>
    <div class="actions">
      {spotify_embed_btn}
      <button data-action="toggle-sources" data-closed-label="Sets ({set_links_count})" data-open-label="Hide Sets">Sets ({set_links_count})</button>
    </div>
    <div class="source-panel">{source_panel_html}</div>
  </div>
</article>
"""
        )

    recurring_counts = [r["count"] for r in recurring_records if r["count"] >= 1]
    recurring_max = max(recurring_counts, default=1)
    recurring_thresholds = [v for v in (1, 2, 3, 5, 8, 12) if v <= recurring_max]
    if 1 not in recurring_thresholds:
        recurring_thresholds.insert(0, 1)
    if recurring_max not in recurring_thresholds:
        recurring_thresholds.append(recurring_max)
    recurring_thresholds = sorted({int(v) for v in recurring_thresholds if int(v) > 0})
    recurring_default = 1
    if recurring_default not in recurring_thresholds:
        recurring_thresholds.insert(0, recurring_default)
    recurring_thresholds_data = ",".join(str(v) for v in recurring_thresholds)

    recurring_filter_btns = (
        f'<div class="threshold-stepper" id="recThresholdStepper" data-thresholds="{esc(recurring_thresholds_data)}">'
        f'<button class="btn threshold-arrow" data-action="rec-threshold-down" aria-label="Decrease recurring set threshold">▼</button>'
        f'<span class="btn threshold-value">{recurring_default}+ SETS</span>'
        f'<button class="btn threshold-arrow" data-action="rec-threshold-up" aria-label="Increase recurring set threshold">▲</button>'
        "</div>"
    )
    recurring_conf_filter_btns = (
        '<button class="btn js-rec-conf active" data-conf="all">All confidence</button>'
        '<button class="btn js-rec-conf" data-conf="HIGH">High</button>'
        '<button class="btn js-rec-conf" data-conf="MEDIUM">Medium</button>'
        '<button class="btn js-rec-conf" data-conf="LOW">Low</button>'
    )

    if failed:
        failed_items = []
        for f in failed:
            url = f.get("url") or ""
            err = f.get("status") or "FAILED"
            failed_items.append(
                f'<div class="status-item"><div class="status-url">{esc(url)}</div><div class="status-err">{esc(err)}</div></div>'
            )
        failed_html = "".join(failed_items)
    else:
        failed_html = '<div class="empty">No failed sets were recorded for this artist.</div>'

    payload = {
        "setAtlasSets": set_atlas_sets,
        "allAtlasTracks": all_atlas_tracks,
        "recurringDefault": recurring_default,
        "recurringThresholds": recurring_thresholds,
    }

    html_template = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>__TITLE__</title>
  <style>__CSS__</style>
</head>
<body class="artist-page"__ARTIST_BODY_STYLE__>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand">[SET SIGNAL ARCHIVE]</div>
      <nav class="topnav">
        <a href="#overview">Overview</a>
        <a href="#recurring-section">Recurring</a>
        <a href="#set-atlas-section">Set Atlas</a>
        <a href="#sets-section">Set Explorer</a>
        <a href="#status-section">Status</a>
      </nav>
    </div>
  </header>

  <main class="shell artist-shell">
    <section class="section" id="overview">
      <div class="section-inner">
        <div class="kicker">Artist Intelligence Deck</div>
        <div class="artist-hero">
          <div class="artist-hero-main">
            <div class="artist-hero-visual" id="artistHeroVisual">
              __ARTIST_HERO_IMAGE__
              <h1 class="artist-hero-title"><span>__ARTIST_HERO_NAME_PRIMARY__</span>__ARTIST_HERO_NAME_SECONDARY__</h1>
            </div>
            <div class="stats-grid artist-hero-stats">
              <div class="stat"><span class="stat-value">__SETS_ANALYZED__</span><span class="stat-label">Sets analyzed</span></div>
              <div class="stat"><span class="stat-value">__UNIQUE_TRACKS__</span><span class="stat-label">Unique tracks</span></div>
              <div class="stat"><span class="stat-value">__TOTAL_DETECTIONS__</span><span class="stat-label">Total detections</span></div>
              <div class="stat"><span class="stat-value">__RECURRING_TRACKS__</span><span class="stat-label">Recurring tracks</span></div>
            </div>
          </div>
          <aside class="artist-hero-side" id="artistHeroSide">
            __ARTIST_HERO_SIDE__
          </aside>
        </div>
      </div>
    </section>

    <section class="section" id="recurring-section">
      <div class="section-inner">
        <div class="section-head">
          <h2 class="recurring-heading">Recurring Tracks</h2>
          <p>Index-style track cards with set evidence and source deep links. Threshold and search controls are available below.</p>
        </div>
        <div class="recurring-controls">
          <div class="controls-row">__RECURRING_FILTER_BTNS__ __RECURRING_CONF_FILTER_BTNS__</div>
          <input class="input" id="recSearchInput" type="search" placeholder="Search recurring tracks..." />
        </div>
        <div class="recurring-grid" id="recurringGrid">__RECURRING_CARDS__</div>
        <div class="no-results" id="recNoResults">No recurring tracks match the active threshold/filter.</div>
      </div>
    </section>

    <section class="section" id="set-atlas-section">
      <div class="section-inner">
        <div class="section-head">
          <h2>Set Atlas</h2>
          <p>Pick a set on the left, then investigate genres, labels, track artists, and tracks with evidence in the right pane.</p>
        </div>

        <div class="atlas-layout">
          <div class="artist-stack">
            <div class="control">
              <label for="setAtlasSearch">Search Sets</label>
              <input id="setAtlasSearch" type="text" placeholder="find set cards" />
            </div>
            <div class="artist-grid atlas-set-grid" id="atlasSetList">__ATLAS_SET_CARDS__</div>
            <div class="no-results" id="atlasSetNoResults">No sets match current filters.</div>
          </div>

          <aside class="atlas-panel">
            <div class="focus-header" id="setAtlasFocusHeader"></div>

            <div class="taxonomy-workbench">
              <div class="taxonomy-panel">
                <div class="panel-head taxonomy-head">
                  <h3 class="panel-title" id="setAtlasTitle">Taxonomy Atlas</h3>
                  <div class="lens-tabs" id="setAtlasLensTabs"></div>
                </div>
                <p class="panel-copy" id="setAtlasSummary">Select a set to begin investigation.</p>

                <div class="taxonomy-controls-bar">
                  <div class="control taxonomy-search-control">
                    <input id="setAtlasQuery" type="text" placeholder="search" aria-label="Search taxonomy entries" />
                  </div>
                  <div class="taxonomy-controls-row">
                    <div class="pill-row" id="setAtlasThresholds"></div>
                    <div class="pill-row" id="setAtlasConfidenceFilters"></div>
                    <div class="control taxonomy-sort-control">
                      <span class="taxonomy-sort-icon" aria-hidden="true">&#8597;</span>
                      <select id="setAtlasSort" aria-label="Sort taxonomy entries">
                        <option value="count">Highest Usage</option>
                        <option value="alpha">Alphabetical</option>
                      </select>
                    </div>
                  </div>
                </div>

                <div class="rows" id="setAtlasRows"></div>
                <div class="pager" id="setAtlasPager"></div>
                <div class="no-results" id="setAtlasNoResults">No taxonomy entries match current controls.</div>
              </div>

              <div class="evidence-panel" id="setAtlasEvidencePanel">
                <div class="panel-head">
                  <h3 class="panel-title">Evidence Tracks</h3>
                  <p class="panel-copy" id="setAtlasEvidenceSummary"></p>
                </div>
                <div class="evidence-grid" id="setAtlasEvidence"></div>
                <div class="pager" id="setAtlasEvidencePager"></div>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </section>

    <section class="section" id="sets-section">
      <div class="section-inner">
        <div class="section-head">
          <h2>Set Explorer</h2>
          <p>Search and compare sets, then inspect shared tracks through expanded tracklists and deep links.</p>
        </div>

        <div class="set-panel">
          <div class="controls-grid set-controls-inline" style="margin-top: 0; margin-bottom: 10px;">
            <div class="control">
              <label for="setSearch">Search Sets</label>
              <input id="setSearch" type="text" placeholder="set title, track" aria-label="Search sets" />
            </div>
            <div class="control">
              <label for="setSort">Sort</label>
              <select id="setSort" aria-label="Sort sets">
                <option value="default">Default</option>
                <option value="rate">Recognition Rate</option>
                <option value="tracks">Track Count</option>
                <option value="duration">Duration</option>
              </select>
            </div>
          </div>

          <div class="compare-panel" id="setComparePanel" hidden>
            <div class="controls-row" style="justify-content:space-between;">
              <strong style="font-size:13px;letter-spacing:0.03em;text-transform:uppercase;">Set Connection View</strong>
              <button class="btn" id="clearSetCompareBtn">Clear</button>
            </div>
            <div id="setCompareBody" style="margin-top:8px;color:var(--muted);font-size:13px;">Select two sets to compare overlap.</div>
          </div>

          <div class="set-grid" id="setGrid">__SET_CARDS__</div>
          <div class="pager" id="setPager"></div>
          <div class="no-results" id="setNoResults">No sets match current filters.</div>
        </div>
      </div>
    </section>

    <section class="section" id="status-section">
      <div class="section-inner">
        <div class="section-head">
          <h2>Collection Status</h2>
          <p>Visibility into failed set collection attempts for this artist.</p>
        </div>
        <div class="status-list">__FAILED_HTML__</div>
        <div class="footer-note">Generated __GENERATED__ · Set Signal Explorer</div>
      </div>
    </section>
  </main>

  <script>
    const ARTIST_DATA = __PAYLOAD_JSON__;
  </script>
  <script>
(() => {
  function escapeHtml(s) {
    return String(s || '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function fmt(n) {
    return Number(n || 0).toLocaleString();
  }
  const CONF_FILTER_LEVELS = ['HIGH', 'MEDIUM', 'LOW'];

  function formatDuration(seconds) {
    const s = Number(seconds || 0);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  }

  function normalizeConfidence(value) {
    const conf = String(value || 'UNCERTAIN').toUpperCase();
    return ['HIGH', 'MEDIUM', 'LOW', 'UNCERTAIN'].includes(conf) ? conf : 'UNCERTAIN';
  }

  function trackHasConfidence(track, level) {
    const target = normalizeConfidence(level);
    const counts = track && typeof track === 'object' ? (track.confidence_counts || {}) : {};
    const hasCounts = counts && typeof counts === 'object' && Object.keys(counts).length > 0;
    if (hasCounts) {
      return Number(counts[target] || 0) > 0;
    }
    return normalizeConfidence(track?.confidence) === target;
  }

  function trackMatchesConfidence(track, confFilter) {
    if (confFilter === 'all') return true;
    return trackHasConfidence(track, confFilter);
  }

  function filterTracksByConfidence(tracks, confFilter) {
    return (tracks || []).filter((track) => trackMatchesConfidence(track, confFilter));
  }

  function normalizeConfFilter(confFilter) {
    const raw = String(confFilter || 'all').toUpperCase();
    if (raw === 'ALL') return 'all';
    return CONF_FILTER_LEVELS.includes(raw) ? raw : 'all';
  }

  function filterSetRefsByConfidence(setRefs, confFilter) {
    const target = normalizeConfFilter(confFilter);
    if (target === 'all') return Array.isArray(setRefs) ? setRefs.slice() : [];
    return (setRefs || []).filter((setRef) => normalizeConfidence(setRef?.confidence) === target);
  }

  function projectTrackByConfidence(track, confFilter) {
    const target = normalizeConfFilter(confFilter);
    if (!track) return null;

    const refs = [];
    let selectedAppearances = 0;
    const confCounts = { HIGH: 0, MEDIUM: 0, LOW: 0, UNCERTAIN: 0 };

    for (const ref of (track.selected_refs || [])) {
      const setRefs = filterSetRefsByConfidence(ref?.set_refs || [], target);
      if (!setRefs.length) continue;
      refs.push({
        ...ref,
        set_refs: setRefs,
        appearances: setRefs.length,
      });
      for (const setRef of setRefs) {
        const conf = normalizeConfidence(setRef?.confidence);
        confCounts[conf] = Number(confCounts[conf] || 0) + 1;
        selectedAppearances += 1;
      }
    }

    if (selectedAppearances <= 0) return null;

    let confidence = normalizeConfidence(track.confidence);
    if (target === 'all') {
      confidence = primaryConfidenceFromCounts(confCounts);
    } else {
      for (const level of Object.keys(confCounts)) confCounts[level] = 0;
      confCounts[target] = selectedAppearances;
      confidence = target;
    }

    return {
      ...track,
      selected_refs: refs,
      selected_appearances: Number(selectedAppearances || 0),
      selected_artist_count: refs.length,
      confidence_counts: confCounts,
      confidence,
    };
  }

  function tracksWithConfidenceProjection(tracks, confFilter) {
    const out = [];
    for (const track of tracks || []) {
      const projected = projectTrackByConfidence(track, confFilter);
      if (!projected) continue;
      out.push(projected);
    }
    return out;
  }

  function confidenceCountsFromTracks(tracks) {
    const out = { HIGH: 0, MEDIUM: 0, LOW: 0 };
    for (const track of tracks || []) {
      for (const level of CONF_FILTER_LEVELS) {
        if (trackHasConfidence(track, level)) out[level] += 1;
      }
    }
    return out;
  }

  function primaryConfidenceFromCounts(confCounts) {
    const ordered = ['HIGH', 'MEDIUM', 'LOW', 'UNCERTAIN'];
    let best = 'UNCERTAIN';
    let bestCount = -1;
    for (const level of ordered) {
      const count = Number((confCounts || {})[level] || 0);
      if (count > bestCount) {
        best = level;
        bestCount = count;
      }
    }
    return best;
  }

  function parseThresholdLevels(raw, fallback = [1]) {
    const fromRaw = Array.isArray(raw)
      ? raw
      : String(raw || '')
        .split(',')
        .map((v) => v.trim())
        .filter(Boolean);
    const levels = fromRaw
      .map((v) => Number(v))
      .filter((v) => Number.isFinite(v) && v > 0)
      .sort((a, b) => a - b);
    if (levels.length) return levels;
    return fallback.slice();
  }

  function normalizeThresholdValue(value, levels) {
    const options = parseThresholdLevels(levels, [1]);
    const current = Number(value);
    if (Number.isFinite(current) && options.includes(current)) return current;
    if (!Number.isFinite(current)) return options[0];
    let fallback = options[0];
    for (const option of options) {
      if (option <= current) fallback = option;
    }
    return fallback;
  }

  function stepThresholdValue(value, levels, direction) {
    const options = parseThresholdLevels(levels, [1]);
    const current = normalizeThresholdValue(value, options);
    const idx = options.indexOf(current);
    const nextIdx = Math.max(0, Math.min(options.length - 1, idx + (direction > 0 ? 1 : -1)));
    return options[nextIdx];
  }

  function buildThresholdStepperHtml(buttonClass, downAction, upAction, currentValue, levels) {
    const options = parseThresholdLevels(levels, [1]);
    const current = normalizeThresholdValue(currentValue, options);
    const idx = options.indexOf(current);
    const canDown = idx > 0;
    const canUp = idx < options.length - 1;
    return `
      <button class="${buttonClass} threshold-arrow" data-action="${downAction}" ${canDown ? '' : 'disabled'} aria-label="Decrease set threshold">▼</button>
      <span class="${buttonClass} threshold-value">${fmt(current)}+ SETS</span>
      <button class="${buttonClass} threshold-arrow" data-action="${upAction}" ${canUp ? '' : 'disabled'} aria-label="Increase set threshold">▲</button>
    `;
  }

  function fitArtistHeroTitle() {
    const visual = document.getElementById('artistHeroVisual');
    const title = visual ? visual.querySelector('.artist-hero-title') : null;
    if (!visual || !title) return;

    const fitVar = '--artist-hero-title-fit-size';
    const minSize = 24;
    const safePadding = 6;

    const applyFontSize = (size) => {
      if (Number.isFinite(size) && size > 0) {
        title.style.setProperty(fitVar, `${size}px`);
      } else {
        title.style.removeProperty(fitVar);
      }
    };

    const titleFits = () => {
      const visualRect = visual.getBoundingClientRect();
      const titleRect = title.getBoundingClientRect();
      const textFitsOwnBox = title.scrollWidth <= title.clientWidth + safePadding;
      return (
        textFitsOwnBox &&
        titleRect.top >= visualRect.top + safePadding &&
        titleRect.left >= visualRect.left + safePadding &&
        titleRect.right <= visualRect.right - safePadding &&
        titleRect.bottom <= visualRect.bottom - safePadding
      );
    };

    applyFontSize();
    const baseSize = Number.parseFloat(window.getComputedStyle(title).fontSize);
    if (!Number.isFinite(baseSize) || baseSize <= minSize || titleFits()) return;

    let low = minSize;
    let high = baseSize;
    let best = minSize;

    applyFontSize(minSize);
    if (!titleFits()) return;

    for (let iteration = 0; iteration < 12; iteration += 1) {
      const mid = (low + high) / 2;
      applyFontSize(mid);
      if (titleFits()) {
        best = mid;
        low = mid;
      } else {
        high = mid;
      }
    }

    applyFontSize(Math.floor(best * 10) / 10);
  }

  let artistHeroRailRaf = 0;
  let artistHeroRailLastTs = 0;

  function stopArtistHeroRail() {
    if (artistHeroRailRaf) {
      cancelAnimationFrame(artistHeroRailRaf);
      artistHeroRailRaf = 0;
    }
    artistHeroRailLastTs = 0;
  }

  function startArtistHeroRail() {
    stopArtistHeroRail();
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    if (window.matchMedia('(max-width: 1320px)').matches) return;

    const viewport = document.getElementById('artistHeroSideViewport');
    const track = document.getElementById('artistHeroSideTrack');
    if (!viewport || !track) return;

    const cycleHeight = track.scrollHeight / 2;
    if (cycleHeight <= viewport.clientHeight + 4) return;

    if (!viewport.dataset.bound) {
      viewport.addEventListener('mouseenter', () => stopArtistHeroRail());
      viewport.addEventListener('mouseleave', () => startArtistHeroRail());
      viewport.dataset.bound = '1';
    }

    let scrollPos = viewport.scrollTop % cycleHeight;
    viewport.scrollTop = scrollPos;
    const pxPerSecond = 12;

    const tick = (ts) => {
      if (!artistHeroRailRaf) return;
      if (!artistHeroRailLastTs) artistHeroRailLastTs = ts;
      const dt = (ts - artistHeroRailLastTs) / 1000;
      artistHeroRailLastTs = ts;
      scrollPos += pxPerSecond * dt;
      if (scrollPos >= cycleHeight) {
        scrollPos -= cycleHeight;
      }
      viewport.scrollTop = scrollPos;
      artistHeroRailRaf = requestAnimationFrame(tick);
    };

    artistHeroRailRaf = requestAnimationFrame(tick);
  }

  function renderTrackCard(track, sourceHeaderText) {
    const spotifyAction = track.spotify_track_id
      ? `<button data-action="spotify-embed" data-track-id="${escapeHtml(track.spotify_track_id)}">Embed</button>`
      : '';

    const setPageLi = track.set_anchor
      ? `<li><a href="${escapeHtml(track.set_anchor)}" target="_blank" rel="noopener">Set Page</a></li>`
      : '';
    const sourceLi = track.source_deep_link
      ? `<li><a href="${escapeHtml(track.source_deep_link)}" target="_blank" rel="noopener">Source Time ${escapeHtml(track.time_range || '')}</a></li>`
      : '';
    const confLi = track.confidence ? `<li>Confidence: ${escapeHtml(track.confidence)}</li>` : '';

    return `
      <article class="track-card">
        <div class="track-art">${track.album_art ? `<img src="${escapeHtml(track.album_art)}" alt="${escapeHtml(track.title || 'Track')}" loading="lazy" />` : ''}</div>
        <div class="track-body">
          <h4 class="track-title">${escapeHtml(track.artist || 'Unknown')} - ${escapeHtml(track.title || 'Unknown')}</h4>
          <p class="muted">${escapeHtml(track.time || '')}${track.label ? ` | ${escapeHtml(track.label)}` : ''}</p>
          <div class="actions">
            <button data-action="toggle-sources" data-closed-label="Context" data-open-label="Hide">Context</button>
            <a class="spotify" href="${escapeHtml(track.spotify_url || '#')}" target="_blank" rel="noopener">Spotify</a>
            <a href="${escapeHtml(track.youtube_url || '#')}" target="_blank" rel="noopener">YouTube</a>
            <a href="${escapeHtml(track.discogs_url || '#')}" target="_blank" rel="noopener">Discogs</a>
            ${spotifyAction}
          </div>
          <div class="source-panel">
            <div class="source-group">
              <h5>${escapeHtml(sourceHeaderText || 'Set Context')}</h5>
              <ul class="source-list">
                ${setPageLi}
                ${sourceLi}
                ${confLi}
              </ul>
            </div>
          </div>
        </div>
      </article>
    `;
  }

  function toggleSources(btn) {
    const card = btn.closest('.track-card');
    if (!card) return;
    const panel = card.querySelector('.source-panel');
    if (!panel) return;
    const open = panel.classList.toggle('open');
    card.classList.toggle('sources-open', open);
    const closedLabel = btn.dataset.closedLabel || 'Context';
    const openLabel = btn.dataset.openLabel || 'Hide';
    btn.textContent = open ? openLabel : closedLabel;
  }

  function toggleSpotifyEmbed(btn, trackId) {
    if (!trackId) return;
    const card = btn.closest('.track-card');
    if (!card) return;
    const body = card.querySelector('.track-body');
    if (!body) return;
    const closedLabel = btn.dataset.closedLabel || 'Spotify';
    const openLabel = btn.dataset.openLabel || 'Hide Spotify';

    let mount = card.querySelector('.spotify-embed');
    if (!mount) {
      mount = document.createElement('div');
      mount.className = 'spotify-embed';
      body.appendChild(mount);
    }

    const isOpen = !!mount.querySelector('iframe');
    if (isOpen) {
      mount.innerHTML = '';
      card.classList.remove('embed-open');
      btn.textContent = closedLabel;
      return;
    }

    mount.innerHTML = `<iframe style="border-radius:0" src="https://open.spotify.com/embed/track/${trackId}?utm_source=generator&theme=0" width="100%" height="80" frameborder="0" allow="autoplay; clipboard-write; encrypted-media" loading="lazy"></iframe>`;
    card.classList.add('embed-open');
    btn.textContent = openLabel;
  }

  // Recurring filters
  const recCards = Array.from(document.querySelectorAll('.rec-card'));
  const recurringGrid = document.getElementById('recurringGrid');
  const recSearchInput = document.getElementById('recSearchInput');
  const recNoResults = document.getElementById('recNoResults');
  const recThresholdStepper = document.getElementById('recThresholdStepper');
  const REC_THRESHOLD_VALUES = parseThresholdLevels(
    ARTIST_DATA.recurringThresholds || recThresholdStepper?.dataset?.thresholds || '1,2,3,5,8,12',
    [1, 2, 3, 5, 8, 12],
  );
  const recConfBtns = Array.from(document.querySelectorAll('.js-rec-conf'));
  let recMin = normalizeThresholdValue(ARTIST_DATA.recurringDefault || REC_THRESHOLD_VALUES[0] || 1, REC_THRESHOLD_VALUES);
  let recConf = String((document.querySelector('.js-rec-conf.active') || {}).dataset?.conf || 'all').toUpperCase();
  if (recConf !== 'ALL' && !CONF_FILTER_LEVELS.includes(recConf)) recConf = 'ALL';

  function recurringCountForCard(card, confFilter) {
    const links = recurringLinksForCard(card, confFilter);
    if (Array.isArray(links)) return links.length;
    const key = String(confFilter || 'ALL').toUpperCase();
    if (key === 'HIGH') return Number(card.dataset.countHigh || 0);
    if (key === 'MEDIUM') return Number(card.dataset.countMedium || 0);
    if (key === 'LOW') return Number(card.dataset.countLow || 0);
    return Number(card.dataset.countAll || card.dataset.count || 0);
  }

  function recurringLinksForCard(card, confFilter) {
    if (!card) return [];
    if (!card._recurringLinksByConf) {
      try {
        const parsed = JSON.parse(card.dataset.setLinks || '{}');
        card._recurringLinksByConf = parsed && typeof parsed === 'object' ? parsed : {};
      } catch (_err) {
        card._recurringLinksByConf = {};
      }
    }
    const key = String(confFilter || 'ALL').toUpperCase();
    const linksByConf = card._recurringLinksByConf || {};
    const links = linksByConf[key] || linksByConf.ALL || [];
    return Array.isArray(links) ? links : [];
  }

  function recurringLinksHtml(links) {
    if (!links.length) return '<div class="empty">No set links available.</div>';
    return `<ul class="source-list">${links.map((link) => {
      const href = escapeHtml(String(link?.href || '').trim());
      const title = escapeHtml(String(link?.title || 'Unknown set'));
      return href
        ? `<li><a href="${href}" target="_blank" rel="noopener">${title}</a></li>`
        : `<li>${title}</li>`;
    }).join('')}</ul>`;
  }

  function syncRecurringCardContext(card, confFilter) {
    if (!card) return;
    const links = recurringLinksForCard(card, confFilter);
    const setCount = links.length;
    const btn = card.querySelector('[data-action="toggle-sources"]');
    const panel = card.querySelector('.source-panel');
    const closedLabel = `Sets (${fmt(setCount)})`;
    if (btn) {
      btn.dataset.closedLabel = closedLabel;
      btn.textContent = card.classList.contains('sources-open')
        ? (btn.dataset.openLabel || 'Hide Sets')
        : closedLabel;
    }
    if (panel) {
      panel.innerHTML = recurringLinksHtml(links);
    }
  }

  function renderRecurringThresholdStepper() {
    if (!recThresholdStepper) return;
    recMin = normalizeThresholdValue(recMin, REC_THRESHOLD_VALUES);
    recThresholdStepper.innerHTML = buildThresholdStepperHtml(
      'btn',
      'rec-threshold-down',
      'rec-threshold-up',
      recMin,
      REC_THRESHOLD_VALUES,
    );
  }

  function applyRecurringFilters() {
    const q = String(recSearchInput?.value || '').trim().toLowerCase();
    const visibleCards = [];
    let visible = 0;
    recCards.forEach((card) => {
      const count = recurringCountForCard(card, recConf);
      const search = String(card.dataset.search || '');
      const confMatch = recConf === 'ALL' ? true : count > 0;
      const show = count >= recMin && confMatch && (!q || search.includes(q));
      syncRecurringCardContext(card, recConf);
      card.style.display = show ? '' : 'none';
      if (show) {
        visible += 1;
        visibleCards.push({
          card,
          count,
          name: String(card.querySelector('.track-title')?.textContent || '').toLowerCase(),
        });
      }
    });
    if (recurringGrid) {
      visibleCards
        .sort((a, b) => (b.count - a.count) || a.name.localeCompare(b.name))
        .forEach((entry) => recurringGrid.appendChild(entry.card));
    }
    if (recNoResults) recNoResults.style.display = visible ? 'none' : 'block';
  }

  recConfBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      recConfBtns.forEach((b) => b.classList.toggle('active', b === btn));
      recConf = String(btn.dataset.conf || 'all').toUpperCase();
      if (recConf !== 'ALL' && !CONF_FILTER_LEVELS.includes(recConf)) recConf = 'ALL';
      applyRecurringFilters();
    });
  });
  if (recSearchInput) recSearchInput.addEventListener('input', applyRecurringFilters);
  renderRecurringThresholdStepper();

  // Set Explorer
  const setGrid = document.getElementById('setGrid');
  const setPager = document.getElementById('setPager');
  const setNoResults = document.getElementById('setNoResults');
  const setSearch = document.getElementById('setSearch');
  const setSortSelect = document.getElementById('setSort');
  const setCards = Array.from(document.querySelectorAll('.set-card'));
  const setComparePanel = document.getElementById('setComparePanel');
  const setCompareBody = document.getElementById('setCompareBody');
  const clearSetCompareBtn = document.getElementById('clearSetCompareBtn');
  const setCompareSelection = [];
  const expandedSetCards = new Set();
  const SETS_PAGE_SIZE = 24;
  let setSort = 'default';
  let setPage = 0;

  function getSetCardByIdx(idx) {
    const key = String(idx || '');
    return setCards.find((card) => String(card.dataset.cardIdx || '') === key) || null;
  }

  function filteredSetCards() {
    const q = String(setSearch?.value || '').trim().toLowerCase();
    const rows = setCards.filter((card) => {
      if (!q) return true;
      return String(card.dataset.search || '').includes(q);
    });

    rows.sort((a, b) => {
      if (setSort === 'tracks') return (parseInt(b.dataset.tracks || '0', 10) || 0) - (parseInt(a.dataset.tracks || '0', 10) || 0);
      if (setSort === 'rate') return (parseFloat(b.dataset.rate || '0') || 0) - (parseFloat(a.dataset.rate || '0') || 0);
      if (setSort === 'duration') return (parseInt(b.dataset.duration || '0', 10) || 0) - (parseInt(a.dataset.duration || '0', 10) || 0);
      return (parseInt(a.dataset.cardIdx || '0', 10) || 0) - (parseInt(b.dataset.cardIdx || '0', 10) || 0);
    });

    return rows;
  }

  function syncSharedHighlights() {
    setCards.forEach((card) => {
      card.querySelectorAll('.set-track').forEach((row) => row.classList.remove('shared'));
    });
    if (setCompareSelection.length !== 2) return;
    const a = getSetCardByIdx(setCompareSelection[0]);
    const b = getSetCardByIdx(setCompareSelection[1]);
    if (!a || !b) return;
    const setA = new Set((a.dataset.trackKeys || '').split('|').filter(Boolean));
    const setB = new Set((b.dataset.trackKeys || '').split('|').filter(Boolean));
    if (!setA.size || !setB.size) return;
    const shared = new Set();
    setA.forEach((k) => { if (setB.has(k)) shared.add(k); });
    [a, b].forEach((card) => {
      card.querySelectorAll('.set-track').forEach((row) => {
        const key = row.dataset.trackKey || '';
        if (shared.has(key)) row.classList.add('shared');
      });
    });
  }

  function renderSetCompare() {
    if (!setCompareSelection.length) {
      setComparePanel.hidden = true;
      return;
    }
    setComparePanel.hidden = false;
    if (setCompareSelection.length < 2) {
      setCompareBody.innerHTML = '1 set selected. Choose one more to compare.';
      syncSharedHighlights();
      return;
    }
    const cardA = getSetCardByIdx(setCompareSelection[0]);
    const cardB = getSetCardByIdx(setCompareSelection[1]);
    if (!cardA || !cardB) {
      setCompareBody.innerHTML = 'Comparison unavailable.';
      return;
    }

    const setA = new Set((cardA.dataset.trackKeys || '').split('|').filter(Boolean));
    const setB = new Set((cardB.dataset.trackKeys || '').split('|').filter(Boolean));
    const shared = [];
    setA.forEach((k) => { if (setB.has(k)) shared.push(k); });
    const union = new Set([...Array.from(setA), ...Array.from(setB)]);
    const overlapPct = union.size ? Math.round((shared.length / union.size) * 100) : 0;
    const rateDelta = Math.abs((parseFloat(cardA.dataset.rate || '0') || 0) - (parseFloat(cardB.dataset.rate || '0') || 0));
    const durDelta = Math.abs((parseInt(cardA.dataset.duration || '0', 10) || 0) - (parseInt(cardB.dataset.duration || '0', 10) || 0));
    const onlyA = Math.max(0, setA.size - shared.length);
    const onlyB = Math.max(0, setB.size - shared.length);
    const titleA = cardA.querySelector('.set-title')?.textContent?.trim() || 'Set A';
    const titleB = cardB.querySelector('.set-title')?.textContent?.trim() || 'Set B';

    setCompareBody.innerHTML = `
      <div style="display:grid;gap:8px;">
        <div style="font-size:12px;color:var(--muted);">${escapeHtml(titleA)} <-> ${escapeHtml(titleB)}</div>
        <div class="compare-grid">
          <div class="compare-card"><span class="compare-value">${shared.length}</span><span class="compare-label">Shared tracks</span></div>
          <div class="compare-card"><span class="compare-value">${overlapPct}%</span><span class="compare-label">Overlap</span></div>
          <div class="compare-card"><span class="compare-value">${Math.round(rateDelta)}%</span><span class="compare-label">ID delta</span></div>
          <div class="compare-card"><span class="compare-value">${Math.round(durDelta / 60)}m</span><span class="compare-label">Duration delta</span></div>
          <div class="compare-card"><span class="compare-value">${onlyA}</span><span class="compare-label">Only in A</span></div>
          <div class="compare-card"><span class="compare-value">${onlyB}</span><span class="compare-label">Only in B</span></div>
        </div>
      </div>`;

    syncSharedHighlights();
  }

  function toggleSetCompare(card) {
    const idx = String(card.dataset.cardIdx || '');
    const pos = setCompareSelection.indexOf(idx);
    if (pos >= 0) setCompareSelection.splice(pos, 1);
    else {
      if (setCompareSelection.length >= 2) setCompareSelection.shift();
      setCompareSelection.push(idx);
    }
    setCards.forEach((c) => c.classList.toggle('selected', setCompareSelection.includes(String(c.dataset.cardIdx))));
    renderSetCompare();
  }

  function syncSetTracklists() {
    setCards.forEach((card) => {
      const idx = String(card.dataset.cardIdx || '');
      const panel = card.querySelector('.set-tracklist');
      const toggleBtn = card.querySelector('.js-tracklist-toggle');
      if (!panel || !toggleBtn) return;
      const isOpen = expandedSetCards.has(idx);
      panel.classList.toggle('open', isOpen);
      toggleBtn.textContent = isOpen ? 'Hide Tracklist' : 'Show Tracklist';
    });
  }

  function applySetFilters() {
    const rows = filteredSetCards();
    const totalPages = Math.max(1, Math.ceil(rows.length / SETS_PAGE_SIZE));
    if (setPage >= totalPages) setPage = totalPages - 1;
    if (setPage < 0) setPage = 0;

    const start = setPage * SETS_PAGE_SIZE;
    const pageRows = rows.slice(start, start + SETS_PAGE_SIZE);
    setGrid.innerHTML = '';
    pageRows.forEach((card) => setGrid.appendChild(card));

    if (setSortSelect) setSortSelect.value = setSort;
    setNoResults.style.display = rows.length ? 'none' : 'block';
    setPager.innerHTML = rows.length
      ? `<button data-action="set-page" data-delta="-1" ${setPage <= 0 ? 'disabled' : ''}>Prev</button><span class="info">Page ${setPage + 1} / ${totalPages} | ${fmt(rows.length)} sets</span><button data-action="set-page" data-delta="1" ${setPage >= totalPages - 1 ? 'disabled' : ''}>Next</button>`
      : '';
    syncSetTracklists();
    renderSetCompare();
  }

  if (setSortSelect) {
    setSortSelect.addEventListener('change', (ev) => {
      setSort = ev.target.value || 'default';
      setPage = 0;
      applySetFilters();
    });
  }

  if (setSearch) {
    setSearch.addEventListener('input', () => {
      setPage = 0;
      applySetFilters();
    });
  }


  if (clearSetCompareBtn) {
    clearSetCompareBtn.addEventListener('click', () => {
      setCompareSelection.splice(0, setCompareSelection.length);
      setCards.forEach((c) => c.classList.remove('selected'));
      syncSharedHighlights();
      renderSetCompare();
    });
  }

  if (setSortSelect) {
    setSort = setSortSelect.value || 'default';
  }

  if (setSearch) {
    applySetFilters();
  }

  // Set Atlas state (master artist-atlas interaction language)
  const atlasSetList = document.getElementById('atlasSetList');
  const atlasSetCards = Array.from(document.querySelectorAll('.atlas-set-card'));
  const atlasSetSearch = document.getElementById('setAtlasSearch');
  const atlasSetNoResults = document.getElementById('atlasSetNoResults');
  const atlasFocusHeader = document.getElementById('setAtlasFocusHeader');
  const atlasRowsEl = document.getElementById('setAtlasRows');
  const atlasPagerEl = document.getElementById('setAtlasPager');
  const atlasNoResults = document.getElementById('setAtlasNoResults');
  const atlasEvidencePanel = document.getElementById('setAtlasEvidencePanel');
  const atlasEvidenceEl = document.getElementById('setAtlasEvidence');
  const atlasEvidenceSummaryEl = document.getElementById('setAtlasEvidenceSummary');
  const atlasEvidencePagerEl = document.getElementById('setAtlasEvidencePager');
  const atlasLensTabsEl = document.getElementById('setAtlasLensTabs');
  const atlasThresholdsEl = document.getElementById('setAtlasThresholds');
  const atlasConfidenceFiltersEl = document.getElementById('setAtlasConfidenceFilters');
  const atlasQueryInput = document.getElementById('setAtlasQuery');
  const atlasSortSelect = document.getElementById('setAtlasSort');
  const atlasTitleEl = document.getElementById('setAtlasTitle');
  const atlasSummaryEl = document.getElementById('setAtlasSummary');
  const artistWideAtlasTracks = Array.isArray(ARTIST_DATA.allAtlasTracks) ? ARTIST_DATA.allAtlasTracks : [];

  const ATLAS_ROWS_PER_PAGE = 10;
  const ATLAS_THRESHOLD_VALUES = [1, 2, 3, 5, 8, 12];
  let selectedAtlasSetIdx = ARTIST_DATA.setAtlasSets.length ? String(ARTIST_DATA.setAtlasSets[0].idx) : null;
  let atlasSelectedSetIds = new Set(selectedAtlasSetIdx ? [selectedAtlasSetIdx] : []);
  let atlasDockedSelectedSetIds = new Set(selectedAtlasSetIdx ? [selectedAtlasSetIdx] : []);
  let atlasPanePointerInside = false;
  let atlasHoverLatchedSetIdx = null;
  let atlasScope = 'set';
  let atlasCompareMode = 'union';
  let atlasLens = 'genres';
  let atlasMin = 1;
  let atlasTrackConf = 'all';
  let atlasQuery = '';
  let atlasSort = 'count';
  let atlasPage = 0;
  let atlasActiveName = null;

  function isHoverCapablePointer() {
    return window.matchMedia('(hover: hover) and (pointer: fine)').matches;
  }

  function captureAtlasSetCardRects() {
    const rects = new Map();
    if (!atlasSetList) return rects;
    atlasSetList.querySelectorAll('.atlas-set-card[data-atlas-set-idx]').forEach((card) => {
      const idx = String(card.dataset.atlasSetIdx || '');
      if (!idx) return;
      rects.set(idx, card.getBoundingClientRect());
    });
    return rects;
  }

  function animateAtlasSetCardReflow(beforeRects) {
    if (!atlasSetList || !beforeRects || !beforeRects.size || !isHoverCapablePointer()) return;
    atlasSetList.querySelectorAll('.atlas-set-card[data-atlas-set-idx]').forEach((card) => {
      const idx = String(card.dataset.atlasSetIdx || '');
      if (!idx) return;
      const before = beforeRects.get(idx);
      if (!before) return;
      const after = card.getBoundingClientRect();
      const dx = before.left - after.left;
      const dy = before.top - after.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;

      card.style.transition = 'none';
      card.style.translate = `${dx}px ${dy}px`;
      card.getBoundingClientRect();
      card.style.transition = 'translate 320ms cubic-bezier(0.22, 1, 0.36, 1)';
      card.style.translate = '0px 0px';
      card.addEventListener('transitionend', () => {
        card.style.removeProperty('transition');
        card.style.removeProperty('translate');
      }, { once: true });
    });
  }

  function syncDockedAtlasSelectedSets(commitAdds = false) {
    const next = new Set(
      Array.from(atlasDockedSelectedSetIds).filter((idx) => atlasSelectedSetIds.has(String(idx)))
    );
    if (commitAdds) {
      for (const idx of atlasSelectedSetIds) {
        next.add(String(idx));
      }
    }
    atlasDockedSelectedSetIds = next;
  }

  function getSelectedAtlasSets() {
    const byId = new Map((ARTIST_DATA.setAtlasSets || []).map((s) => [String(s.idx), s]));
    const selected = Array.from(atlasSelectedSetIds).map((idx) => byId.get(String(idx))).filter(Boolean);
    if (selected.length) return selected;
    const fallback = byId.get(String(selectedAtlasSetIdx || ''));
    return fallback ? [fallback] : [];
  }

  function toggleAtlasSetSelection(idx) {
    const key = String(idx || '');
    if (!key) return;
    if (atlasSelectedSetIds.has(key)) {
      if (atlasSelectedSetIds.size > 1) {
        atlasSelectedSetIds.delete(key);
      }
    } else {
      atlasSelectedSetIds.add(key);
    }
    if (!atlasSelectedSetIds.size && key) atlasSelectedSetIds.add(key);
    if (!atlasSelectedSetIds.has(String(selectedAtlasSetIdx || ''))) {
      selectedAtlasSetIdx = atlasSelectedSetIds.values().next().value || null;
    }
  }

  function extractSpotifyId(url) {
    if (!url) return '';
    const m = String(url).match(/track\\/([A-Za-z0-9]+)/);
    return m ? m[1] : '';
  }

  function getSelectedSet() {
    return getSelectedAtlasSets()[0] || null;
  }

  function setAtlasLenses() {
    return [
      { id: 'genres', label: 'Genres' },
      { id: 'labels', label: 'Labels' },
      { id: 'track-artists', label: 'Artists' },
      { id: 'tracks', label: 'Tracks' },
    ];
  }

  function atlasTrackMergeKey(track) {
    return String(track?.track_key || `${track?.artist || 'Unknown'} - ${track?.title || 'Unknown'}`).trim().toLowerCase();
  }

  function collectUniqueTracks(rows) {
    const merged = new Map();
    for (const row of rows || []) {
      for (const track of (row?.tracks || [])) {
        const key = atlasTrackMergeKey(track);
        if (!merged.has(key)) merged.set(key, track);
      }
    }
    return Array.from(merged.values());
  }

  function renderAtlasConfidenceFilters(tracks) {
    if (!atlasConfidenceFiltersEl) return;
    const total = (tracks || []).length;
    const buttons = [
      `<button class="chip-btn ${atlasTrackConf === 'all' ? 'active' : ''}" data-action="set-atlas-conf" data-conf="all">All (${fmt(total)})</button>`,
    ];
    for (const level of CONF_FILTER_LEVELS) {
      buttons.push(
        `<button class="chip-btn ${atlasTrackConf === level ? 'active' : ''}" data-action="set-atlas-conf" data-conf="${level}">${level}</button>`
      );
    }
    atlasConfidenceFiltersEl.innerHTML = buttons.join('');
  }

  function getSetAtlasCompositeTracks() {
    const selectedSets = getSelectedAtlasSets();
    if (atlasScope === 'set') {
      if (!selectedSets.length) return [];

      const merged = new Map();
      const selectedSetCount = selectedSets.length;
      for (const selectedSet of selectedSets) {
        const selectedSetId = String(selectedSet.idx ?? selectedSet.title ?? '');
        const selectedSetRefKey = selectedSetId || String(selectedSet.title || '');
        for (const track of (selectedSet.tracks || [])) {
          const rawKey = track.track_key || `${track.artist || 'Unknown'} - ${track.title || 'Unknown'}`;
          const mergeKey = String(rawKey).trim().toLowerCase();
          if (!merged.has(mergeKey)) {
            merged.set(mergeKey, {
              track_key: rawKey,
              artist: track.artist || 'Unknown',
              title: track.title || 'Unknown',
              genres: track.genres || [],
              label: track.label || '',
              label_url: track.label_url || '',
              spotify_url: track.spotify_url || '',
              album_art: track.album_art || '',
              selected_appearances: 0,
              selected_artist_count: 0,
              confidence: 'UNCERTAIN',
              confidence_counts: { HIGH: 0, MEDIUM: 0, LOW: 0, UNCERTAIN: 0 },
              _refsMap: new Map(),
              _setIds: new Set(),
            });
          }
          const row = merged.get(mergeKey);
          row.selected_appearances += 1;
          const conf = normalizeConfidence(track.confidence);
          row.confidence_counts[conf] = Number(row.confidence_counts[conf] || 0) + 1;
          row.confidence = primaryConfidenceFromCounts(row.confidence_counts);
          if (!row.spotify_url && track.spotify_url) row.spotify_url = track.spotify_url;
          if (!row.album_art && track.album_art) row.album_art = track.album_art;
          if ((!row.genres || !row.genres.length) && (track.genres || []).length) row.genres = track.genres || [];
          if (!row.label && track.label) row.label = track.label;
          if (!row.label_url && track.label_url) row.label_url = track.label_url;
          if (selectedSetRefKey) row._setIds.add(selectedSetRefKey);

          const setTitle = selectedSet.title || 'Unknown Set';
          if (!row._refsMap.has(selectedSetRefKey)) {
            row._refsMap.set(selectedSetRefKey, {
              artist_name: setTitle,
              set_refs: [],
              source_deep_link: track.source_deep_link || '',
              time_range: track.time_range || track.time || '',
            });
          }
          const ref = row._refsMap.get(selectedSetRefKey);
          const setHref = track.set_anchor || selectedSet.set_href || '';
          if (setHref && !(ref.set_refs || []).some((r) => r.href === setHref)) {
            ref.set_refs.push({
              title: setTitle,
              href: setHref,
              confidence: normalizeConfidence(track.confidence),
            });
          }
          if (!ref.source_deep_link && track.source_deep_link) ref.source_deep_link = track.source_deep_link;
          if (!ref.time_range && (track.time_range || track.time)) ref.time_range = track.time_range || track.time;
        }
      }

      return Array.from(merged.values())
        .map((row) => {
          const refs = Array.from(row._refsMap.values());
          const selectedCoverage = row._setIds instanceof Set ? row._setIds.size : refs.length;
          return {
            ...row,
            selected_artist_count: refs.length,
            _selected_coverage: selectedCoverage,
            selected_refs: refs,
          };
        })
        .filter((row) => {
          if (atlasCompareMode === 'intersection') return Number(row._selected_coverage || 0) === selectedSetCount;
          return Number(row._selected_coverage || 0) > 0;
        });
    }

    const merged = new Map();
    for (const occ of artistWideAtlasTracks) {
      const rawKey = occ.track_key || `${occ.artist || 'Unknown'} - ${occ.title || 'Unknown'}`;
      const mergeKey = String(rawKey).trim().toLowerCase();
      if (!merged.has(mergeKey)) {
        merged.set(mergeKey, {
          track_key: rawKey,
          artist: occ.artist || 'Unknown',
          title: occ.title || 'Unknown',
          genres: occ.genres || [],
          label: occ.label || '',
          label_url: occ.label_url || '',
          spotify_url: occ.spotify_url || '',
          album_art: occ.album_art || '',
          selected_appearances: 0,
          selected_artist_count: 0,
          confidence: 'UNCERTAIN',
          confidence_counts: { HIGH: 0, MEDIUM: 0, LOW: 0, UNCERTAIN: 0 },
          _refsMap: new Map(),
        });
      }
      const row = merged.get(mergeKey);
      row.selected_appearances += 1;
      const conf = normalizeConfidence(occ.confidence);
      row.confidence_counts[conf] = Number(row.confidence_counts[conf] || 0) + 1;
      row.confidence = primaryConfidenceFromCounts(row.confidence_counts);
      if (!row.spotify_url && occ.spotify_url) row.spotify_url = occ.spotify_url;
      if (!row.album_art && occ.album_art) row.album_art = occ.album_art;
      if ((!row.genres || !row.genres.length) && (occ.genres || []).length) row.genres = occ.genres || [];
      if (!row.label && occ.label) row.label = occ.label;
      if (!row.label_url && occ.label_url) row.label_url = occ.label_url;

      const setTitle = occ.set_title || 'Unknown Set';
      if (!row._refsMap.has(setTitle)) {
        row._refsMap.set(setTitle, {
          artist_name: setTitle,
          set_refs: [],
          source_deep_link: occ.source_deep_link || '',
          time_range: occ.time_range || occ.time || '',
        });
      }
      const ref = row._refsMap.get(setTitle);
      const setHref = occ.set_anchor || '';
      if (setHref && !(ref.set_refs || []).some((r) => r.href === setHref)) {
        ref.set_refs.push({
          title: setTitle,
          href: setHref,
          confidence: normalizeConfidence(occ.confidence),
        });
      }
      if (!ref.source_deep_link && occ.source_deep_link) ref.source_deep_link = occ.source_deep_link;
      if (!ref.time_range && (occ.time_range || occ.time)) ref.time_range = occ.time_range || occ.time;
    }

    return Array.from(merged.values()).map((row) => {
      const refs = Array.from(row._refsMap.values());
      return {
        ...row,
        selected_artist_count: refs.length,
        selected_refs: refs,
      };
    });
  }

  function splitSetAtlasHeadingTwoLines(title) {
    const normalized = String(title || '').replace(/\\s+/g, ' ').trim();
    if (!normalized) {
      return { line1: 'No Set Selected', line2: '\u00a0', sizeClass: 'focus-title-md' };
    }

    const words = normalized.split(' ');
    if (words.length === 1) {
      const singleLen = normalized.length;
      const singleClass = singleLen > 42 ? 'focus-title-sm' : (singleLen > 26 ? 'focus-title-md' : 'focus-title-lg');
      return { line1: normalized, line2: '\u00a0', sizeClass: singleClass };
    }

    let splitIdx = 1;
    let bestScore = Number.POSITIVE_INFINITY;
    for (let idx = 1; idx < words.length; idx += 1) {
      const left = words.slice(0, idx).join(' ');
      const right = words.slice(idx).join(' ');
      const delta = Math.abs(left.length - right.length);
      const longest = Math.max(left.length, right.length);
      const shortest = Math.min(left.length, right.length);
      // Bias toward balanced and similarly dense two-line headings.
      const score = delta + (longest > 52 ? (longest - 52) * 2 : 0) + (shortest < 8 ? 8 - shortest : 0);
      if (score < bestScore) {
        bestScore = score;
        splitIdx = idx;
      }
    }

    const line1 = words.slice(0, splitIdx).join(' ');
    const line2 = words.slice(splitIdx).join(' ') || '\u00a0';
    const longestLine = Math.max(line1.length, line2.length);
    const totalLen = normalized.length;
    let sizeClass = 'focus-title-lg';
    if (longestLine > 46 || totalLen > 92) sizeClass = 'focus-title-xs';
    else if (longestLine > 36 || totalLen > 74) sizeClass = 'focus-title-sm';
    else if (longestLine > 27 || totalLen > 56) sizeClass = 'focus-title-md';

    return { line1, line2, sizeClass };
  }

  function renderSetAtlasFocusHeader() {
    if (!atlasFocusHeader) return;
    const selectedSet = getSelectedSet();
    const selectedSets = getSelectedAtlasSets();
    const multi = atlasScope === 'set' && selectedSets.length > 1;
    const modeLabel = atlasCompareMode === 'intersection' ? 'Intersection' : 'Union';
    const scopeTracks = getSetAtlasCompositeTracks();
    const uniqueTracks = new Set(scopeTracks.map((t) => String(t.track_key || `${t.artist || ''}-${t.title || ''}`).toLowerCase()));
    const setsInScope = atlasScope === 'artist' ? (ARTIST_DATA.setAtlasSets || []).length : selectedSets.length;
    const detectionsInScope = atlasScope === 'artist'
      ? artistWideAtlasTracks.length
      : selectedSets.reduce((sum, setObj) => sum + ((Array.isArray(setObj.tracks) ? setObj.tracks.length : 0)), 0);
    const summary = atlasScope === 'artist'
      ? `${fmt(setsInScope)} sets selected in artist-wide scope.`
      : (selectedSets.length <= 1
        ? 'Single set focus. Select another set card to pivot taxonomy.'
        : `${fmt(selectedSets.length)} sets in scope. ${modeLabel} mode active.`);
    const heading = atlasScope === 'artist'
      ? 'Artist Wide Scope'
      : (selectedSets.length > 1 ? `${fmt(selectedSets.length)} Sets Selected` : (selectedSet ? selectedSet.title : 'No Set Selected'));
    const headingLayout = splitSetAtlasHeadingTwoLines(heading);

    atlasFocusHeader.innerHTML = `
      <div class="focus-names single ${headingLayout.sizeClass}">
        <span class="focus-name">
          <span class="focus-line">${escapeHtml(headingLayout.line1)}</span>
          <span class="focus-line">${escapeHtml(headingLayout.line2)}</span>
        </span>
      </div>
      <div class="focus-toolbar">
        <p class="focus-summary">${escapeHtml(summary)}</p>
        <div class="focus-mode">
          <button class="chip-btn ${atlasScope === 'set' ? 'active' : ''}" data-action="set-atlas-scope" data-scope="set">Selected Set</button>
          <button class="chip-btn ${atlasScope === 'artist' ? 'active' : ''}" data-action="set-atlas-scope" data-scope="artist">Artist Wide</button>
          ${multi ? `<button class="chip-btn ${atlasCompareMode === 'union' ? 'active' : ''}" data-action="set-atlas-mode" data-mode="union">Union</button>` : ''}
          ${multi ? `<button class="chip-btn ${atlasCompareMode === 'intersection' ? 'active' : ''}" data-action="set-atlas-mode" data-mode="intersection">Intersection</button>` : ''}
        </div>
      </div>
      <div class="focus-stats">
        <article class="focus-tile"><p>Sets</p><h4>${fmt(setsInScope)}</h4></article>
        <article class="focus-tile"><p>Unique Tracks</p><h4>${fmt(uniqueTracks.size)}</h4></article>
        <article class="focus-tile"><p>Detections</p><h4>${fmt(detectionsInScope)}</h4></article>
        <article class="focus-tile"><p>Scope</p><h4>${atlasScope === 'artist' ? 'Artist' : 'Set'}</h4></article>
      </div>
    `;
  }

  function buildSetAtlasRows(compositeTracks, confFilter = 'all') {
    const lens = atlasLens;
    const bucket = new Map();
    const scopedTracks = tracksWithConfidenceProjection(compositeTracks, confFilter);

    function put(name, track) {
      const key = (name || '').trim() || 'Unknown';
      if (!bucket.has(key)) {
        bucket.set(key, { name: key, tracksMap: new Map(), plays: 0 });
      }
      const row = bucket.get(key);
      const trackId = track.track_key || `${track.artist || 'Unknown'} - ${track.title || 'Unknown'}`;
      if (!row.tracksMap.has(trackId)) {
        row.tracksMap.set(trackId, track);
      }
      row.plays += Number(track.selected_appearances || 0);
    }

    for (const track of scopedTracks) {
      if (lens === 'genres') {
        const genres = (track.genres || []).length ? track.genres : ['Unknown Genre'];
        for (const g of genres) put(g, track);
      } else if (lens === 'labels') {
        put(track.label || 'Unknown Label', track);
      } else if (lens === 'track-artists') {
        put(track.artist || 'Unknown Artist', track);
      } else {
        put(`${track.artist || 'Unknown'} - ${track.title || 'Unknown'}`, track);
      }
    }

    let rows = Array.from(bucket.values()).map((row) => {
      const tracks = Array.from(row.tracksMap.values());
      const count = lens === 'tracks' ? Number(row.plays || 0) : tracks.length;
      return { name: row.name, tracks, count };
    });

    rows = rows.filter((row) => Number(row.count || 0) >= Number(atlasMin || 1));

    const q = atlasQuery.trim().toLowerCase();
    if (q) {
      rows = rows.filter((row) => row.name.toLowerCase().includes(q));
    }

    if (atlasSort === 'alpha') {
      rows.sort((a, b) => a.name.localeCompare(b.name));
    } else {
      rows.sort((a, b) => (Number(b.count || 0) - Number(a.count || 0)) || a.name.localeCompare(b.name));
    }

    return rows;
  }

  function resolveSetAtlasLabelDiscogsUrl(row) {
    if (atlasLens !== 'labels') return '';
    const target = String(row.name || '').trim().toLowerCase();
    if (!target || target === 'unknown label') return '';
    const isHttpUrl = (url) => url.startsWith('http://') || url.startsWith('https://');

    const tracks = row.tracks || [];
    const matching = tracks.find((track) => {
      const name = String(track.label || '').trim().toLowerCase();
      const url = String(track.label_url || '').trim();
      return name === target && isHttpUrl(url);
    });
    if (matching) return String(matching.label_url || '').trim();

    const fallback = tracks.find((track) => isHttpUrl(String(track.label_url || '').trim()));
    return fallback ? String(fallback.label_url || '').trim() : '';
  }

  function buildSetAtlasTrackSetLinks(track) {
    const links = [];
    const seen = new Set();
    for (const ref of (track.selected_refs || [])) {
      for (const setRef of (ref.set_refs || [])) {
        const href = String(setRef.href || '').trim();
        if (!href) continue;
        const title = String(setRef.title || ref.artist_name || 'Set').trim() || 'Set';
        const key = `${href}|||${title.toLowerCase()}`;
        if (seen.has(key)) continue;
        seen.add(key);
        links.push({ title, href });
      }
    }
    return links;
  }

  function renderSetAtlasTrackCard(track) {
    const image = track.album_art || '';
    const spotifyId = extractSpotifyId(track.spotify_url || '');
    const conf = normalizeConfidence(track.confidence);
    const confColor = { HIGH: '#00e676', MEDIUM: '#ffd740', LOW: '#ff9100', UNCERTAIN: '#757575' }[conf] || '#757575';
    const setLinks = buildSetAtlasTrackSetLinks(track);
    const sourceLabel = `Sets (${fmt(setLinks.length)})`;
    const sourceList = setLinks.length
      ? `<ul class="source-list">${setLinks.map((setLink) => `<li><a href="${escapeHtml(setLink.href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(setLink.title)}</a></li>`).join('')}</ul>`
      : '<div class="empty">No set links available.</div>';

    return `
      <article class="track-card" data-track-key="${escapeHtml(track.track_key || '')}">
        <div class="track-art">${image ? `<img src="${image}" alt="${escapeHtml(track.title || 'Track')}" loading="lazy" />` : ''}</div>
        <div class="track-body">
          <h4 class="track-title">${escapeHtml(track.artist || 'Unknown')} - ${escapeHtml(track.title || 'Unknown')}</h4>
          <p class="muted">Confidence <span class="set-track-conf" style="border-color:${confColor}; color:${confColor};">${escapeHtml(conf)}</span></p>
          <div class="actions">
            ${spotifyId ? `<button data-action="set-atlas-spotify" data-url="${escapeHtml(track.spotify_url || '')}">Spotify</button>` : ''}
            <button data-action="set-atlas-sources" data-closed-label="${escapeHtml(sourceLabel)}" data-open-label="Hide Sets">${escapeHtml(sourceLabel)}</button>
          </div>
          <div class="source-panel">${sourceList}</div>
        </div>
      </article>
    `;
  }

  function renderInlineSetAtlasEvidence(row) {
    const tracksAll = [...(row.tracks || [])].sort((a, b) => {
      return (Number(b.selected_appearances || 0) - Number(a.selected_appearances || 0))
        || (Number(b.selected_artist_count || 0) - Number(a.selected_artist_count || 0))
        || String(a.artist || '').localeCompare(String(b.artist || ''));
    });
    const tracks = filterTracksByConfidence(tracksAll, atlasTrackConf);
    const labelDiscogsUrl = resolveSetAtlasLabelDiscogsUrl(row);
    const headActions = labelDiscogsUrl
      ? `<div class="inline-head-actions"><a class="discogs" href="${escapeHtml(labelDiscogsUrl)}" target="_blank" rel="noopener noreferrer">Label Page</a></div>`
      : '';
    const countLabel = atlasTrackConf === 'all'
      ? `${fmt(tracks.length)} matching tracks`
      : `${fmt(tracks.length)} / ${fmt(tracksAll.length)} matching tracks`;
    const head = `
      <div class="inline-head-row">
        <p class="inline-head">${escapeHtml(row.name)} | ${countLabel}</p>
        ${headActions}
      </div>
    `;

    if (!tracks.length) {
      return `
        <div class="inline-evidence">
          ${head}
          <div class="empty">No evidence tracks match the selected confidence filter.</div>
        </div>
      `;
    }

    return `
      <div class="inline-evidence">
        ${head}
        <div class="evidence-grid">${tracks.map((track) => renderSetAtlasTrackCard(track)).join('')}</div>
      </div>
    `;
  }

  function renderSetAtlas() {
    const setObj = getSelectedSet();
    renderSetAtlasFocusHeader();

    if (atlasScope !== 'artist' && !setObj) {
      atlasTitleEl.textContent = 'Taxonomy Atlas';
      atlasSummaryEl.textContent = 'No selected set.';
      atlasRowsEl.innerHTML = '<div class="empty">No selected set available.</div>';
      atlasPagerEl.innerHTML = '';
      if (atlasConfidenceFiltersEl) atlasConfidenceFiltersEl.innerHTML = '';
      atlasNoResults.style.display = 'block';
      if (atlasEvidencePanel) atlasEvidencePanel.classList.remove('open');
      if (atlasEvidenceEl) atlasEvidenceEl.innerHTML = '';
      if (atlasEvidenceSummaryEl) atlasEvidenceSummaryEl.textContent = '';
      if (atlasEvidencePagerEl) atlasEvidencePagerEl.innerHTML = '';
      return;
    }

    if (atlasScope === 'artist') {
      atlasTitleEl.textContent = 'Taxonomy Atlas';
      atlasSummaryEl.textContent = `${fmt(artistWideAtlasTracks.length)} detections across ${fmt((ARTIST_DATA.setAtlasSets || []).length)} sets`;
    } else {
      const selectedSets = getSelectedAtlasSets();
      atlasTitleEl.textContent = 'Taxonomy Atlas';
      if (selectedSets.length <= 1) {
        atlasSummaryEl.textContent = `${setObj.title || 'Set'} | ${fmt(setObj.tracks_count || 0)} tracks | ${Math.round(Number(setObj.recognition_rate || 0))}% match`;
      } else {
        const detections = selectedSets.reduce((sum, item) => sum + Number(item.tracks_count || 0), 0);
        atlasSummaryEl.textContent = `${fmt(selectedSets.length)} sets | ${fmt(detections)} detections in selected scope`;
      }
    }

    const composite = getSetAtlasCompositeTracks();
    const rowsAll = buildSetAtlasRows(composite, 'all');
    const rows = buildSetAtlasRows(composite, atlasTrackConf);
    const isTracksLens = atlasLens === 'tracks';

    if (atlasLensTabsEl) {
      atlasLensTabsEl.innerHTML = setAtlasLenses().map((lens) => {
        const active = lens.id === atlasLens;
        return `<button class="chip-btn ${active ? 'active' : ''}" data-action="set-atlas-lens" data-lens="${lens.id}">${lens.label}</button>`;
      }).join('');
    }

    if (atlasThresholdsEl) {
      atlasMin = normalizeThresholdValue(atlasMin, ATLAS_THRESHOLD_VALUES);
      atlasThresholdsEl.innerHTML = `<div class="threshold-stepper">${
        buildThresholdStepperHtml(
          'chip-btn',
          'set-atlas-threshold-down',
          'set-atlas-threshold-up',
          atlasMin,
          ATLAS_THRESHOLD_VALUES,
        )
      }</div>`;
    }
    renderAtlasConfidenceFilters(collectUniqueTracks(rowsAll));

    if (isTracksLens) {
      atlasActiveName = null;
      const tracksUniverse = rowsAll.map((row) => (row.tracks || [])[0]).filter(Boolean);
      const tracks = rows.map((row) => (row.tracks || [])[0]).filter(Boolean);
      const countLabel = atlasTrackConf === 'all'
        ? `${fmt(tracks.length)} matching tracks`
        : `${fmt(tracks.length)} / ${fmt(tracksUniverse.length)} matching tracks`;
      if (!tracks.length) {
        atlasRowsEl.innerHTML = '<div class="empty">No tracks match current scope, query, and confidence filter.</div>';
      } else {
        atlasRowsEl.innerHTML = `
          <div class="inline-evidence">
            <p class="inline-head">Tracks | ${countLabel}</p>
            <div class="evidence-grid">${tracks.map((track) => renderSetAtlasTrackCard(track)).join('')}</div>
          </div>
        `;
      }
      atlasPagerEl.innerHTML = '';
      atlasNoResults.style.display = rows.length ? 'none' : 'block';
      if (atlasEvidencePanel) atlasEvidencePanel.classList.remove('open');
      if (atlasEvidenceEl) atlasEvidenceEl.innerHTML = '';
      if (atlasEvidenceSummaryEl) atlasEvidenceSummaryEl.textContent = '';
      if (atlasEvidencePagerEl) atlasEvidencePagerEl.innerHTML = '';
      return;
    }

    const maxCount = rows.length ? Math.max(...rows.map((r) => Number(r.count || 0))) : 1;
    const totalPages = Math.max(1, Math.ceil(rows.length / ATLAS_ROWS_PER_PAGE));
    if (atlasPage >= totalPages) atlasPage = totalPages - 1;
    if (atlasPage < 0) atlasPage = 0;

    const start = atlasPage * ATLAS_ROWS_PER_PAGE;
    const pageRows = rows.slice(start, start + ATLAS_ROWS_PER_PAGE);

    const activeExists = rows.some((r) => r.name === atlasActiveName);
    if (!activeExists) atlasActiveName = null;

    if (!rows.length) {
      atlasRowsEl.innerHTML = '<div class="empty">No taxonomy entries match current scope and query.</div>';
    } else {
      atlasRowsEl.innerHTML = pageRows.map((row) => {
        const pct = maxCount ? ((Number(row.count || 0) / maxCount) * 100) : 0;
        const active = row.name === atlasActiveName;
        const base = `
          <div class="row-line">
            <span class="row-name" title="${escapeHtml(row.name)}">${escapeHtml(row.name)}</span>
            <div class="bar"><span style="width:${pct}%;"></span></div>
            <span class="row-count">${fmt(row.count)}</span>
          </div>
        `;
        const trigger = `<button class="row-hit" data-action="set-atlas-row" data-name="${escapeHtml(row.name)}">${base}</button>`;
        const inline = active ? renderInlineSetAtlasEvidence(row) : '';
        return `
          <article class="quant-row ${active ? 'active' : ''}">
            ${trigger}
            ${inline}
          </article>
        `;
      }).join('');
    }

    atlasPagerEl.innerHTML = rows.length
      ? `<button data-action="set-atlas-page" data-delta="-1" ${atlasPage <= 0 ? 'disabled' : ''}>Prev</button><span class="info">Page ${atlasPage + 1} / ${totalPages}</span><button data-action="set-atlas-page" data-delta="1" ${atlasPage >= totalPages - 1 ? 'disabled' : ''}>Next</button>`
      : '';

    atlasNoResults.style.display = rows.length ? 'none' : 'block';
    if (atlasEvidencePanel) atlasEvidencePanel.classList.remove('open');
    if (atlasEvidenceEl) atlasEvidenceEl.innerHTML = '';
    if (atlasEvidenceSummaryEl) atlasEvidenceSummaryEl.textContent = '';
    if (atlasEvidencePagerEl) atlasEvidencePagerEl.innerHTML = '';
  }

  function applyAtlasSetList() {
    const beforeRects = captureAtlasSetCardRects();
    const q = String(atlasSetSearch?.value || '').trim().toLowerCase();
    const visible = [];
    atlasSetCards.forEach((card) => {
      const show = !q || String(card.dataset.search || '').includes(q);
      card.style.display = show ? '' : 'none';
      if (show) visible.push(card);
    });

    atlasSetNoResults.style.display = visible.length ? 'none' : 'block';

    const visibleIds = new Set(visible.map((card) => String(card.dataset.atlasSetIdx || '')));
    if (atlasHoverLatchedSetIdx && !visibleIds.has(String(atlasHoverLatchedSetIdx))) {
      atlasHoverLatchedSetIdx = null;
    }
    atlasSelectedSetIds = new Set(Array.from(atlasSelectedSetIds).filter((idx) => visibleIds.has(String(idx))));
    if (atlasScope !== 'artist' && !atlasSelectedSetIds.size && visible.length) {
      const firstVisible = String(visible[0].dataset.atlasSetIdx || '');
      if (firstVisible) atlasSelectedSetIds.add(firstVisible);
    }
    syncDockedAtlasSelectedSets(false);

    const visibleDockedSelected = visible.filter((card) => atlasDockedSelectedSetIds.has(String(card.dataset.atlasSetIdx || '')));
    const shouldDockSelected = visibleDockedSelected.length > 0;
    atlasSetList?.classList.toggle('selected-dock', shouldDockSelected);
    const orderedVisible = shouldDockSelected
      ? [...visibleDockedSelected, ...visible.filter((card) => !atlasDockedSelectedSetIds.has(String(card.dataset.atlasSetIdx || '')))]
      : visible;
    orderedVisible.forEach((card) => atlasSetList?.appendChild(card));
    orderedVisible.forEach((card, idx) => {
      card.style.zIndex = String(orderedVisible.length - idx);
    });

    const selectedVisible = orderedVisible.some((card) => atlasSelectedSetIds.has(String(card.dataset.atlasSetIdx || '')));
    if (!selectedVisible) {
      if (atlasScope === 'artist') {
        selectedAtlasSetIdx = null;
        atlasSelectedSetIds = new Set();
        syncDockedAtlasSelectedSets(false);
      } else {
        selectedAtlasSetIdx = orderedVisible.length ? String(orderedVisible[0].dataset.atlasSetIdx || '') : null;
        atlasSelectedSetIds = new Set(selectedAtlasSetIdx ? [selectedAtlasSetIdx] : []);
        syncDockedAtlasSelectedSets(true);
      }
      atlasActiveName = null;
      atlasPage = 0;
    } else if (!atlasSelectedSetIds.has(String(selectedAtlasSetIdx || ''))) {
      selectedAtlasSetIdx = atlasSelectedSetIds.values().next().value || null;
    }

    atlasSetCards.forEach((card) => {
      const cardIdx = String(card.dataset.atlasSetIdx || '');
      const isFocused = cardIdx === String(selectedAtlasSetIdx || '');
      const isSelected = atlasSelectedSetIds.has(cardIdx);
      const isHoverLatched = cardIdx === String(atlasHoverLatchedSetIdx || '');
      card.classList.toggle('focus', isFocused);
      card.classList.toggle('selected', isSelected);
      card.classList.toggle('hover-latched', isHoverLatched);
      const toggleBtn = card.querySelector('[data-action="set-atlas-toggle"]');
      if (toggleBtn) {
        toggleBtn.classList.toggle('active', isSelected);
        toggleBtn.textContent = isSelected ? 'In Scope' : 'Add to Scope';
      }
    });

    renderSetAtlas();
    animateAtlasSetCardReflow(beforeRects);
  }

  if (atlasSetSearch) {
    atlasSetSearch.addEventListener('input', () => {
      applyAtlasSetList();
    });
  }

  if (atlasQueryInput) {
    atlasQueryInput.addEventListener('input', (ev) => {
      atlasQuery = ev.target.value || '';
      atlasPage = 0;
      atlasActiveName = null;
      renderSetAtlas();
    });
  }

  if (atlasSortSelect) {
    atlasSortSelect.addEventListener('change', (ev) => {
      atlasSort = ev.target.value || 'count';
      atlasPage = 0;
      atlasActiveName = null;
      renderSetAtlas();
    });
  }

  if (atlasSetList) {
    atlasSetList.addEventListener('pointerenter', () => {
      if (!isHoverCapablePointer()) return;
      atlasPanePointerInside = true;
    });

    atlasSetList.addEventListener('pointermove', (ev) => {
      if (!isHoverCapablePointer()) return;
      atlasPanePointerInside = true;
      if (!atlasHoverLatchedSetIdx) return;
      const target = ev.target;
      const card = target instanceof Element ? target.closest('.atlas-set-card') : null;
      const hoveredIdx = card ? String(card.dataset.atlasSetIdx || '') : null;
      if (hoveredIdx === atlasHoverLatchedSetIdx) return;
      atlasHoverLatchedSetIdx = null;
      applyAtlasSetList();
    });

    atlasSetList.addEventListener('pointerleave', () => {
      if (!isHoverCapablePointer()) return;
      atlasPanePointerInside = false;
      atlasHoverLatchedSetIdx = null;
      syncDockedAtlasSelectedSets(true);
      applyAtlasSetList();
      if (atlasDockedSelectedSetIds.size) {
        atlasSetList.scrollTo({ top: 0, behavior: 'smooth' });
      }
    });
  }

  // Unified click delegation
  document.addEventListener('click', (ev) => {
    const actionEl = ev.target.closest('[data-action]');
    if (actionEl) {
      const action = actionEl.dataset.action;

      if (action === 'toggle-sources') {
        toggleSources(actionEl);
        return;
      }

      if (action === 'spotify-embed') {
        toggleSpotifyEmbed(actionEl, actionEl.dataset.trackId || '');
        return;
      }

      if (action === 'rec-threshold-down' || action === 'rec-threshold-up') {
        const direction = action === 'rec-threshold-up' ? 1 : -1;
        recMin = stepThresholdValue(recMin, REC_THRESHOLD_VALUES, direction);
        renderRecurringThresholdStepper();
        applyRecurringFilters();
        return;
      }

      if (action === 'set-atlas-scope') {
        const scope = actionEl.dataset.scope || 'set';
        atlasScope = (scope === 'artist') ? 'artist' : 'set';
        atlasPage = 0;
        atlasActiveName = null;
        if (atlasScope === 'artist') {
          selectedAtlasSetIdx = null;
          atlasSelectedSetIds = new Set();
          atlasDockedSelectedSetIds = new Set();
          atlasPanePointerInside = false;
          atlasHoverLatchedSetIdx = null;
        }
        applyAtlasSetList();
        return;
      }

      if (action === 'set-atlas-mode') {
        const mode = actionEl.dataset.mode || 'union';
        if (mode === 'union' || mode === 'intersection') {
          atlasCompareMode = mode;
          atlasPage = 0;
          atlasActiveName = null;
          renderSetAtlas();
        }
        return;
      }

      if (action === 'set-atlas-toggle') {
        ev.preventDefault();
        ev.stopPropagation();
        const idx = String(actionEl.dataset.atlasSetIdx || actionEl.closest('.atlas-set-card')?.dataset.atlasSetIdx || '');
        if (!idx) return;
        const deferDockAdds = isHoverCapablePointer()
          && atlasPanePointerInside
          && Boolean(actionEl.closest('#atlasSetList'));
        atlasHoverLatchedSetIdx = isHoverCapablePointer() ? idx : null;
        atlasScope = 'set';
        selectedAtlasSetIdx = idx;
        toggleAtlasSetSelection(idx);
        if (!deferDockAdds) {
          syncDockedAtlasSelectedSets(true);
        }
        atlasPage = 0;
        atlasActiveName = null;
        applyAtlasSetList();
        return;
      }

      if (action === 'set-atlas-lens') {
        const lens = actionEl.dataset.lens || 'genres';
        atlasLens = lens;
        atlasPage = 0;
        atlasActiveName = null;
        renderSetAtlas();
        return;
      }

      if (action === 'set-atlas-threshold') {
        const v = Number(actionEl.dataset.threshold || 1);
        atlasMin = normalizeThresholdValue(Number.isFinite(v) && v > 0 ? v : 1, ATLAS_THRESHOLD_VALUES);
        atlasPage = 0;
        atlasActiveName = null;
        renderSetAtlas();
        return;
      }

      if (action === 'set-atlas-threshold-down' || action === 'set-atlas-threshold-up') {
        const direction = action === 'set-atlas-threshold-up' ? 1 : -1;
        atlasMin = stepThresholdValue(atlasMin, ATLAS_THRESHOLD_VALUES, direction);
        atlasPage = 0;
        atlasActiveName = null;
        renderSetAtlas();
        return;
      }

      if (action === 'set-atlas-conf') {
        const conf = String(actionEl.dataset.conf || 'all').toUpperCase();
        atlasTrackConf = conf === 'ALL' ? 'all' : (CONF_FILTER_LEVELS.includes(conf) ? conf : 'all');
        renderSetAtlas();
        return;
      }

      if (action === 'set-page') {
        setPage += Number(actionEl.dataset.delta || 0);
        applySetFilters();
        setGrid.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return;
      }

      if (action === 'set-atlas-page') {
        atlasPage += Number(actionEl.dataset.delta || 0);
        renderSetAtlas();
        return;
      }

      if (action === 'set-atlas-row') {
        const name = actionEl.dataset.name || null;
        atlasActiveName = (atlasActiveName === name) ? null : name;
        renderSetAtlas();
        return;
      }

      if (action === 'set-atlas-sources') {
        const card = actionEl.closest('.track-card');
        const panel = card ? card.querySelector('.source-panel') : null;
        if (!panel) return;
        const closedLabel = actionEl.dataset.closedLabel || 'Sets';
        const openLabel = actionEl.dataset.openLabel || 'Hide Sets';
        const isOpen = card.classList.contains('sources-open');
        if (isOpen) {
          panel.classList.remove('open');
          card.classList.remove('sources-open');
          card.style.removeProperty('--open-art-height');
          card.style.removeProperty('--open-card-height');
          card.style.removeProperty('--open-body-height');
          card.style.removeProperty('--open-source-height');
          actionEl.textContent = closedLabel;
          return;
        }

        const existingEmbed = card.querySelector('.spotify-embed');
        if (existingEmbed) {
          existingEmbed.remove();
          card.classList.remove('embed-open');
          card.style.removeProperty('--open-embed-height');
          card.querySelectorAll('[data-action="set-atlas-spotify"]').forEach((btn) => {
            if (!btn.closest('.spotify-embed')) btn.textContent = 'Spotify';
          });
        }

        const art = card.querySelector('.track-art');
        const body = card.querySelector('.track-body');
        const actionsWrap = body ? body.querySelector('.actions') : null;
        const cardHeight = Math.round(card.getBoundingClientRect().height);
        if (cardHeight > 0) {
          const targetSourceHeight = 91.2;
          const controls = actionsWrap || body;
          const actionsHeight = controls ? Math.max(28, Math.round(controls.getBoundingClientRect().height)) : 32;
          const bodyHeight = Math.min(cardHeight, actionsHeight + targetSourceHeight);
          const artHeight = Math.max(0, cardHeight - bodyHeight);
          const sourceHeight = Math.max(0, bodyHeight - actionsHeight);
          card.style.setProperty('--open-card-height', `${cardHeight}px`);
          card.style.setProperty('--open-art-height', `${Math.max(0, artHeight)}px`);
          card.style.setProperty('--open-body-height', `${Math.max(0, bodyHeight)}px`);
          card.style.setProperty('--open-source-height', `${Math.max(0, sourceHeight)}px`);
        } else if (art) {
          card.style.setProperty('--open-art-height', `${Math.round(art.getBoundingClientRect().height)}px`);
        }

        panel.classList.add('open');
        card.classList.add('sources-open');
        actionEl.textContent = openLabel;
        return;
      }

      if (action === 'set-atlas-spotify') {
        const card = actionEl.closest('.track-card');
        if (!card) return;
        if (card.classList.contains('sources-open')) {
          const panel = card.querySelector('.source-panel');
          if (panel) panel.classList.remove('open');
          card.classList.remove('sources-open');
          card.style.removeProperty('--open-art-height');
          card.style.removeProperty('--open-card-height');
          card.style.removeProperty('--open-body-height');
          card.style.removeProperty('--open-source-height');
          card.querySelectorAll('[data-action="set-atlas-sources"]').forEach((btn) => {
            btn.textContent = btn.dataset.closedLabel || 'Sets';
          });
        }

        const existing = card.querySelector('.spotify-embed');
        if (existing) {
          existing.remove();
          card.classList.remove('embed-open');
          card.style.removeProperty('--open-art-height');
          card.style.removeProperty('--open-card-height');
          card.style.removeProperty('--open-body-height');
          card.style.removeProperty('--open-embed-height');
          card.style.removeProperty('--open-source-height');
          card.querySelectorAll('[data-action="set-atlas-spotify"]').forEach((btn) => {
            if (!btn.closest('.spotify-embed')) btn.textContent = 'Spotify';
          });
          return;
        }

        const id = extractSpotifyId(actionEl.dataset.url || '');
        if (!id) return;

        const art = card.querySelector('.track-art');
        const body = card.querySelector('.track-body');
        const actionsWrap = body ? body.querySelector('.actions') : null;
        const cardHeight = Math.round(card.getBoundingClientRect().height);
        if (cardHeight > 0) {
          const targetEmbedHeight = 91.2;
          const controls = actionsWrap || body;
          const actionsHeight = controls ? Math.max(28, Math.round(controls.getBoundingClientRect().height)) : 32;
          const bodyHeight = Math.min(cardHeight, actionsHeight + targetEmbedHeight);
          const artHeight = Math.max(0, cardHeight - bodyHeight);
          const embedHeight = Math.max(0, bodyHeight - actionsHeight);
          card.style.setProperty('--open-card-height', `${cardHeight}px`);
          card.style.setProperty('--open-art-height', `${Math.max(0, artHeight)}px`);
          card.style.setProperty('--open-body-height', `${Math.max(0, bodyHeight)}px`);
          card.style.setProperty('--open-embed-height', `${Math.max(0, embedHeight)}px`);
        } else if (art) {
          card.style.setProperty('--open-art-height', `${Math.round(art.getBoundingClientRect().height)}px`);
        }

        const div = document.createElement('div');
        div.className = 'spotify-embed';
        div.innerHTML = `<iframe src="https://open.spotify.com/embed/track/${id}?utm_source=generator&theme=0" allow="autoplay; clipboard-write; encrypted-media"></iframe>`;
        const mount = card.querySelector('.track-body');
        if (!mount) return;
        mount.appendChild(div);
        card.classList.add('embed-open');
        actionEl.textContent = 'Hide Spotify';
        return;
      }
    }

    const atlasSetCard = ev.target.closest('.atlas-set-card');
    if (atlasSetCard && atlasSetCard.style.display !== 'none') {
      if (ev.target.closest('a,button')) return;
      const idx = String(atlasSetCard.dataset.atlasSetIdx || '');
      const additive = ev.shiftKey || ev.metaKey || ev.ctrlKey;
      const deferDockAdds = isHoverCapablePointer() && atlasPanePointerInside;
      atlasHoverLatchedSetIdx = isHoverCapablePointer() ? idx : null;
      atlasScope = 'set';
      selectedAtlasSetIdx = idx;
      if (additive) {
        toggleAtlasSetSelection(idx);
      } else {
        atlasSelectedSetIds = new Set(idx ? [idx] : []);
      }
      if (!atlasSelectedSetIds.size && idx) atlasSelectedSetIds = new Set([idx]);
      if (!deferDockAdds) {
        syncDockedAtlasSelectedSets(true);
      }
      atlasActiveName = null;
      atlasPage = 0;
      applyAtlasSetList();
      return;
    }

    const toggleBtn = ev.target.closest('.js-tracklist-toggle');
    if (toggleBtn) {
      const card = toggleBtn.closest('.set-card');
      const idx = String(card?.dataset.cardIdx || '');
      const panel = card?.querySelector('.set-tracklist');
      if (!panel || !idx) return;
      if (expandedSetCards.has(idx)) expandedSetCards.delete(idx);
      else expandedSetCards.add(idx);
      panel.classList.toggle('open', expandedSetCards.has(idx));
      toggleBtn.textContent = expandedSetCards.has(idx) ? 'Hide Tracklist' : 'Show Tracklist';
      return;
    }

    const compareBtn = ev.target.closest('.js-set-compare');
    if (compareBtn) {
      const card = compareBtn.closest('.set-card');
      if (card) toggleSetCompare(card);
      return;
    }
  });

  // ?q=... and #sets-section behavior
  const params = new URLSearchParams(window.location.search);
  const q = params.get('q');
  if (q && setSearch) {
    setSearch.value = q;
    applySetFilters();
  }
  if (window.location.hash === '#sets-section' || q) {
    const section = document.getElementById('sets-section');
    if (section) {
      setTimeout(() => section.scrollIntoView({ behavior: 'smooth', block: 'start' }), 90);
    }
  }

  applyRecurringFilters();
  applySetFilters();
  applyAtlasSetList();
  fitArtistHeroTitle();
  startArtistHeroRail();
  const artistHeroVisual = document.getElementById('artistHeroVisual');
  const artistHeroResizeObserver = typeof ResizeObserver === 'undefined'
    ? null
    : new ResizeObserver(() => fitArtistHeroTitle());
  if (artistHeroVisual && artistHeroResizeObserver) {
    artistHeroResizeObserver.observe(artistHeroVisual);
  }
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => fitArtistHeroTitle());
  }
  window.addEventListener('resize', startArtistHeroRail);
  window.addEventListener('resize', fitArtistHeroTitle);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopArtistHeroRail();
    else {
      fitArtistHeroTitle();
      startArtistHeroRail();
    }
  });
})();
  </script>
</body>
</html>
"""

    html = (
        html_template
        .replace("__TITLE__", f"{esc(artist_name)} - Artist Explorer")
        .replace("__CSS__", _artist_css())
        .replace("__ARTIST_BODY_STYLE__", artist_body_style)
        .replace("__ARTIST_NAME__", esc(artist_name))
        .replace("__ARTIST_HERO_IMAGE__", hero_image_html)
        .replace("__ARTIST_HERO_NAME_PRIMARY__", esc(hero_name_primary))
        .replace("__ARTIST_HERO_NAME_SECONDARY__", hero_name_secondary_html)
        .replace("__ARTIST_HERO_SIDE__", hero_side_html)
        .replace("__SETS_ANALYZED__", str(len(successful)))
        .replace("__UNIQUE_TRACKS__", str(unique_tracks))
        .replace("__TOTAL_DETECTIONS__", str(total_appearances))
        .replace("__RECURRING_TRACKS__", str(recurring_tracks))
        .replace("__RECURRING_FILTER_BTNS__", recurring_filter_btns)
        .replace("__RECURRING_CONF_FILTER_BTNS__", recurring_conf_filter_btns)
        .replace("__RECURRING_CARDS__", "".join(recurring_cards_html))
        .replace("__ATLAS_SET_CARDS__", "".join(atlas_set_cards_html))
        .replace("__SET_CARDS__", "".join(set_cards_html))
        .replace("__FAILED_HTML__", failed_html)
        .replace("__GENERATED__", esc(generated))
        .replace("__PAYLOAD_JSON__", to_json(payload))
    )

    output_path.write_text(html, encoding="utf-8")
    print(f"Saved artist explorer HTML: {output_path}")
    return output_path
