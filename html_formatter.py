"""Generate interactive HTML setlist output."""

from html import escape
from pathlib import Path
from datetime import datetime
from urllib.parse import quote, urlparse, parse_qs
from config import Config
from output_formatter import format_time, serialize_track


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


def _build_track_data(enriched_tracks: list, total_duration: float, source_url: str = '') -> list:
    """Convert enriched tracks to a list of plain dicts for rendering."""
    rows = []
    for i, item in enumerate(enriched_tracks, 1):
        t = serialize_track(item, i, source_url)

        # Apply end_time fallback and reformat for HTML (end_time must be a concrete value)
        end_t = t['end_time'] if t['end_time'] is not None else total_duration
        t['end_time'] = end_t
        t['end_time_formatted'] = format_time(end_t)

        # HTML-specific timeline layout fields
        t['start_pct'] = (t['start_time'] / total_duration * 100) if total_duration else 0
        t['width_pct'] = max(0.5, ((end_t - t['start_time']) / total_duration * 100)) if total_duration else 0

        rows.append(t)
    return rows


def _detect_platform(source_url: str) -> tuple:
    """Detect platform and extract embed identifier from source URL.

    Returns:
        (platform, embed_id) where platform is 'youtube', 'soundcloud', or 'unknown'
        For YouTube: embed_id is the video ID
        For SoundCloud: embed_id is the full track URL (needed for SC widget)
    """
    if not source_url:
        return ('unknown', '')
    try:
        parsed = urlparse(source_url)
        host = parsed.netloc.lower()
        if 'youtube.com' in host:
            qs = parse_qs(parsed.query)
            video_ids = qs.get('v', [])
            if video_ids:
                return ('youtube', video_ids[0])
        elif 'youtu.be' in host:
            video_id = parsed.path.lstrip('/')
            if video_id:
                return ('youtube', video_id)
        elif 'soundcloud.com' in host:
            # SC widget needs the full track URL (without timestamp fragment)
            clean_url = source_url.split('#')[0]
            return ('soundcloud', clean_url)
    except Exception:
        pass
    return ('unknown', '')


def _render_player(platform: str, embed_id: str) -> str:
    """Return the embedded player HTML for the detected platform."""
    if platform == 'youtube':
        return '''<div class="player-wrap" id="playerWrap">
  <div id="ytPlayer"></div>
</div>'''
    elif platform == 'soundcloud':
        encoded_url = quote(embed_id, safe='')
        return (
            f'<div class="player-wrap sc" id="playerWrap">\n'
            f'  <iframe id="scWidget" scrolling="no" frameborder="no" allow="autoplay"\n'
            f'    src="https://w.soundcloud.com/player/?url={encoded_url}'
            f'&auto_play=false&show_artwork=true&color=%2300e676&hide_related=true">\n'
            f'  </iframe>\n'
            f'</div>'
        )
    return ''


def _render_player_js(platform: str, embed_id: str, tracks: list) -> str:
    """Return platform-specific player JS including trackTimes array and now-playing logic."""
    if platform == 'unknown':
        return ''

    # Build trackTimes array from tracks list
    track_times_entries = []
    for t in tracks:
        track_times_entries.append(
            f'  {{idx: "{t["position"]}", start: {t["start_time"]:.3f}, end: {t["end_time"]:.3f}}}'
        )
    track_times_js = 'const trackTimes = [\n' + ',\n'.join(track_times_entries) + '\n];'

    now_playing_js = """
let nowPlayingInterval = null;

function startNowPlaying() {
  if (nowPlayingInterval) return;
  nowPlayingInterval = setInterval(updateNowPlaying, 1000);
}

function stopNowPlaying() {
  clearInterval(nowPlayingInterval);
  nowPlayingInterval = null;
}

function updateNowPlaying() {
  if (typeof player !== 'undefined' && player && player.getCurrentTime) {
    highlightTrackAt(player.getCurrentTime());
    return;
  }
  if (typeof widget !== 'undefined' && widget && widget.getPosition) {
    widget.getPosition(function(pos) { highlightTrackAt(pos / 1000); });
  }
}

function highlightTrackAt(seconds) {
  const match = trackTimes.find(t => seconds >= t.start && seconds < t.end);
  if (match && match.idx !== String(activeIdx)) {
    clearActive();
    setActive(String(match.idx));
  }
}
"""

    if platform == 'youtube':
        return f"""<script>
{track_times_js}

var tag = document.createElement('script');
tag.src = "https://www.youtube.com/iframe_api";
var firstScriptTag = document.getElementsByTagName('script')[0];
firstScriptTag.parentNode.insertBefore(tag, firstScriptTag);

var player;
function onYouTubeIframeAPIReady() {{
  player = new YT.Player('ytPlayer', {{
    videoId: '{embed_id}',
    playerVars: {{ autoplay: 0, modestbranding: 1, rel: 0 }},
    events: {{
      onReady: function() {{ console.log('YT player ready'); }},
      onStateChange: function(e) {{
        if (e.data === YT.PlayerState.PLAYING) startNowPlaying();
        else stopNowPlaying();
      }}
    }}
  }});
}}

function seekPlayer(seconds) {{
  if (player && player.seekTo) {{
    player.seekTo(seconds, true);
    player.playVideo();
  }}
}}
{now_playing_js}
</script>"""

    elif platform == 'soundcloud':
        return f"""<script src="https://w.soundcloud.com/player/api.js"></script>
<script>
{track_times_js}

var widget = SC.Widget(document.getElementById('scWidget'));
widget.bind(SC.Widget.Events.READY, function() {{
  console.log('SC widget ready');
}});
widget.bind(SC.Widget.Events.PLAY, function() {{ startNowPlaying(); }});
widget.bind(SC.Widget.Events.PAUSE, function() {{ stopNowPlaying(); }});
widget.bind(SC.Widget.Events.FINISH, function() {{ stopNowPlaying(); }});

function seekPlayer(seconds) {{
  widget.seekTo(seconds * 1000);
  widget.play();
}}
{now_playing_js}
</script>"""

    return ''


def _render_timeline(tracks: list, total_duration: float) -> str:
    """Render the mix timeline as HTML segments."""
    segments_html = []
    for t in tracks:
        conf   = t['confidence']
        cfg    = CONFIDENCE_CONFIG.get(conf, CONFIDENCE_CONFIG['UNCERTAIN'])
        color  = cfg[2]

        segments_html.append(
            f'<div class="tl-segment" '
            f'style="left:{t["start_pct"]:.3f}%;width:{t["width_pct"]:.3f}%;background:{color};" '
            f'data-conf="{_esc(conf)}" '
            f'data-track-idx="{t["position"]}" '
            f'data-artist="{_esc(t["artist"])}" '
            f'data-title="{_esc(t["title"])}" '
            f'data-time="{_esc(t["start_time_formatted"])} \u2013 {_esc(t["end_time_formatted"])}" '
            f'data-color="{_esc(color)}">'
            f'</div>'
        )
    return '\n'.join(segments_html)


def _render_track_cards(tracks: list, platform: str = 'unknown') -> str:
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

        density_pct = f"{t['cluster_density']:.0%}"

        deep_link = t.get('source_deep_link') or ''
        start_esc = _esc(t['start_time_formatted'])
        end_esc   = _esc(t['end_time_formatted'])
        start_seconds = t['start_time']

        if platform in ('youtube', 'soundcloud'):
            # Timestamp seeks the embedded player instead of opening a new tab
            time_cell = (
                f'<div class="track-time">'
                f'<a class="track-time-link" href="#" '
                f'onclick="seekPlayer({start_seconds:.3f}); return false;" '
                f'title="Jump to this track">{start_esc}</a>'
                f'<span class="track-time-sep"> \u2013 </span>{end_esc}'
                f'</div>'
            )
        elif deep_link:
            time_cell = (
                f'<div class="track-time">'
                f'<a class="track-time-link" '
                f'href="{_esc(deep_link)}" target="_blank" rel="noopener" '
                f'title="Open at this timestamp">{start_esc}</a>'
                f'<span class="track-time-sep"> \u2013 </span>{end_esc}'
                f'</div>'
            )
        else:
            time_cell = (
                f'<div class="track-time">'
                f'{start_esc}<span class="track-time-sep"> \u2013 </span>{end_esc}'
                f'</div>'
            )

        play_btn = (
            f'<button class="btn btn-play" onclick="seekPlayer({start_seconds:.3f})" '
            f'title="Play from here">&#9654;</button>'
            if platform in ('youtube', 'soundcloud') else ''
        )

        cards.append(f'''
<div class="track-card" data-conf="{_esc(conf)}" data-track-idx="{t["position"]}" data-search="{artist_esc.lower()} {title_esc.lower()}">
  <div class="track-num">{t["position"]}</div>
  {time_cell}
  <div class="track-info">
    <div class="track-title-row">
      <span class="track-artist">{artist_esc}</span>
      <span class="track-sep"> — </span>
      <span class="track-title">{title_esc}</span>
    </div>
    <div class="track-meta">
      <span class="conf-badge {cls}" style="border-color:{color};color:{color};">{_esc(conf)}</span>
      <span class="track-stats">{t["detection_count"]} detections &middot; {density_pct} density</span>
    </div>
  </div>
  <div class="track-actions">
    {play_btn}
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
  cursor: pointer;
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
  grid-template-columns: 36px max-content 1fr auto;
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

.track-time-link {
  color: #00e676;
  text-decoration: none;
  display: inline;
}
.track-time-link:hover {
  text-decoration: underline;
  opacity: 0.8;
}

.track-time-sep { color: #333; }

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
  .track-card { grid-template-columns: 28px max-content 1fr; }
  .track-actions { grid-column: 1 / -1; justify-content: flex-start; }
  .track-num { display: none; }
}

/* ── Timeline segment interactive states ── */
.tl-segment--hover {
  outline: 2px solid rgba(255,255,255,0.6);
  outline-offset: -1px;
  z-index: 2;
}
.tl-segment--active {
  outline: 2px solid #fff;
  outline-offset: -1px;
  z-index: 3;
  opacity: 1 !important;
}

/* ── Track card active state ── */
.track-card--active {
  border-color: #fff !important;
  box-shadow: 0 0 0 2px rgba(255,255,255,0.25), 0 0 12px rgba(255,255,255,0.12);
  background: #1a1a1a !important;
  animation: card-pulse 0.5s ease-out 1;
}
@keyframes card-pulse {
  0%   { box-shadow: 0 0 0 4px rgba(255,255,255,0.45), 0 0 20px rgba(255,255,255,0.2); }
  100% { box-shadow: 0 0 0 2px rgba(255,255,255,0.25), 0 0 12px rgba(255,255,255,0.12); }
}

/* ── Player ── */
.player-wrap {
  margin-bottom: 24px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #222;
  background: #111;
}
.player-wrap iframe, .player-wrap #ytPlayer {
  width: 100%;
  aspect-ratio: 16 / 9;
  display: block;
}
.player-wrap.sc iframe { height: 166px; aspect-ratio: auto; }

.btn-play { color: #00e676; border-color: #00e676; font-size: 11px; padding: 3px 8px; }

.track-card--now-playing {
  border-left: 3px solid #00e676;
}
.track-card--now-playing .track-num::before {
  content: '\25B6 ';
  color: #00e676;
}

@media (max-width: 600px) {
  .player-wrap {
    position: sticky;
    top: 0;
    z-index: 100;
  }
}

/* ── Custom tooltip ── */
#tl-tooltip {
  position: fixed;
  z-index: 9000;
  pointer-events: none;
  background: #1a1a1a;
  border: 1px solid #333;
  border-radius: 7px;
  padding: 9px 13px;
  min-width: 180px;
  max-width: 280px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.6);
  opacity: 0;
  transition: opacity 0.12s;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
#tl-tooltip.visible { opacity: 1; }
.tl-tip-num  { font-size: 10px; text-transform: uppercase; letter-spacing: 1px; color: #555; font-weight: 600; }
.tl-tip-track { font-size: 13px; font-weight: 600; color: #fff; line-height: 1.3; word-break: break-word; }
.tl-tip-time { font-size: 11px; font-family: 'Courier New', monospace; color: #888; font-variant-numeric: tabular-nums; }
.tl-tip-badge { margin-top: 2px; align-self: flex-start; padding: 1px 7px; border-radius: 10px; border: 1px solid; font-size: 10px; font-weight: 700; letter-spacing: 0.5px; }
"""

JS = """
let activeIdx = null;

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

  // Re-assert opacity on active segment (it should not be dimmed)
  if (activeIdx !== null) {
    document.querySelector('.tl-segment[data-track-idx="' + activeIdx + '"]')
      ?.style.setProperty('opacity', '1');
  }
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

// ── Timeline Interactivity ──
const tooltip  = document.getElementById('tl-tooltip');
const tipNum   = tooltip.querySelector('.tl-tip-num');
const tipTrack = tooltip.querySelector('.tl-tip-track');
const tipTime  = tooltip.querySelector('.tl-tip-time');
const tipBadge = tooltip.querySelector('.tl-tip-badge');

function positionTooltip(cx, cy) {
  const OFFSET = 14, vw = window.innerWidth, vh = window.innerHeight;
  const tw = tooltip.offsetWidth || 200, th = tooltip.offsetHeight || 90;
  let left = cx + OFFSET, top = cy + OFFSET;
  if (left + tw > vw - 8) left = cx - tw - OFFSET;
  if (top  + th > vh - 8) top  = cy - th - OFFSET;
  tooltip.style.left = Math.max(8, left) + 'px';
  tooltip.style.top  = Math.max(8, top)  + 'px';
}

function populateTooltip(seg) {
  tipNum.textContent   = 'Track #' + seg.dataset.trackIdx;
  tipTrack.textContent = seg.dataset.artist + ' \u2014 ' + seg.dataset.title;
  tipTime.textContent  = seg.dataset.time;
  tipBadge.textContent = seg.dataset.conf;
  tipBadge.style.borderColor = seg.dataset.color;
  tipBadge.style.color       = seg.dataset.color;
}

function clearActive() {
  if (activeIdx === null) return;
  document.querySelector('.tl-segment[data-track-idx="' + activeIdx + '"]')
    ?.classList.remove('tl-segment--active');
  const card = document.querySelector('.track-card[data-track-idx="' + activeIdx + '"]');
  if (card) { card.classList.remove('track-card--active'); void card.offsetWidth; }
  activeIdx = null;
}

function setActive(idx) {
  const seg  = document.querySelector('.tl-segment[data-track-idx="' + idx + '"]');
  const card = document.querySelector('.track-card[data-track-idx="' + idx + '"]');
  if (!seg) return;
  seg.classList.add('tl-segment--active');
  if (card && !card.hidden) {
    card.style.animation = 'none'; void card.offsetWidth; card.style.animation = '';
    card.classList.add('track-card--active');
    const rect = card.getBoundingClientRect();
    const viewH = window.innerHeight;
    // Target: card top at ~67% down the viewport (bottom third)
    const targetTop = viewH * 0.67;
    const offset = rect.top - targetTop;
    if (offset > 0 || rect.bottom > viewH) {
      window.scrollBy({ top: offset, behavior: 'smooth' });
    }
  }
  activeIdx = idx;
}

document.querySelectorAll('.tl-segment').forEach(seg => {
  seg.addEventListener('mouseenter', e => {
    populateTooltip(seg);
    positionTooltip(e.clientX, e.clientY);
    tooltip.classList.add('visible');
    if (seg.dataset.trackIdx !== String(activeIdx))
      seg.classList.add('tl-segment--hover');
  });
  seg.addEventListener('mousemove', e => { positionTooltip(e.clientX, e.clientY); });
  seg.addEventListener('mouseleave', () => {
    tooltip.classList.remove('visible');
    seg.classList.remove('tl-segment--hover');
  });
  seg.addEventListener('click', e => {
    e.stopPropagation();
    const idx = seg.dataset.trackIdx;
    if (String(activeIdx) === idx) { clearActive(); }
    else {
      clearActive(); setActive(idx);
      if (typeof trackTimes !== 'undefined') {
        const trackTime = trackTimes.find(t => t.idx === idx);
        if (trackTime && typeof seekPlayer === 'function') seekPlayer(trackTime.start);
      }
    }
  });
});

document.querySelectorAll('.track-card').forEach(card => {
  card.addEventListener('mouseenter', () => {
    const idx = card.dataset.trackIdx;
    if (idx !== String(activeIdx))
      document.querySelector('.tl-segment[data-track-idx="' + idx + '"]')
        ?.classList.add('tl-segment--hover');
  });
  card.addEventListener('mouseleave', () => {
    const idx = card.dataset.trackIdx;
    if (idx !== String(activeIdx))
      document.querySelector('.tl-segment[data-track-idx="' + idx + '"]')
        ?.classList.remove('tl-segment--hover');
  });
});

document.addEventListener('click', () => { clearActive(); });
"""


_SUMMARY_CSS = """
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
  padding: 32px 16px 64px;
}

/* ── Header ── */
.artist-name {
  font-size: clamp(28px, 6vw, 52px);
  font-weight: 800;
  letter-spacing: -1px;
  color: #00e676;
  line-height: 1;
  margin-bottom: 6px;
}

.page-subtitle {
  font-size: 14px;
  text-transform: uppercase;
  letter-spacing: 2px;
  color: #555;
  margin-bottom: 24px;
}

.header-meta {
  font-size: 12px;
  color: #444;
  margin-bottom: 40px;
}

/* ── Stats strip ── */
.stats-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 48px;
}

.stat-block {
  flex: 1;
  min-width: 120px;
  padding: 16px 20px;
  background: #111;
  border: 1px solid #1e1e1e;
  border-radius: 8px;
}

.stat-value {
  display: block;
  font-size: 32px;
  font-weight: 800;
  color: #fff;
  line-height: 1;
  margin-bottom: 4px;
}

.stat-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #555;
}

/* ── Section headings ── */
section { margin-bottom: 48px; }

h2 {
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 2px;
  color: #555;
  margin-bottom: 16px;
  padding-bottom: 8px;
  border-bottom: 1px solid #1e1e1e;
}

/* ── Set cards grid ── */
.sets-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(270px, 1fr));
  gap: 12px;
}

.set-card {
  padding: 16px;
  background: #111;
  border: 1px solid #1e1e1e;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: border-color 0.15s;
}
.set-card:hover { border-color: #2a2a2a; }

.set-card-title {
  font-size: 13px;
  font-weight: 600;
  color: #fff;
  line-height: 1.3;
  /* Clamp to 2 lines */
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.set-card-title:hover { color: #00e676; }

.set-card-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 11px;
  color: #666;
}

.set-card-pill {
  padding: 2px 8px;
  border-radius: 10px;
  border: 1px solid #2a2a2a;
  white-space: nowrap;
}

.pill-high { border-color: #00e676; color: #00e676; }

.set-card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: auto;
  padding-top: 4px;
}

.source-link {
  font-size: 11px;
  color: #444;
  transition: color 0.15s;
}
.source-link:hover { color: #00e676; }

/* ── Most-played tracks ── */
.tracks-list { display: flex; flex-direction: column; gap: 4px; }

.track-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: #111;
  border: 1px solid #1e1e1e;
  border-radius: 6px;
  transition: background 0.15s;
}
.track-row:hover { background: #161616; }

.track-rank {
  font-size: 11px;
  color: #444;
  font-weight: 700;
  min-width: 28px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.track-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.track-info {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.track-artist { font-weight: 600; color: #fff; }
.track-sep    { color: #444; }
.track-title  { color: #ccc; }

/* ── Per-set appearance chips ── */
.appearances {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.app-chip {
  display: inline-flex;
  align-items: center;
  padding: 1px 7px;
  border-radius: 4px;
  border: 1px solid #2a2a2a;
  font-size: 10px;
  color: #666;
  white-space: nowrap;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.app-time {
  color: #00e676;
  font-variant-numeric: tabular-nums;
  font-family: 'Courier New', monospace;
  font-size: 10px;
}

.app-chip-title { transition: color 0.15s; }
.app-chip-title:hover { color: #fff; }

.app-chip-time {
  color: #00e676;
  font-variant-numeric: tabular-nums;
  font-family: 'Courier New', monospace;
  font-size: 10px;
  transition: opacity 0.15s;
}
.app-chip-time:hover { opacity: 0.7; text-decoration: underline; }

.track-actions {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-shrink: 0;
}

.count-badge {
  padding: 2px 9px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
  border: 1px solid #2a2a2a;
  color: #666;
}
.count-multi { border-color: #ffd740; color: #ffd740; }

.btn-spotify {
  padding: 3px 9px;
  border-radius: 5px;
  border: 1px solid #1db954;
  color: #1db954;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  transition: opacity 0.15s;
}
.btn-spotify:hover { opacity: 0.8; }

/* ── Failed sets ── */
.failed-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.failed-item {
  padding: 10px 14px;
  background: #111;
  border: 1px solid #2a1010;
  border-radius: 6px;
  font-size: 12px;
  color: #888;
  word-break: break-all;
}

.failed-url { color: #555; }

/* ── Empty states ── */
.empty { color: #444; font-style: italic; padding: 16px 0; }

/* ── Footer ── */
.footer {
  margin-top: 48px;
  padding-top: 24px;
  border-top: 1px solid #1e1e1e;
  font-size: 12px;
  color: #444;
}
"""


def _render_set_cards(set_summaries: list) -> str:
    """Render the set cards grid HTML."""
    if not set_summaries:
        return '<p class="empty">No sets were successfully processed.</p>'

    cards = []
    for s in set_summaries:
        title_esc = _esc(s['title'])
        source_url = s.get('url', '')

        if s.get('set_html_rel'):
            primary_href = _esc(quote(s['set_html_rel'], safe='/'))
            primary_target = '_self'
        elif source_url:
            primary_href = _esc(source_url)
            primary_target = '_blank'
        else:
            primary_href = '#'
            primary_target = '_self'

        high_conf = s.get('high_confidence', 0)
        total = s.get('total_tracks', 0)

        high_pill = (
            f'<span class="set-card-pill pill-high">{_esc(high_conf)} high conf.</span>'
            if high_conf else ''
        )

        source_link = (
            f'<a class="source-link" href="{_esc(source_url)}" '
            f'target="_blank" rel="noopener">↗ Source</a>'
            if source_url else ''
        )

        cards.append(f'''<div class="set-card">
  <a class="set-card-title" href="{primary_href}" target="{primary_target}">{title_esc}</a>
  <div class="set-card-stats">
    <span class="set-card-pill">{_esc(total)} tracks</span>
    {high_pill}
  </div>
  <div class="set-card-footer">
    {source_link}
  </div>
</div>''')

    return '\n'.join(cards)


def _render_most_played(track_counter, track_info: dict) -> str:
    """Render the most-played tracks list HTML (top 30)."""
    most_common = track_counter.most_common(30)
    if not most_common:
        return '<p class="empty">No tracks found.</p>'

    rows = []
    for rank, (key, count) in enumerate(most_common, 1):
        info = track_info.get(key, {})
        artist_esc = _esc(info.get('artist', ''))
        title_esc  = _esc(info.get('title', key))
        spotify_url = info.get('spotify_url') or ''

        count_class = 'count-multi' if count > 1 else 'count-badge'
        count_label = f"{count} set{'s' if count != 1 else ''}"

        spotify_btn = (
            f'<a class="btn-spotify" href="{_esc(spotify_url)}" '
            f'target="_blank" rel="noopener">Spotify</a>'
        ) if spotify_url else ''

        appearances = info.get('appearances', [])
        app_chips = ''
        if appearances:
            chips = []
            for app in appearances:
                set_html_rel = app.get('set_html_rel') or ''
                deep_link    = app.get('source_deep_link') or ''

                # Set title: clickable link to set HTML when available
                if set_html_rel:
                    title_html = (
                        f'<a class="app-chip-title"'
                        f' href="{_esc(quote(set_html_rel, safe="/"))}"'
                        f' title="Open setlist">'
                        f'{_esc(app["set_title"])}</a>'
                    )
                else:
                    title_html = _esc(app["set_title"])

                # Timestamp: clickable link to source audio at that moment
                if app.get('time_range') and deep_link:
                    time_html = (
                        f'<a class="app-chip-time"'
                        f' href="{_esc(deep_link)}"'
                        f' target="_blank" rel="noopener"'
                        f' title="Listen at this timestamp">'
                        f'\u00a0{_esc(app["time_range"])}</a>'
                    )
                elif app.get('time_range'):
                    time_html = f'<span class="app-time">\u00a0{_esc(app["time_range"])}</span>'
                else:
                    time_html = ''

                chips.append(
                    f'<span class="app-chip">{title_html}{time_html}</span>'
                )
            app_chips = f'<div class="appearances">{"".join(chips)}</div>'

        rows.append(f'''<div class="track-row">
  <span class="track-rank">#{rank}</span>
  <div class="track-body">
    <div class="track-info">
      <span class="track-artist">{artist_esc}</span><span class="track-sep"> — </span><span class="track-title">{title_esc}</span>
    </div>
    {app_chips}
  </div>
  <div class="track-actions">
    <span class="count-badge {count_class}">{_esc(count_label)}</span>
    {spotify_btn}
  </div>
</div>''')

    return '\n'.join(rows)


def _render_failed_section(failed: list) -> str:
    """Render the failed sets section HTML, or empty string if none."""
    if not failed:
        return ''

    items = ''.join(
        f'<li class="failed-item"><span class="failed-url">{_esc(r["url"])}</span>'
        f' — {_esc(r["status"])}</li>'
        for r in failed
    )
    return f'''<section>
  <h2>Failed Sets ({len(failed)})</h2>
  <ul class="failed-list">{items}</ul>
</section>'''


class HtmlFormatter:
    """Generate self-contained interactive HTML setlist pages."""

    def __init__(self, checkpoint_manager=None, artist_manager=None):
        if checkpoint_manager:
            self.output_dir = checkpoint_manager.output_dir
        elif artist_manager:
            self.output_dir = artist_manager.output_dir
        else:
            self.output_dir = Config.OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_setlist_html(self, enriched_tracks: list, mix_info: dict, filename: str = None) -> Path:
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
        source_url = mix_info.get('url', '')
        tracks = _build_track_data(enriched_tracks, total_duration, source_url=source_url)

        # Detect embedded player platform
        platform, embed_id = _detect_platform(source_url)

        # Confidence counts
        from collections import Counter
        counts    = Counter(t['confidence'] for t in tracks)
        total     = len(tracks)
        recognized = sum(1 for t in tracks if t['title'] != 'Unknown Track')

        # Section HTML
        stats_html    = _render_stats(counts, total, recognized)
        timeline_html = _render_timeline(tracks, total_duration)
        cards_html    = _render_track_cards(tracks, platform)
        player_html   = _render_player(platform, embed_id)
        player_js     = _render_player_js(platform, embed_id, tracks)

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

  <!-- Embedded Player -->
  {player_html}

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

<div id="tl-tooltip" aria-hidden="true">
  <div class="tl-tip-num"></div>
  <div class="tl-tip-track"></div>
  <div class="tl-tip-time"></div>
  <div class="tl-tip-badge"></div>
</div>
<div id="toast">Copied!</div>

<script>{JS}</script>
{player_js}
</body>
</html>"""

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)

        print(f"Saved HTML:     {output_path}")
        return output_path

    def save_artist_summary_html(
        self, artist_name, set_summaries, track_counter, track_info, successful, failed
    ) -> Path:
        """Save artist-level aggregate summary as a self-contained HTML page."""
        generated = datetime.now().strftime('%Y-%m-%d %H:%M')
        unique_tracks = len(track_counter)
        total_appearances = sum(track_counter.values())
        repeat_tracks = sum(1 for c in track_counter.values() if c > 1)

        sets_html   = _render_set_cards(set_summaries)
        played_html = _render_most_played(track_counter, track_info)
        failed_html = _render_failed_section(failed)

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_esc(artist_name)} — DJ Set Analysis</title>
  <style>{_SUMMARY_CSS}</style>
</head>
<body>

<div class="container">

  <div class="artist-name">{_esc(artist_name)}</div>
  <div class="page-subtitle">DJ Set Analysis</div>
  <div class="header-meta">Generated {_esc(generated)}</div>

  <div class="stats-strip">
    <div class="stat-block">
      <span class="stat-value">{len(successful)}</span>
      <span class="stat-label">Sets Analyzed</span>
    </div>
    <div class="stat-block">
      <span class="stat-value">{unique_tracks}</span>
      <span class="stat-label">Unique Tracks</span>
    </div>
    <div class="stat-block">
      <span class="stat-value">{total_appearances}</span>
      <span class="stat-label">Total Detections</span>
    </div>
    <div class="stat-block">
      <span class="stat-value">{repeat_tracks}</span>
      <span class="stat-label">Recurring Tracks</span>
    </div>
  </div>

  <section>
    <h2>Sets Analyzed ({len(set_summaries)})</h2>
    <div class="sets-grid">
      {sets_html}
    </div>
  </section>

  <section>
    <h2>Most Played Tracks</h2>
    <div class="tracks-list">
      {played_html}
    </div>
  </section>

  {failed_html}

  <div class="footer">
    Generated {_esc(generated)} &middot; DJ Set Setlist Generator
  </div>

</div>
</body>
</html>"""

        output_path = self.output_dir / "artist_summary.html"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Saved artist summary HTML: {output_path}")
        return output_path
