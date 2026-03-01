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
        title_js = t.get('title', '').replace('\\', '\\\\').replace('"', '\\"')
        artist_js = t.get('artist', '').replace('\\', '\\\\').replace('"', '\\"')
        art_js = (t.get('spotify_album_art') or '').replace('\\', '\\\\').replace('"', '\\"')
        track_times_entries.append(
            f'  {{idx: "{t["position"]}", start: {t["start_time"]:.3f}, end: {t["end_time"]:.3f}, '
            f'title: "{title_js}", artist: "{artist_js}", art: "{art_js}"}}'
        )
    track_times_js = 'const trackTimes = [\n' + ',\n'.join(track_times_entries) + '\n];'

    now_playing_js = """
let currentTime = 0;
let isPlaying = false;

function updatePillIcon() {
  const btn = document.getElementById('pillPlayBtn');
  if (btn) btn.innerHTML = isPlaying ? '&#9646;&#9646;' : '&#9654;';
  if (activeIdx !== null) {
    const card = document.querySelector('.track-card[data-track-idx="' + activeIdx + '"]');
    if (card) {
      const playBtn = card.querySelector('.btn-play');
      if (playBtn) playBtn.innerHTML = isPlaying ? '&#9646;&#9646;' : '&#9654;';
    }
  }
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

let _prevPressTime = 0;

function skipToNextTrack() {
  const sorted = [...trackTimes].sort((a, b) => a.start - b.start);
  const next = sorted.find(t => t.start > currentTime + 1);
  if (next) { seekPlayer(next.start); setActive(next.idx, false); }
}

function skipToPrevTrack() {
  const sorted = [...trackTimes].sort((a, b) => a.start - b.start);
  const now = Date.now();
  const currentTrack = [...sorted].reverse().find(t => t.start <= currentTime);
  if (currentTrack && (now - _prevPressTime < 2000)) {
    const prev = [...sorted].reverse().find(t => t.start < currentTrack.start);
    if (prev) { seekPlayer(prev.start); setActive(prev.idx, false); }
  } else {
    if (currentTrack) { seekPlayer(currentTrack.start); setActive(currentTrack.idx, false); }
    else { seekPlayer(0); }
  }
  _prevPressTime = now;
}
"""

    if platform == 'youtube':
        return f"""<script>
{track_times_js}

var tag = document.createElement('script');
tag.src = "https://www.youtube-nocookie.com/iframe_api";
var firstScriptTag = document.getElementsByTagName('script')[0];
firstScriptTag.parentNode.insertBefore(tag, firstScriptTag);

var player;
var ytEmbedFailed = false;
var ytPlayerReady = false;
var ytHasPlayed = false;
var ytOrigin = (window.location.protocol === 'file:') ? undefined : window.location.origin;

function showYtFallback() {{
  ytEmbedFailed = true;
  stopNowPlaying();
  var wrap = document.getElementById('playerWrap');
  wrap.innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:32px 16px;color:#aaa;text-align:center;">'
    + '<div style="font-size:18px;margin-bottom:12px;">Video cannot be embedded</div>'
    + '<div style="font-size:13px;margin-bottom:14px;color:#666;">The uploader may have disabled embedding for this video.</div>'
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
    host: 'https://www.youtube-nocookie.com',
    videoId: '{embed_id}',
    playerVars: {{ autoplay: 1, modestbranding: 1, rel: 0, origin: ytOrigin, start: Math.floor(window._ytPendingSeek || 0) }},
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
    host: 'https://www.youtube-nocookie.com',
    videoId: '{embed_id}',
    playerVars: {{ autoplay: 0, modestbranding: 1, rel: 0, origin: ytOrigin }},
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



def _render_journey_chart(tracks: list, total_duration: float) -> str:
    """Render a collapsible JS-driven journey chart.

    Emits a journeyData JSON array and HTML container shell. All drawing is
    handled client-side by drawJourneyChart() in the JS constant.
    Returns an empty string if no tracks have metric data.
    """
    if total_duration <= 0:
        return ''

    import json

    points = []
    for t in tracks:
        if t.get('title') == 'Unknown Track':
            continue
        start = t.get('start_time', 0) or 0

        bpm    = t.get('bpm')
        energy = t.get('energy')
        dance  = t.get('danceability')

        if bpm is None and energy is None and dance is None:
            continue

        title  = t.get('title', '') or ''
        artist = t.get('artist', '') or ''

        points.append({
            'idx':    str(t.get('position', '')),
            'start':  round(start, 3),
            'title':  title,
            'artist': artist,
            'bpm':    round(float(bpm),    1) if bpm    is not None else None,
            'energy': round(float(energy), 3) if energy is not None else None,
            'dance':  round(float(dance),  3) if dance  is not None else None,
        })

    if not points:
        return ''

    has_bpm    = any(p['bpm']    is not None for p in points)
    has_energy = any(p['energy'] is not None for p in points)
    has_dance  = any(p['dance']  is not None for p in points)

    filter_btns = []
    if has_bpm:
        filter_btns.append(
            '<button class="journey-filter active" data-metric="bpm" '
            'style="--mc:#00e676">BPM</button>'
        )
    if has_energy:
        filter_btns.append(
            '<button class="journey-filter active" data-metric="energy" '
            'style="--mc:#ff9800">Energy</button>'
        )
    if has_dance:
        filter_btns.append(
            '<button class="journey-filter active" data-metric="dance" '
            'style="--mc:#64b5f6">Dance</button>'
        )

    data_js = (
        f'var journeyData={json.dumps(points)};'
        f'var journeyTotalDuration={total_duration:.3f};'
    )

    return (
        f'<div class="journey-section">'
        f'<div class="journey-header">'
        f'<button class="btn btn-journey" onclick="toggleJourneyChart()">'
        f'\U0001F4C8 Journey</button>'
        f'<div class="journey-filters" id="journeyFilters" style="display:none">'
        f'{"".join(filter_btns)}'
        f'</div>'
        f'</div>'
        f'<div class="journey-chart" id="journeyChart">'
        f'<div class="journey-yaxis-left" id="journeyYLeft"></div>'
        f'<svg id="journeySvg" preserveAspectRatio="none" '
        f'xmlns="http://www.w3.org/2000/svg"></svg>'
        f'<div class="journey-yaxis-right" id="journeyYRight"></div>'
        f'</div>'
        f'<script>{data_js}</script>'
        f'</div>\n'
    )


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
            f'<button class="btn btn-play" onclick="event.stopPropagation(); if(String(activeIdx)===\'{t["position"]}\'){{if(isPlaying){{pausePlayer();}}else{{playPlayer();}}}}else{{seekPlayer({start_seconds:.3f});setActive(\'{t["position"]}\');}}" '
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
        label_url = t.get('discogs_label_url') or ''
        if label and label_url:
            label_html = f'<a class="track-label" href="{_esc(label_url)}" target="_blank" rel="noopener">{_esc(label)}</a>'
        elif label:
            label_html = f'<span class="track-label">{_esc(label)}</span>'
        else:
            label_html = ''

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
<div class="track-card" id="track-{t["position"]}" data-conf="{_esc(conf)}" data-track-idx="{t["position"]}" data-search="{artist_esc.lower()} {title_esc.lower()}">
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


def _render_sparkline_pill(label: str, values: list, color: str) -> str:
    """Render a small SVG sparkline as a stat-pill."""
    if not values:
        return ''
    n = len(values)
    w, h = 60, 16  # SVG dimensions
    vmin, vmax = min(values), max(values)
    vrange = vmax - vmin if vmax != vmin else 1.0

    pts = []
    for i, v in enumerate(values):
        x = i / max(n - 1, 1) * w
        y = h - ((v - vmin) / vrange) * (h - 4) - 2
        pts.append((x, y))

    polyline = ' '.join(f'{x:.1f},{y:.1f}' for x, y in pts)
    dots = ''.join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.5" fill="{color}"/>'
        for x, y in pts
    )

    avg = sum(values) / n
    tooltip = f'{label}: min={vmin:.1f} avg={avg:.1f} max={vmax:.1f}'

    svg = (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" style="overflow:visible;vertical-align:middle">'
        f'<polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="1.5"/>'
        f'{dots}'
        f'</svg>'
    )

    return (
        f'<span class="stat-pill sparkline-pill" title="{tooltip}" '
        f'style="border-color:{color};color:{color};display:inline-flex;align-items:center;gap:4px;padding:2px 8px;">'
        f'<span style="font-size:9px;letter-spacing:0.5px">{label}</span>{svg}'
        f'</span>'
    )


def _render_stats(counts: dict, total: int, recognized: int, tracks: list = None) -> str:
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

    sparkline_html = ''
    if tracks:
        sorted_tracks = sorted(tracks, key=lambda t: t.get('start_time', 0))
        bpm_vals = [t['bpm'] for t in sorted_tracks if t.get('bpm') is not None]
        energy_vals = [t['energy'] for t in sorted_tracks if t.get('energy') is not None]
        dance_vals = [t['danceability'] for t in sorted_tracks if t.get('danceability') is not None]
        sparkline_html = (
            _render_sparkline_pill('BPM', bpm_vals, '#00e676')
            + _render_sparkline_pill('NRG', energy_vals, '#ff9800')
            + _render_sparkline_pill('DNC', dance_vals, '#64b5f6')
        )

    return f'''
<div class="stats-bar">
  <span class="stat-total">{total} tracks</span>
  <span class="stat-rate">{recognition_rate:.0f}% identified</span>
  {pills_html}
  {sparkline_html}
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
  text-decoration: none;
}
a.track-label {
  cursor: pointer;
}
a.track-label:hover {
  color: #bbb;
  border-color: #555;
  background: #1a1a1a;
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
  gap: 6px;
}
.pill-skip { flex: 1; color: #888; border-color: #444; text-align: center; font-size: 12px; padding: 4px 8px; }
.pill-skip:hover { color: #ccc; border-color: #666; opacity: 1; }
.pill-play { color: #00e676; border-color: #00e676; min-width: 40px; text-align: center; font-size: 13px; padding: 5px 12px; font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; }
.pill-play:hover { opacity: 1; }
.pill-track-nav { display: flex; gap: 6px; }
.pill-track-nav-btn { flex: 1; color: #888; border-color: #444; text-align: center; font-size: 13px; padding: 2px 6px; }
.pill-track-nav-btn:hover { color: #ccc; border-color: #666; opacity: 1; }
.pill-nav { display: flex; gap: 6px; }
.pill-nav-btn { flex: 1; color: #555; border-color: #2a2a2a; font-size: 10px; text-align: center; padding: 3px 6px; font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; }
.pill-nav-btn:hover { color: #999; border-color: #555; opacity: 1; }
.pill-now-playing {
  display: none;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  text-align: center;
}
.pill-now-playing.visible { display: flex; }
.pill-album-art {
  width: 80px;
  height: 80px;
  border-radius: 8px;
  object-fit: cover;
  display: none;
}
.pill-album-art.visible { display: block; }
.pill-track-title {
  font-size: 13px;
  font-weight: 600;
  color: #fff;
  width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.pill-track-artist {
  font-size: 11px;
  color: #888;
  width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-top: -4px;
}

/* ── Journey chart ── */
.journey-section { margin-bottom: 20px; }

.journey-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.btn-journey {
  color: #555;
  border-color: #2a2a2a;
  font-size: 11px;
  padding: 4px 10px;
  flex-shrink: 0;
}
.btn-journey:hover { color: #888; border-color: #444; opacity: 1; }

.journey-filters {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}

.journey-filter {
  background: none;
  border: 1px solid #333;
  border-radius: 20px;
  padding: 2px 10px;
  font-size: 11px;
  color: #555;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
}
.journey-filter.active { border-color: var(--mc); color: var(--mc); }
.journey-filter:hover { opacity: 0.8; }

.journey-chart {
  display: none;
  width: 100%;
  background: #1a1a1a;
  border: 1px solid #222;
  border-radius: 6px;
  align-items: flex-start;
}
.journey-chart.visible { display: flex; }

.journey-yaxis-left,
.journey-yaxis-right {
  position: relative;
  width: 36px;
  min-width: 36px;
  flex-shrink: 0;
  height: 140px;
}
.journey-yaxis-right { text-align: right; }

#journeySvg {
  display: block;
  flex: 1;
  min-width: 0;
  height: 120px;
  align-self: flex-start;
  border-radius: 0 6px 6px 0;
}

/* Journey tooltip */
#journey-tooltip {
  position: fixed;
  z-index: 9001;
  pointer-events: none;
  background: #1a1a1a;
  border: 1px solid #333;
  border-radius: 7px;
  padding: 8px 12px;
  min-width: 160px;
  max-width: 260px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.6);
  opacity: 0;
  transition: opacity 0.12s;
  font-size: 12px;
  color: #ccc;
  line-height: 1.5;
}
#journey-tooltip.visible { opacity: 1; }
#journey-tooltip .jt-title { font-weight: 600; color: #fff; font-size: 13px; margin-bottom: 2px; }
#journey-tooltip .jt-value { color: #888; font-size: 11px; }
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
  if (window._journeyUnhighlight) window._journeyUnhighlight();
  activeIdx = null;
}

function _updatePillNowPlaying(idx) {
  const nowPlaying = document.getElementById('pillNowPlaying');
  if (!nowPlaying) return;
  const track = typeof trackTimes !== 'undefined' ? trackTimes.find(t => t.idx === String(idx)) : null;
  if (!track) return;
  const titleEl  = document.getElementById('pillTrackTitle');
  const artistEl = document.getElementById('pillTrackArtist');
  const artEl    = document.getElementById('pillAlbumArt');
  if (titleEl)  titleEl.textContent  = track.title  || '';
  if (artistEl) artistEl.textContent = track.artist || '';
  if (artEl) {
    if (track.art) {
      artEl.src = track.art;
      artEl.classList.add('visible');
    } else {
      artEl.src = '';
      artEl.classList.remove('visible');
    }
  }
  nowPlaying.classList.add('visible');
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
  _updatePillNowPlaying(idx);
  if (window._journeyHighlight) window._journeyHighlight(idx);
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


// ── Journey Chart ──
(function() {
  if (typeof journeyData === 'undefined') return;

  var COLORS        = { bpm: '#00e676', energy: '#ff9800', dance: '#64b5f6' };
  var ALL_METRICS   = ['bpm', 'energy', 'dance'];
  var jTip          = document.getElementById('journey-tooltip');
  var activeJourneyIdx = null;

  // SVG coordinate constants (must match drawJourneyChart)
  var VB_W = 1000, VB_H = 120, Y_TOP = 10, Y_BOT = 110, Y_RANGE = Y_BOT - Y_TOP;

  // Start with all metrics that have at least one data point
  var activeMetrics = ALL_METRICS.filter(function(m) {
    return journeyData.some(function(p) { return p[m] !== null; });
  });

  // Expose toggle for inline onclick
  window.toggleJourneyChart = function() {
    var chart   = document.getElementById('journeyChart');
    var filters = document.getElementById('journeyFilters');
    var btn     = document.querySelector('.btn-journey');
    var visible = chart.classList.toggle('visible');
    if (filters) filters.style.display = visible ? 'flex' : 'none';
    if (btn) btn.textContent = visible ? '\U0001F4C8 Journey \u25be' : '\U0001F4C8 Journey';
    if (visible) drawJourneyChart();
  };

  // Expose highlight hooks for setActive / clearActive
  window._journeyHighlight = function(idx) {
    activeJourneyIdx = String(idx);
    _applyJourneyHighlight();
  };
  window._journeyUnhighlight = function() {
    activeJourneyIdx = null;
    _applyJourneyHighlight();
  };

  function _applyJourneyHighlight() {
    var svg = document.getElementById('journeySvg');
    if (!svg) return;
    svg.querySelectorAll('.journey-dot').forEach(function(dot) {
      var isActive = activeJourneyIdx !== null && dot.getAttribute('data-idx') === activeJourneyIdx;
      dot.setAttribute('stroke', isActive ? '#fff' : '#1a1a1a');
      dot.setAttribute('stroke-width', isActive ? '2.5' : '1.5');
    });
  }

  // Filter buttons — click to isolate; click again to restore all
  document.querySelectorAll('.journey-filter').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      var m = btn.getAttribute('data-metric');
      if (activeMetrics.length === 1 && activeMetrics[0] === m) {
        // Already isolated — restore all available metrics
        activeMetrics = ALL_METRICS.filter(function(metric) {
          return journeyData.some(function(p) { return p[metric] !== null; });
        });
        document.querySelectorAll('.journey-filter').forEach(function(b) {
          b.classList.add('active');
        });
      } else {
        // Isolate to this metric
        activeMetrics = [m];
        document.querySelectorAll('.journey-filter').forEach(function(b) {
          b.classList.toggle('active', b.getAttribute('data-metric') === m);
        });
      }
      drawJourneyChart();
    });
  });

  function drawJourneyChart() {
    var svg    = document.getElementById('journeySvg');
    var yLeft  = document.getElementById('journeyYLeft');
    var yRight = document.getElementById('journeyYRight');
    if (!svg) return;

    var totalDur = typeof journeyTotalDuration !== 'undefined' ? journeyTotalDuration : 1;
    var isolated = activeMetrics.length === 1;

    // Gather sorted points per active metric
    var metricPts = {};
    activeMetrics.forEach(function(m) {
      metricPts[m] = journeyData
        .filter(function(p) { return p[m] !== null; })
        .map(function(p) {
          return { x: p.start / totalDur, val: p[m], idx: p.idx,
                   start: p.start, title: p.title, artist: p.artist };
        })
        .sort(function(a, b) { return a.x - b.x; });
    });

    // ── Y-scale ──
    var leftScale, rightScale;

    if (isolated) {
      var m0 = activeMetrics[0];
      if (m0 === 'bpm') {
        var vals = metricPts[m0].map(function(p) { return p.val; });
        var vmin = Math.min.apply(null, vals);
        var vmax = Math.max.apply(null, vals);
        if (vmin === vmax) { vmin -= 1; vmax += 1; }
        leftScale = { min: vmin, max: vmax, isBpm: true };
      } else {
        leftScale = { min: 0, max: 1, isBpm: false };
      }
      rightScale = null;
    } else {
      leftScale  = { min: 0, max: 1, isBpm: false };
      rightScale = null;
      if (activeMetrics.indexOf('bpm') !== -1 && metricPts['bpm'].length) {
        var bvals = metricPts['bpm'].map(function(p) { return p.val; });
        var bmin  = Math.min.apply(null, bvals);
        var bmax  = Math.max.apply(null, bvals);
        if (bmin === bmax) { bmin -= 1; bmax += 1; }
        rightScale = { min: bmin, max: bmax, isBpm: true };
      }
    }

    function scaleToY(val, scale) {
      return Y_BOT - ((val - scale.min) / (scale.max - scale.min)) * Y_RANGE;
    }

    function getScaleFor(m) {
      if (isolated) return leftScale;
      return (m === 'bpm' && rightScale) ? rightScale : leftScale;
    }

    // ── Build SVG ──
    var parts = [];
    parts.push('<rect x="0" y="0" width="' + VB_W + '" height="' + VB_H + '" fill="#1a1a1a"/>');
    [0.25, 0.5, 0.75].forEach(function(pct) {
      var gy = (Y_BOT - pct * Y_RANGE).toFixed(1);
      parts.push('<line x1="0" y1="' + gy + '" x2="' + VB_W + '" y2="' + gy +
                 '" stroke="#333" stroke-width="0.8" stroke-dasharray="4 4"/>');
    });

    activeMetrics.forEach(function(m) {
      var pts   = metricPts[m];
      if (!pts.length) return;
      var color = COLORS[m];
      var scale = getScaleFor(m);

      // Polyline
      var ptStr = pts.map(function(p) {
        return (p.x * VB_W).toFixed(2) + ',' + scaleToY(p.val, scale).toFixed(2);
      }).join(' ');
      parts.push('<polyline points="' + ptStr + '" fill="none" stroke="' + color +
                 '" stroke-width="1.5" stroke-dasharray="4 4"' +
                 ' stroke-linecap="round" stroke-linejoin="round" opacity="0.7"/>');

      // Dots
      pts.forEach(function(p) {
        var cx      = (p.x * VB_W).toFixed(2);
        var cy      = scaleToY(p.val, scale).toFixed(2);
        var valStr  = m === 'bpm' ? p.val.toFixed(0) + ' BPM'
                    : m === 'energy' ? 'Energy: ' + p.val.toFixed(2)
                    : 'Danceability: ' + p.val.toFixed(2);
        var lbl     = (p.artist && p.title)
          ? p.artist + ' \u2014 ' + p.title
          : (p.title || p.artist || 'Unknown');
        var isActive = activeJourneyIdx !== null && String(p.idx) === activeJourneyIdx;
        parts.push(
          '<circle class="journey-dot" cx="' + cx + '" cy="' + cy + '" r="5"' +
          ' fill="' + color + '"' +
          ' stroke="' + (isActive ? '#fff' : '#1a1a1a') + '"' +
          ' stroke-width="' + (isActive ? '2.5' : '1.5') + '"' +
          ' style="cursor:pointer;"' +
          ' data-idx="' + p.idx + '" data-start="' + p.start + '"' +
          ' data-label="' + lbl.replace(/&/g, '&amp;').replace(/"/g, '&quot;') + '"' +
          ' data-value="' + valStr + '"' +
          '/>'
        );
      });
    });

    svg.setAttribute('viewBox', '0 0 ' + VB_W + ' ' + VB_H);
    svg.setAttribute('height', '120');
    svg.innerHTML = parts.join('');

    // ── Dot events: tooltip + click-to-seek ──
    svg.querySelectorAll('.journey-dot').forEach(function(dot) {
      if (jTip) {
        dot.addEventListener('mouseenter', function(e) {
          jTip.querySelector('.jt-title').textContent = dot.getAttribute('data-label') || '';
          jTip.querySelector('.jt-value').textContent = dot.getAttribute('data-value') || '';
          _jtPos(e.clientX, e.clientY);
          jTip.classList.add('visible');
        });
        dot.addEventListener('mousemove', function(e) { _jtPos(e.clientX, e.clientY); });
        dot.addEventListener('mouseleave', function() { jTip.classList.remove('visible'); });
      }
      dot.addEventListener('click', function(e) {
        e.stopPropagation();
        var start = parseFloat(dot.getAttribute('data-start'));
        var idx   = dot.getAttribute('data-idx');
        if (typeof seekPlayer === 'function') seekPlayer(start);
        if (typeof setActive  === 'function') setActive(idx, false);
      });
    });

    // ── Y-axis labels (pixel positions aligned with SVG coordinate space) ──
    var leftColors = [], rightColors = [];
    if (isolated) {
      leftColors = [COLORS[activeMetrics[0]]];
    } else {
      if (activeMetrics.indexOf('energy') !== -1) leftColors.push(COLORS['energy']);
      if (activeMetrics.indexOf('dance')  !== -1) leftColors.push(COLORS['dance']);
      if (rightScale && activeMetrics.indexOf('bpm') !== -1) rightColors = [COLORS['bpm']];
    }
    _renderYAxis(yLeft,  leftScale,  false, leftColors);
    _renderYAxis(yRight, rightScale, true,  rightColors);
  }

  function _renderYAxis(el, scale, isRight, colors) {
    if (!el) return;
    if (!scale) { el.innerHTML = ''; return; }
    // el is 120px tall matching VB_H; labels positioned using SVG Y coordinates:
    // topPx = Y_BOT - pct*Y_RANGE maps min→Y_BOT=110px, max→Y_TOP=10px
    var html  = '';
    var ticks = 5;
    var align = isRight ? 'right:2px' : 'left:2px';
    for (var i = 0; i < ticks; i++) {
      var pct   = i / (ticks - 1);
      var val   = scale.min + pct * (scale.max - scale.min);
      var topPx = Y_BOT - pct * Y_RANGE;
      var lbl   = scale.isBpm ? val.toFixed(0) : val.toFixed(2);
      html += '<span style="position:absolute;top:' + topPx.toFixed(0) + 'px;' + align +
              ';transform:translateY(-50%);font-size:9px;color:#888;white-space:nowrap">' +
              lbl + '</span>';
    }
    // Colored metric label words below the chart area (below Y_BOT=110px)
    if (colors && colors.length) {
      var METRIC_LABELS = { '#00e676': 'BPM', '#ff9800': 'NRG', '#64b5f6': 'DNC' };
      var labelAlign = isRight ? 'right:2px;text-align:right' : 'left:2px;text-align:left';
      var labelsHtml = '<span style="position:absolute;top:116px;' + labelAlign +
                       ';display:flex;flex-direction:column;gap:1px;line-height:1">';
      colors.forEach(function(c) {
        var lbl = METRIC_LABELS[c] || '';
        labelsHtml += '<span style="font-size:8px;color:' + c + ';white-space:nowrap">' + lbl + '</span>';
      });
      labelsHtml += '</span>';
      html += labelsHtml;
    }
    el.innerHTML = html;
  }

  function _jtPos(cx, cy) {
    if (!jTip) return;
    var OFFSET = 14, vw = window.innerWidth, vh = window.innerHeight;
    var tw = jTip.offsetWidth || 180, th = jTip.offsetHeight || 60;
    var left = cx + OFFSET, top = cy + OFFSET;
    if (left + tw > vw - 8) left = cx - tw - OFFSET;
    if (top  + th > vh - 8) top  = cy - th - OFFSET;
    jTip.style.left = Math.max(8, left) + 'px';
    jTip.style.top  = Math.max(8, top)  + 'px';
  }
})();
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
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.sets-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.set-card {
  background: #111;
  border: 1px solid #1e1e1e;
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: border-color 0.15s, transform 0.15s, height 0.2s;
  height: 260px;
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
  margin-top: 12px;
}

/* ── 2-row horizontal scroll grid ── */
.hscroll-outer {
  overflow-x: auto;
  overflow-y: visible;
}
.hscroll-inner {
  display: flex;
  flex-direction: row;
  align-items: flex-start;
  gap: 8px;
  padding-bottom: 4px;
}
.hscroll-col {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 200px;
  flex-shrink: 0;
  overflow: visible;
  position: relative;
}
.hscroll-col .sig-staple-card {
  width: 200px;
  flex-shrink: 0;
  align-self: flex-start;
}

.sig-staple-card--expanded {
  position: absolute;
  z-index: 10;
  box-shadow: 0 8px 32px rgba(0,0,0,0.7), 0 2px 8px rgba(0,0,0,0.5);
  /* top, left, width set by JS */
}

.sig-staple-card {
  padding: 12px 16px;
  background: #111;
  border: 1px solid #1e1e1e;
  border-left: 3px solid #00e676;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow: hidden;
  transition: border-color 0.15s, transform 0.15s;
}
.sig-staple-card:hover { border-color: #2a2a2a; transform: translateY(-2px); }

.sig-staple-art {
  width: calc(100% + 32px);
  margin: -12px -16px 8px;
  height: 120px;
  object-fit: cover;
  display: block;
  border-radius: 5px 5px 0 0;
}
.sig-staple-art--empty {
  width: calc(100% + 32px);
  margin: -12px -16px 8px;
  height: 120px;
  background: linear-gradient(135deg, #0d0d0d 0%, #161616 100%);
  border-radius: 5px 5px 0 0;
}

.sig-staple-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
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

.sig-staple-actions {
  display: flex;
  gap: 6px;
  margin-top: 6px;
  flex-wrap: wrap;
}

.btn-staple-sets,
.btn-staple-spotify {
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 4px;
  border: 1px solid #333;
  background: #1a1a1a;
  color: #aaa;
  cursor: pointer;
}
.btn-staple-sets:hover { border-color: #00e676; color: #00e676; }
.btn-staple-spotify:hover { border-color: #1db954; color: #1db954; }

.staple-sets-panel {
  margin-top: 8px;
  border-top: 1px solid #1e1e1e;
  padding-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.staple-sets-panel[hidden] { display: none; }

.staple-sets-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 11px;
}

.staple-sets-link {
  color: #00e676;
  text-decoration: none;
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.staple-sets-link:hover { text-decoration: underline; }
.staple-sets-time { color: #666; white-space: nowrap; }
.staple-sets-conf { font-size: 10px; font-weight: 700; white-space: nowrap; }
.staple-sets-dj-label { color: #555; white-space: nowrap; font-size: 10px; }
.staple-spotify-embed { margin-top: 8px; }

/* ── Staple filter bar ── */
.sig-staples-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 4px;
}
.sig-staples-header h3 { margin: 0; }
.staple-filter-bar { display: flex; gap: 4px; flex-wrap: wrap; }
.staple-filter-btn {
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 12px;
  border: 1px solid #333;
  background: #1a1a1a;
  color: #888;
  cursor: pointer;
}
.staple-filter-btn--active { border-color: #00e676; color: #00e676; background: #0d1f14; }
.staple-filter-btn:hover { border-color: #00e676; color: #00e676; }

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
  grid-template-columns: 16px 120px 1fr 40px;
  align-items: center;
  gap: 8px;
}

.genre-bar-arrow {
  font-size: 12px;
  color: #555;
  display: inline-block;
  transition: transform 0.2s, color 0.15s;
  line-height: 1;
}

.genre-bar-row--clickable {
  cursor: pointer;
  border-radius: 4px;
  padding: 2px 0;
  transition: background 0.15s;
}
.genre-bar-row--clickable:hover { background: #181818; }
.genre-bar-row--clickable:hover .genre-bar-label { color: #fff; }
.genre-bar-row--clickable:hover .genre-bar-arrow { color: #aaa; }
.genre-bar-row--open .genre-bar-arrow { transform: rotate(90deg); color: #00e676; }

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

.genre-tracks-panel {
  margin: 4px 0 8px 0;
  padding: 10px;
  background: #0d0d0d;
  border: 1px solid #1e1e1e;
  border-radius: 6px;
}
.genre-tracks-panel[hidden] { display: none; }

.genre-tracks-grid {
  margin-top: 4px;
}

/* ── Genre / Label distribution tabs ── */
.distrib-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 12px;
}

.distrib-tab {
  font-size: 12px;
  padding: 5px 14px;
  border-radius: 12px;
  border: 1px solid #333;
  background: #1a1a1a;
  color: #888;
  cursor: pointer;
}
.distrib-tab--active { border-color: #00e676; color: #00e676; background: #0d1f14; }
.distrib-tab:hover:not(.distrib-tab--active) { border-color: #555; color: #ccc; }
.distrib-pane[hidden] { display: none; }

/* Genre/label search + pagination */
.distrib-search-wrap {
  margin: 10px 0 6px;
}
.distrib-search-input {
  width: 100%;
  box-sizing: border-box;
  background: #111;
  border: 1px solid #2a2a2a;
  border-radius: 4px;
  color: #ccc;
  font-size: 12px;
  padding: 6px 10px;
  outline: none;
  transition: border-color 0.15s;
}
.distrib-search-input:focus { border-color: #444; }
.distrib-search-input::placeholder { color: #555; }
.distrib-pagination {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid #1a1a1a;
}
.distrib-pg-btn {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 4px;
  color: #aaa;
  cursor: pointer;
  font-size: 12px;
  padding: 4px 10px;
  transition: background 0.15s, color 0.15s;
}
.distrib-pg-btn:hover:not(:disabled) { background: #252525; color: #fff; }
.distrib-pg-btn:disabled { opacity: 0.3; cursor: default; }
.distrib-pg-info { font-size: 12px; color: #555; flex: 1; text-align: center; }
.genre-bar-item[hidden] { display: none; }

.label-panel-header {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 8px;
}

.btn-discogs-label {
  display: inline-block;
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 4px;
  border: 1px solid #333;
  background: #1a1a1a;
  color: #aaa;
  text-decoration: none;
  cursor: pointer;
}
.btn-discogs-label:hover { border-color: #f60; color: #f60; }

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

/* ── Set card: in-place expand on tracklist toggle ── */
.set-card--expanded {
  height: 520px;
  transform: none !important;
}
.set-card--expanded .set-card-body {
  flex: 0 0 auto;
}
.set-card--expanded .set-card-tracklist {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.set-card-tracklist {
  border-top: 1px solid #1e1e1e;
  padding: 10px 16px 14px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.set-card-tracklist[hidden] { display: none; }

.sc-toggle-btn {
  font-size: 11px;
  color: #666;
  background: none;
  border: none;
  cursor: pointer;
  padding: 0;
  white-space: nowrap;
}
.sc-toggle-btn:hover { color: #00e676; text-decoration: underline; }
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
    set_titles = [s['title'] for s in set_summaries]

    for key, count in track_counter.most_common():
        info = track_info.get(key, {})
        appeared_in = {a['set_title'] for a in info.get('appearances', [])}
        presence = [1 if title in appeared_in else 0 for title in set_titles]
        entry = {
            'key': key,
            'artist': info.get('artist', ''),
            'title': info.get('title', key),
            'count': count,
            'spotify_url': info.get('spotify_url'),
            'spotify_album_art': info.get('spotify_album_art'),
            'appearances': info.get('appearances', []),
            'presence': presence,
        }
        if count >= 3:
            staples.append(entry)
        elif count == 2:
            regulars.append(entry)
        else:
            one_offs.append(entry)

    recurring = len(staples) + len(regulars)
    signature_score = (recurring / unique * 100) if unique else 0

    # Genre, label, and artist distribution from track_info
    genre_counter: Counter = Counter()
    label_counter: Counter = Counter()
    artist_counter: Counter = Counter()
    for info in track_info.values():
        for genre in info.get('genres', []):
            genre_counter[genre] += 1
        if info.get('discogs_label'):
            label_counter[info['discogs_label']] += 1
        if info.get('artist'):
            artist_counter[info['artist']] += 1

    return {
        'unique_tracks': unique,
        'staples': staples,
        'regulars': regulars,
        'one_offs': one_offs,
        'signature_score': signature_score,
        'total_sets': len(set_summaries),
        'top_genres': genre_counter.most_common(),
        'top_labels': label_counter.most_common(),
        'top_artists': artist_counter.most_common(),
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

    # All recurring tracks (count >= 2): staples + regulars, sorted by count desc
    all_recurring = staples + regulars
    staple_cards_html = ''
    if all_recurring:
        # Dynamic filter thresholds based on actual max play count
        max_recurring_count = all_recurring[0]['count'] if all_recurring else 2
        filter_thresholds = [t for t in [2, 3, 4, 5, 10] if t <= max_recurring_count]
        if max_recurring_count > 10:
            filter_thresholds.append(max_recurring_count)

        filter_btns = ''.join(
            f'<button class="staple-filter-btn{" staple-filter-btn--active" if thresh == 3 else ""}" '
            f'data-min="{thresh}" onclick="filterStaples({thresh})">{thresh}+ sets</button>'
            for i, thresh in enumerate(filter_thresholds)
        )

        _conf_colors_map = {'HIGH': '#00e676', 'MEDIUM': '#ffd740', 'LOW': '#ff9100', 'UNCERTAIN': '#757575'}
        cards = []
        for entry in all_recurring:
            count = entry['count']
            sparkline = _render_sparkline(entry['presence'])

            # Spotify embed button
            spotify_btn = ''
            if entry.get('spotify_url'):
                spot_id = entry['spotify_url'].split('/')[-1].split('?')[0]
                spot_id_esc = _esc(spot_id)
                spotify_btn = (
                    f'<button class="btn-staple-spotify" '
                    f'onclick="toggleStapleSpotify(this, \'{spot_id_esc}\')">'
                    f'\u25b6 Spotify</button>'
                )

            # Sets panel rows
            appearances = entry.get('appearances', [])
            sets_rows = []
            for app in appearances:
                set_html_rel = app.get('set_html_rel')
                pos = app.get('track_position')
                anchor = f'#track-{pos}' if pos else ''
                if set_html_rel:
                    href = quote(set_html_rel, safe='/') + anchor
                    target = '_self'
                elif app.get('source_deep_link'):
                    href = _esc(app['source_deep_link'])
                    target = '_blank'
                else:
                    href = '#'
                    target = '_self'
                set_title_esc = _esc(app.get('set_title', 'Unknown Set'))
                time_esc = _esc(app.get('time_range', ''))
                conf = app.get('confidence', 'UNCERTAIN')
                conf_color = _conf_colors_map.get(conf, '#757575')
                sets_rows.append(
                    f'<div class="staple-sets-row">'
                    f'<a class="staple-sets-link" href="{href}" target="{target}">{set_title_esc}</a>'
                    f'<span class="staple-sets-time">{time_esc}</span>'
                    f'<span class="staple-sets-conf" style="color:{conf_color};">{_esc(conf)}</span>'
                    f'</div>'
                )

            sets_panel = (
                f'<div class="staple-sets-panel" hidden>'
                + '\n'.join(sets_rows)
                + '</div>'
            ) if sets_rows else ''

            sets_btn = (
                f'<button class="btn-staple-sets" onclick="toggleStapleSets(this)">'
                f'\u25b8 Sets ({count})</button>'
            ) if sets_rows else ''

            art_url = entry.get('spotify_album_art') or ''
            art_html = (
                f'<img class="sig-staple-art" src="{_esc(art_url)}" alt="" loading="lazy">'
                if art_url else '<div class="sig-staple-art--empty"></div>'
            )
            cards.append(
                f'<div class="sig-staple-card" data-count="{count}">'
                f'{art_html}'
                f'<div class="sig-staple-header">'
                f'<div class="sig-staple-count">{count} sets</div>'
                f'{sparkline}'
                f'</div>'
                f'<div class="sig-staple-artist">{_esc(entry["artist"])}</div>'
                f'<div class="sig-staple-title">{_esc(entry["title"])}</div>'
                f'<div class="sig-staple-actions">'
                f'{sets_btn}'
                f'{spotify_btn}'
                f'</div>'
                f'{sets_panel}'
                f'</div>'
            )

        staple_cards_html = (
            f'<div class="sig-staples">'
            f'<div class="sig-staples-header">'
            f'<div class="staple-filter-bar">{filter_btns}</div>'
            f'</div>'
            f'<div class="sig-staples-grid" id="staplesGrid">'
            + ''.join(cards)
            + '</div></div>'
        )

    # Genre + Label + Artist distribution (tabbed)
    distrib_html = ''
    top_genres = sig['top_genres']
    top_labels = sig['top_labels']
    top_artists = sig.get('top_artists', [])
    if top_genres or top_labels or top_artists:
        _gc_map = {'HIGH': '#00e676', 'MEDIUM': '#ffd740', 'LOW': '#ff9100', 'UNCERTAIN': '#757575'}
        _set_titles = [s['title'] for s in set_summaries]

        def _make_track_entry(key, info):
            _appeared_in = {a['set_title'] for a in info.get('appearances', [])}
            return {
                'key': key,
                'artist': info.get('artist', ''),
                'title': info.get('title', key),
                'count': track_counter.get(key, 1),
                'spotify_url': info.get('spotify_url'),
                'spotify_album_art': info.get('spotify_album_art'),
                'appearances': info.get('appearances', []),
                'presence': [1 if t in _appeared_in else 0 for t in _set_titles],
                'discogs_label_url': info.get('discogs_label_url'),
            }

        def _render_track_card(ge):
            ge_count = ge['count']
            ge_spotify_btn = ''
            if ge.get('spotify_url'):
                ge_spot_id = _esc(ge['spotify_url'].split('/')[-1].split('?')[0])
                ge_spotify_btn = (
                    f'<button class="btn-staple-spotify" '
                    f'onclick="toggleStapleSpotify(this, \'{ge_spot_id}\')">'
                    f'\u25b6 Spotify</button>'
                )
            ge_sets_rows = []
            for app in ge.get('appearances', []):
                set_html_rel = app.get('set_html_rel')
                pos = app.get('track_position')
                anchor = f'#track-{pos}' if pos else ''
                if set_html_rel:
                    href = quote(set_html_rel, safe='/') + anchor
                    target = '_self'
                elif app.get('source_deep_link'):
                    href = _esc(app['source_deep_link'])
                    target = '_blank'
                else:
                    href = '#'
                    target = '_self'
                conf = app.get('confidence', 'UNCERTAIN')
                ge_sets_rows.append(
                    f'<div class="staple-sets-row">'
                    f'<a class="staple-sets-link" href="{href}" target="{target}">{_esc(app.get("set_title", "Unknown Set"))}</a>'
                    f'<span class="staple-sets-time">{_esc(app.get("time_range", ""))}</span>'
                    f'<span class="staple-sets-conf" style="color:{_gc_map.get(conf, "#757575")};">{_esc(conf)}</span>'
                    f'</div>'
                )
            ge_sets_panel = (
                '<div class="staple-sets-panel" hidden>' + '\n'.join(ge_sets_rows) + '</div>'
            ) if ge_sets_rows else ''
            ge_sets_btn = (
                f'<button class="btn-staple-sets" onclick="toggleStapleSets(this)">'
                f'\u25b8 Sets ({ge_count})</button>'
            ) if ge_sets_rows else ''
            ge_art = ge.get('spotify_album_art') or ''
            ge_art_html = (
                f'<img class="sig-staple-art" src="{_esc(ge_art)}" alt="" loading="lazy">'
                if ge_art else '<div class="sig-staple-art--empty"></div>'
            )
            return (
                f'<div class="sig-staple-card" data-count="{ge_count}">'
                f'{ge_art_html}'
                f'<div class="sig-staple-header">'
                f'<div class="sig-staple-count">{ge_count} set{"s" if ge_count != 1 else ""}</div>'
                f'{_render_sparkline(ge["presence"])}'
                f'</div>'
                f'<div class="sig-staple-artist">{_esc(ge["artist"])}</div>'
                f'<div class="sig-staple-title">{_esc(ge["title"])}</div>'
                f'<div class="sig-staple-actions">{ge_sets_btn}{ge_spotify_btn}</div>'
                f'{ge_sets_panel}'
                f'</div>'
            )

        def _render_bar_rows(top_items, lookup, label_urls=None):
            max_count = top_items[0][1]
            rows = []
            for name, count in top_items:
                pct = count / max_count * 100
                entries = lookup.get(name, [])
                cards_html = ''.join(_render_track_card(e) for e in entries)
                discogs_hdr = ''
                if label_urls:
                    lurl = label_urls.get(name)
                    if lurl:
                        discogs_hdr = (
                            f'<div class="label-panel-header">'
                            f'<a class="btn-discogs-label" href="{_esc(lurl)}" target="_blank">'
                            f'View Label on Discogs \u2192</a></div>'
                        )
                panel_html = (
                    f'<div class="genre-tracks-panel" hidden>'
                    f'{discogs_hdr}'
                    f'<div class="genre-tracks-grid">{cards_html}</div></div>'
                ) if cards_html else ''
                clickable = bool(cards_html)
                row_cls = 'genre-bar-row genre-bar-row--clickable' if clickable else 'genre-bar-row'
                click_attr = ' onclick="toggleGenreTracks(this)"' if clickable else ''
                arrow_html = '<span class="genre-bar-arrow">&#8250;</span>' if clickable else '<span></span>'
                rows.append(
                    f'<div class="genre-bar-item">'
                    f'<div class="{row_cls}"{click_attr}>'
                    f'{arrow_html}'
                    f'<span class="genre-bar-label">{_esc(name)}</span>'
                    f'<div class="genre-bar-track"><div class="genre-bar-fill" style="width:{pct:.1f}%;"></div></div>'
                    f'<span class="genre-bar-count">{count}</span>'
                    f'</div>' + panel_html +
                    f'</div>'
                )
            return f'<div class="sig-genres"><div class="genre-bars">{"".join(rows)}</div></div>'

        # ── Genre pane ──
        genre_pane_html = ''
        if top_genres:
            genre_to_tracks: dict = {}
            for _key, _info in track_info.items():
                if not _info.get('genres'):
                    continue
                _entry = _make_track_entry(_key, _info)
                for _g in _info['genres']:
                    genre_to_tracks.setdefault(_g, []).append(_entry)
            for _g in genre_to_tracks:
                genre_to_tracks[_g].sort(key=lambda x: x['count'], reverse=True)
            genre_pane_html = _render_bar_rows(top_genres, genre_to_tracks)

        # ── Label pane ──
        label_pane_html = ''
        if top_labels:
            label_to_tracks: dict = {}
            label_to_url: dict = {}
            for _key, _info in track_info.items():
                label = _info.get('discogs_label')
                if not label:
                    continue
                _entry = _make_track_entry(_key, _info)
                label_to_tracks.setdefault(label, []).append(_entry)
                if _info.get('discogs_label_url') and label not in label_to_url:
                    label_to_url[label] = _info['discogs_label_url']
            for lb in label_to_tracks:
                label_to_tracks[lb].sort(key=lambda x: x['count'], reverse=True)
            label_pane_html = _render_bar_rows(top_labels, label_to_tracks, label_to_url)

        # ── Artist pane ──
        artist_pane_html = ''
        if top_artists:
            artist_to_tracks: dict = {}
            for _key, _info in track_info.items():
                _artist = _info.get('artist')
                if not _artist:
                    continue
                _entry = _make_track_entry(_key, _info)
                artist_to_tracks.setdefault(_artist, []).append(_entry)
            for _a in artist_to_tracks:
                artist_to_tracks[_a].sort(key=lambda x: x['count'], reverse=True)
            artist_pane_html = _render_bar_rows(top_artists, artist_to_tracks)

        # ── Assemble tabbed widget ──
        genres_first = bool(genre_pane_html)
        labels_first = not genres_first and bool(label_pane_html)
        artists_first = not genres_first and not labels_first and bool(artist_pane_html)
        genre_btn_cls = 'distrib-tab distrib-tab--active' if genres_first else 'distrib-tab'
        label_btn_cls = 'distrib-tab distrib-tab--active' if labels_first else 'distrib-tab'
        artist_btn_cls = 'distrib-tab distrib-tab--active' if artists_first else 'distrib-tab'
        tabs_html = (
            f'<div class="distrib-tabs">'
            f'<button class="{genre_btn_cls}" data-tab="genres" onclick="switchDistribTab(\'genres\', this)">Genres</button>'
            f'<button class="{label_btn_cls}" data-tab="labels" onclick="switchDistribTab(\'labels\', this)">Labels</button>'
            f'<button class="{artist_btn_cls}" data-tab="track-artists" onclick="switchDistribTab(\'track-artists\', this)">Artists</button>'
            f'</div>'
        )

        def _artist_paged_pane(bars_html, tab, placeholder, hidden):
            if not bars_html:
                return (
                    f'<div class="distrib-pane" data-tab="{tab}" data-page="0"{" hidden" if hidden else ""}>'
                    f'<p class="empty">No data available.</p></div>'
                )
            return (
                f'<div class="distrib-pane" data-tab="{tab}" data-page="0"{" hidden" if hidden else ""}>'
                f'<div class="distrib-search-wrap">'
                f'<input class="distrib-search-input" type="text" placeholder="{placeholder}" '
                f'oninput="distribSearch(this)">'
                f'</div>'
                + bars_html +
                f'<div class="distrib-pagination">'
                f'<button class="distrib-pg-btn" onclick="distribPage(this,-1)">&#8249; Prev</button>'
                f'<span class="distrib-pg-info"></span>'
                f'<button class="distrib-pg-btn" onclick="distribPage(this,1)">Next &#8250;</button>'
                f'</div>'
                f'</div>'
            )

        genre_pane = _artist_paged_pane(genre_pane_html, 'genres', 'Search genres\u2026', hidden=not genres_first)
        label_pane = _artist_paged_pane(label_pane_html, 'labels', 'Search labels\u2026', hidden=not labels_first)
        artist_pane = _artist_paged_pane(artist_pane_html, 'track-artists', 'Search artists\u2026', hidden=not artists_first)
        distrib_html = tabs_html + genre_pane + label_pane + artist_pane

    return staple_cards_html, distrib_html


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
    <button class="stl-expand-btn" onclick="toggleSetExpand({idx})">\u25b8 Show Tracklist</button>
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
    if (btn) btn.innerHTML = '\u25be Hide Tracklist';
    drawContinuityArcs();
  } else {
    tracklist.hidden = true;
    if (btn) btn.innerHTML = '\u25b8 Show Tracklist';
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
    for idx, s in enumerate(set_summaries):
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

        # Tracklist rows (same format as Set Timeline)
        _card_conf_colors = {
            'HIGH': '#00e676',
            'MEDIUM': '#ffd740',
            'LOW': '#ff9100',
            'UNCERTAIN': '#757575',
        }
        card_tracks = s.get('tracks', [])
        track_rows_html = ''
        if card_tracks:
            row_parts = []
            for t in card_tracks:
                conf = t.get('confidence', 'UNCERTAIN')
                conf_color = _card_conf_colors.get(conf, '#757575')
                artist_esc_t = _esc(t.get('artist', ''))
                title_esc_t = _esc(t.get('title', ''))
                time_esc = _esc(t.get('start_time_formatted', ''))
                tkey_esc = _esc(t.get('track_key', ''))
                row_parts.append(
                    f'<div class="stl-track" data-track-key="{tkey_esc}">'
                    f'<span class="stl-track-time">{time_esc}</span>'
                    f'<span class="stl-track-name">'
                    f'<span class="stl-track-artist">{artist_esc_t}</span>'
                    f' \u2014 '
                    f'<span class="stl-track-title">{title_esc_t}</span>'
                    f'</span>'
                    f'<span class="stl-track-conf" style="border-color:{conf_color};color:{conf_color};">'
                    f'{_esc(conf)}</span>'
                    f'</div>'
                )
            track_rows_html = '\n'.join(row_parts)

        toggle_btn = (
            f'<button class="sc-toggle-btn" onclick="toggleCardTracklist({idx})">'
            f'\u25b8 Show Tracklist</button>'
            if card_tracks else ''
        )

        tracklist_div = (
            f'<div class="set-card-tracklist" hidden>\n{track_rows_html}\n</div>'
            if card_tracks else ''
        )

        cards.append(f'''<div class="set-card" data-card-idx="{idx}" data-tracks="{data_tracks}" data-rate="{data_rate}" data-duration="{data_duration}" data-search="{data_search}">
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
      {toggle_btn}
    </div>
  </div>
  {tracklist_div}
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
        stats_html         = _render_stats(counts, total, recognized, tracks)
        timeline_html      = _render_timeline(tracks, total_duration)
        journey_chart_html = _render_journey_chart(tracks, total_duration)
        cards_html         = _render_track_cards(tracks, platform)
        player_html   = _render_player(platform, embed_id)
        player_js     = _render_player_js(platform, embed_id, tracks)
        pill_html = (
            f'<div class="player-pill" id="playerPill" onclick="event.stopPropagation()" data-duration="{total_duration:.3f}">'
            f'<div class="pill-now-playing" id="pillNowPlaying">'
            f'<img class="pill-album-art" id="pillAlbumArt" src="" alt="" />'
            f'<div class="pill-track-title" id="pillTrackTitle"></div>'
            f'<div class="pill-track-artist" id="pillTrackArtist"></div>'
            f'</div>'
            f'<div class="pill-progress-bar" id="pillProgressBar"><div class="pill-progress-fill" id="pillProgressFill"></div></div>'
            f'<div class="pill-time-row">'
            f'<span id="pillTimeCurrent">0:00</span>'
            f'<span>{_esc(format_time(total_duration))}</span>'
            f'</div>'
            f'<div class="pill-controls">'
            f'<button class="btn pill-track-nav-btn" onclick="skipToPrevTrack()" title="Previous track">&#9198;</button>'
            f'<button class="btn pill-play" id="pillPlayBtn" onclick="togglePillPlay()" title="Play / Pause">&#9654;</button>'
            f'<button class="btn pill-track-nav-btn" onclick="skipToNextTrack()" title="Next track">&#9197;</button>'
            f'</div>'
            f'<div class="pill-track-nav">'
            f'<button class="btn pill-skip" onclick="skipPlayer(-15)" title="Back 15 seconds">\u221215</button>'
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

  <!-- Journey Chart -->
  {journey_chart_html}

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

<div id="journey-tooltip" aria-hidden="true">
  <div class="jt-title"></div>
  <div class="jt-value"></div>
</div>

{pill_html}

<script>{JS}</script>
{_render_track_card_js()}
{player_js}
<script>
// ── Hash-based track deep-link: scroll to and briefly highlight ──
(function() {{
  var hash = window.location.hash;
  if (!hash) return;
  var el = document.querySelector(hash);
  if (!el) return;
  el.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
  el.style.transition = 'background 0.3s';
  el.style.background = '#2a3a1a';
  setTimeout(function() {{ el.style.background = ''; }}, 2000);
}})();
</script>
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

        sets_html                    = _render_set_cards(set_summaries)
        failed_html                  = _render_failed_section(failed)
        signature_html, distrib_html  = _render_signature_analysis(track_counter, track_info, set_summaries)

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

  {f'<section><h2>Track Distribution</h2>{distrib_html}</section>' if distrib_html else ''}

  <section>
    <h2>Most Played Tracks</h2>
    {signature_html}
  </section>

  <section id="sets-section">
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
    <div class="sets-grid" id="setsGrid">
      {sets_html}
    </div>
  </section>

  {failed_html}

  <div class="footer">
    Generated {_esc(generated)} &middot; DJ Set Setlist Generator
  </div>

</div>

<script>
/* ── Set card: tracklist toggle ── */
function toggleCardTracklist(idx) {{
  var card = document.querySelector('.set-card[data-card-idx="' + idx + '"]');
  var tracklist = card ? card.querySelector('.set-card-tracklist') : null;
  var btn = card ? card.querySelector('.sc-toggle-btn') : null;
  if (!tracklist) return;
  if (tracklist.hidden) {{
    tracklist.hidden = false;
    card.classList.add('set-card--expanded');
    if (btn) btn.innerHTML = '\u25be Hide Tracklist';
  }} else {{
    tracklist.hidden = true;
    card.classList.remove('set-card--expanded');
    if (btn) btn.innerHTML = '\u25b8 Show Tracklist';
  }}
}}

/* ── Set grid: stable explicit columns ── */
(function () {{
  var setsGrid = document.getElementById('setsGrid');
  if (!setsGrid) return;

  var CARD_MIN_WIDTH = 270;
  var GAP = 12;

  function getNumCols() {{
    return Math.max(1, Math.floor((setsGrid.offsetWidth + GAP) / (CARD_MIN_WIDTH + GAP)));
  }}

  function buildColumns(cards) {{
    var nCols = getNumCols();
    var cols = [];
    for (var i = 0; i < nCols; i++) {{
      var col = document.createElement('div');
      col.className = 'sets-col';
      cols.push(col);
    }}
    cards.forEach(function (card, i) {{ cols[i % nCols].appendChild(card); }});
    setsGrid.innerHTML = '';
    cols.forEach(function (col) {{ setsGrid.appendChild(col); }});
  }}

  function getAllCards() {{
    return Array.from(setsGrid.querySelectorAll('.set-card'));
  }}

  buildColumns(getAllCards());

  var resizeTimer;
  window.addEventListener('resize', function () {{
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {{ buildColumns(getAllCards()); }}, 150);
  }});

  var searchInput = document.getElementById('setSearch');
  if (searchInput) {{
    searchInput.addEventListener('input', function () {{
      var query = searchInput.value.toLowerCase().trim();
      getAllCards().forEach(function (card) {{
        card.style.display = !query || card.dataset.search.includes(query) ? '' : 'none';
      }});
    }});
  }}

  /* ── Handle ?q= URL param: pre-fill setSearch and scroll to section ── */
  (function() {{
    var params = new URLSearchParams(window.location.search);
    var q = params.get('q');
    if (q && searchInput) {{
      searchInput.value = q;
      searchInput.dispatchEvent(new Event('input'));
      var section = document.getElementById('sets-section');
      if (section) {{
        setTimeout(function() {{ section.scrollIntoView({{behavior: 'smooth', block: 'start'}}); }}, 120);
      }}
    }}
  }})();

  document.querySelectorAll('.sort-btn').forEach(function (btn) {{
    btn.addEventListener('click', function () {{
      document.querySelectorAll('.sort-btn').forEach(function (b) {{ b.classList.remove('active'); }});
      btn.classList.add('active');
      var sortBy = btn.dataset.sort;
      var cards = getAllCards();
      cards.sort(function (a, b) {{
        switch (sortBy) {{
          case 'tracks':   return parseInt(b.dataset.tracks)   - parseInt(a.dataset.tracks);
          case 'rate':     return parseInt(b.dataset.rate)     - parseInt(a.dataset.rate);
          case 'duration': return parseInt(b.dataset.duration) - parseInt(a.dataset.duration);
          default: return 0;
        }}
      }});
      buildColumns(cards);
    }});
  }});
}})();

/* ── DJ Staples: filter by minimum play count (scoped to #staplesGrid only) ── */
/* ── Build 2-row horizontal scroll grid ── */
function build2RowGrid(grid) {{
  var allCards = Array.from(grid.querySelectorAll('.sig-staple-card'));
  // Stamp each card with its original position on first encounter so
  // subsequent rebuilds (after filter, etc.) sort back to the correct order.
  allCards.forEach(function(card, i) {{
    if (card.dataset.rank == null) card.dataset.rank = i;
  }});
  allCards.sort(function(a, b) {{
    return parseInt(a.dataset.rank, 10) - parseInt(b.dataset.rank, 10);
  }});
  allCards.forEach(function(card) {{
    var embed = card.querySelector('.staple-spotify-embed');
    if (embed) {{
      embed.remove();
      var btn = card.querySelector('.btn-staple-spotify');
      if (btn) btn.textContent = '\u25b6 Spotify';
      card.classList.remove('sig-staple-card--expanded');
      card.style.removeProperty('top');
      card.style.removeProperty('left');
      card.style.removeProperty('width');
    }}
    card.style.removeProperty('margin-top');
    card.style.removeProperty('margin-left');
  }});
  var visible = allCards.filter(function(c) {{ return c.style.display !== 'none'; }});
  var hidden  = allCards.filter(function(c) {{ return c.style.display === 'none'; }});
  var inner = document.createElement('div'); inner.className = 'hscroll-inner';
  for (var i = 0; i < visible.length; i += 2) {{
    var col = document.createElement('div'); col.className = 'hscroll-col';
    col.appendChild(visible[i]);
    if (visible[i + 1]) col.appendChild(visible[i + 1]);
    inner.appendChild(col);
  }}
  var outer = document.createElement('div'); outer.className = 'hscroll-outer';
  outer.appendChild(inner);
  var buf = document.createElement('div'); buf.style.display = 'none';
  hidden.forEach(function(c) {{ buf.appendChild(c); }});
  grid.innerHTML = '';
  grid.appendChild(outer);
  if (buf.children.length) grid.appendChild(buf);
}}

function filterStaples(minCount) {{
  var grid = document.getElementById('staplesGrid');
  if (grid) {{
    grid.querySelectorAll('.sig-staple-card').forEach(function(card) {{
      var count = parseInt(card.dataset.count, 10);
      card.style.display = count >= minCount ? '' : 'none';
    }});
    build2RowGrid(grid);
  }}
  document.querySelectorAll('.staple-filter-btn').forEach(function(btn) {{
    btn.classList.toggle('staple-filter-btn--active', parseInt(btn.dataset.min, 10) === minCount);
  }});
}}

/* ── Helpers: grow hscroll-outer so expanded card is fully visible ── */
function _syncOuterHeight(card) {{
  var outer = card.closest('.hscroll-outer');
  if (!outer) return;
  outer.style.removeProperty('padding-bottom');
  requestAnimationFrame(function() {{
    var overflow = Math.ceil(card.getBoundingClientRect().bottom - outer.getBoundingClientRect().bottom);
    if (overflow > 0) outer.style.paddingBottom = overflow + 'px';
  }});
}}
function _resetOuterHeight(card) {{
  var outer = card.closest('.hscroll-outer');
  if (outer) outer.style.removeProperty('padding-bottom');
}}

/* ── DJ Staples: toggle "sets played in" panel ── */
function toggleStapleSets(btn) {{
  var card = btn.closest('.sig-staple-card');
  var panel = card ? card.querySelector('.staple-sets-panel') : null;
  if (!panel) return;
  var col = card ? card.parentElement : null;
  var inHscroll = col && col.classList.contains('hscroll-col');
  if (panel.hidden) {{
    if (inHscroll && !col.querySelector('.staple-expand-spacer')) {{
      var t = card.offsetTop, h = card.offsetHeight;
      var sp = document.createElement('div');
      sp.className = 'staple-expand-spacer'; sp.style.height = h + 'px'; sp.style.flexShrink = '0';
      col.insertBefore(sp, card);
      card.style.top = t + 'px'; card.style.left = '0';
      card.classList.add('sig-staple-card--expanded');
    }}
    panel.hidden = false;
    btn.innerHTML = '\u25be Sets';
    if (inHscroll) _syncOuterHeight(card);
  }} else {{
    panel.hidden = true;
    btn.innerHTML = '\u25b8 Sets (' + card.dataset.count + ')';
    if (inHscroll && !card.querySelector('.staple-spotify-embed')) {{
      var sp = col.querySelector('.staple-expand-spacer');
      if (sp) sp.remove();
      card.classList.remove('sig-staple-card--expanded');
      card.style.removeProperty('top'); card.style.removeProperty('left');
      _resetOuterHeight(card);
    }}
  }}
}}

/* ── DJ Staples: Spotify embed toggle (expands card 2× width, overlays neighbours) ── */
function toggleStapleSpotify(btn, trackId) {{
  var card = btn.closest('.sig-staple-card');
  var embed = card ? card.querySelector('.staple-spotify-embed') : null;
  var col = card ? card.parentElement : null;
  var inHscroll = col && col.classList.contains('hscroll-col');
  if (embed) {{
    embed.remove();
    btn.textContent = '\u25b6 Spotify';
    card.style.removeProperty('width');
    if (inHscroll) {{
      var setsPanel = card.querySelector('.staple-sets-panel');
      if (!setsPanel || setsPanel.hidden) {{
        var sp = col.querySelector('.staple-expand-spacer');
        if (sp) sp.remove();
        card.classList.remove('sig-staple-card--expanded');
        card.style.removeProperty('top'); card.style.removeProperty('left');
        _resetOuterHeight(card);
      }} else {{
        _syncOuterHeight(card);
      }}
    }}
    return;
  }}
  if (inHscroll && !col.querySelector('.staple-expand-spacer')) {{
    var t = card.offsetTop, h = card.offsetHeight;
    var sp = document.createElement('div');
    sp.className = 'staple-expand-spacer'; sp.style.height = h + 'px'; sp.style.flexShrink = '0';
    col.insertBefore(sp, card);
    card.style.top = t + 'px'; card.style.left = '0';
    card.classList.add('sig-staple-card--expanded');
  }}
  card.style.width = '408px';
  var div = document.createElement('div');
  div.className = 'staple-spotify-embed';
  div.innerHTML = '<iframe style="border-radius:8px" src="https://open.spotify.com/embed/track/' + trackId + '?utm_source=generator&theme=0" width="100%" height="80" frameBorder="0" allow="autoplay; clipboard-write; encrypted-media" loading="lazy"></iframe>';
  card.appendChild(div);
  btn.textContent = '\u2715 Close';
  if (inHscroll) _syncOuterHeight(card);
}}

/* ── Genre / Label distribution tabs ── */
function switchDistribTab(tabName, btn) {{
  var section = btn.closest('section') || document;
  section.querySelectorAll('.distrib-tab').forEach(function(t) {{
    t.classList.toggle('distrib-tab--active', t.dataset.tab === tabName);
  }});
  section.querySelectorAll('.distrib-pane').forEach(function(p) {{
    p.hidden = p.dataset.tab !== tabName;
  }});
}}

/* ── Genre breakdown: toggle track panel ── */
function toggleGenreTracks(row) {{
  var panel = row.nextElementSibling;
  if (!panel || !panel.classList.contains('genre-tracks-panel')) return;
  if (panel.hidden) {{
    panel.hidden = false;
    row.classList.add('genre-bar-row--open');
    var grid = panel.querySelector('.genre-tracks-grid');
    if (grid) build2RowGrid(grid);
  }} else {{
    panel.hidden = true;
    row.classList.remove('genre-bar-row--open');
  }}
}}

/* ── DJ Staples: 2-row horizontal scroll init ── */
(function () {{
  var staplesGrid = document.getElementById('staplesGrid');
  if (!staplesGrid) return;
  build2RowGrid(staplesGrid);
  filterStaples(3);
}})();

/* ── Genre/Label distribution: search + pagination ── */
var DISTRIB_PER_PAGE = 15;

function _distribUpdate(pane) {{
  var input = pane.querySelector('.distrib-search-input');
  var query = input ? input.value.toLowerCase().trim() : '';
  var items = Array.from(pane.querySelectorAll('.genre-bar-item'));
  var visible = query
    ? items.filter(function(item) {{
        var label = item.querySelector('.genre-bar-label');
        return label && label.textContent.toLowerCase().includes(query);
      }})
    : items;
  var page = parseInt(pane.dataset.page || '0', 10);
  var total = Math.max(1, Math.ceil(visible.length / DISTRIB_PER_PAGE));
  if (page >= total) page = total - 1;
  if (page < 0) page = 0;
  pane.dataset.page = page;
  var start = page * DISTRIB_PER_PAGE;
  var end = start + DISTRIB_PER_PAGE;
  items.forEach(function(item) {{ item.hidden = true; }});
  visible.slice(start, end).forEach(function(item) {{ item.hidden = false; }});
  var info = pane.querySelector('.distrib-pg-info');
  if (info) {{
    info.textContent = visible.length
      ? (page + 1) + ' / ' + total + (query ? '  (' + visible.length + ' match' + (visible.length !== 1 ? 'es' : '') + ')' : '')
      : 'No results';
  }}
  var btns = pane.querySelectorAll('.distrib-pg-btn');
  if (btns[0]) btns[0].disabled = page <= 0;
  if (btns[1]) btns[1].disabled = page >= total - 1;
}}

function distribSearch(input) {{
  var pane = input.closest('.distrib-pane');
  if (!pane) return;
  pane.dataset.page = '0';
  _distribUpdate(pane);
}}

function distribPage(btn, delta) {{
  var pane = btn.closest('.distrib-pane');
  if (!pane) return;
  pane.dataset.page = Math.max(0, parseInt(pane.dataset.page || '0', 10) + delta);
  _distribUpdate(pane);
}}

document.querySelectorAll('.distrib-pane[data-page]').forEach(function(pane) {{
  _distribUpdate(pane);
}});
</script>
</body>
</html>"""

        output_path = self.output_dir / "artist_summary.html"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Saved artist summary HTML: {output_path}")
        return output_path

    def save_master_summary_html(self, data: dict) -> Path:
        """Save the master cross-artist summary as output/index.html."""
        from collections import defaultdict as _ddict

        gs = data["global_stats"]
        generated = data["generated_at"]
        artists = data["artists"]
        genre_totals = data["genre_totals"]
        label_totals = data["label_totals"]
        most_played = data["most_played_tracks"]
        similarity_list = data["similarity_list"]
        all_sets = data["all_sets"]

        # Build track_registry: aggregates per-DJ appearances so genre/label
        # track cards can show the same "N DJs · M plays" header as most-played cards.
        track_registry: dict = {}  # track_key -> unified dict with dj_appearances
        for a in artists:
            for key, track in a.get("tracks", {}).items():
                if key not in track_registry:
                    track_registry[key] = {
                        "display_artist": track["display_artist"],
                        "display_title": track["display_title"],
                        "spotify_url": track.get("spotify_url"),
                        "spotify_album_art": track.get("spotify_album_art"),
                        "discogs_label": track.get("discogs_label"),
                        "discogs_label_url": track.get("discogs_label_url"),
                        "genres": track.get("genres", []),
                        "dj_appearances": [],
                        "total_appearances": 0,
                    }
                else:
                    reg = track_registry[key]
                    if not reg["spotify_album_art"] and track.get("spotify_album_art"):
                        reg["spotify_album_art"] = track["spotify_album_art"]
                    if not reg["discogs_label"] and track.get("discogs_label"):
                        reg["discogs_label"] = track["discogs_label"]
                        reg["discogs_label_url"] = track.get("discogs_label_url")
                    if not reg["genres"] and track.get("genres"):
                        reg["genres"] = track["genres"]
                track_registry[key]["dj_appearances"].append({
                    "dj": a["name"],
                    "appearances": track.get("appearances", 1),
                    "sets": track.get("sets", []),
                    "dir_name": a.get("dir_name", ""),
                })
                track_registry[key]["total_appearances"] += track.get("appearances", 1)

        for reg in track_registry.values():
            reg["num_djs"] = len(reg["dj_appearances"])
            reg["is_cross_artist"] = reg["num_djs"] >= 2
            reg["dj_appearances"].sort(key=lambda x: x["appearances"], reverse=True)

        # Build genre/label/artist lookups from registry
        genre_to_tracks: dict = _ddict(dict)  # genre -> {track_key: registry_entry}
        label_to_tracks: dict = _ddict(dict)  # label -> {track_key: registry_entry}
        ta_to_tracks: dict = _ddict(dict)      # track artist -> {track_key: registry_entry}
        label_to_url: dict = {}
        for key, reg in track_registry.items():
            for g in reg.get("genres", []):
                norm = g.title()
                if norm != "House":
                    genre_to_tracks[norm][key] = reg
            label = reg.get("discogs_label")
            if label:
                label_to_tracks[label][key] = reg
                if label not in label_to_url and reg.get("discogs_label_url"):
                    label_to_url[label] = reg["discogs_label_url"]
            ta = reg.get("display_artist")
            if ta:
                ta_to_tracks[ta][key] = reg

        from collections import Counter as _Counter
        ta_counter = _Counter({ta: len(tracks) for ta, tracks in ta_to_tracks.items()})
        artist_totals_master = [{"artist": ta, "count": cnt} for ta, cnt in ta_counter.most_common()]

        artist_cards_html = _render_master_artist_cards(artists)
        genre_label_html = _render_master_genre_label(
            genre_totals, label_totals, genre_to_tracks, label_to_tracks, label_to_url,
            artist_totals=artist_totals_master, artist_to_tracks=ta_to_tracks,
            most_played=most_played,
        )
        matrix_html = _render_master_similarity_matrix(artists, data["similarity_matrix"])
        all_sets_html = _render_master_all_sets(all_sets)

        import json as _json
        sim_json = _json.dumps(
            [
                {
                    "artist_a": s["artist_a"],
                    "artist_b": s["artist_b"],
                    "score": s["score"],
                    "normalized_score": s["normalized_score"],
                    "shared_tracks": s["shared_tracks"],
                    "shared_labels": s["shared_labels"],
                    "shared_music_artists": s["shared_music_artists"],
                    "shared_genres": s["shared_genres"],
                }
                for s in similarity_list
            ],
            ensure_ascii=False,
        )

        # Serialize track_registry for client-side filtering
        track_reg_json = _json.dumps(track_registry, ensure_ascii=False)

        n_artists = gs["total_artists"]
        n_sets = gs["total_sets"]
        n_tracks = gs["total_unique_tracks"]
        n_appearances = gs["total_appearances"]
        n_all_sets = len(all_sets)
        artist_filter_btns = "".join(
            '<button class="sort-btn" data-artist="{esc_name}" '
            'onclick="filterAllSets({json_name}, this)">'
            '{esc_name}</button>'.format(
                esc_name=_esc(a["name"]),
                json_name=_esc(_json.dumps(a["name"])),
            )
            for a in artists
        )
        distrib_artist_btns = "".join(
            '<button class="sort-btn distrib-artist-btn" data-artist="{esc_name}" '
            'onclick="toggleDistribArtistBtn(this)">'
            '{esc_name}</button>'.format(
                esc_name=_esc(a["name"]),
            )
            for a in artists
        )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>All Artists — Master Overview</title>
  <style>{_SUMMARY_CSS}{_MASTER_CSS}</style>
</head>
<body>
<div class="container">

  <div class="artist-name">All Artists</div>
  <div class="page-subtitle">Master Overview</div>
  <div class="header-meta">Generated {_esc(generated)}</div>

  <div class="stats-strip">
    <div class="stat-block">
      <span class="stat-value">{n_artists}</span>
      <span class="stat-label">Artists</span>
    </div>
    <div class="stat-block">
      <span class="stat-value">{n_tracks:,}</span>
      <span class="stat-label">Unique Tracks</span>
    </div>
    <div class="stat-block">
      <span class="stat-value">{n_sets}</span>
      <span class="stat-label">Sets Analyzed</span>
    </div>
    <div class="stat-block">
      <span class="stat-value">{n_appearances:,}</span>
      <span class="stat-label">Total Appearances</span>
    </div>
  </div>

  <section>
    <h2>Artists ({n_artists})</h2>
    <input id="artistSearch" class="search-input" type="search"
           placeholder="Filter artists…" autocomplete="off"
           style="margin-bottom:16px"
           oninput="filterArtistCards(this.value)">
    <div class="master-artist-grid" id="artistCardsGrid">
      {artist_cards_html}
    </div>
  </section>

  {f'''<section id="trackDistribSection">
  <div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:8px">
    <h2 style="margin:0">Track Distribution</h2>
    <span id="distribHint" class="distrib-section-hint"></span>
  </div>
  <div class="sort-buttons" id="distribArtistBtns" style="margin-bottom:12px">
    {distrib_artist_btns}
  </div>
  <div id="distribFilterBar" hidden>
    <div class="distrib-mode-group">
      <button id="distribUnionBtn" class="distrib-mode-btn distrib-mode-btn--active" onclick="setDistribMode('union')">Union</button>
      <button id="distribIntersectBtn" class="distrib-mode-btn" onclick="setDistribMode('intersection')">Intersection</button>
    </div>
    <button class="distrib-clear-btn" onclick="clearDistribSelection()">\u00d7 Clear All</button>
  </div>
  {genre_label_html}
</section>''' if genre_label_html else ''}

  <section id="connectionsSection">
    <h2>Artist Connections</h2>
    <p class="master-hint">Click a cell in the matrix to explore what two artists share.</p>
    {matrix_html}
    <div id="connectionCards" class="master-connection-area">
      <p class="empty">Select a cell above to see shared tracks, labels, and artists.</p>
    </div>
  </section>

  <section>
    <h2>All Sets ({n_all_sets})</h2>
    <div class="sets-controls">
      <input id="allSetsSearch" class="search-input" type="search"
             placeholder="Search sets or tracks…" autocomplete="off">
      <div class="sort-buttons" id="artistFilterBtns">
        <button class="sort-btn active" data-artist="" onclick="filterAllSets('',this)">All Artists</button>
        {artist_filter_btns}
      </div>
    </div>
    <div class="sets-grid" id="allSetsGrid">
      {all_sets_html}
    </div>
  </section>

  <div class="footer">
    Generated {_esc(generated)} &middot; DJ Set Setlist Generator &middot;
    <a href="#" onclick="window.scrollTo({{top:0,behavior:'smooth'}});return false;">&uarr; Top</a>
  </div>

</div>
<script>
var SIMILARITY = {sim_json};
var TRACK_REGISTRY = {track_reg_json};
var _activePair = null;

/* ── Artist filter state ── */
var _distribSelectedArtists = new Set();
var _distribMode = 'union';
var _distribStaticBars = {{}};
(function() {{
  document.querySelectorAll('.distrib-pane[data-tab]').forEach(function(pane) {{
    var bars = pane.querySelector('.genre-bars');
    if (bars) _distribStaticBars[pane.dataset.tab] = bars.innerHTML;
  }});
  var playedGrid = document.getElementById('playedGrid');
  if (playedGrid) _distribStaticBars['tracks'] = playedGrid.innerHTML;
}})();

/* ── HTML escape helper ── */
function esc(s) {{
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

/* ── Genre / Label distribution tabs ── */
var _tracksGridBuilt = false;
function switchDistribTab(tabName, btn) {{
  var section = btn.closest('section') || document;
  section.querySelectorAll('.distrib-tab').forEach(function(t) {{
    t.classList.toggle('distrib-tab--active', t.dataset.tab === tabName);
  }});
  section.querySelectorAll('.distrib-pane').forEach(function(p) {{
    p.hidden = p.dataset.tab !== tabName;
  }});
  if (tabName === 'tracks' && !_tracksGridBuilt) {{
    var grid = document.getElementById('playedGrid');
    if (grid) build2RowGrid(grid);
    _tracksGridBuilt = true;
  }}
}}

/* ── Build 2-row horizontal scroll grid ── */
function build2RowGrid(grid) {{
  var allCards = Array.from(grid.querySelectorAll('.sig-staple-card'));
  // Stamp each card with its original position on first encounter so
  // subsequent rebuilds (after filter, etc.) sort back to the correct order.
  allCards.forEach(function(card, i) {{
    if (card.dataset.rank == null) card.dataset.rank = i;
  }});
  allCards.sort(function(a, b) {{
    return parseInt(a.dataset.rank, 10) - parseInt(b.dataset.rank, 10);
  }});
  allCards.forEach(function(card) {{
    var embed = card.querySelector('.staple-spotify-embed');
    if (embed) {{
      embed.remove();
      var btn = card.querySelector('.btn-staple-spotify');
      if (btn) btn.textContent = '\u25b6 Spotify';
      card.classList.remove('sig-staple-card--expanded');
      card.style.removeProperty('top');
      card.style.removeProperty('left');
      card.style.removeProperty('width');
    }}
    card.style.removeProperty('margin-top');
    card.style.removeProperty('margin-left');
  }});
  var visible = allCards.filter(function(c) {{ return c.style.display !== 'none'; }});
  var hidden  = allCards.filter(function(c) {{ return c.style.display === 'none'; }});
  var inner = document.createElement('div'); inner.className = 'hscroll-inner';
  for (var i = 0; i < visible.length; i += 2) {{
    var col = document.createElement('div'); col.className = 'hscroll-col';
    col.appendChild(visible[i]);
    if (visible[i + 1]) col.appendChild(visible[i + 1]);
    inner.appendChild(col);
  }}
  var outer = document.createElement('div'); outer.className = 'hscroll-outer';
  outer.appendChild(inner);
  var buf = document.createElement('div'); buf.style.display = 'none';
  hidden.forEach(function(c) {{ buf.appendChild(c); }});
  grid.innerHTML = '';
  grid.appendChild(outer);
  if (buf.children.length) grid.appendChild(buf);
}}

/* ── Genre breakdown: toggle track panel ── */
function toggleGenreTracks(row) {{
  var panel = row.nextElementSibling;
  if (!panel || !panel.classList.contains('genre-tracks-panel')) return;
  if (panel.hidden) {{
    panel.hidden = false;
    row.classList.add('genre-bar-row--open');
    var grid = panel.querySelector('.genre-tracks-grid');
    if (grid) build2RowGrid(grid);
  }} else {{
    panel.hidden = true;
    row.classList.remove('genre-bar-row--open');
  }}
}}

/* ── Helpers: grow hscroll-outer so expanded card is fully visible ── */
function _syncOuterHeight(card) {{
  var outer = card.closest('.hscroll-outer');
  if (!outer) return;
  outer.style.removeProperty('padding-bottom');
  requestAnimationFrame(function() {{
    var overflow = Math.ceil(card.getBoundingClientRect().bottom - outer.getBoundingClientRect().bottom);
    if (overflow > 0) outer.style.paddingBottom = overflow + 'px';
  }});
}}
function _resetOuterHeight(card) {{
  var outer = card.closest('.hscroll-outer');
  if (outer) outer.style.removeProperty('padding-bottom');
}}

/* ── DJ Staples: toggle "sets played in" panel ── */
function toggleStapleSets(btn) {{
  var card = btn.closest('.sig-staple-card');
  var panel = card ? card.querySelector('.staple-sets-panel') : null;
  if (!panel) return;
  var col = card ? card.parentElement : null;
  var inHscroll = col && col.classList.contains('hscroll-col');
  if (panel.hidden) {{
    if (inHscroll && !col.querySelector('.staple-expand-spacer')) {{
      var t = card.offsetTop, h = card.offsetHeight;
      var sp = document.createElement('div');
      sp.className = 'staple-expand-spacer'; sp.style.height = h + 'px'; sp.style.flexShrink = '0';
      col.insertBefore(sp, card);
      card.style.top = t + 'px'; card.style.left = '0';
      card.classList.add('sig-staple-card--expanded');
    }}
    panel.hidden = false;
    btn.innerHTML = '\u25be Sets';
    if (inHscroll) _syncOuterHeight(card);
  }} else {{
    panel.hidden = true;
    btn.innerHTML = btn.dataset.closedText || ('\u25b8 Sets (' + (card.dataset.count || '?') + ')');
    if (inHscroll && !card.querySelector('.staple-spotify-embed')) {{
      var sp = col.querySelector('.staple-expand-spacer');
      if (sp) sp.remove();
      card.classList.remove('sig-staple-card--expanded');
      card.style.removeProperty('top'); card.style.removeProperty('left');
      _resetOuterHeight(card);
    }}
  }}
}}

/* ── DJ Staples: Spotify embed toggle (expands card 2× width, overlays neighbours) ── */
function toggleStapleSpotify(btn, trackId) {{
  var card = btn.closest('.sig-staple-card');
  var embed = card ? card.querySelector('.staple-spotify-embed') : null;
  var col = card ? card.parentElement : null;
  var inHscroll = col && col.classList.contains('hscroll-col');
  if (embed) {{
    embed.remove();
    btn.textContent = '\u25b6 Spotify';
    card.style.removeProperty('width');
    if (inHscroll) {{
      var setsPanel = card.querySelector('.staple-sets-panel');
      if (!setsPanel || setsPanel.hidden) {{
        var sp = col.querySelector('.staple-expand-spacer');
        if (sp) sp.remove();
        card.classList.remove('sig-staple-card--expanded');
        card.style.removeProperty('top'); card.style.removeProperty('left');
        _resetOuterHeight(card);
      }} else {{
        _syncOuterHeight(card);
      }}
    }}
    return;
  }}
  if (inHscroll && !col.querySelector('.staple-expand-spacer')) {{
    var t = card.offsetTop, h = card.offsetHeight;
    var sp = document.createElement('div');
    sp.className = 'staple-expand-spacer'; sp.style.height = h + 'px'; sp.style.flexShrink = '0';
    col.insertBefore(sp, card);
    card.style.top = t + 'px'; card.style.left = '0';
    card.classList.add('sig-staple-card--expanded');
  }}
  card.style.width = '408px';
  var div = document.createElement('div');
  div.className = 'staple-spotify-embed';
  div.innerHTML = '<iframe style="border-radius:8px" src="https://open.spotify.com/embed/track/' + trackId + '?utm_source=generator&theme=0" width="100%" height="80" frameBorder="0" allow="autoplay; clipboard-write; encrypted-media" loading="lazy"></iframe>';
  card.appendChild(div);
  btn.textContent = '\u2715 Close';
  if (inHscroll) _syncOuterHeight(card);
}}


/* ── Matrix cell click ── */
function matrixClick(artistA, artistB) {{
  var same = _activePair && _activePair[0] === artistA && _activePair[1] === artistB;
  document.querySelectorAll('.matrix-cell--clickable').forEach(function(c) {{
    c.classList.remove('matrix-cell--active');
  }});
  if (same) {{
    _activePair = null;
    renderConnectionCards(null, null);
    return;
  }}
  _activePair = [artistA, artistB];
  document.querySelectorAll('.matrix-cell--clickable').forEach(function(c) {{
    if ((c.dataset.a === artistA && c.dataset.b === artistB) ||
        (c.dataset.a === artistB && c.dataset.b === artistA)) {{
      c.classList.add('matrix-cell--active');
    }}
  }});
  renderConnectionCards(artistA, artistB);
  setTimeout(function() {{
    document.getElementById('connectionsSection').scrollIntoView({{behavior:'smooth',block:'start'}});
  }}, 80);
}}

/* ── Render connection cards for selected pair ── */
function renderConnectionCards(artistA, artistB) {{
  var container = document.getElementById('connectionCards');
  if (!artistA) {{
    container.innerHTML = '<p class="empty">Select a cell above to see shared tracks, labels, and artists.</p>';
    return;
  }}
  var data = null;
  for (var i = 0; i < SIMILARITY.length; i++) {{
    var s = SIMILARITY[i];
    if ((s.artist_a === artistA && s.artist_b === artistB) ||
        (s.artist_a === artistB && s.artist_b === artistA)) {{
      data = s; break;
    }}
  }}
  if (!data || data.score === 0) {{
    container.innerHTML = '<p class="empty">No overlapping tracks, labels, or artists found between ' + esc(artistA) + ' and ' + esc(artistB) + '.</p>';
    return;
  }}
  var html = '<div class="master-pair-header">'
    + '<span class="master-pair-name">' + esc(artistA) + '</span>'
    + '<span class="master-pair-sep">&times;</span>'
    + '<span class="master-pair-name">' + esc(artistB) + '</span>'
    + '<button class="master-clear-btn" onclick="matrixClick(' + esc(JSON.stringify(artistA)) + ',' + esc(JSON.stringify(artistB)) + ')">&#x2715;</button>'
    + '</div>';

  // Build a trackMap keyed by track_key for bar-row accordion lookups
  var trackMap = {{}};
  if (data.shared_tracks) {{
    data.shared_tracks.forEach(function(t) {{ trackMap[t.track_key] = t; }});
  }}

  // Build tab specs in fixed order: Genres, Labels, Artists, Tracks
  var tabSpecs = [];
  var filteredGenres = (data.shared_genres || []).filter(function(g) {{ return (g.track_keys || []).length > 0; }});
  if (filteredGenres.length) {{
    tabSpecs.push({{
      id: 'genres', label: 'Genres', count: filteredGenres.length,
      content: buildConnBarSection(filteredGenres, trackMap, artistA, artistB, 'genre', 'Search genres\u2026'),
    }});
  }}
  var filteredLabels = (data.shared_labels || []).filter(function(l) {{ return (l.track_keys || []).length > 0; }});
  if (filteredLabels.length) {{
    tabSpecs.push({{
      id: 'labels', label: 'Labels', count: filteredLabels.length,
      content: buildConnBarSection(filteredLabels, trackMap, artistA, artistB, 'label', 'Search labels\u2026'),
    }});
  }}
  var filteredArtists = (data.shared_music_artists || []).filter(function(a) {{ return (a.track_keys || []).length > 0; }});
  if (filteredArtists.length) {{
    tabSpecs.push({{
      id: 'artists', label: 'Artists', count: filteredArtists.length,
      content: buildConnBarSection(filteredArtists, trackMap, artistA, artistB, 'music_artist', 'Search artists\u2026'),
    }});
  }}
  if (data.shared_tracks && data.shared_tracks.length) {{
    tabSpecs.push({{
      id: 'tracks', label: 'Tracks', count: data.shared_tracks.length,
      content: buildConnTrackPane(data.shared_tracks, artistA, artistB),
    }});
  }}

  if (tabSpecs.length) {{
    var defaultTab = tabSpecs.some(function(t) {{ return t.id === 'tracks'; }}) ? 'tracks' : tabSpecs[0].id;
    html += '<div class="distrib-tabs">';
    tabSpecs.forEach(function(tab) {{
      var cls = tab.id === defaultTab ? 'distrib-tab distrib-tab--active' : 'distrib-tab';
      html += '<button class="' + cls + '" data-tab="' + tab.id + '" onclick="switchConnTab(\\'' + tab.id + '\\', this)">'
        + esc(tab.label) + '</button>';
    }});
    html += '</div>';
    tabSpecs.forEach(function(tab) {{
      html += '<div class="conn-pane" data-tab="' + tab.id + '"' + (tab.id !== defaultTab ? ' hidden' : '') + '>'
        + tab.content + '</div>';
    }});
  }}

  container.innerHTML = html;
  container.querySelectorAll('.conn-bar-section').forEach(function(sec) {{
    _connBarUpdate(sec);
  }});
}}

function switchConnTab(tabName, btn) {{
  var container = document.getElementById('connectionCards');
  container.querySelectorAll('.distrib-tab').forEach(function(t) {{
    t.classList.toggle('distrib-tab--active', t.dataset.tab === tabName);
  }});
  container.querySelectorAll('.conn-pane').forEach(function(p) {{
    p.hidden = p.dataset.tab !== tabName;
  }});
}}

/* ── Connection panel: build one sig-staple-card for a shared track ── */
function buildConnTrackCard(t, artistA, artistB) {{
  var artHtml = t.spotify_album_art
    ? '<img class="sig-staple-art" src="' + esc(t.spotify_album_art) + '" alt="" loading="lazy">'
    : '<div class="sig-staple-art--empty"></div>';
  var countLine = esc(artistA) + ' &times;' + (t.appearances_a || 0)
    + ' &middot; ' + esc(artistB) + ' &times;' + (t.appearances_b || 0);
  var setsRows = '';
  function _connSetRow(artistLabel, s) {{
    var title = typeof s === 'string' ? s : s.title;
    var href  = typeof s === 'string' ? '' : (s.href || '');
    var setLink = href
      ? '<a class="staple-sets-link" href="' + esc(href) + '">' + esc(title) + '</a>'
      : '<span class="staple-sets-link">' + esc(title) + '</span>';
    return '<div class="staple-sets-row">'
      + setLink
      + '<span class="staple-sets-time">' + esc(artistLabel) + '</span>'
      + '</div>';
  }}
  if (t.sets_a && t.sets_a.length) {{
    t.sets_a.forEach(function(s) {{ setsRows += _connSetRow(artistA, s); }});
  }}
  if (t.sets_b && t.sets_b.length) {{
    t.sets_b.forEach(function(s) {{ setsRows += _connSetRow(artistB, s); }});
  }}
  var setsPanel = setsRows
    ? '<div class="staple-sets-panel" hidden>' + setsRows + '</div>'
    : '';
  var totalSets = (t.sets_a ? t.sets_a.length : 0) + (t.sets_b ? t.sets_b.length : 0);
  var setsBtn = setsRows
    ? '<button class="btn-staple-sets" data-closed-text="&#9658; Sets (' + totalSets + ')" onclick="toggleStapleSets(this)">&#9658; Sets (' + totalSets + ')</button>'
    : '';
  var spotifyBtn = '';
  if (t.spotify_url) {{
    var trackId = t.spotify_url.split('/').pop().split('?')[0];
    spotifyBtn = '<button class="btn-staple-spotify" onclick="toggleStapleSpotify(this,&apos;' + esc(trackId) + '&apos;)">&#9654; Spotify</button>';
  }}
  var totalPlays = (t.appearances_a || 0) + (t.appearances_b || 0);
  return '<div class="sig-staple-card" data-ndjs="2" data-total="' + totalPlays + '">'
    + artHtml
    + '<div class="sig-staple-header"><div class="sig-staple-count">' + countLine + '</div></div>'
    + '<div class="sig-staple-artist">' + esc(t.display_artist) + '</div>'
    + '<div class="sig-staple-title">' + esc(t.display_title) + '</div>'
    + '<div class="sig-staple-actions">' + setsBtn + spotifyBtn + '</div>'
    + setsPanel
    + '</div>';
}}

/* ── Connection panel: build 2-row horizontal scroll grid from track objects ── */
function buildConnTrackGrid(tracks, artistA, artistB) {{
  if (!tracks || !tracks.length) return '<p class="empty" style="padding:8px 0">No tracks.</p>';
  var cols = '';
  for (var i = 0; i < tracks.length; i += 2) {{
    cols += '<div class="hscroll-col">'
      + buildConnTrackCard(tracks[i], artistA, artistB)
      + (tracks[i + 1] ? buildConnTrackCard(tracks[i + 1], artistA, artistB) : '')
      + '</div>';
  }}
  return '<div class="conn-cards-grid"><div class="hscroll-outer"><div class="hscroll-inner">' + cols + '</div></div></div>';
}}

/* ── Connection panel: tracks tab with filter pills ── */
function buildConnTrackPane(tracks, artistA, artistB) {{
  if (!tracks || !tracks.length) return '<p class="empty" style="padding:8px 0">No tracks.</p>';
  var maxTotal = 0;
  tracks.forEach(function(t) {{
    var tot = (t.appearances_a || 0) + (t.appearances_b || 0);
    if (tot > maxTotal) maxTotal = tot;
  }});
  var thresholds = [2, 3, 5, 10, 20, 50].filter(function(t) {{ return t <= maxTotal; }});
  var pills = '<button class="staple-filter-btn staple-filter-btn--active" onclick="filterConnTracks(0,this)">All</button>';
  thresholds.forEach(function(t) {{
    pills += '<button class="staple-filter-btn" onclick="filterConnTracks(' + t + ',this)">' + t + '+ plays</button>';
  }});
  return '<div class="staple-filter-bar conn-tracks-filter-bar" style="margin-bottom:14px">' + pills + '</div>'
    + buildConnTrackGrid(tracks, artistA, artistB);
}}

function filterConnTracks(minTotal, btn) {{
  var bar = btn.closest('.conn-tracks-filter-bar');
  if (bar) {{
    bar.querySelectorAll('.staple-filter-btn').forEach(function(b) {{
      b.classList.remove('staple-filter-btn--active');
    }});
  }}
  btn.classList.add('staple-filter-btn--active');
  var pane = btn.closest('.conn-pane');
  if (!pane) return;
  var grid = pane.querySelector('.conn-cards-grid');
  if (!grid) return;
  grid.querySelectorAll('.sig-staple-card').forEach(function(card) {{
    var t = parseInt(card.dataset.total || '2', 10);
    card.style.display = (minTotal === 0 || t >= minTotal) ? '' : 'none';
  }});
  build2RowGrid(grid);
}}

/* ── Connection panel: horizontal bar chart with search + pagination ── */
var CONN_BAR_PER_PAGE = 15;

function buildConnBarSection(items, trackMap, artistA, artistB, labelField, placeholder) {{
  if (!items || !items.length) return '';
  var sorted = items.slice().sort(function(a, b) {{
    return (b.track_keys || []).length - (a.track_keys || []).length;
  }});
  var maxCount = (sorted[0].track_keys || []).length || 1;
  var rows = '';
  sorted.forEach(function(item) {{
    var name = item[labelField] || '';
    var count = (item.track_keys || []).length;
    var pct = maxCount > 0 ? (count / maxCount * 100).toFixed(1) : '0';
    var keys = item.track_keys || [];
    var tracks = keys.map(function(k) {{ return trackMap[k]; }}).filter(Boolean);
    var cardsHtml = '';
    tracks.forEach(function(t) {{ cardsHtml += buildConnTrackCard(t, artistA, artistB); }});
    var panelHtml = cardsHtml
      ? '<div class="genre-tracks-panel" hidden><div class="genre-tracks-grid">' + cardsHtml + '</div></div>'
      : '';
    var rowCls = tracks.length ? 'genre-bar-row genre-bar-row--clickable' : 'genre-bar-row';
    var clickAttr = tracks.length ? ' onclick="connBarToggle(this)"' : '';
    var arrowHtml = tracks.length ? '<span class="genre-bar-arrow">&#8250;</span>' : '<span></span>';
    rows += '<div class="genre-bar-item" data-name="' + esc(name.toLowerCase()) + '">'
      + '<div class="' + rowCls + '"' + clickAttr + '>'
      + arrowHtml
      + '<span class="genre-bar-label">' + esc(name) + '</span>'
      + '<div class="genre-bar-track"><div class="genre-bar-fill" style="width:' + pct + '%"></div></div>'
      + '<span class="genre-bar-count">' + count + '</span>'
      + '</div>'
      + panelHtml
      + '</div>';
  }});
  return '<div class="conn-bar-section" data-page="0">'
    + '<div class="distrib-search-wrap">'
    + '<input class="distrib-search-input" type="text" placeholder="' + esc(placeholder) + '" oninput="connBarSearch(this)">'
    + '</div>'
    + '<div class="sig-genres"><div class="genre-bars">' + rows + '</div></div>'
    + '<div class="distrib-pagination">'
    + '<button class="distrib-pg-btn" onclick="connBarPage(this,-1)">&#8249; Prev</button>'
    + '<span class="distrib-pg-info"></span>'
    + '<button class="distrib-pg-btn" onclick="connBarPage(this,1)">Next &#8250;</button>'
    + '</div>'
    + '</div>';
}}

function connBarToggle(row) {{
  var panel = row.nextElementSibling;
  if (!panel || !panel.classList.contains('genre-tracks-panel')) return;
  if (panel.hidden) {{
    panel.hidden = false;
    row.classList.add('genre-bar-row--open');
    var grid = panel.querySelector('.genre-tracks-grid');
    if (grid) build2RowGrid(grid);
  }} else {{
    panel.hidden = true;
    row.classList.remove('genre-bar-row--open');
  }}
}}

function _connBarUpdate(section) {{
  var input = section.querySelector('.distrib-search-input');
  var query = input ? input.value.toLowerCase().trim() : '';
  var items = Array.from(section.querySelectorAll('.genre-bar-item'));
  var visible = query
    ? items.filter(function(item) {{ return (item.dataset.name || '').indexOf(query) !== -1; }})
    : items;
  var page = parseInt(section.dataset.page || '0', 10);
  var total = Math.max(1, Math.ceil(visible.length / CONN_BAR_PER_PAGE));
  if (page >= total) page = total - 1;
  if (page < 0) page = 0;
  section.dataset.page = page;
  var start = page * CONN_BAR_PER_PAGE;
  var end = start + CONN_BAR_PER_PAGE;
  items.forEach(function(item) {{ item.hidden = true; }});
  visible.slice(start, end).forEach(function(item) {{ item.hidden = false; }});
  var info = section.querySelector('.distrib-pg-info');
  if (info) {{
    info.textContent = visible.length
      ? (page + 1) + ' / ' + total + (query ? ' (' + visible.length + ' match' + (visible.length !== 1 ? 'es' : '') + ')' : '')
      : 'No results';
  }}
  var btns = section.querySelectorAll('.distrib-pg-btn');
  if (btns[0]) btns[0].disabled = page <= 0;
  if (btns[1]) btns[1].disabled = page >= total - 1;
}}

function connBarSearch(input) {{
  var section = input.closest('.conn-bar-section');
  if (!section) return;
  section.dataset.page = '0';
  _connBarUpdate(section);
}}

function connBarPage(btn, delta) {{
  var section = btn.closest('.conn-bar-section');
  if (!section) return;
  section.dataset.page = Math.max(0, parseInt(section.dataset.page || '0', 10) + delta);
  _connBarUpdate(section);
}}

/* ── Artist card selection for Track Distribution filtering ── */
function artistCardClick(event, card) {{
  if (event.target.closest('a')) return;
  var name = card.dataset.name;
  if (_distribSelectedArtists.has(name)) {{
    _distribSelectedArtists.delete(name);
    card.classList.remove('master-artist-card--selected');
  }} else {{
    _distribSelectedArtists.add(name);
    card.classList.add('master-artist-card--selected');
  }}
  _syncDistribArtistBtns();
  _updateDistribFilterBar();
  rebuildDistribution();
}}

function toggleDistribArtistBtn(btn) {{
  var name = btn.dataset.artist;
  if (_distribSelectedArtists.has(name)) {{
    _distribSelectedArtists.delete(name);
    btn.classList.remove('active');
  }} else {{
    _distribSelectedArtists.add(name);
    btn.classList.add('active');
  }}
  // Sync the artist cards above
  document.querySelectorAll('.master-artist-card').forEach(function(card) {{
    card.classList.toggle('master-artist-card--selected', _distribSelectedArtists.has(card.dataset.name));
  }});
  _updateDistribFilterBar();
  rebuildDistribution();
}}

function _syncDistribArtistBtns() {{
  document.querySelectorAll('#distribArtistBtns .distrib-artist-btn').forEach(function(btn) {{
    btn.classList.toggle('active', _distribSelectedArtists.has(btn.dataset.artist));
  }});
}}

function _updateDistribFilterBar() {{
  var selected = Array.from(_distribSelectedArtists);
  var bar = document.getElementById('distribFilterBar');
  var hint = document.getElementById('distribHint');
  if (!selected.length) {{
    if (bar) bar.hidden = true;
    if (hint) hint.textContent = '';
    return;
  }}
  if (bar) bar.hidden = false;
  if (hint) {{
    hint.textContent = selected.length + ' artist' + (selected.length !== 1 ? 's' : '') + ' selected \u00b7 ' + _distribMode;
  }}
}}

function removeDistribArtist(name) {{
  _distribSelectedArtists.delete(name);
  document.querySelectorAll('.master-artist-card').forEach(function(card) {{
    if (card.dataset.name === name) card.classList.remove('master-artist-card--selected');
  }});
  _syncDistribArtistBtns();
  _updateDistribFilterBar();
  rebuildDistribution();
}}

function setDistribMode(mode) {{
  _distribMode = mode;
  var unionBtn = document.getElementById('distribUnionBtn');
  var intBtn = document.getElementById('distribIntersectBtn');
  if (unionBtn) unionBtn.classList.toggle('distrib-mode-btn--active', mode === 'union');
  if (intBtn) intBtn.classList.toggle('distrib-mode-btn--active', mode === 'intersection');
  _updateDistribFilterBar();
  rebuildDistribution();
}}

function clearDistribSelection() {{
  _distribSelectedArtists.clear();
  _distribMode = 'union';
  document.querySelectorAll('.master-artist-card--selected').forEach(function(c) {{
    c.classList.remove('master-artist-card--selected');
  }});
  document.querySelectorAll('#distribArtistBtns .distrib-artist-btn').forEach(function(btn) {{
    btn.classList.remove('active');
  }});
  var unionBtn = document.getElementById('distribUnionBtn');
  var intBtn = document.getElementById('distribIntersectBtn');
  if (unionBtn) unionBtn.classList.add('distrib-mode-btn--active');
  if (intBtn) intBtn.classList.remove('distrib-mode-btn--active');
  _updateDistribFilterBar();
  document.querySelectorAll('.distrib-pane[data-tab]').forEach(function(pane) {{
    var bars = pane.querySelector('.genre-bars');
    if (bars && _distribStaticBars[pane.dataset.tab] !== undefined) {{
      bars.innerHTML = _distribStaticBars[pane.dataset.tab];
    }}
    pane.dataset.page = '0';
    var input = pane.querySelector('.distrib-search-input');
    if (input) input.value = '';
    _distribUpdate(pane);
  }});
  var tracksGrid = document.getElementById('playedGrid');
  if (tracksGrid && _distribStaticBars['tracks'] !== undefined) {{
    tracksGrid.innerHTML = _distribStaticBars['tracks'];
    if (_tracksGridBuilt) build2RowGrid(tracksGrid);
  }}
  var firstPill = document.querySelector('#playedTracksFilterBar .staple-filter-btn');
  if (firstPill) filterPlayedTracks(0, firstPill);
}}

/* ── Dynamic track card builder (mirrors Python _render_master_sig_card) ── */
function _buildMasterSigCardJS(entry) {{
  var total = entry.total_appearances || 1;
  var djApps = entry.dj_appearances || [];
  var numDjs = djApps.length;
  var artHtml = entry.spotify_album_art
    ? '<img class="sig-staple-art" src="' + esc(entry.spotify_album_art) + '" alt="" loading="lazy">'
    : '<div class="sig-staple-art--empty"></div>';
  var spotifyBtn = '';
  if (entry.spotify_url) {{
    var spotId = entry.spotify_url.split('/').pop().split('?')[0];
    spotifyBtn = '<button class="btn-staple-spotify" onclick="toggleStapleSpotify(this,&apos;' + esc(spotId) + '&apos;)">\u25b6 Spotify</button>';
  }}
  var setsRows = djApps.map(function(app) {{
    var nSets = (app.sets || []).length;
    var trackQ = encodeURIComponent((entry.display_artist || '') + ' ' + (entry.display_title || ''));
    var djHtml = app.dir_name
      ? '<a class="staple-sets-link" href="' + esc(app.dir_name) + '/artist_summary.html?q=' + trackQ + '#sets-section">' + esc(app.dj) + '</a>'
      : '<span class="staple-sets-link">' + esc(app.dj) + '</span>';
    return '<div class="staple-sets-row">'
      + djHtml
      + '<span class="staple-sets-time">' + nSets + ' set' + (nSets !== 1 ? 's' : '') + '</span>'
      + '</div>';
  }}).join('');
  var setsPanel = setsRows ? '<div class="staple-sets-panel" hidden>' + setsRows + '</div>' : '';
  var closedText = '\u25b8 DJs (' + numDjs + ')';
  var setsBtn = setsRows
    ? '<button class="btn-staple-sets" data-closed-text="' + esc(closedText) + '" onclick="toggleStapleSets(this)">' + esc(closedText) + '</button>'
    : '';
  var countLabel = numDjs + ' DJ' + (numDjs !== 1 ? 's' : '') + ' &middot; ' + total + ' play' + (total !== 1 ? 's' : '');
  return '<div class="sig-staple-card" data-ndjs="' + numDjs + '" data-total="' + total + '">'
    + artHtml
    + '<div class="sig-staple-header"><div class="sig-staple-count">' + countLabel + '</div></div>'
    + '<div class="sig-staple-artist">' + esc(entry.display_artist) + '</div>'
    + '<div class="sig-staple-title">' + esc(entry.display_title) + '</div>'
    + '<div class="sig-staple-actions">' + setsBtn + spotifyBtn + '</div>'
    + setsPanel
    + '</div>';
}}

/* ── Dynamic bar rows builder (mirrors Python _bar_rows) ── */
function _buildDistribBarsHTML(items) {{
  if (!items.length) return '';
  var maxCount = items.reduce(function(m, i) {{ return Math.max(m, i.tracks.length); }}, 0);
  return items.map(function(item) {{
    var count = item.tracks.length;
    var pct = maxCount ? (count / maxCount * 100) : 0;
    var cardsHtml = item.tracks.slice(0, 30).map(_buildMasterSigCardJS).join('');
    var innerPanel = cardsHtml ? '<div class="genre-tracks-grid">' + cardsHtml + '</div>' : '';
    if (item.url && innerPanel) {{
      innerPanel = '<div class="label-panel-header"><a class="btn-discogs-label" href="' + esc(item.url) + '" target="_blank">View Label on Discogs \u2192</a></div>' + innerPanel;
    }}
    var panelHtml = innerPanel ? '<div class="genre-tracks-panel" hidden>' + innerPanel + '</div>' : '';
    var clickable = !!panelHtml;
    var rowCls = 'genre-bar-row' + (clickable ? ' genre-bar-row--clickable' : '');
    var clickAttr = clickable ? ' onclick="toggleGenreTracks(this)"' : '';
    var arrow = clickable ? '<span class="genre-bar-arrow">\u203a</span>' : '<span></span>';
    return '<div class="genre-bar-item">'
      + '<div class="' + rowCls + '"' + clickAttr + '>'
      + arrow
      + '<span class="genre-bar-label">' + esc(item.name) + '</span>'
      + '<div class="genre-bar-track"><div class="genre-bar-fill" style="width:' + pct.toFixed(1) + '%;"></div></div>'
      + '<span class="genre-bar-count">' + count + '</span>'
      + '</div>'
      + panelHtml
      + '</div>';
  }}).join('');
}}

/* ── Rebuild Track Distribution for selected artists ── */
function rebuildDistribution() {{
  var selected = Array.from(_distribSelectedArtists);
  if (!selected.length) return; // clearDistribSelection handles the restore path

  var selectedSet = new Set(selected);
  var filteredEntries = [];

  Object.keys(TRACK_REGISTRY).forEach(function(key) {{
    var entry = TRACK_REGISTRY[key];
    var djApps = entry.dj_appearances || [];
    var matchingApps;
    if (_distribMode === 'union') {{
      matchingApps = djApps.filter(function(app) {{ return selectedSet.has(app.dj); }});
      if (!matchingApps.length) return;
    }} else {{
      var hasAll = selected.every(function(name) {{
        return djApps.some(function(app) {{ return app.dj === name; }});
      }});
      if (!hasAll) return;
      matchingApps = djApps.filter(function(app) {{ return selectedSet.has(app.dj); }});
    }}
    var totalApp = matchingApps.reduce(function(s, a) {{ return s + (a.appearances || 1); }}, 0);
    filteredEntries.push(Object.assign({{}}, entry, {{
      dj_appearances: matchingApps,
      total_appearances: totalApp,
      num_djs: matchingApps.length,
      is_cross_artist: matchingApps.length >= 2,
    }}));
  }});

  var genreMap = {{}}, labelMap = {{}}, taMap = {{}}, labelUrlMap = {{}};
  filteredEntries.forEach(function(entry) {{
    (entry.genres || []).forEach(function(g) {{
      var norm = g.charAt(0).toUpperCase() + g.slice(1).toLowerCase();
      if (norm === 'House') return;
      if (!genreMap[norm]) genreMap[norm] = [];
      genreMap[norm].push(entry);
    }});
    if (entry.discogs_label) {{
      if (!labelMap[entry.discogs_label]) labelMap[entry.discogs_label] = [];
      labelMap[entry.discogs_label].push(entry);
      if (!labelUrlMap[entry.discogs_label] && entry.discogs_label_url) {{
        labelUrlMap[entry.discogs_label] = entry.discogs_label_url;
      }}
    }}
    if (entry.display_artist && entry.display_artist.toLowerCase() !== 'unknown') {{
      if (!taMap[entry.display_artist]) taMap[entry.display_artist] = [];
      taMap[entry.display_artist].push(entry);
    }}
  }});

  function toItems(map, urlMap) {{
    return Object.keys(map).map(function(name) {{
      return {{ name: name, tracks: map[name], url: urlMap ? (urlMap[name] || null) : null }};
    }}).sort(function(a, b) {{ return b.tracks.length - a.tracks.length; }});
  }}

  var genreItems = toItems(genreMap, null);
  var labelItems = toItems(labelMap, labelUrlMap);
  var taItems    = toItems(taMap, null);

  var emptyMsg = _distribMode === 'intersection' && !filteredEntries.length
    ? '<p class="empty">No tracks in common between ' + selected.map(esc).join(', ') + '.</p>'
    : '<p class="empty">No data for selected artists.</p>';

  function updatePane(tab, items) {{
    var pane = document.querySelector('.distrib-pane[data-tab="' + tab + '"]');
    if (!pane) return;
    var barsDiv = pane.querySelector('.genre-bars');
    if (!barsDiv) return;
    var html = filteredEntries.length ? _buildDistribBarsHTML(items) : '';
    barsDiv.innerHTML = html || emptyMsg;
    pane.dataset.page = '0';
    var inp = pane.querySelector('.distrib-search-input');
    if (inp) inp.value = '';
    _distribUpdate(pane);
  }}

  updatePane('genres', genreItems);
  updatePane('labels', labelItems);
  updatePane('track-artists', taItems);

  // ── Tracks pane ──
  var tracksGrid = document.getElementById('playedGrid');
  if (tracksGrid) {{
    var sortedTracks = filteredEntries.slice().sort(function(a, b) {{
      return (b.total_appearances || 0) - (a.total_appearances || 0);
    }});
    var top60 = sortedTracks.slice(0, 60);
    tracksGrid.innerHTML = top60.length
      ? top60.map(_buildMasterSigCardJS).join('')
      : emptyMsg;
    if (_tracksGridBuilt) build2RowGrid(tracksGrid);
    document.querySelectorAll('#playedTracksFilterBar .staple-filter-btn').forEach(function(b) {{
      b.classList.remove('staple-filter-btn--active');
    }});
    var firstPill = document.querySelector('#playedTracksFilterBar .staple-filter-btn');
    if (firstPill) firstPill.classList.add('staple-filter-btn--active');
  }}
}}

/* ── Artist card search ── */
function filterArtistCards(query) {{
  var q = query.toLowerCase();
  document.querySelectorAll('.master-artist-card').forEach(function(card) {{
    card.style.display = (!q || (card.dataset.name||'').toLowerCase().indexOf(q) !== -1) ? '' : 'none';
  }});
}}

/* ── Tracks tab: filter by total appearances ── */
function filterPlayedTracks(minTotal, btn) {{
  document.querySelectorAll('#playedTracksFilterBar .staple-filter-btn').forEach(function(b) {{
    b.classList.remove('staple-filter-btn--active');
  }});
  if (btn) btn.classList.add('staple-filter-btn--active');
  var grid = document.getElementById('playedGrid');
  if (!grid) return;
  grid.querySelectorAll('.sig-staple-card').forEach(function(card) {{
    var t = parseInt(card.dataset.total || '1', 10);
    card.style.display = (minTotal <= 1 || t >= minTotal) ? '' : 'none';
  }});
  build2RowGrid(grid);
}}

/* ── Set card tracklist toggle ── */
function toggleCardTracklist(idx) {{
  var card = document.querySelector('.set-card[data-card-idx="' + idx + '"]');
  var tracklist = card ? card.querySelector('.set-card-tracklist') : null;
  var btn = card ? card.querySelector('.sc-toggle-btn') : null;
  if (!tracklist) return;
  if (tracklist.hidden) {{
    tracklist.hidden = false;
    card.classList.add('set-card--expanded');
    if (btn) btn.innerHTML = '\u25be Hide Tracklist';
  }} else {{
    tracklist.hidden = true;
    card.classList.remove('set-card--expanded');
    if (btn) btn.innerHTML = '\u25b8 Show Tracklist';
  }}
}}

/* ── All Sets: search + artist filter ── */
var _allSetsArtist = '';
document.getElementById('allSetsSearch').addEventListener('input', function() {{
  _applySetsFilter(this.value, _allSetsArtist);
}});
function filterAllSets(artist, btn) {{
  _allSetsArtist = artist;
  document.querySelectorAll('#artistFilterBtns .sort-btn').forEach(function(b) {{ b.classList.remove('active'); }});
  btn.classList.add('active');
  _applySetsFilter(document.getElementById('allSetsSearch').value, artist);
}}
function _applySetsFilter(query, artist) {{
  var q = query.toLowerCase();
  document.querySelectorAll('.set-card').forEach(function(card) {{
    var matchQ = !q || (card.dataset.searchText||'').toLowerCase().indexOf(q) !== -1;
    var matchA = !artist || card.dataset.artistName === artist;
    card.style.display = (matchQ && matchA) ? '' : 'none';
  }});
  _rebuildSetsGrid();
}}

/* ── All Sets masonry layout ── */
var _setsTimer;
function _rebuildSetsGrid() {{
  var grid = document.getElementById('allSetsGrid');
  if (!grid) return;
  var GAP = 12, MIN_W = 260;
  var nCols = Math.max(1, Math.floor((grid.offsetWidth + GAP) / (MIN_W + GAP)));
  var cols = [];
  for (var i = 0; i < nCols; i++) {{
    var col = document.createElement('div');
    col.className = 'sets-col';
    cols.push(col);
  }}
  var allCards = Array.from(grid.querySelectorAll('.set-card'));
  var visibleCards = allCards.filter(function(c) {{ return c.style.display !== 'none'; }});
  var hiddenCards = allCards.filter(function(c) {{ return c.style.display === 'none'; }});
  visibleCards.forEach(function(card, i) {{ cols[i % nCols].appendChild(card); }});
  grid.innerHTML = '';
  cols.forEach(function(col) {{ grid.appendChild(col); }});
  hiddenCards.forEach(function(card) {{ grid.appendChild(card); }});
}}
window.addEventListener('resize', function() {{
  clearTimeout(_setsTimer);
  _setsTimer = setTimeout(_rebuildSetsGrid, 150);
}});
_rebuildSetsGrid();

/* ── Genre/Label distribution: search + pagination ── */
var DISTRIB_PER_PAGE = 20;

function _distribUpdate(pane) {{
  var input = pane.querySelector('.distrib-search-input');
  var query = input ? input.value.toLowerCase().trim() : '';
  var items = Array.from(pane.querySelectorAll('.genre-bar-item'));
  var visible = query
    ? items.filter(function(item) {{
        var label = item.querySelector('.genre-bar-label');
        return label && label.textContent.toLowerCase().includes(query);
      }})
    : items;
  var page = parseInt(pane.dataset.page || '0', 10);
  var total = Math.max(1, Math.ceil(visible.length / DISTRIB_PER_PAGE));
  if (page >= total) page = total - 1;
  if (page < 0) page = 0;
  pane.dataset.page = page;
  var start = page * DISTRIB_PER_PAGE;
  var end = start + DISTRIB_PER_PAGE;
  items.forEach(function(item) {{ item.hidden = true; }});
  visible.slice(start, end).forEach(function(item) {{ item.hidden = false; }});
  var info = pane.querySelector('.distrib-pg-info');
  if (info) {{
    info.textContent = visible.length
      ? (page + 1) + ' / ' + total + (query ? '  (' + visible.length + ' match' + (visible.length !== 1 ? 'es' : '') + ')' : '')
      : 'No results';
  }}
  var btns = pane.querySelectorAll('.distrib-pg-btn');
  if (btns[0]) btns[0].disabled = page <= 0;
  if (btns[1]) btns[1].disabled = page >= total - 1;
}}

function distribSearch(input) {{
  var pane = input.closest('.distrib-pane');
  if (!pane) return;
  pane.dataset.page = '0';
  _distribUpdate(pane);
}}

function distribPage(btn, delta) {{
  var pane = btn.closest('.distrib-pane');
  if (!pane) return;
  pane.dataset.page = Math.max(0, parseInt(pane.dataset.page || '0', 10) + delta);
  _distribUpdate(pane);
}}

document.querySelectorAll('.distrib-pane[data-page]').forEach(function(pane) {{
  _distribUpdate(pane);
}});
</script>
</body>
</html>"""

        output_path = self.output_dir / "index.html"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Saved master summary HTML: {output_path}")
        return output_path


# ─────────────────────────────────────────────────────────────────────────────
# Master summary CSS & helpers  (used by save_master_summary_html above)
# ─────────────────────────────────────────────────────────────────────────────

_MASTER_CSS = """
/* ── Master: artist cards grid ── */
.master-artist-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
  margin-top: 8px;
}
.master-artist-card {
  background: #111;
  border: 1px solid #1e1e1e;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: border-color 0.15s, transform 0.15s;
}
.master-artist-card { cursor: pointer; position: relative; }
.master-artist-card:hover { border-color: #2a2a2a; transform: translateY(-2px); }
.master-artist-card--selected { border-color: #00e676 !important; background: rgba(0,230,118,0.07); transform: none; }
.master-select-badge { display: none; position: absolute; top: 8px; right: 10px; color: #00e676; font-size: 13px; font-weight: 700; pointer-events: none; }
.master-artist-card--selected .master-select-badge { display: block; }
.master-artist-name {
  font-size: 16px;
  font-weight: 700;
  color: #00e676;
  line-height: 1.2;
  text-decoration: none;
}
.master-artist-name:hover { text-decoration: underline; }
.master-artist-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 12px;
  color: #888;
}
.master-artist-stats strong { color: #ccc; }
.master-artist-genres { display: flex; flex-wrap: wrap; gap: 5px; }
.master-genre-tag {
  font-size: 10px;
  padding: 2px 7px;
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  color: #777;
}
.master-artist-overlaps { display: flex; flex-direction: column; gap: 4px; }
.master-overlap-badge {
  display: block;
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 5px;
  border: 1px solid;
  cursor: pointer;
  text-decoration: none;
  transition: opacity 0.15s;
}
.master-overlap-badge:hover { opacity: 0.8; }
.master-overlap-badge--high { color: #00e676; border-color: #00e676; background: rgba(0,230,118,0.06); }
.master-overlap-badge--med  { color: #ffd740; border-color: #ffd740; background: rgba(255,215,64,0.06); }
.master-overlap-badge--low  { color: #888;    border-color: #333;    background: transparent; }

/* ── Master: most played grid ── */
.master-played-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
}
.master-played-card {
  background: #111;
  border: 1px solid #1e1e1e;
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: border-color 0.15s;
}
.master-played-card:hover { border-color: #2a2a2a; }
.master-played-art {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  display: block;
  background: #0a0a0a;
}
.master-played-art--empty {
  width: 100%;
  aspect-ratio: 1;
  background: linear-gradient(135deg, #111 0%, #1a1a1a 100%);
}
.master-played-body { padding: 10px 12px 12px; display: flex; flex-direction: column; gap: 5px; }
.master-played-title {
  font-size: 12px;
  font-weight: 600;
  color: #fff;
  line-height: 1.3;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.master-played-artist-name { font-size: 11px; color: #777; }
.master-cross-badge {
  display: inline-block;
  font-size: 10px;
  padding: 2px 6px;
  background: rgba(0,230,118,0.12);
  border: 1px solid #00e676;
  color: #00e676;
  border-radius: 10px;
  margin-top: 2px;
  align-self: flex-start;
}
.master-dj-chips { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.master-dj-chip {
  font-size: 10px;
  padding: 2px 6px;
  background: #1a1a1a;
  border-radius: 8px;
  color: #888;
}

/* ── Master: similarity matrix ── */
.master-hint { font-size: 12px; color: #555; margin-bottom: 14px; }
.master-matrix-scroll { overflow-x: auto; margin-bottom: 24px; }
.master-matrix {
  display: inline-grid;
  border-collapse: collapse;
  min-width: 100%;
}
.matrix-header-cell {
  padding: 6px 10px;
  font-size: 11px;
  color: #666;
  white-space: nowrap;
  text-align: center;
  font-weight: 600;
}
.matrix-row-label {
  padding: 6px 10px;
  font-size: 11px;
  color: #666;
  white-space: nowrap;
  font-weight: 600;
  text-align: right;
}
.matrix-cell {
  padding: 8px 12px;
  text-align: center;
  font-size: 11px;
  border: 1px solid #1a1a1a;
  min-width: 48px;
}
.matrix-cell--diag { color: #2a2a2a; background: #0d0d0d; }
.matrix-cell--clickable {
  cursor: pointer;
  border-radius: 4px;
  transition: filter 0.15s, border-color 0.15s;
}
.matrix-cell--clickable:hover { filter: brightness(1.4); border-color: #555 !important; }
.matrix-cell--active { border-color: #fff !important; filter: brightness(1.6) !important; }

/* ── Master: connection area ── */
.master-connection-area {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.master-pair-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
.master-pair-name { font-size: 15px; font-weight: 700; color: #00e676; }
.master-pair-sep { font-size: 18px; color: #444; }
.master-clear-btn {
  margin-left: auto;
  background: none;
  border: 1px solid #333;
  color: #666;
  border-radius: 5px;
  padding: 3px 8px;
  font-size: 12px;
  cursor: pointer;
}
.master-clear-btn:hover { border-color: #555; color: #aaa; }
.conn-pane { padding-top: 4px; }
.conn-tab-count { color: #888; font-weight: 400; }
.conn-track-item { display: flex; align-items: center; gap: 10px; padding: 4px 0; }
.conn-track-art {
  width: 40px; height: 40px;
  border-radius: 4px;
  object-fit: cover;
  flex-shrink: 0;
  background: #1a1a1a;
}
.conn-track-art--empty { background: #1a1a1a; }
.conn-track-info { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.conn-track-name { font-size: 12px; color: #ddd; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.conn-track-counts { font-size: 11px; color: #666; }
.conn-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
  padding: 4px 0;
  border-bottom: 1px solid #1a1a1a;
}
.conn-row:last-child { border-bottom: none; }
.conn-row-name { font-size: 12px; color: #ccc; flex-shrink: 0; }
.conn-row-meta { font-size: 11px; color: #666; }

/* ── Connection area: masonry card grid ── */
.conn-cards-grid {
  margin-top: 8px;
}

/* ── Connection bar section spacing ── */
.conn-bar-section { margin-top: 4px; }
.conn-bar-section .distrib-search-wrap { margin-bottom: 6px; }
.conn-bar-section .distrib-pagination { margin-top: 8px; }

/* ── Master: all-sets artist label ── */
.master-set-artist-label {
  display: inline-block;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #00e676;
  margin-bottom: 2px;
  text-decoration: none;
}
.master-set-artist-label:hover { text-decoration: underline; }

/* Genre/label search + pagination */
.distrib-search-wrap {
  margin: 10px 0 6px;
}
.distrib-search-input {
  width: 100%;
  box-sizing: border-box;
  background: #111;
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  color: #ddd;
  font-size: 13px;
  padding: 7px 10px;
  outline: none;
  transition: border-color 0.15s;
}
.distrib-search-input:focus { border-color: #444; }
.distrib-search-input::placeholder { color: #555; }
.distrib-pagination {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid #1a1a1a;
}
.distrib-pg-btn {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 4px;
  color: #aaa;
  cursor: pointer;
  font-size: 13px;
  padding: 4px 10px;
  transition: background 0.15s, color 0.15s;
}
.distrib-pg-btn:hover:not(:disabled) { background: #252525; color: #fff; }
.distrib-pg-btn:disabled { opacity: 0.3; cursor: default; }
.distrib-pg-info { font-size: 12px; color: #555; flex: 1; text-align: center; }
.genre-bar-item[hidden] { display: none; }

/* ── Track Distribution filter bar ── */
.distrib-section-hint { font-size: 12px; color: #666; }
#distribFilterBar {
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
  margin-bottom: 14px; padding: 10px 12px;
  background: #0d0d0d; border: 1px solid #1e1e1e; border-radius: 8px;
}
#distribFilterBar[hidden] { display: none; }
.distrib-chips { display: flex; flex-wrap: wrap; gap: 6px; flex: 1; min-width: 0; }
.distrib-chip {
  display: inline-flex; align-items: center; gap: 5px;
  background: rgba(0,230,118,0.12); border: 1px solid rgba(0,230,118,0.4);
  border-radius: 12px; padding: 3px 8px 3px 12px; font-size: 12px; color: #ccc;
}
.distrib-chip-remove {
  background: none; border: none; color: #777; cursor: pointer;
  padding: 0 2px; font-size: 14px; line-height: 1;
}
.distrib-chip-remove:hover { color: #fff; }
.distrib-mode-group {
  display: flex; border: 1px solid #2a2a2a; border-radius: 6px;
  overflow: hidden; flex-shrink: 0;
}
.distrib-mode-btn {
  background: #111; border: none; color: #777;
  padding: 5px 14px; font-size: 12px; cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.distrib-mode-btn--active { background: rgba(0,230,118,0.15); color: #00e676; }
.distrib-clear-btn {
  background: none; border: 1px solid #2a2a2a; color: #777;
  border-radius: 6px; padding: 5px 12px; font-size: 12px;
  cursor: pointer; flex-shrink: 0;
}
.distrib-clear-btn:hover { border-color: #444; color: #ccc; }
"""


def _render_master_artist_cards(artists: list) -> str:
    import json as _j
    if not artists:
        return '<p class="empty">No artists found.</p>'
    cards = []
    for a in artists:
        name_esc = _esc(a["name"])
        html_rel = _esc(a["html_rel"])
        genre_tags = "".join(
            f'<span class="master-genre-tag">{_esc(g)}</span>' for g in a["top_genres"][:3]
        )
        overlap_html = ""
        for conn in a["top_connections"]:
            if conn["score"] <= 0:
                continue
            shared = conn["shared_tracks"]
            other_esc = _esc(conn["other_artist"])
            a_json = _esc(_j.dumps(a["name"]))
            b_json = _esc(_j.dumps(conn["other_artist"]))
            score = conn["score"]
            cls = (
                "master-overlap-badge--high"
                if score >= 70
                else "master-overlap-badge--med"
                if score >= 30
                else "master-overlap-badge--low"
            )
            label = f'{shared} track{"s" if shared != 1 else ""} w/ {other_esc}'
            overlap_html += (
                f'<a class="master-overlap-badge {cls}" href="#connectionsSection" '
                f'onclick="matrixClick({a_json},{b_json});return false;">'
                f"{label}</a>"
            )
        sets = a["sets_analyzed"]
        unique = a["unique_tracks"]
        sig = a["signature_score"]
        cards.append(
            f'<div class="master-artist-card" data-name="{name_esc}" onclick="artistCardClick(event,this)">'
            f'<span class="master-select-badge">\u2713</span>'
            f'<a class="master-artist-name" href="{html_rel}">{name_esc}</a>'
            f'<div class="master-artist-stats">'
            f'<span class="master-artist-stat"><strong>{sets}</strong> sets</span>'
            f'<span class="master-artist-stat"><strong>{unique:,}</strong> tracks</span>'
            f'<span class="master-artist-stat"><strong>{sig:.0f}%</strong> sig</span>'
            f"</div>"
            + (f'<div class="master-artist-genres">{genre_tags}</div>' if genre_tags else "")
            + (f'<div class="master-artist-overlaps">{overlap_html}</div>' if overlap_html else "")
            + "</div>"
        )
    return "\n".join(cards)


def _render_master_sig_card(t: dict) -> str:
    """Shared sig-staple-card renderer for master summary track cards.

    Accepts a registry entry (from track_registry / most_played_tracks) with fields:
      display_artist, display_title, spotify_url, spotify_album_art,
      dj_appearances: [{dj, appearances, sets: [str]}],
      total_appearances, num_djs, is_cross_artist
    """
    total = t.get("total_appearances", t.get("appearances", 1))
    num_djs = t.get("num_djs", 1)
    art_url = t.get("spotify_album_art") or ""
    art_html = (
        f'<img class="sig-staple-art" src="{_esc(art_url)}" alt="" loading="lazy">'
        if art_url else '<div class="sig-staple-art--empty"></div>'
    )
    spotify_btn = ""
    if t.get("spotify_url"):
        spot_id = _esc(t["spotify_url"].split("/")[-1].split("?")[0])
        spotify_btn = (
            f'<button class="btn-staple-spotify" '
            f'onclick="toggleStapleSpotify(this, \'{spot_id}\')">'
            f'\u25b6 Spotify</button>'
        )
    # DJs panel: one row per DJ — name (hyperlink to artist summary) + set count
    sets_rows = []
    track_q = quote(f'{t.get("display_artist", "")} {t.get("display_title", "")}', safe='')
    for dj_app in t.get("dj_appearances", []):
        dj_name = dj_app["dj"]
        dir_name = dj_app.get("dir_name", "")
        n_sets = len(dj_app.get("sets", []))
        if dir_name:
            artist_href = _esc(f'{dir_name}/artist_summary.html?q={track_q}#sets-section')
            dj_html = f'<a class="staple-sets-link" href="{artist_href}">{_esc(dj_name)}</a>'
        else:
            dj_html = f'<span class="staple-sets-link">{_esc(dj_name)}</span>'
        sets_rows.append(
            f'<div class="staple-sets-row">'
            f'{dj_html}'
            f'<span class="staple-sets-time">{n_sets} set{"s" if n_sets != 1 else ""}</span>'
            f'</div>'
        )
    sets_panel = (
        '<div class="staple-sets-panel" hidden>' + "".join(sets_rows) + "</div>"
    ) if sets_rows else ""
    btn_closed_text = f'\u25b8 DJs ({num_djs})'
    sets_btn = (
        f'<button class="btn-staple-sets" data-closed-text="{_esc(btn_closed_text)}" '
        f'onclick="toggleStapleSets(this)">'
        f'{btn_closed_text}</button>'
    ) if sets_rows else ""
    count_label = f'{num_djs} DJ{"s" if num_djs != 1 else ""} &middot; {total} play{"s" if total != 1 else ""}'
    return (
        f'<div class="sig-staple-card" data-count="{num_djs}" data-ndjs="{num_djs}" data-total="{total}">'
        + art_html
        + f'<div class="sig-staple-header">'
        + f'<div class="sig-staple-count">{count_label}</div>'
        + f'</div>'
        + f'<div class="sig-staple-artist">{_esc(t["display_artist"])}</div>'
        + f'<div class="sig-staple-title">{_esc(t["display_title"])}</div>'
        + f'<div class="sig-staple-actions">{sets_btn}{spotify_btn}</div>'
        + sets_panel
        + "</div>"
    )


def _render_master_genre_label(
    genre_totals: list,
    label_totals: list,
    genre_to_tracks: dict,
    label_to_tracks: dict,
    label_to_url: dict,
    artist_totals: list = None,
    artist_to_tracks: dict = None,
    most_played: list = None,
) -> str:
    """Render the global genre & label distribution as a tabbed widget with clickable bars."""
    artist_totals = artist_totals or []
    artist_to_tracks = artist_to_tracks or {}

    def _bar_rows(items, key_field, count_field, tracks_map, url_map=None):
        if not items:
            return ""
        # Pre-compute track lists so we can derive max from track count, not plays
        precomputed = []
        for item in items:
            name = item[key_field]
            track_list = sorted(
                tracks_map.get(name, {}).values(),
                key=lambda x: x.get("total_appearances", x.get("appearances", 0)),
                reverse=True,
            )
            precomputed.append((item, track_list))
        precomputed.sort(key=lambda x: len(x[1]), reverse=True)
        max_count = max((len(tl) for _, tl in precomputed), default=1) or 1
        rows = []
        for item, track_list in precomputed:
            name = item[key_field]
            count = len(track_list)
            pct = count / max_count * 100 if max_count else 0
            cards_html = "".join(_render_master_sig_card(t) for t in track_list[:30])
            discogs_hdr = ""
            if url_map:
                lurl = url_map.get(name)
                if lurl:
                    discogs_hdr = (
                        f'<div class="label-panel-header">'
                        f'<a class="btn-discogs-label" href="{_esc(lurl)}" target="_blank">'
                        f'View Label on Discogs \u2192</a></div>'
                    )
            panel_html = (
                f'<div class="genre-tracks-panel" hidden>'
                f'{discogs_hdr}'
                f'<div class="genre-tracks-grid">{cards_html}</div></div>'
            ) if cards_html else ""
            clickable = bool(cards_html)
            row_cls = "genre-bar-row genre-bar-row--clickable" if clickable else "genre-bar-row"
            click_attr = ' onclick="toggleGenreTracks(this)"' if clickable else ""
            arrow_html = '<span class="genre-bar-arrow">&#8250;</span>' if clickable else "<span></span>"
            # Wrap row + panel together so pagination can hide/show both atomically
            rows.append(
                f'<div class="genre-bar-item">'
                f'<div class="{row_cls}"{click_attr}>'
                f'{arrow_html}'
                f'<span class="genre-bar-label">{_esc(name)}</span>'
                f'<div class="genre-bar-track"><div class="genre-bar-fill" style="width:{pct:.1f}%;"></div></div>'
                f'<span class="genre-bar-count">{count}</span>'
                f'</div>'
                + panel_html
                + f'</div>'
            )
        return f'<div class="sig-genres"><div class="genre-bars">{"".join(rows)}</div></div>'

    def _paged_pane(bars_html, tab, placeholder, hidden=False):
        """Wrap a bars div with a search input and pagination controls."""
        if not bars_html:
            return f'<div class="distrib-pane" data-tab="{tab}" data-page="0"{"  hidden" if hidden else ""}><p class="empty">No data available.</p></div>'
        return (
            f'<div class="distrib-pane" data-tab="{tab}" data-page="0"{"  hidden" if hidden else ""}>'
            f'<div class="distrib-search-wrap">'
            f'<input class="distrib-search-input" type="text" placeholder="{placeholder}" '
            f'oninput="distribSearch(this)">'
            f'</div>'
            + bars_html +
            f'<div class="distrib-pagination">'
            f'<button class="distrib-pg-btn" onclick="distribPage(this,-1)">&#8249; Prev</button>'
            f'<span class="distrib-pg-info"></span>'
            f'<button class="distrib-pg-btn" onclick="distribPage(this,1)">Next &#8250;</button>'
            f'</div>'
            f'</div>'
        )

    genre_pane_html = _bar_rows(genre_totals, "genre", "count", genre_to_tracks)
    label_pane_html = _bar_rows(label_totals, "label", "count", label_to_tracks, label_to_url)
    artist_pane_html = _bar_rows(artist_totals, "artist", "count", artist_to_tracks)

    if not genre_pane_html and not label_pane_html and not artist_pane_html:
        return ""

    genres_first = bool(genre_pane_html)
    labels_first = not genres_first and bool(label_pane_html)
    artists_first = not genres_first and not labels_first and bool(artist_pane_html)
    genre_btn_cls = "distrib-tab distrib-tab--active" if genres_first else "distrib-tab"
    label_btn_cls = "distrib-tab distrib-tab--active" if labels_first else "distrib-tab"
    artist_btn_cls = "distrib-tab distrib-tab--active" if artists_first else "distrib-tab"
    # ── Tracks pane ──
    _most_played = most_played or []
    _mp_html = _render_master_most_played(_most_played) if _most_played else '<p class="empty">No track data available.</p>'
    _max_total = max(
        (t.get("total_appearances", t.get("appearances", 1)) for t in _most_played),
        default=1,
    )
    _thresholds = [t for t in [2, 3, 5, 10, 20, 50] if t <= _max_total]
    _pills = (
        '<button class="staple-filter-btn staple-filter-btn--active" onclick="filterPlayedTracks(0,this)">All</button>'
        + "".join(
            f'<button class="staple-filter-btn" onclick="filterPlayedTracks({t},this)">{t}+ plays</button>'
            for t in _thresholds
        )
    )
    tracks_pane = (
        f'<div class="distrib-pane" data-tab="tracks" hidden>'
        f'<div id="playedTracksFilterBar" class="staple-filter-bar" style="margin-bottom:14px">{_pills}</div>'
        f'<div class="sig-staples-grid" id="playedGrid">{_mp_html}</div>'
        f'</div>'
    )

    tabs_html = (
        f'<div class="distrib-tabs">'
        f'<button class="{genre_btn_cls}" data-tab="genres" onclick="switchDistribTab(\'genres\', this)">Genres</button>'
        f'<button class="{label_btn_cls}" data-tab="labels" onclick="switchDistribTab(\'labels\', this)">Labels</button>'
        f'<button class="{artist_btn_cls}" data-tab="track-artists" onclick="switchDistribTab(\'track-artists\', this)">Artists</button>'
        f'<button class="distrib-tab" data-tab="tracks" onclick="switchDistribTab(\'tracks\', this)">Tracks</button>'
        f"</div>"
    )
    genre_pane = _paged_pane(genre_pane_html, "genres", "Search genres\u2026", hidden=not genres_first)
    label_pane = _paged_pane(label_pane_html, "labels", "Search labels\u2026", hidden=not labels_first)
    artist_pane = _paged_pane(artist_pane_html, "track-artists", "Search artists\u2026", hidden=not artists_first)
    return tabs_html + genre_pane + label_pane + artist_pane + tracks_pane


def _render_master_most_played(most_played: list) -> str:
    if not most_played:
        return '<p class="empty">No track data available.</p>'
    return "\n".join(_render_master_sig_card(t) for t in most_played[:60])


def _render_master_similarity_matrix(artists: list, similarity_matrix: dict) -> str:
    if len(artists) < 2:
        return '<p class="empty">Need at least 2 artists for similarity comparison.</p>'

    import json as _j

    names = [a["name"] for a in artists]
    n = len(names)

    # Determine max score for color scaling
    scores = [
        similarity_matrix.get((names[i], names[j]), {}).get("normalized_score", 0)
        for i in range(n)
        for j in range(n)
        if i != j
    ]
    max_score = max(scores, default=1) or 1

    # Build CSS grid: n+1 columns (row label + n artist cols)
    col_defs = " ".join(["auto"] + ["1fr"] * n)
    rows_html = ""

    # Header row
    header_cells = '<div class="matrix-header-cell"></div>'  # top-left empty
    for name in names:
        short = _esc(name[:16] + "…" if len(name) > 16 else name)
        header_cells += f'<div class="matrix-header-cell" title="{_esc(name)}">{short}</div>'
    rows_html += header_cells

    # Data rows
    for i, row_name in enumerate(names):
        short_row = _esc(row_name[:16] + "…" if len(row_name) > 16 else row_name)
        rows_html += f'<div class="matrix-row-label" title="{_esc(row_name)}">{short_row}</div>'
        for j, col_name in enumerate(names):
            if i == j:
                rows_html += '<div class="matrix-cell matrix-cell--diag">—</div>'
            else:
                pair = similarity_matrix.get((row_name, col_name), {})
                score = pair.get("normalized_score", 0)
                raw = pair.get("score", 0)
                shared_t = len(pair.get("shared_tracks", []))
                # Interpolate green intensity: 0 = #1a1a1a, max = #00e676
                intensity = score / 100
                r = int(0 * intensity)
                g = int(230 * intensity)
                b = int(118 * intensity)
                bg = f"rgba({r},{g},{b},{max(0.08, intensity * 0.6):.2f})"
                border = f"rgba({r},{g},{b},{max(0.15, intensity * 0.8):.2f})"
                tooltip = (
                    f"{shared_t} shared tracks · score {score}"
                    if raw > 0
                    else "No overlap"
                )
                a_json = _esc(_j.dumps(row_name))
                b_json = _esc(_j.dumps(col_name))
                label = str(shared_t) if shared_t > 0 else ("·" if raw > 0 else "")
                rows_html += (
                    f'<div class="matrix-cell matrix-cell--clickable" '
                    f'data-a="{_esc(row_name)}" data-b="{_esc(col_name)}" '
                    f'style="background:{bg};border-color:{border}" '
                    f'title="{_esc(tooltip)}" '
                    f'onclick="matrixClick({a_json},{b_json})">'
                    f"{label}</div>"
                )

    return (
        f'<div class="master-matrix-scroll">'
        f'<div class="master-matrix" style="grid-template-columns:{col_defs}">'
        f"{rows_html}"
        f"</div></div>"
    )


def _render_master_all_sets(all_sets: list) -> str:
    """Render all sets as set cards (adapted from _render_set_cards) with artist label."""
    if not all_sets:
        return '<p class="empty">No sets found.</p>'

    CONF_COLORS = {
        "HIGH": "#00e676",
        "MEDIUM": "#ffd740",
        "LOW": "#ff9100",
        "UNCERTAIN": "#757575",
    }

    rows = []
    for idx, s in enumerate(all_sets):
        title = s.get("title", "Unknown")
        url = s.get("url", "")
        html_link = s.get("set_html_master_rel") or url or "#"
        thumb = s.get("thumbnail_url")
        total = s.get("total_tracks", 0)
        high = s.get("high_confidence", 0)
        rate = s.get("recognition_rate", 0)
        dur_s = s.get("duration", 0)
        dur_str = f"{int(dur_s // 3600)}h {int((dur_s % 3600) // 60)}m" if dur_s >= 3600 else f"{int(dur_s // 60)}m"
        artist_name = s.get("artist_name", "")
        artist_html_rel = s.get("artist_html_rel", "")

        # Thumb
        thumb_html = (
            f'<div class="set-card-thumb" style="background-image:url(\'{_esc(thumb)}\')"></div>'
            if thumb
            else '<div class="set-card-thumb set-card-thumb--empty"></div>'
        )

        # Mini timeline
        tl_segs = "".join(
            f'<div class="smt-seg" style="left:{seg["start_pct"]:.1f}%;width:{seg["width_pct"]:.1f}%;'
            f'background:{_CONF_COLORS.get(seg["confidence"], "#555")}"></div>'
            for seg in s.get("mini_timeline", [])
        )
        mini_tl = f'<div class="set-mini-timeline">{tl_segs}</div>'

        # Tracklist with confidence badges (matching _render_set_cards)
        _card_conf_colors = {
            "HIGH": "#00e676", "MEDIUM": "#ffd740",
            "LOW": "#ff9100", "UNCERTAIN": "#757575",
        }
        track_rows = "".join(
            '<div class="stl-track" data-track-key="{tkey}">'
            '<span class="stl-track-time">{time}</span>'
            '<span class="stl-track-name">'
            '<span class="stl-track-artist">{artist}</span>'
            ' \u2014 '
            '<span class="stl-track-title">{title}</span>'
            '</span>'
            '<span class="stl-track-conf" style="border-color:{cc};color:{cc};">{conf}</span>'
            '</div>'.format(
                tkey=_esc(t.get("track_key", "")),
                time=_esc(t.get("start_time_formatted", "")),
                artist=_esc(t.get("artist", "")),
                title=_esc(t.get("title", "")),
                conf=_esc(t.get("confidence", "UNCERTAIN")),
                cc=_card_conf_colors.get(t.get("confidence", "UNCERTAIN"), "#757575"),
            )
            for t in s.get("tracks", [])[:40]
        )
        tracklist_html = (
            f'<div class="set-card-tracklist" hidden>{track_rows}</div>'
            if track_rows
            else ""
        )
        toggle_btn = (
            f'<button class="sc-toggle-btn" onclick="toggleCardTracklist({idx})">'
            f"\u25b8 Show Tracklist</button>"
            if track_rows
            else ""
        )
        source_link = (
            f'<a class="source-link" href="{_esc(url)}" target="_blank" rel="noopener">'
            f'\u2197 Source</a>'
            if url else ""
        )

        search_text = _esc(s.get("track_search_text", "") + " " + title + " " + artist_name)
        artist_label = (
            f'<a class="master-set-artist-label" href="{_esc(artist_html_rel)}">{_esc(artist_name)}</a>'
            if artist_name
            else ""
        )
        high_pill = (
            f'<span class="set-card-pill pill-high">{high} high</span>' if high else ""
        )

        rows.append(
            f'<div class="set-card" data-card-idx="{idx}" '
            f'data-search-text="{search_text}" '
            f'data-artist-name="{_esc(artist_name)}">'
            + thumb_html
            + f'<div class="set-card-body">'
            + artist_label
            + f'<a class="set-card-title" href="{_esc(html_link)}" '
            + (f'target="_blank" rel="noopener"' if html_link != "#" else "")
            + f">{_esc(title)}</a>"
            + mini_tl
            + f'<div class="set-card-stats">'
            + f'<span class="set-card-pill">{total} tracks</span>'
            + high_pill
            + f'<span class="set-card-pill">{rate:.0f}% id</span>'
            + f'<span class="set-card-pill">{dur_str}</span>'
            + "</div>"
            + f'<div class="set-card-footer">{source_link}{toggle_btn}</div>'
            + "</div>"
            + tracklist_html
            + "</div>"
        )

    return "\n".join(rows)
