"""Shared styling layer for artist/set detail explorer pages."""

from __future__ import annotations

import re
from pathlib import Path


_THEME_BLOCK_START = "<!-- MASTER_DETAIL_THEME_START -->"
_THEME_BLOCK_END = "<!-- MASTER_DETAIL_THEME_END -->"


_DETAIL_THEME_BASE_CSS = """
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
  --section-pad: clamp(16px, 2vw, 24px);
}

html, body {
  background: var(--bg) !important;
  color: var(--ink) !important;
  font-family: 'Manrope', sans-serif !important;
}

body::before,
body::after {
  display: none !important;
  content: none !important;
}

a {
  color: inherit;
  text-decoration: none;
}

.container.xp-shell {
  max-width: 1480px !important;
  margin: 0 auto !important;
  padding: 0 var(--gutter) 72px !important;
}

.header,
.stats-strip,
.stats-bar,
.timeline-wrap,
.journey-section,
.controls,
.sets-controls,
section,
.player-wrap,
.track-card,
.set-card,
.track-row,
.sig-score,
.sig-staple-card,
.sig-trend-row,
.failed-item,
.master-artist-card,
.master-played-card,
.master-matrix-scroll,
.master-connection-area,
#distribFilterBar,
.genre-tracks-panel,
.hm-tooltip,
#tl-tooltip,
#journey-tooltip,
.player-pill,
.insight-panel,
.set-compare-panel {
  background: var(--paper) !important;
  border: 1px solid var(--line) !important;
  border-radius: var(--radius) !important;
  box-shadow: none !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}

.header,
.timeline-wrap,
.journey-section,
.controls,
.sets-controls,
section,
#distribFilterBar,
.insight-panel {
  padding: var(--section-pad) !important;
}

.explorer-heading,
.set-card-title,
.artist-name,
h1, h2, h3 {
  letter-spacing: 0.01em;
  color: var(--ink) !important;
}

.header-meta,
.page-subtitle,
.track-stats,
.track-time,
.source-link,
.sig-score-desc,
.master-hint,
.conn-row-meta,
.footer,
.empty,
.genre-bar-count,
.master-artist-stats,
.master-played-artist-name,
.explorer-subline,
.insight-label {
  color: var(--muted) !important;
}

.artist-name {
  margin: 24px 0 8px !important;
  font-size: clamp(32px, 5vw, 64px) !important;
  line-height: 0.96 !important;
  text-transform: uppercase;
  letter-spacing: 0.01em;
}

.page-subtitle {
  font-family: 'Space Mono', monospace !important;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.header h1 {
  font-size: clamp(26px, 4.2vw, 52px) !important;
  line-height: 1.04 !important;
  text-transform: uppercase;
}

.header-meta,
.track-time,
.time-range,
.source-link,
.set-card-pill,
.stl-track-time,
.stl-track-conf,
.genre-bar-count,
.insight-block-title,
.insight-label,
.stat-label {
  font-family: 'Space Mono', monospace !important;
}

.header-meta a,
.track-time-link,
.source-link:hover,
.staple-sets-link,
.master-artist-name,
.master-pair-name,
.stat-value,
.sig-score-value,
.pill-high,
.set-card-title:hover,
.track-artist,
.btn-spotify,
.btn-play,
.master-set-artist-label,
.insight-value {
  color: var(--lime) !important;
}

.set-card-title,
.master-artist-name,
.master-set-artist-label {
  text-decoration: none;
}

.set-card-title:hover,
.master-artist-name:hover,
.master-set-artist-label:hover {
  text-decoration: underline;
  text-decoration-color: var(--line);
}

.sort-btn,
.filter-btn,
.distrib-tab,
.distrib-pg-btn,
.staple-filter-btn,
.track-facet-btn,
.sc-toggle-btn,
.sc-compare-btn,
.btn,
.chip-btn,
.explorer-tab {
  border: 1px solid var(--line) !important;
  border-radius: var(--radius) !important;
  background: var(--paper-2) !important;
  color: var(--muted) !important;
  box-shadow: none !important;
  text-transform: uppercase;
  letter-spacing: 0.02em;
}

.sort-btn:hover,
.filter-btn:hover,
.distrib-tab:hover,
.distrib-pg-btn:hover:not(:disabled),
.staple-filter-btn:hover,
.track-facet-btn:hover,
.sc-toggle-btn:hover,
.sc-compare-btn:hover,
.btn:hover,
.chip-btn:hover,
.explorer-tab:hover {
  border-color: var(--ink) !important;
  color: var(--ink) !important;
}

.sort-btn.active,
.filter-btn.active,
.distrib-tab--active,
.staple-filter-btn--active,
.track-facet-btn--active,
.explorer-tab.is-active,
.set-card--selected {
  border-color: var(--lime) !important;
  color: var(--lime) !important;
  background: #0f1210 !important;
}

.search-input,
#searchInput,
#setSearch,
.distrib-search-input,
.track-sort-select {
  border: 1px solid var(--line) !important;
  border-radius: var(--radius) !important;
  background: #171717 !important;
  color: var(--ink) !important;
  font-family: 'Space Mono', monospace !important;
}

.search-input:focus,
#searchInput:focus,
#setSearch:focus,
.distrib-search-input:focus,
.track-sort-select:focus {
  border-color: var(--lime) !important;
  outline: none !important;
}

.search-input::placeholder,
#searchInput::placeholder,
#setSearch::placeholder,
.distrib-search-input::placeholder {
  color: #767676 !important;
}

.xp-tag,
.master-genre-tag,
.master-dj-chip,
.set-card-pill,
.count-badge,
.app-count {
  border: 1px solid var(--line) !important;
  border-radius: 999px !important;
  background: #151515 !important;
  color: var(--muted) !important;
}

.timeline-bar,
.journey-chart,
.set-mini-timeline,
.stl-node-mini-timeline {
  border: 1px solid var(--line) !important;
  border-radius: var(--radius) !important;
  background: #101010 !important;
}

.player-wrap {
  background: #0f0f0f !important;
}

.player-pill {
  background: rgba(10, 10, 10, 0.92) !important;
}

.track-card,
.set-card,
.sig-staple-card,
.genre-bar-item {
  transition: border-color 0.18s ease, background 0.18s ease, transform 0.18s ease !important;
}

.track-card:hover,
.set-card:hover,
.sig-staple-card:hover,
.genre-bar-item:hover {
  border-color: #f0f0f0 !important;
  background: #151515 !important;
}

.detail-view .conf-high { color: #73ff96 !important; border-color: #73ff96 !important; }
.detail-view .conf-medium { color: #ffd166 !important; border-color: #ffd166 !important; }
.detail-view .conf-low { color: #ffa94d !important; border-color: #ffa94d !important; }
.detail-view .conf-uncertain { color: #8f8f8f !important; border-color: #8f8f8f !important; }

.detail-view .ext-link-spotify { color: #1db954 !important; }
.detail-view .ext-link-youtube { color: #ff5252 !important; }
.detail-view .ext-link-discogs { color: #f36a3d !important; }

.set-compare-body .xp-tag,
.staple-sets-link,
.track-title-link {
  text-decoration: none;
}

@media (max-width: 1220px) {
  .set-cockpit {
    grid-template-columns: 1fr !important;
  }
  .set-cockpit-sidebar {
    position: static !important;
  }
}
"""


_SET_THEME_CSS = """
.detail-view--set .explorer-hero {
  border-top: 2px solid var(--lime);
}

.detail-view--set .set-cockpit {
  display: grid;
  grid-template-columns: minmax(360px, 0.95fr) minmax(500px, 1.05fr);
  gap: 16px;
  align-items: start;
}

.detail-view--set .set-cockpit-main,
.detail-view--set .set-cockpit-sidebar {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.detail-view--set .set-cockpit-sidebar {
  position: sticky;
  top: 16px;
}

.detail-view--set .tracklist {
  gap: 8px !important;
}
"""


_ARTIST_THEME_CSS = """
.detail-view--artist .stats-strip {
  border-top: 2px solid var(--lime);
  margin-top: 12px !important;
}

.detail-view--artist .artist-tabs {
  margin-top: 14px !important;
}

.detail-view--artist .sets-grid {
  gap: 12px !important;
}

.detail-view--artist .set-card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

.detail-view--artist .set-card-actions-left,
.detail-view--artist .set-card-actions-right {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
"""


def _append_body_class(html: str, class_name: str) -> str:
    body_match = re.search(r"<body([^>]*)>", html, flags=re.IGNORECASE)
    if not body_match:
        return html
    attrs = body_match.group(1)
    if re.search(r'class\s*=', attrs, flags=re.IGNORECASE):
        def repl_class(match: re.Match) -> str:
            quote = match.group(1)
            classes = match.group(2).split()
            if class_name not in classes:
                classes.append(class_name)
            return f'class={quote}{" ".join(classes)}{quote}'

        new_attrs = re.sub(
            r'class\s*=\s*(["\'])(.*?)\1',
            repl_class,
            attrs,
            count=1,
            flags=re.IGNORECASE,
        )
    else:
        new_attrs = f'{attrs} class="{class_name}"'
    return html[: body_match.start()] + f"<body{new_attrs}>" + html[body_match.end() :]


def apply_master_detail_theme(output_path: Path, view: str) -> None:
    """Inject shared detail theme CSS into generated detail page."""
    html = output_path.read_text(encoding="utf-8")
    view_class = f"detail-view detail-view--{view}"
    html = _append_body_class(html, view_class)

    per_view_css = _SET_THEME_CSS if view == "set" else _ARTIST_THEME_CSS
    theme_block = (
        f"{_THEME_BLOCK_START}\n"
        f"<style id=\"masterDetailTheme\">{_DETAIL_THEME_BASE_CSS}{per_view_css}</style>\n"
        f"{_THEME_BLOCK_END}"
    )

    block_pattern = re.compile(
        re.escape(_THEME_BLOCK_START) + r".*?" + re.escape(_THEME_BLOCK_END),
        flags=re.DOTALL,
    )
    if block_pattern.search(html):
        html = block_pattern.sub(theme_block, html)
    elif "</head>" in html:
        html = html.replace("</head>", f"{theme_block}\n</head>", 1)
    else:
        html = theme_block + "\n" + html

    output_path.write_text(html, encoding="utf-8")
