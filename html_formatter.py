"""Generate interactive HTML setlist output."""

import json
from html import escape
from pathlib import Path
from datetime import datetime
from config import Config
from output_formatter import format_time


# Confidence level configuration: label, CSS class, hex color
CONFIDENCE_CONFIG = {
    'HIGH':      ('HIGH',      'conf-high',     '#00e676'),
    'MEDIUM':    ('MEDIUM',    'conf-medium',   '#ffd740'),
    'LOW':       ('LOW',       'conf-low',      '#ff9100'),
    'UNCERTAIN': ('UNCERTAIN', 'conf-uncertain','#757575'),
}


def _esc(text: str) -> str:
    """Escape text for safe insertion into HTML."""
    return escape(str(text), quote=True)


def _build_track_data(enriched_tracks: list, total_duration: float) -> list:
    """Convert enriched tracks to a list of plain dicts for rendering."""
    rows = []
    for i, item in enumerate(enriched_tracks, 1):
        track = item['track']
        meta  = item['metadata']

        end_t = track.end_time if track.end_time is not None else total_duration
        start_pct = (track.start_time / total_duration * 100) if total_duration else 0
        width_pct  = max(0.5, ((end_t - track.start_time) / total_duration * 100)) if total_duration else 0

        rows.append({
            'position':    i,
            'title':       track.title,
            'artist':      track.artist,
            'start_time':  track.start_time,
            'end_time':    end_t,
            'start_fmt':   format_time(track.start_time),
            'confidence':  track.confidence,
            'detections':  track.detection_count,
            'density':     track.cluster_density,
            'spotify_url': meta.get('spotify_url') or '',
            'youtube_url': meta.get('youtube_url') or '',
            'discogs_url': meta.get('discogs_url') or '',
            'start_pct':   start_pct,
            'width_pct':   width_pct,
        })
    return rows


def _render_timeline(tracks: list, total_duration: float) -> str:
    """Render the mix timeline as HTML segments."""
    segments_html = []
    for t in tracks:
        conf   = t['confidence']
        cfg    = CONFIDENCE_CONFIG.get(conf, CONFIDENCE_CONFIG['UNCERTAIN'])
        color  = cfg[2]
        label  = _esc(f"{t['artist']} — {t['title']}")
        time_l = _esc(t['start_fmt'])

        segments_html.append(
            f'<div class="tl-segment" '
            f'style="left:{t["start_pct"]:.3f}%;width:{t["width_pct"]:.3f}%;background:{color};" '
            f'title="{time_l}  {label}" '
            f'data-conf="{_esc(conf)}">'
            f'</div>'
        )
    return '\n'.join(segments_html)


def _render_track_cards(tracks: list) -> str:
    """Render individual track cards as HTML."""
    cards = []
    for t in tracks:
        conf   = t['confidence']
        cfg    = CONFIDENCE_CONFIG.get(conf, CONFIDENCE_CONFIG['UNCERTAIN'])
        color  = cfg[2]
        cls    = cfg[1]

        artist_esc = _esc(t['artist'])
        title_esc  = _esc(t['title'])
        copy_val   = _esc(f"{t['artist']} - {t['title']}")

        # Platform links
        links_html = []
        if t['spotify_url']:
            links_html.append(
                f'<a href="{_esc(t["spotify_url"])}" class="btn btn-spotify" target="_blank" rel="noopener">Spotify</a>'
            )
        if t['youtube_url']:
            links_html.append(
                f'<a href="{_esc(t["youtube_url"])}" class="btn btn-youtube" target="_blank" rel="noopener">YouTube</a>'
            )
        if t['discogs_url']:
            links_html.append(
                f'<a href="{_esc(t["discogs_url"])}" class="btn btn-discogs" target="_blank" rel="noopener">Discogs</a>'
            )
        links_block = ''.join(links_html)

        density_pct = f"{t['density']:.0%}"

        cards.append(f'''
<div class="track-card" data-conf="{_esc(conf)}" data-search="{artist_esc.lower()} {title_esc.lower()}">
  <div class="track-num">{t["position"]}</div>
  <div class="track-time">{_esc(t["start_fmt"])}</div>
  <div class="track-info">
    <div class="track-title-row">
      <span class="track-artist">{artist_esc}</span>
      <span class="track-sep"> — </span>
      <span class="track-title">{title_esc}</span>
    </div>
    <div class="track-meta">
      <span class="conf-badge {cls}" style="border-color:{color};color:{color};">{_esc(conf)}</span>
      <span class="track-stats">{t["detections"]} detections &middot; {density_pct} density</span>
    </div>
  </div>
  <div class="track-actions">
    {links_block}
    <button class="btn btn-copy" onclick="copyTrack(this)" data-text="{copy_val}" title="Copy to clipboard">&#128203;</button>
  </div>
</div>''')

    return '\n'.join(cards)


def _render_stats(counts: dict, total: int, recognized: int) -> str:
    """Render the stats bar."""
    recognition_rate = (recognized / total * 100) if total else 0
    pills = []
    for level in ('HIGH', 'MEDIUM', 'LOW', 'UNCERTAIN'):
        cnt = counts.get(level, 0)
        if cnt == 0:
            continue
        cfg   = CONFIDENCE_CONFIG[level]
        color = cfg[2]
        pills.append(
            f'<span class="stat-pill" style="border-color:{color};color:{color};">'
            f'{cnt} {_esc(level)}</span>'
        )
    pills_html = ''.join(pills)

    return f'''
<div class="stats-bar">
  <span class="stat-total">{total} tracks</span>
  <span class="stat-rate">{recognition_rate:.0f}% identified</span>
  {pills_html}
</div>'''


CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: #0d0d0d;
  color: #e0e0e0;
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
  font-size: 14px;
  line-height: 1.5;
}

a { color: inherit; text-decoration: none; }

.container {
  max-width: 960px;
  margin: 0 auto;
  padding: 24px 16px 64px;
}

/* ── Header ── */
.header { margin-bottom: 32px; }

.header h1 {
  font-size: clamp(18px, 4vw, 28px);
  font-weight: 700;
  letter-spacing: -0.5px;
  color: #ffffff;
  margin-bottom: 10px;
  word-break: break-word;
}

.header-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 24px;
  font-size: 13px;
  color: #888;
}

.header-meta a { color: #00e676; }
.header-meta a:hover { text-decoration: underline; }

/* ── Stats bar ── */
.stats-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 16px;
  padding: 12px 16px;
  background: #161616;
  border: 1px solid #222;
  border-radius: 8px;
  margin-bottom: 24px;
  font-size: 13px;
}

.stat-total { font-weight: 700; color: #fff; font-size: 15px; }
.stat-rate  { color: #888; }

.stat-pill {
  padding: 2px 10px;
  border-radius: 12px;
  border: 1px solid;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.3px;
}

/* ── Timeline ── */
.timeline-wrap {
  margin-bottom: 28px;
}

.timeline-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #555;
  margin-bottom: 6px;
}

.timeline-bar {
  position: relative;
  height: 20px;
  background: #1a1a1a;
  border-radius: 4px;
  overflow: hidden;
  border: 1px solid #222;
}

.tl-segment {
  position: absolute;
  top: 0;
  height: 100%;
  opacity: 0.85;
  transition: opacity 0.15s;
  cursor: default;
}
.tl-segment:hover { opacity: 1; }

.timeline-ticks {
  display: flex;
  justify-content: space-between;
  margin-top: 4px;
  font-size: 10px;
  color: #444;
}

/* ── Controls ── */
.controls {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 20px;
  align-items: center;
}

.search-input {
  flex: 1;
  min-width: 200px;
  padding: 8px 14px;
  background: #161616;
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  color: #e0e0e0;
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s;
}
.search-input:focus { border-color: #00e676; }
.search-input::placeholder { color: #444; }

.filter-buttons { display: flex; gap: 6px; flex-wrap: wrap; }

.filter-btn {
  padding: 6px 12px;
  background: #161616;
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  color: #888;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  letter-spacing: 0.2px;
}
.filter-btn:hover { border-color: #444; color: #ccc; }
.filter-btn.active { background: #1e2e1e; border-color: #00e676; color: #00e676; }

/* ── Track cards ── */
.tracklist { display: flex; flex-direction: column; gap: 4px; }

.track-card {
  display: grid;
  grid-template-columns: 36px 52px 1fr auto;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: #111;
  border: 1px solid #1e1e1e;
  border-radius: 6px;
  transition: background 0.15s, border-color 0.15s;
}
.track-card:hover { background: #161616; border-color: #2a2a2a; }
.track-card[hidden] { display: none; }

.track-num {
  font-size: 12px;
  color: #444;
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

.track-time {
  font-size: 12px;
  font-family: 'Courier New', monospace;
  color: #666;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.track-info { min-width: 0; }

.track-title-row {
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 3px;
}

.track-artist { font-weight: 600; color: #fff; }
.track-sep    { color: #444; }
.track-title  { color: #ccc; }

.track-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.conf-badge {
  padding: 1px 7px;
  border-radius: 10px;
  border: 1px solid;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.5px;
  white-space: nowrap;
}

.track-stats {
  font-size: 11px;
  color: #555;
}

.track-actions {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.btn {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 600;
  border: 1px solid;
  cursor: pointer;
  transition: opacity 0.15s;
  white-space: nowrap;
  background: transparent;
  font-family: inherit;
}
.btn:hover { opacity: 0.8; }

.btn-spotify { color: #1db954; border-color: #1db954; }
.btn-youtube { color: #ff0000; border-color: #ff0000; }
.btn-discogs { color: #e8472f; border-color: #e8472f; }
.btn-copy    { color: #666; border-color: #333; font-size: 13px; padding: 3px 8px; }

/* ── No-results message ── */
.no-results {
  padding: 40px;
  text-align: center;
  color: #444;
  display: none;
}

/* ── Footer ── */
.footer {
  margin-top: 48px;
  padding-top: 24px;
  border-top: 1px solid #1e1e1e;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 32px;
  font-size: 12px;
  color: #444;
}

.footer span { white-space: nowrap; }

/* ── Copy toast ── */
#toast {
  position: fixed;
  bottom: 24px;
  right: 24px;
  background: #1e2e1e;
  border: 1px solid #00e676;
  color: #00e676;
  padding: 8px 18px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  opacity: 0;
  transition: opacity 0.3s;
  pointer-events: none;
  z-index: 9999;
}
#toast.show { opacity: 1; }

/* ── Responsive ── */
@media (max-width: 600px) {
  .track-card { grid-template-columns: 28px 44px 1fr; }
  .track-actions { grid-column: 1 / -1; justify-content: flex-start; }
  .track-num { display: none; }
}
"""

JS = """
// ── Search ──
const searchInput = document.getElementById('searchInput');
searchInput.addEventListener('input', applyFilters);

// ── Filter buttons ──
const filterBtns = document.querySelectorAll('.filter-btn');
filterBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    filterBtns.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    applyFilters();
  });
});

function applyFilters() {
  const query  = searchInput.value.toLowerCase().trim();
  const active = document.querySelector('.filter-btn.active');
  const conf   = active ? active.dataset.conf : 'all';

  const cards   = document.querySelectorAll('.track-card');
  let   visible = 0;

  cards.forEach(card => {
    const matchConf   = conf === 'all' || card.dataset.conf === conf;
    const matchSearch = !query || card.dataset.search.includes(query);
    const show = matchConf && matchSearch;
    card.hidden = !show;
    if (show) visible++;
  });

  document.getElementById('noResults').style.display = visible === 0 ? 'block' : 'none';

  // Dim timeline segments that don't match conf filter
  document.querySelectorAll('.tl-segment').forEach(seg => {
    const match = conf === 'all' || seg.dataset.conf === conf;
    seg.style.opacity = match ? '0.85' : '0.15';
  });
}

// ── Copy to clipboard ──
function copyTrack(btn) {
  const text = btn.dataset.text;
  if (!navigator.clipboard) {
    // Fallback for older browsers
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity  = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    showToast();
    return;
  }
  navigator.clipboard.writeText(text).then(showToast);
}

function showToast() {
  const toast = document.getElementById('toast');
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 1800);
}
"""


class HtmlFormatter:
    """Generate self-contained interactive HTML setlist pages."""

    def __init__(self, checkpoint_manager=None):
        self.output_dir = checkpoint_manager.output_dir if checkpoint_manager else Config.OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_html(self, enriched_tracks: list, mix_info: dict, filename: str = None) -> Path:
        """
        Save setlist as a self-contained interactive HTML page.

        The page includes:
        - Mix metadata header
        - Confidence statistics bar
        - Visual mix timeline (colour-coded by confidence)
        - Searchable, filterable tracklist
        - Per-track platform links (Spotify / YouTube / Discogs)
        - Copy-to-clipboard for each track

        Args:
            enriched_tracks: List of dicts with 'track' (Track) and 'metadata' keys.
            mix_info:         Dict with 'title', 'uploader', 'duration', 'url' keys.
            filename:         Base filename (without extension).

        Returns:
            Path to the saved HTML file.
        """
        if not filename:
            filename = f"setlist_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        output_path = self.output_dir / f"{filename}.html"

        total_duration = mix_info.get('duration', 0) or 1  # avoid div/0
        tracks = _build_track_data(enriched_tracks, total_duration)

        # Confidence counts
        from collections import Counter
        counts    = Counter(t['confidence'] for t in tracks)
        total     = len(tracks)
        recognized = sum(1 for t in tracks if t['title'] != 'Unknown Track')

        # Section HTML
        stats_html    = _render_stats(counts, total, recognized)
        timeline_html = _render_timeline(tracks, total_duration)
        cards_html    = _render_track_cards(tracks)

        # Timeline tick marks (0%, 25%, 50%, 75%, 100%)
        ticks_html = ''.join(
            f'<span>{format_time(total_duration * pct / 100)}</span>'
            for pct in (0, 25, 50, 75, 100)
        )

        # Header meta
        title_esc    = _esc(mix_info.get('title', 'DJ Set'))
        uploader_esc = _esc(mix_info.get('uploader', 'Unknown'))
        duration_fmt = format_time(total_duration)
        source_url   = _esc(mix_info.get('url', ''))
        generated    = datetime.now().strftime('%Y-%m-%d %H:%M')

        source_link = (
            f'<a href="{source_url}" target="_blank" rel="noopener">{source_url}</a>'
            if source_url else 'N/A'
        )

        # Filter buttons
        filter_buttons = '<button class="filter-btn active" data-conf="all">All</button>'
        for level in ('HIGH', 'MEDIUM', 'LOW', 'UNCERTAIN'):
            if counts.get(level, 0) > 0:
                filter_buttons += (
                    f'<button class="filter-btn" data-conf="{level}">'
                    f'{level} ({counts[level]})</button>'
                )

        # Algorithm parameter footer
        footer_items = [
            f'Min cluster size: {Config.MIN_CLUSTER_SIZE}',
            f'Min cluster density: {Config.MIN_CLUSTER_DENSITY:.0%}',
            f'Min unknown gap: {Config.MIN_UNKNOWN_GAP_SIZE} segments',
            f'Generated: {generated}',
            'DJ Set Setlist Generator',
        ]
        footer_spans = ''.join(f'<span>{_esc(item)}</span>' for item in footer_items)

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Setlist: {title_esc}</title>
  <style>{CSS}</style>
</head>
<body>

<div class="container">

  <!-- Header -->
  <header class="header">
    <h1>{title_esc}</h1>
    <div class="header-meta">
      <span>By <strong>{uploader_esc}</strong></span>
      <span>Duration: {_esc(duration_fmt)}</span>
      <span>Source: {source_link}</span>
      <span>Generated: {_esc(generated)}</span>
    </div>
  </header>

  <!-- Stats -->
  {stats_html}

  <!-- Timeline -->
  <div class="timeline-wrap">
    <div class="timeline-label">Mix Timeline</div>
    <div class="timeline-bar">
      {timeline_html}
    </div>
    <div class="timeline-ticks">{ticks_html}</div>
  </div>

  <!-- Controls -->
  <div class="controls">
    <input id="searchInput" class="search-input" type="search"
           placeholder="Search by artist or title&hellip;" autocomplete="off">
    <div class="filter-buttons">
      {filter_buttons}
    </div>
  </div>

  <!-- Tracklist -->
  <div class="tracklist" id="tracklist">
    {cards_html}
  </div>
  <div class="no-results" id="noResults">No tracks match your filter.</div>

  <!-- Footer -->
  <footer class="footer">
    {footer_spans}
  </footer>

</div><!-- /.container -->

<div id="toast">Copied!</div>

<script>{JS}</script>
</body>
</html>"""

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)

        print(f"Saved HTML:     {output_path}")
        return output_path
