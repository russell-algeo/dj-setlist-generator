# Feature 05: "DJ Signature" Analysis (Artist Level)

## Context

The artist-level HTML summary currently shows aggregate stats (sets analyzed, unique tracks, total detections, recurring tracks) and a most-played list. This feature adds a "DJ Signature" analysis section that provides deeper insights: a breakdown of staple vs. one-off tracks, genre distribution, and most-played tracks with visual indicators of how frequently they recur.

## Goal

- **Most-played tracks leaderboard with sparkline trend**: Show top tracks with a sparkline indicating whether they're played more or less over time (across sets in chronological order)
- **Staples vs. One-offs visual**: Clear split showing tracks played in 3+ sets ("staples"), 2 sets ("regulars"), and 1 set ("one-offs") with counts and percentages
- **Genre distribution**: If genre data is available (from Feature 02 or Spotify enrichment), show genre breakdown as a visual bar chart
- **"Signature Score"**: A computed metric showing how repetitive/consistent the DJ's track selection is (ratio of recurring tracks to total unique)
- **Top staples highlight**: The DJ's most defining tracks, displayed prominently

## Files to Modify

1. **`artist_summary.py`** — compute signature analysis data, pass to HTML formatter
2. **`html_formatter.py`** — add signature analysis section to `save_artist_summary_html()`

## Existing Code Understanding

### Data Available in artist_summary.py
- `track_counter`: Counter of `"Artist - Title"` → appearance count
- `track_info`: dict with `{artist, title, spotify_url, appearances: [...]}`
- `set_summaries`: list of `{title, url, total_tracks, high_confidence}`
- Already computes: `unique_tracks`, `total_appearances`, `repeat_tracks`

### Genre Data
Genre data is NOT currently in the JSON output or enrichment pipeline. It would come from Feature 02 (track card upgrades) which adds `spotify_genres` to each track's metadata. If Feature 02 is implemented first, the JSON files will contain `spotify_genres`. If not, this section gracefully degrades (just don't show genre distribution).

### Current Stats Strip (html_formatter.py:1320-1337)
Already shows 4 stat blocks. The signature analysis will be a new section, not modifications to the existing stats.

## Implementation Plan

### Step 1: Compute Signature Analysis Data

In `artist_summary.py`, add a method or inline logic after building `track_counter` and `track_info`:

```python
def _compute_signature_analysis(track_counter, track_info, set_summaries):
    """Compute DJ signature analysis metrics."""
    unique = len(track_counter)

    # Categorize tracks by frequency
    staples = []    # 3+ sets
    regulars = []   # exactly 2 sets
    one_offs = []   # exactly 1 set

    for key, count in track_counter.most_common():
        info = track_info[key]
        entry = {
            'key': key,
            'artist': info['artist'],
            'title': info['title'],
            'count': count,
            'spotify_url': info.get('spotify_url'),
        }
        if count >= 3:
            staples.append(entry)
        elif count == 2:
            regulars.append(entry)
        else:
            one_offs.append(entry)

    # Signature score: what % of unique tracks are played in 2+ sets
    # Higher = more consistent/repetitive selection
    recurring = len(staples) + len(regulars)
    signature_score = (recurring / unique * 100) if unique else 0

    # Genre analysis (if available)
    genre_counter = Counter()
    for key, info in track_info.items():
        for app in info.get('appearances', []):
            # genres would be stored per-appearance or per-track
            pass
    # For now, genres come from a future enrichment step
    # We'll extract from JSON if available

    return {
        'unique_tracks': unique,
        'staples': staples,
        'regulars': regulars,
        'one_offs': one_offs,
        'signature_score': signature_score,
        'total_sets': len(set_summaries),
    }
```

**Genre extraction from JSON:** When reading JSON files in `generate()`, also collect genres if present:

```python
# In the track loop:
genres = track.get("spotify_genres", [])
```

Store collected genres in a `Counter` and pass to the analysis. Add to the returned dict:
```python
'top_genres': genre_counter.most_common(10),  # list of (genre, count)
```

### Step 2: Pass Signature Data to HTML Formatter

Extend the `save_artist_summary_html()` call to include the new data. Two options:

**Option A (clean):** Pass the signature dict as an additional parameter:
```python
html_fmt.save_artist_summary_html(
    self._artist_name, set_summaries, track_counter, track_info,
    successful, failed, signature_analysis=signature_data
)
```

**Option B (minimal change):** Compute it inside the HTML formatter using the data already passed (track_counter, track_info, set_summaries are already available). This avoids changing the function signature.

**Recommend Option B** since all needed data is already passed to the formatter.

### Step 3: Render Signature Analysis Section

Add `_render_signature_analysis(track_counter, track_info, set_summaries) -> str` in `html_formatter.py`:

**Visual breakdown bar:**
A horizontal stacked bar showing the proportion of staples / regulars / one-offs:

```html
<div class="sig-section">
  <div class="sig-score">
    <span class="sig-score-value">32%</span>
    <span class="sig-score-label">Signature Score</span>
    <span class="sig-score-desc">of unique tracks played in 2+ sets</span>
  </div>

  <div class="sig-breakdown">
    <div class="sig-bar">
      <div class="sig-bar-segment sig-staple" style="width: 15%;" title="5 staples (3+ sets)"></div>
      <div class="sig-bar-segment sig-regular" style="width: 17%;" title="6 regulars (2 sets)"></div>
      <div class="sig-bar-segment sig-oneoff" style="width: 68%;" title="23 one-offs"></div>
    </div>
    <div class="sig-legend">
      <span class="sig-legend-item"><span class="sig-dot sig-staple"></span> Staples (3+ sets): 5</span>
      <span class="sig-legend-item"><span class="sig-dot sig-regular"></span> Regulars (2 sets): 6</span>
      <span class="sig-legend-item"><span class="sig-dot sig-oneoff"></span> One-offs: 23</span>
    </div>
  </div>
</div>
```

**CSS:**
```css
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
.sig-oneoff { background: #333; }

.sig-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 8px;
  font-size: 12px;
  color: #888;
}

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
.sig-dot.sig-oneoff { background: #333; }
```

### Step 4: Staples Highlight Cards

Below the breakdown bar, show the top staples prominently:

```html
<div class="sig-staples">
  <h3>DJ Staples</h3>
  <div class="sig-staples-grid">
    <div class="sig-staple-card">
      <div class="sig-staple-count">5 sets</div>
      <div class="sig-staple-artist">Artist Name</div>
      <div class="sig-staple-title">Track Title</div>
      <a class="btn-spotify" href="..." target="_blank">Spotify</a>
    </div>
    ...
  </div>
</div>
```

```css
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
}

.sig-staple-title {
  font-size: 12px;
  color: #888;
}
```

### Step 5: Most-Played Leaderboard with Sparkline Trend

Add a "Top Tracks Trend" section showing the top staple/regular tracks with a tiny inline SVG sparkline. The sparkline shows presence (1) or absence (0) across sets in order, revealing whether the DJ plays a track consistently or started/stopped playing it.

**Data needed:** For each staple/regular track, build an array of booleans indicating presence in each set (in set_summaries order). This is already computable from the appearances data:

```python
def _build_trend_data(track_counter, track_info, set_summaries):
    """For each recurring track, build a presence array across sets."""
    set_titles = [s['title'] for s in set_summaries]
    trends = []
    for key, count in track_counter.most_common():
        if count < 2:
            break  # only recurring tracks
        info = track_info[key]
        appeared_in = {a['set_title'] for a in info.get('appearances', [])}
        presence = [1 if title in appeared_in else 0 for title in set_titles]
        trends.append({
            'key': key,
            'artist': info['artist'],
            'title': info['title'],
            'count': count,
            'presence': presence,
            'spotify_url': info.get('spotify_url'),
        })
    return trends[:15]  # top 15
```

**Render sparkline as inline SVG** (no library needed):

```python
def _render_sparkline(presence: list) -> str:
    """Render a tiny inline SVG sparkline for track presence across sets."""
    if not presence:
        return ''
    n = len(presence)
    w = 60  # total width
    h = 16  # total height
    step = w / max(n - 1, 1)

    # Build polyline points
    points = []
    for i, v in enumerate(presence):
        x = round(i * step, 1)
        y = round(h - (v * (h - 4)) - 2, 1)  # 2px padding top/bottom
        points.append(f"{x},{y}")

    # Also add dots for each set
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
```

**HTML for the leaderboard:**
```html
<div class="sig-trends">
  <h3>Track Trends</h3>
  <div class="sig-trend-list">
    <div class="sig-trend-row">
      <span class="sig-trend-rank">#1</span>
      <div class="sig-trend-info">
        <span class="sig-trend-artist">Artist</span>
        <span class="sig-trend-sep"> — </span>
        <span class="sig-trend-title">Title</span>
      </div>
      <svg class="sparkline" ...></svg>
      <span class="sig-trend-count">5 sets</span>
    </div>
    ...
  </div>
</div>
```

**CSS:**
```css
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
.sig-trend-sep { color: #444; }
.sig-trend-title { color: #888; }
.sparkline { flex-shrink: 0; }
.sig-trend-count {
  font-size: 11px;
  color: #00e676;
  font-weight: 700;
  white-space: nowrap;
}
```

The sparkline gives an at-a-glance view: a flat line at the top means "played in every set", dots dropping to the bottom show gaps. This helps users see if a track is a rising favorite or a fading one.

### Step 6: Genre Distribution (Conditional)

Only render if genre data is available. Check by scanning `track_info` for any entries with genres.

**Extract genres from JSON:** In `artist_summary.py`, when reading tracks from JSON:
```python
genres = track.get("spotify_genres", [])
```
Accumulate into a `genre_counter = Counter()` and store as `track_info[key]['genres']`.

**Render as horizontal bar chart:**
```html
<div class="sig-genres">
  <h3>Genre Distribution</h3>
  <div class="genre-bars">
    <div class="genre-bar-row">
      <span class="genre-bar-label">House</span>
      <div class="genre-bar-track">
        <div class="genre-bar-fill" style="width: 65%;"></div>
      </div>
      <span class="genre-bar-count">18</span>
    </div>
    ...
  </div>
</div>
```

```css
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
```

The width percentage for each genre bar is calculated as `(count / max_count) * 100`.

### Step 7: Insert Section into Artist Summary HTML

Place the signature analysis section after the stats strip and before "Sets Analyzed":

```python
signature_html = _render_signature_analysis(track_counter, track_info, set_summaries)
```

In the template:
```html
<section>
  <h2>DJ Signature</h2>
  {signature_html}
</section>
```

## Testing

1. Run in artist mode for a DJ with 5+ sets processed → open artist_summary.html
2. Verify:
   - Signature score displays correctly (cross-check: manually count recurring tracks / total unique)
   - Breakdown bar proportions match actual staple/regular/one-off counts
   - Legend numbers match
   - Staple cards show tracks played in 3+ sets
   - Genre distribution appears if JSON files contain `spotify_genres` (run enrichment with Spotify enabled first)
   - Genre distribution section is absent if no genre data exists
3. Test edge cases:
   - DJ with only 1 set → signature score = 0%, all one-offs, no staples
   - DJ where every track repeats → score = 100%
