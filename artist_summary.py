"""Generate aggregate artist summary across all processed DJ sets."""

import json
from html import escape
from pathlib import Path
from datetime import datetime
from collections import Counter


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _h(text: str) -> str:
    """HTML-escape a value for safe insertion into attribute or text nodes."""
    return escape(str(text), quote=True)


class ArtistSummarizer:
    """Generate aggregate artist summary across all processed DJ sets."""

    def __init__(self, artist_manager):
        self._artist_name = artist_manager.artist_name
        self._output_dir = artist_manager.output_dir

    def generate(self, results: list[dict]):
        """Generate artist_summary.md and artist_summary.json.

        Args:
            results: List of dicts with keys: url, status, mix_name, output_dir
        """
        successful = [r for r in results if r["status"] == "SUCCESS"]
        failed = [r for r in results if r["status"] != "SUCCESS"]

        all_tracks = []
        set_summaries = []

        for result in successful:
            set_output_dir = result.get("output_dir")
            if not set_output_dir:
                continue

            json_files = list(Path(set_output_dir).glob("*.json"))
            if not json_files:
                continue

            try:
                with open(json_files[0]) as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            tracks = data.get("tracks", [])
            mix_info = data.get("mix_info", {})
            metadata = data.get("metadata", {})

            # Find per-set HTML file and compute its path relative to the
            # artist summary page so set cards can link to it directly.
            html_files = list(Path(set_output_dir).glob("*.html"))
            set_html_rel = None
            if html_files:
                try:
                    set_html_rel = str(html_files[0].relative_to(self._output_dir))
                except ValueError:
                    pass  # output_dir outside expected tree — skip relative link

            set_summaries.append({
                "title": mix_info.get("title", result.get("mix_name", "Unknown")),
                "url": result["url"],
                "total_tracks": metadata.get("total_tracks", len(tracks)),
                "high_confidence": metadata.get("high_confidence_tracks", 0),
                "set_html_rel": set_html_rel,
            })

            set_title = mix_info.get("title", "Unknown")
            for track in tracks:
                if track.get("artist") != "Unknown" and track.get("title") != "Unknown Track":
                    start_fmt = track.get("start_time_formatted", "")
                    end_fmt   = track.get("end_time_formatted") or ""
                    time_range = f"{start_fmt} \u2013 {end_fmt}" if end_fmt else start_fmt
                    all_tracks.append({
                        "artist":    track["artist"],
                        "title":     track["title"],
                        "spotify_url": track.get("spotify_url"),
                        "from_set":  set_title,
                        "time_range": time_range,
                    })

        track_counter = Counter()
        track_info = {}
        for t in all_tracks:
            key = f"{t['artist']} - {t['title']}"
            track_counter[key] += 1
            if key not in track_info:
                track_info[key] = {
                    "artist":     t["artist"],
                    "title":      t["title"],
                    "spotify_url": t.get("spotify_url"),
                    "appearances": [],
                }
            track_info[key]["appearances"].append({
                "set_title":  t["from_set"],
                "time_range": t.get("time_range", ""),
            })

        _save_summary_markdown(
            self._artist_name, self._output_dir, set_summaries, track_counter,
            track_info, successful, failed
        )
        _save_summary_json(
            self._artist_name, self._output_dir, set_summaries, track_counter,
            track_info, all_tracks, successful, failed
        )
        _save_summary_html(
            self._artist_name, self._output_dir, set_summaries, track_counter,
            track_info, successful, failed
        )


def _save_summary_markdown(
    artist_name, output_dir, set_summaries, track_counter,
    track_info, successful, failed
):
    """Write the artist_summary.md file."""
    lines = []
    lines.append(f"# {artist_name} - DJ Set Analysis")
    lines.append(f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Sets Analyzed:** {len(successful)} successful, {len(failed)} failed")
    lines.append(f"**Unique Tracks Found:** {len(track_counter)}")

    # Sets overview
    lines.append(f"\n---\n")
    lines.append(f"## Sets Analyzed\n")
    for i, s in enumerate(set_summaries, 1):
        lines.append(f"{i}. **{s['title']}** - {s['total_tracks']} tracks ({s['high_confidence']} high confidence)")
        lines.append(f"   Source: {s['url']}")

    # Most played tracks
    most_common = track_counter.most_common(30)
    if most_common:
        lines.append(f"\n---\n")
        lines.append(f"## Most Played Tracks\n")
        lines.append("Tracks that appear across multiple sets:\n")
        for rank, (track_key, count) in enumerate(most_common, 1):
            info = track_info[track_key]
            spotify = f" | [Spotify]({info['spotify_url']})" if info.get("spotify_url") else ""
            lines.append(f"{rank}. **{track_key}** - played in {count} set(s){spotify}")
            for app in info.get("appearances", []):
                time_part = f" ({app['time_range']})" if app.get("time_range") else ""
                lines.append(f"   - {app['set_title']}{time_part}")

    # Failed sets
    if failed:
        lines.append(f"\n---\n")
        lines.append(f"## Failed Sets\n")
        for r in failed:
            lines.append(f"- {r['url']}: {r['status']}")

    output_path = output_dir / "artist_summary.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nSaved artist summary: {output_path}")


def _save_summary_json(
    artist_name, output_dir, set_summaries, track_counter,
    track_info, all_tracks, successful, failed
):
    """Write the artist_summary.json file."""
    summary = {
        "artist": artist_name,
        "generated_at": datetime.now().isoformat(),
        "stats": {
            "sets_analyzed": len(successful),
            "sets_failed": len(failed),
            "unique_tracks": len(track_counter),
            "total_track_appearances": len(all_tracks),
        },
        "sets": set_summaries,
        "most_played_tracks": [
            {
                "artist": track_info[key]["artist"],
                "title": track_info[key]["title"],
                "appearances": count,
                "spotify_url": track_info[key].get("spotify_url"),
            }
            for key, count in track_counter.most_common(50)
        ],
        "failed_sets": [
            {"url": r["url"], "error": r["status"]}
            for r in failed
        ],
    }

    output_path = output_dir / "artist_summary.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"Saved artist summary JSON: {output_path}")


# ---------------------------------------------------------------------------
# HTML artist summary
# ---------------------------------------------------------------------------

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
        title_esc = _h(s['title'])
        source_url = s.get('url', '')

        # Prefer internal HTML link; fall back to original source URL
        if s.get('set_html_rel'):
            primary_href = _h(s['set_html_rel'])
            primary_target = '_self'
        elif source_url:
            primary_href = _h(source_url)
            primary_target = '_blank'
        else:
            primary_href = '#'
            primary_target = '_self'

        high_conf = s.get('high_confidence', 0)
        total = s.get('total_tracks', 0)

        high_pill = (
            f'<span class="set-card-pill pill-high">{_h(high_conf)} high conf.</span>'
            if high_conf else ''
        )

        source_link = (
            f'<a class="source-link" href="{_h(source_url)}" '
            f'target="_blank" rel="noopener">↗ Source</a>'
            if source_url else ''
        )

        cards.append(f'''<div class="set-card">
  <a class="set-card-title" href="{primary_href}" target="{primary_target}">{title_esc}</a>
  <div class="set-card-stats">
    <span class="set-card-pill">{_h(total)} tracks</span>
    {high_pill}
  </div>
  <div class="set-card-footer">
    {source_link}
  </div>
</div>''')

    return '\n'.join(cards)


def _render_most_played(track_counter: Counter, track_info: dict) -> str:
    """Render the most-played tracks list HTML (top 30)."""
    most_common = track_counter.most_common(30)
    if not most_common:
        return '<p class="empty">No tracks found.</p>'

    rows = []
    for rank, (key, count) in enumerate(most_common, 1):
        info = track_info.get(key, {})
        artist_esc = _h(info.get('artist', ''))
        title_esc  = _h(info.get('title', key))
        spotify_url = info.get('spotify_url') or ''

        count_class = 'count-multi' if count > 1 else 'count-badge'
        count_label = f"{count} set{'s' if count != 1 else ''}"

        spotify_btn = (
            f'<a class="btn-spotify" href="{_h(spotify_url)}" '
            f'target="_blank" rel="noopener">Spotify</a>'
        ) if spotify_url else ''

        appearances = info.get('appearances', [])
        app_chips = ''
        if appearances:
            chips = []
            for app in appearances:
                time_part = (
                    f'<span class="app-time">\u00a0{_h(app["time_range"])}</span>'
                    if app.get('time_range') else ''
                )
                chips.append(
                    f'<span class="app-chip">{_h(app["set_title"])}{time_part}</span>'
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
    <span class="count-badge {count_class}">{_h(count_label)}</span>
    {spotify_btn}
  </div>
</div>''')

    return '\n'.join(rows)


def _render_failed_section(failed: list) -> str:
    """Render the failed sets section HTML, or empty string if none."""
    if not failed:
        return ''

    items = ''.join(
        f'<li class="failed-item"><span class="failed-url">{_h(r["url"])}</span>'
        f' — {_h(r["status"])}</li>'
        for r in failed
    )
    return f'''<section>
  <h2>Failed Sets ({len(failed)})</h2>
  <ul class="failed-list">{items}</ul>
</section>'''


def _save_summary_html(
    artist_name, output_dir, set_summaries, track_counter,
    track_info, successful, failed
):
    """Write the artist_summary.html file."""
    generated = datetime.now().strftime('%Y-%m-%d %H:%M')
    unique_tracks = len(track_counter)
    total_appearances = sum(track_counter.values())
    repeat_tracks = sum(1 for c in track_counter.values() if c > 1)

    sets_html     = _render_set_cards(set_summaries)
    played_html   = _render_most_played(track_counter, track_info)
    failed_html   = _render_failed_section(failed)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_h(artist_name)} — DJ Set Analysis</title>
  <style>{_SUMMARY_CSS}</style>
</head>
<body>

<div class="container">

  <div class="artist-name">{_h(artist_name)}</div>
  <div class="page-subtitle">DJ Set Analysis</div>
  <div class="header-meta">Generated {_h(generated)}</div>

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
    Generated {_h(generated)} &middot; DJ Set Setlist Generator
  </div>

</div>
</body>
</html>"""

    output_path = output_dir / "artist_summary.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved artist summary HTML: {output_path}")
