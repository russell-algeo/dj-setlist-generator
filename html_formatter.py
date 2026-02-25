"""Generate interactive HTML setlist output."""

from collections import Counter
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
let currentTime = 0;
let isPlaying = false;

function updatePillIcon() {
  const btn = document.getElementById('pillPlayBtn');
  if (btn) btn.innerHTML = isPlaying ? '&#9646;&#9646;' : '&#9654;';
}

function playPlayer() {
  if (typeof player !== 'undefined' && player && player.playVideo) {
    player.playVideo();
  } else if (typeof widget !== 'undefined' && widget && widget.play) {
    widget.play();
  }
}

let _skipTarget = null;
let _skipClearTimer = null;

function skipPlayer(delta) {
  let base;
  if (_skipTarget !== null) {
    base = _skipTarget;
  } else if (typeof player !== 'undefined' && player && player.getCurrentTime) {
    base = player.getCurrentTime();
  } else {
    base = currentTime;
  }
  const target = Math.max(0, base + delta);
  _skipTarget = target;
  clearTimeout(_skipClearTimer);
  _skipClearTimer = setTimeout(function() { _skipTarget = null; }, 2000);
  seekPlayer(target);
}

function togglePillPlay() {
  if (isPlaying) pausePlayer();
  else playPlayer();
}

function scrollToActiveCard() {
  if (activeIdx === null) return;
  const card = document.querySelector('.track-card[data-track-idx="' + activeIdx + '"]');
  if (!card || card.hidden) return;
  const rect = card.getBoundingClientRect();
  const viewH = window.innerHeight;
  const targetTop = viewH * 0.67;
  window.scrollBy({ top: rect.top - targetTop, behavior: 'smooth' });
}

function scrollToTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function formatPillTime(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
  return m + ':' + String(s).padStart(2, '0');
}

function updateProgressBar() {
  const pill = document.getElementById('playerPill');
  if (!pill) return;
  const total = parseFloat(pill.dataset.duration) || 0;
  if (!total) return;
  const fill = document.getElementById('pillProgressFill');
  const timeEl = document.getElementById('pillTimeCurrent');
  if (fill) fill.style.width = Math.min(100, (currentTime / total) * 100) + '%';
  if (timeEl) timeEl.textContent = formatPillTime(currentTime);
}

(function() {
  const bar = document.getElementById('pillProgressBar');
  if (!bar) return;
  bar.addEventListener('click', function(e) {
    const pill = document.getElementById('playerPill');
    if (!pill) return;
    const total = parseFloat(pill.dataset.duration) || 0;
    if (!total) return;
    const rect = bar.getBoundingClientRect();
    const fraction = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    seekPlayer(fraction * total);
  });
})();

let nowPlayingInterval = null;
let seekLockUntil = 0;

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
    currentTime = player.getCurrentTime();
    highlightTrackAt(currentTime);
    updateProgressBar();
    return;
  }
  if (typeof widget !== 'undefined' && widget && widget.getPosition) {
    widget.getPosition(function(pos) { currentTime = pos / 1000; highlightTrackAt(currentTime); updateProgressBar(); });
  }
}

function _applyTrackHighlight(seconds) {
  const matches = trackTimes.filter(t => seconds >= t.start && seconds < t.end);
  if (!matches.length) return;
  // When tracks overlap, prefer the one that started most recently (highest start time)
  const match = matches.reduce((best, t) => t.start > best.start ? t : best);
  if (match.idx !== String(activeIdx)) {
    setActive(String(match.idx), false);
  }
}

function highlightTrackAt(seconds) {
  if (Date.now() < seekLockUntil) return;
  _applyTrackHighlight(seconds);
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
var ytEmbedFailed = false;
var ytPlayerReady = false;
var ytHasPlayed = false;

function showYtFallback() {{
  ytEmbedFailed = true;
  stopNowPlaying();
  var wrap = document.getElementById('playerWrap');
  wrap.innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:32px 16px;color:#aaa;text-align:center;">'
    + '<div style="font-size:18px;margin-bottom:12px;">Video cannot be embedded</div>'
    + '<a href="https://www.youtube.com/watch?v={embed_id}" target="_blank" rel="noopener" '
    + 'style="display:inline-flex;align-items:center;gap:8px;padding:10px 20px;background:#ff0000;color:#fff;border-radius:6px;text-decoration:none;font-weight:600;">'
    + '\u25B6 Watch on YouTube</a>'
    + '<div style="font-size:12px;margin-top:8px;color:#666;">Timestamp links will open YouTube at the correct position</div>'
    + '</div>';
  var pill = document.getElementById('playerPill');
  if (pill) pill.style.display = 'none';
}}

function rebuildYtPlayer() {{
  var wrap = document.getElementById('playerWrap');
  wrap.innerHTML = '<div id="ytPlayer"></div>';
  player = new YT.Player('ytPlayer', {{
    videoId: '{embed_id}',
    playerVars: {{ autoplay: 1, modestbranding: 1, rel: 0, start: Math.floor(window._ytPendingSeek || 0) }},
    events: {{
      onReady: function() {{
        ytPlayerReady = true;
        console.log('YT player rebuilt');
      }},
      onStateChange: onYtStateChange,
      onError: onYtError
    }}
  }});
}}

function onYtStateChange(e) {{
  if (e.data === YT.PlayerState.PLAYING) {{
    ytHasPlayed = true;
    isPlaying = true;
    startNowPlaying();
  }} else {{
    isPlaying = false;
    stopNowPlaying();
  }}
  updatePillIcon();
}}

function onYtError(e) {{
  console.warn('YT embed error code:', e.data);
  if (!ytHasPlayed) {{
    showYtFallback();
  }} else {{
    console.log('YT error after successful playback, rebuilding player...');
    ytPlayerReady = false;
    rebuildYtPlayer();
  }}
}}

function onYouTubeIframeAPIReady() {{
  player = new YT.Player('ytPlayer', {{
    videoId: '{embed_id}',
    playerVars: {{ autoplay: 0, modestbranding: 1, rel: 0 }},
    events: {{
      onReady: function() {{
        ytPlayerReady = true;
        console.log('YT player ready');
      }},
      onStateChange: onYtStateChange,
      onError: onYtError
    }}
  }});
}}

function seekPlayer(seconds) {{
  currentTime = seconds;
  updateProgressBar();
  _applyTrackHighlight(seconds);
  seekLockUntil = Date.now() + 1500;
  if (ytEmbedFailed) {{
    window.open('https://www.youtube.com/watch?v={embed_id}&t=' + Math.floor(seconds) + 's', '_blank');
    return;
  }}
  window._ytPendingSeek = seconds;
  if (player && player.seekTo && ytPlayerReady) {{
    player.seekTo(seconds, true);
    player.playVideo();
  }}
}}

function pausePlayer() {{
  if (player && player.pauseVideo) player.pauseVideo();
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
widget.bind(SC.Widget.Events.PLAY,   function() {{ isPlaying = true;  updatePillIcon(); startNowPlaying(); }});
widget.bind(SC.Widget.Events.PAUSE,  function() {{ isPlaying = false; updatePillIcon(); stopNowPlaying(); }});
widget.bind(SC.Widget.Events.FINISH, function() {{ isPlaying = false; updatePillIcon(); stopNowPlaying(); }});

function seekPlayer(seconds) {{
  currentTime = seconds;
  updateProgressBar();
  _applyTrackHighlight(seconds);
  seekLockUntil = Date.now() + 1500;
  widget.seekTo(seconds * 1000);
  widget.play();
}}

function pausePlayer() {{
  widget.pause();
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

        # Spotify embed toggle
        spotify_embed_btn = ''
        if t.get('spotify_url'):
            _spot_id = t['spotify_url'].split('/')[-1].split('?')[0]
            _spot_id_esc = _esc(_spot_id)
            spotify_embed_btn = (
                f'<button class="btn btn-spotify-embed" '
                f'onclick="toggleSpotifyEmbed(this, \'{_spot_id_esc}\')" '
                f'title="Spotify embed player">\u25b6 Spotify</button>'
            )

        # Platform links
        links_html = []
        if t['spotify_url']:
            links_html.append(
                f'<a href="{_esc(t["spotify_url"])}" class="ext-link ext-link-spotify" target="_blank" rel="noopener">Spotify</a>'
            )
        if t['youtube_url']:
            links_html.append(
                f'<a href="{_esc(t["youtube_url"])}" class="ext-link ext-link-youtube" target="_blank" rel="noopener">YouTube</a>'
            )
        if t['discogs_url']:
            links_html.append(
                f'<a href="{_esc(t["discogs_url"])}" class="ext-link ext-link-discogs" target="_blank" rel="noopener">Discogs</a>'
            )
        links_block = ''.join(links_html)

        density_pct = f"{t['cluster_density']:.0%}"

        deep_link = t.get('source_deep_link') or ''
        start_esc = _esc(t['start_time_formatted'])
        start_seconds = t['start_time']

        # Play button (seeks embedded player) — built here so it can be embedded in time_cell
        play_btn = (
            f'<button class="btn btn-play" onclick="event.stopPropagation(); if(String(activeIdx)===\'{t["position"]}\'){{pausePlayer();clearActive();}}else{{seekPlayer({start_seconds:.3f});setActive(\'{t["position"]}\');}}" '
            f'title="Play / Pause">&#9654;</button>'
            if platform in ('youtube', 'soundcloud') else ''
        )

        if platform in ('youtube', 'soundcloud'):
            # Timestamp seeks the embedded player instead of opening a new tab
            time_cell = (
                f'<div class="track-time">'
                f'{play_btn}'
                f'<a class="track-time-link" href="#" '
                f'onclick="event.stopPropagation(); seekPlayer({start_seconds:.3f}); setActive(\'{t["position"]}\'); return false;" '
                f'title="Jump to this track">{start_esc}</a>'
                f'</div>'
            )
        elif deep_link:
            time_cell = (
                f'<div class="track-time">'
                f'<a class="track-time-link" '
                f'href="{_esc(deep_link)}" target="_blank" rel="noopener" '
                f'title="Open at this timestamp">{start_esc}</a>'
                f'</div>'
            )
        else:
            time_cell = (
                f'<div class="track-time">'
                f'{start_esc}'
                f'</div>'
            )

        # Album art
        album_art_url = t.get('spotify_album_art')
        if album_art_url:
            art_cell = (
                f'<div class="track-art">'
                f'<img src="{_esc(album_art_url)}" alt="" loading="lazy">'
                f'</div>'
            )
        else:
            art_cell = '<div class="track-art track-art--empty">\u266a</div>'

        # Genre tags — combine Discogs styles/genres (track-level) + Spotify genres (artist-level)
        seen_lower = set()
        combined_genres = []
        for g in (t.get('discogs_styles') or []) + (t.get('discogs_genres') or []) + (t.get('spotify_genres') or []):
            gl = g.lower()
            if gl not in seen_lower:
                seen_lower.add(gl)
                combined_genres.append(g)
        genre_tags = ''.join(
            f'<span class="genre-tag">{_esc(g)}</span>' for g in combined_genres
        )

        # Label
        label = t.get('discogs_label') or ''
        label_html = f'<span class="track-label">{_esc(label)}</span>' if label else ''

        # BPM and key (from ReccoBeats)
        bpm = t.get('bpm')
        key = t.get('key') or ''
        bpm_key_html = ''
        if bpm or key:
            parts = []
            if bpm:
                parts.append(f'{bpm} BPM')
            if key:
                parts.append(key)
            bpm_key_html = f'<span class="track-bpm-key">{_esc(" · ".join(parts))}</span>'

        # Audio preview button
        preview_url = t.get('spotify_preview_url')
        preview_btn = ''
        if preview_url:
            preview_btn = (
                f'<button class="btn btn-preview" '
                f'onclick="togglePreview(this, \'{_esc(preview_url)}\')" '
                f'title="30s preview">\u266b Preview</button>'
            )

        # Detection details panel
        density_fill = f"{t['cluster_density'] * 100:.0f}%"
        details_panel = f'''<div class="track-details" hidden>
  <div class="detail-row">
    <span class="detail-label">Detection count:</span>
    <span class="detail-value">{t["detection_count"]}</span>
  </div>
  <div class="detail-row">
    <span class="detail-label">Cluster span:</span>
    <span class="detail-value">{t["cluster_span"]} segments</span>
  </div>
  <div class="detail-row">
    <span class="detail-label">Density:</span>
    <div class="detail-density-bar"><div class="detail-density-fill" style="width:{density_fill};"></div></div>
    <span class="detail-value">{density_pct}</span>
  </div>
</div>'''

        cards.append(f'''
<div class="track-card" data-conf="{_esc(conf)}" data-track-idx="{t["position"]}" data-search="{artist_esc.lower()} {title_esc.lower()}">
  <div class="track-num">{t["position"]}</div>
  {art_cell}
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
      {genre_tags}
      {label_html}
      {bpm_key_html}
    </div>
  </div>
  <div class="track-actions">
    <div class="track-links">{links_block}</div>
    <div class="track-btns">
      {spotify_embed_btn}
      {preview_btn}
      <button class="btn btn-expand-details" onclick="toggleDetails(this)" title="Detection details">&#8943;</button>
    </div>
  </div>
  {details_panel}
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
  grid-template-columns: 36px 48px 56px 1fr auto;
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
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
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
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.track-links {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.track-btns {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

/* ── External links (open in new tab) ── */
.ext-link {
  font-size: 11px;
  font-weight: 600;
  text-decoration: none;
  opacity: 0.65;
  transition: opacity 0.15s;
  white-space: nowrap;
}
.ext-link:hover { opacity: 1; text-decoration: underline; }
.ext-link-spotify { color: #1db954; }
.ext-link-youtube { color: #ff4444; }
.ext-link-discogs { color: #e8472f; }

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


/* ── Responsive ── */
@media (max-width: 600px) {
  .track-card { grid-template-columns: 28px max-content 1fr; }
  .track-art { display: none; }
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

/* ── Album Art ── */
.track-art {
  width: 48px;
  height: 48px;
  border-radius: 4px;
  overflow: hidden;
  background: #1a1a1a;
  flex-shrink: 0;
}
.track-art img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.track-art--empty {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #333;
  font-size: 18px;
}

/* ── Genre tags ── */
.genre-tag {
  padding: 1px 6px;
  border-radius: 8px;
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  font-size: 10px;
  color: #666;
  white-space: nowrap;
}

/* ── Label ── */
.track-label {
  padding: 1px 6px;
  border-radius: 8px;
  background: #111;
  border: 1px solid #333;
  font-size: 10px;
  color: #888;
  white-space: nowrap;
  font-style: italic;
}

/* ── BPM / Key ── */
.track-bpm-key {
  font-size: 10px;
  color: #555;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

/* ── Expandable detection details ── */
.track-details {
  grid-column: 1 / -1;
  padding: 8px 14px;
  border-top: 1px solid #1e1e1e;
  margin-top: 6px;
  flex-wrap: wrap;
  gap: 8px 24px;
  font-size: 11px;
  color: #888;
}
.track-details:not([hidden]) { display: flex; }
.detail-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.detail-label { color: #555; }
.detail-value { color: #ccc; font-variant-numeric: tabular-nums; }
.detail-density-bar {
  width: 80px;
  height: 8px;
  background: #1a1a1a;
  border-radius: 4px;
  overflow: hidden;
}
.detail-density-fill {
  height: 100%;
  background: #00e676;
  border-radius: 4px;
}
.btn-expand-details {
  color: #555;
  border-color: #333;
  font-size: 14px;
  padding: 2px 6px;
  line-height: 1;
}

/* ── Audio preview ── */
.btn-preview { color: #1db954; border-color: #1db954; }
.btn-preview--playing { background: #1db954; color: #000; }


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

.btn-play { color: #00e676; border-color: #00e676; font-size: 11px; padding: 3px 8px; font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; }

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

.spotify-embed { grid-column: 1 / -1; margin-top: 8px; }
.btn-spotify-embed { color: #1db954; border-color: #1db954; font-size: 10px; }

/* ── Floating player pill ── */
.player-pill {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 500;
  background: #1a1a1a;
  border: 1px solid #333;
  border-radius: 16px;
  padding: 12px 16px;
  box-shadow: 0 4px 24px rgba(0,0,0,0.7);
  width: 200px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.pill-progress-bar {
  width: 100%;
  height: 6px;
  background: #333;
  border-radius: 3px;
  overflow: hidden;
  cursor: pointer;
}
.pill-progress-bar:hover { background: #444; }
.pill-progress-fill {
  height: 100%;
  background: #00e676;
  border-radius: 2px;
  width: 0%;
  transition: width 0.5s linear;
}
.pill-time-row {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  font-family: 'Courier New', monospace;
  color: #555;
  font-variant-numeric: tabular-nums;
  margin-top: -6px;
}
.pill-controls {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 8px;
}
.pill-skip { color: #888; border-color: #444; min-width: 48px; text-align: center; font-size: 12px; }
.pill-skip:hover { color: #ccc; border-color: #666; opacity: 1; }
.pill-play { color: #00e676; border-color: #00e676; min-width: 40px; text-align: center; font-size: 13px; padding: 5px 12px; font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; }
.pill-play:hover { opacity: 1; }
.pill-nav { display: flex; gap: 6px; }
.pill-nav-btn { flex: 1; color: #555; border-color: #2a2a2a; font-size: 10px; text-align: center; padding: 3px 6px; font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; }
.pill-nav-btn:hover { color: #999; border-color: #555; opacity: 1; }
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
  if (card) {
    card.classList.remove('track-card--active'); void card.offsetWidth;
    const playBtn = card.querySelector('.btn-play');
    if (playBtn) playBtn.innerHTML = '&#9654;';
  }
  activeIdx = null;
}

function setActive(idx, scroll = true) {
  clearActive();
  const seg  = document.querySelector('.tl-segment[data-track-idx="' + idx + '"]');
  const card = document.querySelector('.track-card[data-track-idx="' + idx + '"]');
  if (!seg) return;
  seg.classList.add('tl-segment--active');
  if (card && !card.hidden) {
    card.style.animation = 'none'; void card.offsetWidth; card.style.animation = '';
    card.classList.add('track-card--active');
    const playBtn = card.querySelector('.btn-play');
    if (playBtn) playBtn.innerHTML = '&#9646;&#9646;';
    if (scroll) {
      const rect = card.getBoundingClientRect();
      const viewH = window.innerHeight;
      // Target: card top at ~67% down the viewport (bottom third)
      const targetTop = viewH * 0.67;
      const offset = rect.top - targetTop;
      if (offset > 0 || rect.bottom > viewH) {
        window.scrollBy({ top: offset, behavior: 'smooth' });
      }
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
      setActive(idx, false);
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
.sets-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-bottom: 14px;
}

.search-input {
  flex: 1;
  min-width: 200px;
  padding: 7px 12px;
  background: #111;
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  color: #e0e0e0;
  font-size: 13px;
  outline: none;
  transition: border-color 0.15s;
}
.search-input:focus { border-color: #00e676; }
.search-input::placeholder { color: #444; }

.sort-buttons {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.sort-btn {
  padding: 5px 12px;
  background: #111;
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  color: #666;
  font-size: 12px;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
}
.sort-btn:hover { border-color: #444; color: #ccc; }
.sort-btn.active { border-color: #00e676; color: #00e676; }

.sets-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(270px, 1fr));
  gap: 12px;
}

.set-card {
  background: #111;
  border: 1px solid #1e1e1e;
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: border-color 0.15s, transform 0.15s;
}
.set-card:hover { border-color: #2a2a2a; transform: translateY(-2px); }

.set-card-thumb {
  height: 120px;
  background-size: cover;
  background-position: center;
  background-color: #0a0a0a;
}
.set-card-thumb--empty {
  height: 40px;
  background: linear-gradient(135deg, #111 0%, #1a1a1a 100%);
}

.set-card-body {
  padding: 12px 16px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 1;
}

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

/* Mini timeline */
.set-mini-timeline {
  position: relative;
  height: 6px;
  background: #1a1a1a;
  border-radius: 3px;
  overflow: hidden;
}

.smt-seg {
  position: absolute;
  top: 0;
  height: 100%;
  opacity: 0.85;
}

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

/* ── Track Frequency Heatmap ── */
.heatmap-container {
  overflow-x: auto;
  margin-bottom: 48px;
}

.hm-header {
  display: flex;
  align-items: flex-end;
  margin-bottom: 4px;
}

.hm-track-label {
  width: 250px;
  min-width: 250px;
  font-size: 12px;
  color: #ccc;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  padding-right: 8px;
}

.hm-set-labels {
  display: flex;
  gap: 2px;
}

.hm-set-label {
  width: 28px;
  font-size: 9px;
  color: #666;
  transform-origin: bottom left;
  transform: rotate(-55deg);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100px;
  height: 80px;
  display: flex;
  align-items: flex-end;
}

.hm-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.hm-row {
  display: flex;
  align-items: center;
}

.hm-cells {
  display: flex;
  gap: 2px;
}

.hm-cell {
  width: 28px;
  height: 28px;
  border-radius: 3px;
  cursor: pointer;
  transition: opacity 0.15s, transform 0.15s;
  opacity: 0.85;
}
.hm-cell:hover {
  opacity: 1;
  transform: scale(1.2);
  z-index: 2;
  position: relative;
}

.hm-cell--empty {
  background: #1a1a1a;
  cursor: default;
}
.hm-cell--empty:hover {
  transform: none;
  opacity: 0.85;
}

.hm-tooltip {
  position: fixed;
  z-index: 9000;
  pointer-events: none;
  background: #1a1a1a;
  border: 1px solid #333;
  border-radius: 7px;
  padding: 9px 13px;
  min-width: 160px;
  max-width: 280px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.6);
  opacity: 0;
  transition: opacity 0.12s;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.hm-tooltip.visible { opacity: 1; }

.hm-tip-track {
  font-size: 13px;
  font-weight: 600;
  color: #fff;
  line-height: 1.3;
  word-break: break-word;
}

.hm-tip-time {
  font-size: 11px;
  font-family: 'Courier New', monospace;
  color: #888;
  font-variant-numeric: tabular-nums;
}

.hm-tip-conf {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  margin-top: 2px;
}

/* ── DJ Signature Analysis ── */
.sig-section {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.sig-score {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 24px;
  background: #111;
  border: 1px solid #1e1e1e;
  border-radius: 8px;
}

.sig-score-value {
  font-size: 48px;
  font-weight: 800;
  color: #00e676;
  line-height: 1;
}

.sig-score-label {
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 2px;
  color: #888;
  margin-top: 4px;
}

.sig-score-desc {
  font-size: 11px;
  color: #555;
  margin-top: 2px;
}

.sig-bar {
  display: flex;
  height: 32px;
  border-radius: 6px;
  overflow: hidden;
  background: #1a1a1a;
}

.sig-bar-segment {
  transition: opacity 0.2s;
  cursor: pointer;
}
.sig-bar-segment:hover { opacity: 0.8; }

.sig-staple { background: #00e676; }
.sig-regular { background: #ffd740; }
.sig-oneoff  { background: #333; }

.sig-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 8px;
  font-size: 12px;
  color: #888;
}

.sig-legend-item { display: flex; align-items: center; }

.sig-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-right: 4px;
  vertical-align: middle;
}
.sig-dot.sig-staple { background: #00e676; }
.sig-dot.sig-regular { background: #ffd740; }
.sig-dot.sig-oneoff  { background: #333; }

.sig-staples h3,
.sig-trends h3,
.sig-genres h3 {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: #555;
  margin-bottom: 0;
  padding-bottom: 6px;
  border-bottom: 1px solid #1e1e1e;
}

.sig-staples-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 8px;
  margin-top: 12px;
}

.sig-staple-card {
  padding: 12px 16px;
  background: #111;
  border: 1px solid #1e1e1e;
  border-left: 3px solid #00e676;
  border-radius: 6px;
}

.sig-staple-count {
  font-size: 11px;
  font-weight: 700;
  color: #00e676;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.sig-staple-artist {
  font-size: 13px;
  font-weight: 600;
  color: #fff;
  margin-top: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sig-staple-title {
  font-size: 12px;
  color: #888;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sig-trend-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 12px;
}

.sig-trend-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  background: #111;
  border: 1px solid #1e1e1e;
  border-radius: 6px;
}

.sig-trend-rank {
  font-size: 11px;
  color: #444;
  font-weight: 700;
  min-width: 28px;
  text-align: right;
}

.sig-trend-info {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 12px;
}

.sig-trend-artist { color: #fff; font-weight: 600; }
.sig-trend-sep    { color: #444; }
.sig-trend-title  { color: #888; }
.sparkline        { flex-shrink: 0; }

.sig-trend-count {
  font-size: 11px;
  color: #00e676;
  font-weight: 700;
  white-space: nowrap;
}

.genre-bars {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 12px;
}

.genre-bar-row {
  display: grid;
  grid-template-columns: 120px 1fr 40px;
  align-items: center;
  gap: 8px;
}

.genre-bar-label {
  font-size: 12px;
  color: #ccc;
  text-align: right;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.genre-bar-track {
  height: 16px;
  background: #1a1a1a;
  border-radius: 4px;
  overflow: hidden;
}

.genre-bar-fill {
  height: 100%;
  background: #00e676;
  border-radius: 4px;
  transition: width 0.3s ease;
}

.genre-bar-count {
  font-size: 11px;
  color: #666;
  font-variant-numeric: tabular-nums;
}

/* ── Interactive Set Timeline ── */
.stl-container {
  margin-bottom: 48px;
  position: relative;
}

.stl-container::after {
  content: '';
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 60px;
  background: linear-gradient(to right, transparent, #0d0d0d);
  pointer-events: none;
  z-index: 10;
}

.stl-scroll {
  overflow-x: auto;
  padding: 20px 0 40px;
  position: relative;
}

.stl-axis {
  position: absolute;
  top: 50px;
  left: 0;
  right: 0;
  height: 2px;
  background: #2a2a2a;
  z-index: 0;
}

.stl-nodes {
  display: flex;
  gap: 24px;
  position: relative;
  z-index: 1;
  padding: 0 24px;
  min-width: min-content;
}

.stl-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 220px;
  max-width: 260px;
}

.stl-node-dot {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #00e676;
  border: 2px solid #0d0d0d;
  margin-bottom: 12px;
  z-index: 2;
}

.stl-node-card {
  background: #111;
  border: 1px solid #1e1e1e;
  border-radius: 8px;
  padding: 12px 16px;
  width: 100%;
  cursor: pointer;
  transition: border-color 0.15s;
}
.stl-node-card:hover { border-color: #2a2a2a; }

.stl-node-title {
  font-size: 12px;
  font-weight: 600;
  color: #fff;
  line-height: 1.3;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin-bottom: 6px;
}

.stl-node-meta {
  font-size: 11px;
  color: #666;
  margin-bottom: 8px;
}

.stl-node-mini-timeline {
  position: relative;
  height: 4px;
  background: #1a1a1a;
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 8px;
}

.stl-mini-seg {
  position: absolute;
  top: 0;
  height: 100%;
}

.stl-expand-btn {
  background: none;
  border: none;
  color: #00e676;
  font-size: 11px;
  cursor: pointer;
  padding: 4px 0;
  font-family: inherit;
  width: 100%;
  text-align: center;
}
.stl-expand-btn:hover { text-decoration: underline; }

.stl-tracklist {
  width: 100%;
  margin-top: 8px;
  background: #0d0d0d;
  border: 1px solid #1e1e1e;
  border-radius: 6px;
  padding: 8px;
  max-height: 400px;
  overflow-y: auto;
}

.stl-track {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 6px;
  font-size: 11px;
  border-radius: 3px;
  transition: background 0.1s;
  cursor: default;
}
.stl-track:hover { background: #161616; }

.stl-track-time {
  font-family: 'Courier New', monospace;
  color: #555;
  font-size: 10px;
  min-width: 36px;
}

.stl-track-name {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stl-track-artist { color: #fff; font-weight: 600; }
.stl-track-title { color: #888; }

.stl-track-conf {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.4px;
  white-space: nowrap;
  padding: 1px 5px;
  border-radius: 8px;
  border: 1px solid;
}

.stl-track--recurring {
  border-left: 2px solid #ffd740;
  padding-left: 4px;
}
.stl-track--recurring:hover {
  background: #1a1a0a;
}

.stl-track--highlight {
  background: #2a2a0a !important;
  outline: 1px solid #ffd740;
}

.stl-arcs {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 0;
  overflow: visible;
}

.stl-arc {
  fill: none;
  stroke: #ffd740;
  stroke-width: 1;
  opacity: 0.15;
  transition: opacity 0.2s;
}

.stl-arc--highlight {
  opacity: 0.6;
  stroke-width: 2;
}
"""


def _build_heatmap_data(track_counter, track_info: dict, set_summaries: list) -> dict:
    """Build the data needed for the heatmap visualization.

    Returns a dict with:
        set_titles: ordered list of set names
        set_html_rels: list of relative HTML paths (or None) per set
        rows: list of track row dicts, each with artist, title, track_key, and cells list.
              Each cell: {'present': bool, 'confidence': str, 'time_range': str,
                          'deep_link': str, 'set_html_rel': str}
    """
    set_titles = [s['title'] for s in set_summaries]
    set_html_rels = [s.get('set_html_rel') for s in set_summaries]

    rows = []
    for track_key, _ in track_counter.most_common(30):
        info = track_info.get(track_key, {})
        appearances = info.get('appearances', [])

        # Index appearances by set_title for O(1) lookup
        # If a track appears multiple times in the same set, keep the highest confidence one
        conf_order = {'HIGH': 4, 'MEDIUM': 3, 'LOW': 2, 'UNCERTAIN': 1}
        by_set: dict[str, dict] = {}
        for app in appearances:
            st = app.get('set_title', '')
            existing = by_set.get(st)
            if existing is None or conf_order.get(app.get('confidence', 'UNCERTAIN'), 1) > conf_order.get(existing.get('confidence', 'UNCERTAIN'), 1):
                by_set[st] = app

        cells = []
        for set_title in set_titles:
            app = by_set.get(set_title)
            if app:
                cells.append({
                    'present': True,
                    'confidence': app.get('confidence', 'UNCERTAIN'),
                    'time_range': app.get('time_range', ''),
                    'deep_link': app.get('source_deep_link') or '',
                    'set_html_rel': app.get('set_html_rel') or '',
                })
            else:
                cells.append({'present': False})

        rows.append({
            'track_key': track_key,
            'artist': info.get('artist', ''),
            'title': info.get('title', track_key),
            'cells': cells,
        })

    return {
        'set_titles': set_titles,
        'set_html_rels': set_html_rels,
        'rows': rows,
    }


def _render_heatmap(heatmap_data: dict) -> str:
    """Render the track frequency heatmap as HTML."""
    set_titles = heatmap_data['set_titles']
    rows = heatmap_data['rows']

    if not rows or not set_titles:
        return '<p class="empty">Not enough data to display heatmap.</p>'

    conf_colors = {
        'HIGH': '#00e676',
        'MEDIUM': '#ffd740',
        'LOW': '#ff9100',
        'UNCERTAIN': '#757575',
    }

    # Column headers (rotated set names)
    header_labels = []
    for title in set_titles:
        header_labels.append(
            f'<div class="hm-set-label">{_esc(title)}</div>'
        )
    headers_html = '\n'.join(header_labels)

    # Rows
    row_htmls = []
    for row in rows:
        label = f'{_esc(row["artist"])} \u2014 {_esc(row["title"])}'

        cells_html_parts = []
        for cell in row['cells']:
            if not cell['present']:
                cells_html_parts.append('<div class="hm-cell hm-cell--empty"></div>')
            else:
                conf = cell['confidence']
                color = conf_colors.get(conf, '#757575')
                set_html_rel = _esc(cell['set_html_rel'])
                deep_link = _esc(cell['deep_link'])
                time_range = _esc(cell['time_range'])
                track_label = _esc(f'{row["artist"]} — {row["title"]}')
                # Find the set title for this cell
                # We rely on the same ordering as set_titles; find the index via the cell's set_html_rel
                # Use data attributes for JS to pick up
                navigate_target = set_html_rel or deep_link
                cells_html_parts.append(
                    f'<div class="hm-cell" '
                    f'style="background:{color};" '
                    f'data-track="{track_label}" '
                    f'data-time="{time_range}" '
                    f'data-conf="{_esc(conf)}" '
                    f'data-href="{navigate_target}" '
                    f'onclick="navigateHmCell(this)"></div>'
                )
        cells_block = '\n'.join(cells_html_parts)

        row_htmls.append(f'''<div class="hm-row">
  <div class="hm-track-label" title="{label}">{label}</div>
  <div class="hm-cells">
    {cells_block}
  </div>
</div>''')

    rows_html = '\n'.join(row_htmls)

    # Tooltip div + JS injected inline at bottom of the heatmap container
    hm_js = """<script>
(function() {
  var hmTooltip = document.getElementById('hm-tooltip');
  if (!hmTooltip) return;

  document.querySelectorAll('.hm-cell:not(.hm-cell--empty)').forEach(function(cell) {
    cell.addEventListener('mouseenter', function(e) {
      hmTooltip.querySelector('.hm-tip-track').textContent = this.dataset.track;
      hmTooltip.querySelector('.hm-tip-time').textContent = this.dataset.time || '';
      var confEl = hmTooltip.querySelector('.hm-tip-conf');
      confEl.textContent = this.dataset.conf;
      confEl.style.color = getHmConfColor(this.dataset.conf);
      positionHmTooltip(e.clientX, e.clientY);
      hmTooltip.classList.add('visible');
    });
    cell.addEventListener('mousemove', function(e) {
      positionHmTooltip(e.clientX, e.clientY);
    });
    cell.addEventListener('mouseleave', function() {
      hmTooltip.classList.remove('visible');
    });
  });

  function getHmConfColor(conf) {
    return {HIGH: '#00e676', MEDIUM: '#ffd740', LOW: '#ff9100', UNCERTAIN: '#757575'}[conf] || '#757575';
  }

  function positionHmTooltip(cx, cy) {
    var OFFSET = 14, vw = window.innerWidth, vh = window.innerHeight;
    var tw = hmTooltip.offsetWidth || 200, th = hmTooltip.offsetHeight || 80;
    var left = cx + OFFSET, top = cy + OFFSET;
    if (left + tw > vw - 8) left = cx - tw - OFFSET;
    if (top + th > vh - 8) top = cy - th - OFFSET;
    hmTooltip.style.left = Math.max(8, left) + 'px';
    hmTooltip.style.top = Math.max(8, top) + 'px';
  }
})();

function navigateHmCell(cell) {
  var href = cell.dataset.href;
  if (href) window.open(href, '_self');
}
</script>"""

    return f'''<div class="heatmap-container">
  <div class="hm-header">
    <div class="hm-track-label"></div>
    <div class="hm-set-labels">
      {headers_html}
    </div>
  </div>
  <div class="hm-body">
    {rows_html}
  </div>
</div>
<div id="hm-tooltip" class="hm-tooltip" aria-hidden="true">
  <div class="hm-tip-track"></div>
  <div class="hm-tip-time"></div>
  <div class="hm-tip-conf"></div>
</div>
{hm_js}'''


def _compute_signature_analysis(track_counter, track_info: dict, set_summaries: list) -> dict:
    """Compute DJ signature analysis metrics."""
    unique = len(track_counter)
    staples = []
    regulars = []
    one_offs = []

    for key, count in track_counter.most_common():
        info = track_info.get(key, {})
        entry = {
            'key': key,
            'artist': info.get('artist', ''),
            'title': info.get('title', key),
            'count': count,
            'spotify_url': info.get('spotify_url'),
        }
        if count >= 3:
            staples.append(entry)
        elif count == 2:
            regulars.append(entry)
        else:
            one_offs.append(entry)

    recurring = len(staples) + len(regulars)
    signature_score = (recurring / unique * 100) if unique else 0

    # Genre distribution from track_info
    genre_counter: Counter = Counter()
    for info in track_info.values():
        for genre in info.get('genres', []):
            genre_counter[genre] += 1

    return {
        'unique_tracks': unique,
        'staples': staples,
        'regulars': regulars,
        'one_offs': one_offs,
        'signature_score': signature_score,
        'total_sets': len(set_summaries),
        'top_genres': genre_counter.most_common(10),
    }


def _build_trend_data(track_counter, track_info: dict, set_summaries: list) -> list:
    """For each recurring track, build a presence array across sets."""
    set_titles = [s['title'] for s in set_summaries]
    trends = []
    for key, count in track_counter.most_common():
        if count < 2:
            break
        info = track_info.get(key, {})
        appeared_in = {a['set_title'] for a in info.get('appearances', [])}
        presence = [1 if title in appeared_in else 0 for title in set_titles]
        trends.append({
            'key': key,
            'artist': info.get('artist', ''),
            'title': info.get('title', key),
            'count': count,
            'presence': presence,
            'spotify_url': info.get('spotify_url'),
        })
    return trends[:15]


def _render_sparkline(presence: list) -> str:
    """Render a tiny inline SVG sparkline for track presence across sets."""
    if not presence:
        return ''
    n = len(presence)
    w = 60
    h = 16
    step = w / max(n - 1, 1)

    points = []
    for i, v in enumerate(presence):
        x = round(i * step, 1)
        y = round(h - (v * (h - 4)) - 2, 1)
        points.append(f"{x},{y}")

    dots = ''.join(
        f'<circle cx="{round(i * step, 1)}" cy="{round(h - (v * (h - 4)) - 2, 1)}" r="2" '
        f'fill="{("#00e676" if v else "#333")}"/>'
        for i, v in enumerate(presence)
    )

    return (
        f'<svg class="sparkline" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
        f'<polyline points="{" ".join(points)}" fill="none" stroke="#00e676" stroke-width="1.5" opacity="0.6"/>'
        f'{dots}'
        f'</svg>'
    )


def _render_signature_analysis(track_counter, track_info: dict, set_summaries: list) -> str:
    """Render the DJ signature analysis section as HTML."""
    if not track_counter:
        return '<p class="empty">No track data available for signature analysis.</p>'

    sig = _compute_signature_analysis(track_counter, track_info, set_summaries)
    unique = sig['unique_tracks']
    staples = sig['staples']
    regulars = sig['regulars']
    one_offs = sig['one_offs']
    signature_score = sig['signature_score']

    n_staples = len(staples)
    n_regulars = len(regulars)
    n_oneoffs = len(one_offs)
    total = unique or 1
    pct_staple = n_staples / total * 100
    pct_regular = n_regulars / total * 100
    pct_oneoff = n_oneoffs / total * 100

    breakdown_bar = f'''<div class="sig-bar">
  <div class="sig-bar-segment sig-staple" style="width:{pct_staple:.1f}%;" title="{n_staples} staples (3+ sets)"></div>
  <div class="sig-bar-segment sig-regular" style="width:{pct_regular:.1f}%;" title="{n_regulars} regulars (2 sets)"></div>
  <div class="sig-bar-segment sig-oneoff" style="width:{pct_oneoff:.1f}%;" title="{n_oneoffs} one-offs"></div>
</div>
<div class="sig-legend">
  <span class="sig-legend-item"><span class="sig-dot sig-staple"></span> Staples (3+ sets): {n_staples}</span>
  <span class="sig-legend-item"><span class="sig-dot sig-regular"></span> Regulars (2 sets): {n_regulars}</span>
  <span class="sig-legend-item"><span class="sig-dot sig-oneoff"></span> One-offs: {n_oneoffs}</span>
</div>'''

    # Staple cards (top 12)
    staple_cards_html = ''
    if staples:
        cards = []
        for entry in staples[:12]:
            spotify_link = (
                f'<a class="btn-spotify" href="{_esc(entry["spotify_url"])}" target="_blank" rel="noopener">Spotify</a>'
                if entry.get('spotify_url') else ''
            )
            cards.append(f'''<div class="sig-staple-card">
  <div class="sig-staple-count">{entry["count"]} sets</div>
  <div class="sig-staple-artist">{_esc(entry["artist"])}</div>
  <div class="sig-staple-title">{_esc(entry["title"])}</div>
  {spotify_link}
</div>''')
        staple_cards_html = f'''<div class="sig-staples">
  <h3>DJ Staples</h3>
  <div class="sig-staples-grid">
    {''.join(cards)}
  </div>
</div>'''

    # Track trends with sparklines (only useful when there are multiple sets)
    trends_html = ''
    if len(set_summaries) > 1:
        trends = _build_trend_data(track_counter, track_info, set_summaries)
        if trends:
            rows = []
            for rank, t in enumerate(trends, 1):
                sparkline = _render_sparkline(t['presence'])
                rows.append(f'''<div class="sig-trend-row">
  <span class="sig-trend-rank">#{rank}</span>
  <div class="sig-trend-info">
    <span class="sig-trend-artist">{_esc(t["artist"])}</span>
    <span class="sig-trend-sep"> — </span>
    <span class="sig-trend-title">{_esc(t["title"])}</span>
  </div>
  {sparkline}
  <span class="sig-trend-count">{t["count"]} sets</span>
</div>''')
            trends_html = f'''<div class="sig-trends">
  <h3>Track Trends</h3>
  <div class="sig-trend-list">
    {''.join(rows)}
  </div>
</div>'''

    # Genre distribution (conditional — only shown when genre data is present)
    genres_html = ''
    top_genres = sig['top_genres']
    if top_genres:
        max_count = top_genres[0][1]
        genre_rows = []
        for genre, count in top_genres:
            pct = count / max_count * 100
            genre_rows.append(f'''<div class="genre-bar-row">
  <span class="genre-bar-label">{_esc(genre)}</span>
  <div class="genre-bar-track">
    <div class="genre-bar-fill" style="width:{pct:.1f}%;"></div>
  </div>
  <span class="genre-bar-count">{count}</span>
</div>''')
        genres_html = f'''<div class="sig-genres">
  <h3>Genre Distribution</h3>
  <div class="genre-bars">
    {''.join(genre_rows)}
  </div>
</div>'''

    return f'''<div class="sig-section">
  <div class="sig-score">
    <span class="sig-score-value">{signature_score:.0f}%</span>
    <span class="sig-score-label">Signature Score</span>
    <span class="sig-score-desc">of unique tracks played in 2+ sets</span>
  </div>
  <div class="sig-breakdown">
    {breakdown_bar}
  </div>
  {staple_cards_html}
  {trends_html}
  {genres_html}
</div>'''


def _render_set_timeline(set_summaries: list) -> str:
    """Render an interactive horizontal set timeline with expandable tracklists and SVG continuity arcs."""
    if not set_summaries:
        return '<p class="empty">No sets to display in timeline.</p>'

    # Build recurring_map: track_key -> [set_index, ...]
    # Only keep tracks appearing in 2+ sets; limit to top 20 by frequency for performance
    track_counts: dict[str, int] = {}
    track_sets: dict[str, list[int]] = {}
    for s in set_summaries:
        seen_in_set: set[str] = set()
        for t in s.get('tracks', []):
            key = t.get('track_key', '')
            if not key or key in seen_in_set:
                continue
            seen_in_set.add(key)
            track_counts[key] = track_counts.get(key, 0) + 1
            if key not in track_sets:
                track_sets[key] = []
            track_sets[key].append(s.get('index', 0))

    # Filter to tracks in 2+ sets, then take top 20 most recurring
    recurring_map = {k: v for k, v in track_sets.items() if track_counts.get(k, 0) >= 2}
    recurring_keys: set[str] = set(
        sorted(recurring_map.keys(), key=lambda k: track_counts[k], reverse=True)[:20]
    )

    conf_colors = {
        'HIGH': '#00e676',
        'MEDIUM': '#ffd740',
        'LOW': '#ff9100',
        'UNCERTAIN': '#757575',
    }

    # Render each set node
    nodes_html_parts = []
    for s in set_summaries:
        idx = s.get('index', 0)
        title_esc = _esc(s['title'])
        total = s.get('total_tracks', 0)
        tracks = s.get('tracks', [])

        # Set title link
        set_html_rel = s.get('set_html_rel')
        source_url = s.get('url', '')
        if set_html_rel:
            href = _esc(quote(set_html_rel, safe='/'))
            title_html = f'<a class="stl-node-title" href="{href}">{title_esc}</a>'
        elif source_url:
            title_html = f'<a class="stl-node-title" href="{_esc(source_url)}" target="_blank" rel="noopener">{title_esc}</a>'
        else:
            title_html = f'<div class="stl-node-title">{title_esc}</div>'

        # Mini-timeline: colored segments for each track
        mini_segs = []
        if tracks and total > 0:
            n = len(tracks)
            seg_width = 100.0 / n if n > 0 else 100.0
            for ti, t in enumerate(tracks):
                color = conf_colors.get(t.get('confidence', 'UNCERTAIN'), '#757575')
                left = ti * seg_width
                mini_segs.append(
                    f'<div class="stl-mini-seg" '
                    f'style="left:{left:.2f}%;width:{seg_width:.2f}%;background:{color};opacity:0.7;"></div>'
                )
        mini_timeline_html = '\n'.join(mini_segs)

        # Tracklist rows
        track_rows = []
        for t in tracks:
            tkey = t.get('track_key', '')
            is_recurring = tkey in recurring_keys
            cls = 'stl-track stl-track--recurring' if is_recurring else 'stl-track'
            conf = t.get('confidence', 'UNCERTAIN')
            conf_color = conf_colors.get(conf, '#757575')
            artist_esc = _esc(t.get('artist', ''))
            track_title_esc = _esc(t.get('title', ''))
            time_esc = _esc(t.get('start_time_formatted', ''))
            tkey_esc = _esc(tkey)
            track_rows.append(
                f'<div class="{cls}" data-track-key="{tkey_esc}">'
                f'<span class="stl-track-time">{time_esc}</span>'
                f'<span class="stl-track-name">'
                f'<span class="stl-track-artist">{artist_esc}</span>'
                f' \u2014 '
                f'<span class="stl-track-title">{track_title_esc}</span>'
                f'</span>'
                f'<span class="stl-track-conf" style="border-color:{conf_color};color:{conf_color};">{_esc(conf)}</span>'
                f'</div>'
            )
        tracklist_html = '\n'.join(track_rows)

        nodes_html_parts.append(f'''<div class="stl-node" data-set-idx="{idx}">
  <div class="stl-node-dot"></div>
  <div class="stl-node-card">
    {title_html}
    <div class="stl-node-meta">{_esc(str(total))} tracks</div>
    <div class="stl-node-mini-timeline">
      {mini_timeline_html}
    </div>
    <button class="stl-expand-btn" onclick="toggleSetExpand({idx})">&#9660; Show Tracklist</button>
  </div>
  <div class="stl-tracklist" id="stlTracklist{idx}" hidden>
    {tracklist_html}
  </div>
</div>''')

    nodes_html = '\n'.join(nodes_html_parts)

    timeline_js = """<script>
function toggleSetExpand(idx) {
  var tracklist = document.getElementById('stlTracklist' + idx);
  var node = document.querySelector('.stl-node[data-set-idx="' + idx + '"]');
  var btn = node ? node.querySelector('.stl-expand-btn') : null;
  if (!tracklist) return;
  if (tracklist.hidden) {
    tracklist.hidden = false;
    if (btn) btn.innerHTML = '&#9650; Hide Tracklist';
    drawContinuityArcs();
  } else {
    tracklist.hidden = true;
    if (btn) btn.innerHTML = '&#9660; Show Tracklist';
    drawContinuityArcs();
  }
}

// ── Recurring track hover highlighting ──
document.querySelectorAll('.stl-track[data-track-key]').forEach(function(track) {
  track.addEventListener('mouseenter', function() {
    var key = this.dataset.trackKey;
    document.querySelectorAll('.stl-track[data-track-key]').forEach(function(t) {
      if (t.dataset.trackKey === key) t.classList.add('stl-track--highlight');
    });
    document.querySelectorAll('.stl-arc').forEach(function(arc) {
      if (arc.dataset.trackKey === key) arc.classList.add('stl-arc--highlight');
    });
  });
  track.addEventListener('mouseleave', function() {
    document.querySelectorAll('.stl-track--highlight').forEach(function(t) {
      t.classList.remove('stl-track--highlight');
    });
    document.querySelectorAll('.stl-arc--highlight').forEach(function(arc) {
      arc.classList.remove('stl-arc--highlight');
    });
  });
});

// ── SVG continuity arcs ──
function drawContinuityArcs() {
  var svg = document.getElementById('stlArcs');
  if (!svg) return;
  var container = svg.parentElement;
  var containerRect = container.getBoundingClientRect();
  svg.innerHTML = '';

  var trackSets = {};
  var nodes = document.querySelectorAll('.stl-node');
  nodes.forEach(function(node, i) {
    var dot = node.querySelector('.stl-node-dot');
    if (!dot) return;
    var dotRect = dot.getBoundingClientRect();
    var cx = dotRect.left + dotRect.width / 2 - containerRect.left + container.scrollLeft;
    var cy = dotRect.top + dotRect.height / 2 - containerRect.top + container.scrollTop;

    var tracks = node.querySelectorAll('.stl-track[data-track-key]');
    tracks.forEach(function(t) {
      var key = t.dataset.trackKey;
      if (!trackSets[key]) trackSets[key] = [];
      var alreadyAdded = trackSets[key].some(function(p) { return p.idx === i; });
      if (!alreadyAdded) trackSets[key].push({idx: i, x: cx, y: cy});
    });
  });

  Object.keys(trackSets).forEach(function(key) {
    var positions = trackSets[key];
    if (positions.length < 2) return;
    for (var i = 0; i < positions.length - 1; i++) {
      var p1 = positions[i];
      var p2 = positions[i + 1];
      var midX = (p1.x + p2.x) / 2;
      var arcHeight = Math.min(40, Math.abs(p2.x - p1.x) * 0.15);
      var midY = p1.y - arcHeight - 20;
      var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', 'M ' + p1.x + ' ' + p1.y + ' Q ' + midX + ' ' + midY + ' ' + p2.x + ' ' + p2.y);
      path.setAttribute('class', 'stl-arc');
      path.dataset.trackKey = key;
      svg.appendChild(path);
    }
  });
}

drawContinuityArcs();
var stlScroll = document.querySelector('.stl-scroll');
if (stlScroll) stlScroll.addEventListener('scroll', drawContinuityArcs);
window.addEventListener('resize', drawContinuityArcs);
</script>"""

    return f'''<div class="stl-container">
  <div class="stl-scroll">
    <svg class="stl-arcs" id="stlArcs" aria-hidden="true"></svg>
    <div class="stl-axis"></div>
    <div class="stl-nodes">
      {nodes_html}
    </div>
  </div>
</div>
{timeline_js}'''


def _format_duration_hms(seconds: float) -> str:
    """Format seconds as H:MM:SS (or M:SS if under an hour)."""
    if not seconds:
        return ''
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


_CONF_COLORS = {
    "HIGH": "#00e676",
    "MEDIUM": "#ffd740",
    "LOW": "#ff6d00",
    "UNCERTAIN": "#444",
}


def _render_set_cards(set_summaries: list) -> str:
    """Render the set cards grid HTML."""
    if not set_summaries:
        return '<p class="empty">No sets were successfully processed.</p>'

    cards = []
    for s in set_summaries:
        title_esc = _esc(s['title'])
        title_lower = s['title'].lower()
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
        duration = s.get('duration', 0)
        recognition_rate = s.get('recognition_rate', 0)
        mini_timeline = s.get('mini_timeline', [])
        thumbnail_url = s.get('thumbnail_url')
        track_search_text = s.get('track_search_text', '')

        # data-* attributes for JS sort/filter
        data_tracks = int(total)
        data_rate = int(recognition_rate)
        data_duration = int(duration)
        data_search = _esc(f"{title_lower} {track_search_text}")

        # Thumbnail header
        if thumbnail_url:
            thumb_html = (
                f'<div class="set-card-thumb" '
                f'style="background-image: url(\'{_esc(thumbnail_url)}\')"></div>'
            )
        else:
            thumb_html = '<div class="set-card-thumb set-card-thumb--empty"></div>'

        # Mini timeline segments
        smt_segs = ''.join(
            f'<div class="smt-seg" style="left:{seg["start_pct"]:.2f}%;'
            f'width:{seg["width_pct"]:.2f}%;'
            f'background:{_CONF_COLORS.get(seg["confidence"], "#444")};"></div>'
            for seg in mini_timeline
        )
        mini_tl_html = f'<div class="set-mini-timeline">{smt_segs}</div>'

        # Stats pills
        high_pill = (
            f'<span class="set-card-pill pill-high">{_esc(high_conf)} high conf.</span>'
            if high_conf else ''
        )
        rate_pill = (
            f'<span class="set-card-pill">{int(recognition_rate)}% identified</span>'
            if total else ''
        )
        duration_pill = (
            f'<span class="set-card-pill">{_esc(_format_duration_hms(duration))}</span>'
            if duration else ''
        )

        source_link = (
            f'<a class="source-link" href="{_esc(source_url)}" '
            f'target="_blank" rel="noopener">↗ Source</a>'
            if source_url else ''
        )

        cards.append(f'''<div class="set-card" data-tracks="{data_tracks}" data-rate="{data_rate}" data-duration="{data_duration}" data-search="{data_search}">
  {thumb_html}
  <div class="set-card-body">
    <a class="set-card-title" href="{primary_href}" target="{primary_target}">{title_esc}</a>
    {mini_tl_html}
    <div class="set-card-stats">
      <span class="set-card-pill">{_esc(total)} tracks</span>
      {high_pill}
      {rate_pill}
      {duration_pill}
    </div>
    <div class="set-card-footer">
      {source_link}
    </div>
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


def _render_track_card_js() -> str:
    """Return a <script> block with JS for track card upgrades: preview, expand details, Spotify embed."""
    return """<script>
// ── Toggle detection details ──
function toggleDetails(btn) {
  var card = btn.closest('.track-card');
  var details = card.querySelector('.track-details');
  details.hidden = !details.hidden;
}

// ── Audio preview ──
var currentAudio = null;
var currentPreviewBtn = null;

function togglePreview(btn, url) {
  if (currentAudio && currentPreviewBtn === btn) {
    currentAudio.pause();
    currentAudio = null;
    btn.textContent = '\u266b Preview';
    btn.classList.remove('btn-preview--playing');
    currentPreviewBtn = null;
    return;
  }
  if (currentAudio) {
    currentAudio.pause();
    currentPreviewBtn.textContent = '\u266b Preview';
    currentPreviewBtn.classList.remove('btn-preview--playing');
  }
  currentAudio = new Audio(url);
  currentPreviewBtn = btn;
  btn.textContent = '\u25a0 Stop';
  btn.classList.add('btn-preview--playing');
  currentAudio.play();
  currentAudio.onended = function() {
    btn.textContent = '\u266b Preview';
    btn.classList.remove('btn-preview--playing');
    currentAudio = null;
    currentPreviewBtn = null;
  };
}

// ── Spotify embed player ──
function toggleSpotifyEmbed(btn, trackId) {
  var card = btn.closest('.track-card');
  var embed = card.querySelector('.spotify-embed');
  if (embed) {
    embed.remove();
    btn.textContent = '\u25b6 Spotify';
    return;
  }
  embed = document.createElement('div');
  embed.className = 'spotify-embed';
  embed.innerHTML = '<iframe style="border-radius:8px" src="https://open.spotify.com/embed/track/' + trackId + '?utm_source=generator&theme=0" width="100%" height="80" frameBorder="0" allow="autoplay; clipboard-write; encrypted-media" loading="lazy"></iframe>';
  card.appendChild(embed);
  btn.textContent = '\u2715 Close';
}
</script>"""



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
        counts    = Counter(t['confidence'] for t in tracks)
        total     = len(tracks)
        recognized = sum(1 for t in tracks if t['title'] != 'Unknown Track')

        # Section HTML
        stats_html    = _render_stats(counts, total, recognized)
        timeline_html = _render_timeline(tracks, total_duration)
        cards_html    = _render_track_cards(tracks, platform)
        player_html   = _render_player(platform, embed_id)
        player_js     = _render_player_js(platform, embed_id, tracks)
        pill_html = (
            f'<div class="player-pill" id="playerPill" onclick="event.stopPropagation()" data-duration="{total_duration:.3f}">'
            f'<div class="pill-progress-bar" id="pillProgressBar"><div class="pill-progress-fill" id="pillProgressFill"></div></div>'
            f'<div class="pill-time-row">'
            f'<span id="pillTimeCurrent">0:00</span>'
            f'<span>{_esc(format_time(total_duration))}</span>'
            f'</div>'
            f'<div class="pill-controls">'
            f'<button class="btn pill-skip" onclick="skipPlayer(-15)" title="Back 15 seconds">\u221215</button>'
            f'<button class="btn pill-play" id="pillPlayBtn" onclick="togglePillPlay()" title="Play / Pause">&#9654;</button>'
            f'<button class="btn pill-skip" onclick="skipPlayer(15)" title="Forward 15 seconds">+15</button>'
            f'</div>'
            f'<div class="pill-nav">'
            f'<button class="btn pill-nav-btn" onclick="scrollToTop()" title="Scroll to top">\u2191 top</button>'
            f'<button class="btn pill-nav-btn" onclick="scrollToActiveCard()" title="Scroll to current track">\u2193 track</button>'
            f'</div>'
            f'</div>'
        ) if platform in ('youtube', 'soundcloud') else ''


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

{pill_html}

<script>{JS}</script>
{_render_track_card_js()}
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

        sets_html       = _render_set_cards(set_summaries)
        played_html     = _render_most_played(track_counter, track_info)
        failed_html     = _render_failed_section(failed)
        heatmap_data    = _build_heatmap_data(track_counter, track_info, set_summaries)
        heatmap_html    = _render_heatmap(heatmap_data)
        signature_html  = _render_signature_analysis(track_counter, track_info, set_summaries)
        timeline_html   = _render_set_timeline(set_summaries)

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
    <h2>DJ Signature</h2>
    {signature_html}
  </section>

  <section>
    <h2>Set Timeline</h2>
    {timeline_html}
  </section>

  <section>
    <h2>Sets Analyzed ({len(set_summaries)})</h2>
    <div class="sets-controls">
      <input id="setSearch" class="search-input" type="search"
             placeholder="Search sets or find a track across sets…" autocomplete="off">
      <div class="sort-buttons">
        <button class="sort-btn active" data-sort="default">Default</button>
        <button class="sort-btn" data-sort="tracks">Most Tracks</button>
        <button class="sort-btn" data-sort="rate">Best Recognition</button>
        <button class="sort-btn" data-sort="duration">Longest</button>
      </div>
    </div>
    <div class="sets-grid">
      {sets_html}
    </div>
  </section>

  <section>
    <h2>Track Frequency Heatmap</h2>
    {heatmap_html}
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

<script>
/* ── Set grid: search + sort (Feature 6) ── */
(function () {{
  var searchInput = document.getElementById('setSearch');
  var setsGrid = document.querySelector('.sets-grid');
  if (!searchInput || !setsGrid) return;

  function filterSets() {{
    var query = searchInput.value.toLowerCase().trim();
    setsGrid.querySelectorAll('.set-card').forEach(function (card) {{
      var match = !query || card.dataset.search.includes(query);
      card.style.display = match ? '' : 'none';
    }});
  }}

  searchInput.addEventListener('input', filterSets);

  function sortSets(sortBy) {{
    var cards = Array.from(setsGrid.querySelectorAll('.set-card'));
    cards.sort(function (a, b) {{
      switch (sortBy) {{
        case 'tracks':   return parseInt(b.dataset.tracks)   - parseInt(a.dataset.tracks);
        case 'rate':     return parseInt(b.dataset.rate)     - parseInt(a.dataset.rate);
        case 'duration': return parseInt(b.dataset.duration) - parseInt(a.dataset.duration);
        default: return 0;
      }}
    }});
    cards.forEach(function (card) {{ setsGrid.appendChild(card); }});
  }}

  document.querySelectorAll('.sort-btn').forEach(function (btn) {{
    btn.addEventListener('click', function () {{
      document.querySelectorAll('.sort-btn').forEach(function (b) {{ b.classList.remove('active'); }});
      btn.classList.add('active');
      sortSets(btn.dataset.sort);
    }});
  }});
}})();
</script>
</body>
</html>"""

        output_path = self.output_dir / "artist_summary.html"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Saved artist summary HTML: {output_path}")
        return output_path
