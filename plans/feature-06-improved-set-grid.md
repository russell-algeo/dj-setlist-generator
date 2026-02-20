# Feature 06: Improved Set Grid (Artist Level)

## Context

The artist-level HTML shows a grid of set cards with minimal information: title (clickable), total track count, high-confidence count, and a source link. This feature enriches each set card with a mini-timeline visualization, recognition rate indicator, duration display, and thumbnail artwork. It also adds sorting/filtering and a cross-set track search.

## Goal

- **Mini-timeline sparkline** on each set card: a tiny version of the confidence-colored timeline bar
- **Recognition rate indicator**: visual percentage of identified tracks
- **Duration display**: show set length
- **YouTube thumbnail** (if YouTube source): display as card background or header image
- **Sort/filter controls**: sort by track count, recognition rate, duration; filter by search text. (Note: "sort by date" from the original brainstorm is omitted because no date field exists in the JSON output — YouTube/SoundCloud don't reliably expose upload dates through yt-dlp metadata. Could be added in the future if date parsing from video titles is implemented.)
- **Cross-set track search**: "Find which sets contain track X"

## Files to Modify

1. **`artist_summary.py`** — extend `set_summaries` with duration, recognition rate, mini-timeline data, and thumbnail URL
2. **`html_formatter.py`** — update `_render_set_cards()` and add sort/filter JS

## Existing Code Understanding

### set_summaries Data (artist_summary.py:65-71, 123-129)
Currently each entry has:
```python
{
    "title": "...",
    "url": "...",
    "total_tracks": N,
    "high_confidence": N,
    "set_html_rel": "path/to.html" or None,
}
```

### JSON Data Available
When reading set JSON files (line 43-46):
```python
data = json.load(f)
tracks = data.get("tracks", [])
mix_info = data.get("mix_info", {})
metadata = data.get("metadata", {})
```

`mix_info` contains `duration` (total seconds) and `url`.
`metadata` contains confidence count breakdowns.
Each track has `start_time`, `end_time`, `confidence`.

### Set Card HTML (html_formatter.py:987-1032)
Currently renders a `.set-card` div with title, track count pill, high-conf pill, and source link.
Grid: `repeat(auto-fill, minmax(270px, 1fr))`

### YouTube Thumbnail URLs
For YouTube videos, thumbnails are available at predictable URLs:
- `https://img.youtube.com/vi/VIDEO_ID/mqdefault.jpg` (320x180)
- `https://img.youtube.com/vi/VIDEO_ID/hqdefault.jpg` (480x360)
No API call needed — these are static public URLs.

## Implementation Plan

### Step 1: Extend set_summaries with Richer Data

In `artist_summary.py`, when building each set summary entry, add:

```python
# Duration
duration = mix_info.get("duration", 0)

# Recognition rate
total_tracks = metadata.get("total_tracks", len(tracks))
recognized = sum(1 for t in tracks if t.get("title") != "Unknown Track")
recognition_rate = (recognized / total_tracks * 100) if total_tracks else 0

# Confidence breakdown for mini-timeline
confidence_counts = {
    "HIGH": metadata.get("high_confidence_tracks", 0),
    "MEDIUM": metadata.get("medium_confidence_tracks", 0),
    "LOW": metadata.get("low_confidence_tracks", 0),
    "UNCERTAIN": metadata.get("uncertain_tracks", 0),
}

# Mini-timeline data: list of {start_pct, width_pct, confidence}
mini_timeline = []
for t in tracks:
    if duration and t.get("start_time") is not None:
        start = t["start_time"]
        end = t.get("end_time") or duration
        start_pct = start / duration * 100
        width_pct = max(0.5, (end - start) / duration * 100)
        mini_timeline.append({
            "start_pct": start_pct,
            "width_pct": width_pct,
            "confidence": t.get("confidence", "UNCERTAIN"),
        })

# YouTube thumbnail
thumbnail_url = None
url = result.get("url", "") or mix_info.get("url", "")
video_id = _extract_youtube_id(url)  # new helper
if video_id:
    thumbnail_url = f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"

set_summaries.append({
    "title": ...,
    "url": ...,
    "total_tracks": total_tracks,
    "high_confidence": ...,
    "set_html_rel": set_html_rel,
    # NEW fields:
    "duration": duration,
    "recognition_rate": recognition_rate,
    "confidence_counts": confidence_counts,
    "mini_timeline": mini_timeline,
    "thumbnail_url": thumbnail_url,
})
```

### Step 2: Add YouTube ID Extractor Helper

Add to `artist_summary.py` (or import from `output_formatter.py` if factored out):

```python
from urllib.parse import urlparse, parse_qs

def _extract_youtube_id(url: str) -> str | None:
    """Extract YouTube video ID from URL."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower().removeprefix('www.').removeprefix('m.')
        if host == 'youtube.com':
            return parse_qs(parsed.query).get('v', [None])[0]
        if host == 'youtu.be':
            return parsed.path.lstrip('/')
    except Exception:
        pass
    return None
```

### Step 3: Update _render_set_cards() HTML

Rewrite the set card rendering in `html_formatter.py`:

```html
<div class="set-card" data-tracks="26" data-rate="73" data-duration="6865"
     data-search="set title lowercase">

  <!-- Thumbnail header (if available) -->
  <div class="set-card-thumb" style="background-image: url('THUMB_URL')"></div>

  <!-- OR: no thumbnail -->
  <div class="set-card-thumb set-card-thumb--empty"></div>

  <div class="set-card-body">
    <a class="set-card-title" href="...">Set Title</a>

    <!-- Mini timeline -->
    <div class="set-mini-timeline">
      <div class="smt-seg" style="left:0%;width:5%;background:#00e676;"></div>
      <div class="smt-seg" style="left:5%;width:8%;background:#ffd740;"></div>
      ...
    </div>

    <!-- Stats row -->
    <div class="set-card-stats">
      <span class="set-card-pill">26 tracks</span>
      <span class="set-card-pill pill-high">4 high conf.</span>
      <span class="set-card-pill">73% identified</span>
      <span class="set-card-pill">1:54:25</span>
    </div>

    <div class="set-card-footer">
      <a class="source-link" href="..." target="_blank">↗ Source</a>
    </div>
  </div>
</div>
```

### Step 4: New CSS for Enhanced Set Cards

```css
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
```

### Step 5: Sort and Filter Controls

Add a control bar above the set grid:

```html
<div class="sets-controls">
  <input id="setSearch" class="search-input" type="search"
         placeholder="Search sets or find track across sets…" autocomplete="off">
  <div class="sort-buttons">
    <button class="sort-btn active" data-sort="default">Default</button>
    <button class="sort-btn" data-sort="tracks">Most Tracks</button>
    <button class="sort-btn" data-sort="rate">Best Recognition</button>
    <button class="sort-btn" data-sort="duration">Longest</button>
  </div>
</div>
```

### Step 6: Sort and Filter JS

```javascript
// Set search
const setSearchInput = document.getElementById('setSearch');
setSearchInput.addEventListener('input', filterSets);

function filterSets() {
  const query = setSearchInput.value.toLowerCase().trim();
  document.querySelectorAll('.set-card').forEach(card => {
    const match = !query || card.dataset.search.includes(query);
    card.style.display = match ? '' : 'none';
  });
}

// Sort buttons
const sortBtns = document.querySelectorAll('.sort-btn');
const setsGrid = document.querySelector('.sets-grid');

sortBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    sortBtns.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    sortSets(btn.dataset.sort);
  });
});

function sortSets(sortBy) {
  const cards = Array.from(setsGrid.querySelectorAll('.set-card'));
  cards.sort((a, b) => {
    switch(sortBy) {
      case 'tracks': return parseInt(b.dataset.tracks) - parseInt(a.dataset.tracks);
      case 'rate': return parseInt(b.dataset.rate) - parseInt(a.dataset.rate);
      case 'duration': return parseInt(b.dataset.duration) - parseInt(a.dataset.duration);
      default: return 0; // preserve original order
    }
  });
  cards.forEach(card => setsGrid.appendChild(card));
}
```

### Step 7: Cross-Set Track Search

The set search also works as a cross-set track search. To enable this, add all track names to each set card's `data-search` attribute:

In `artist_summary.py`, when building set summaries, also build a list of all track search strings per set:

```python
track_search_text = " ".join(
    f"{t.get('artist', '')} {t.get('title', '')}".lower()
    for t in tracks
    if t.get("title") != "Unknown Track"
)
set_summaries[-1]["track_search_text"] = track_search_text
```

Then in the HTML: `data-search="{title_lower} {track_search_text}"`.

When a user types "Aphex Twin" in the search, all sets containing any Aphex Twin track will be shown.

### Step 8: Duration Formatting Helper

Add (or reuse from `output_formatter.py`) a duration formatter:

```python
def _format_duration_hms(seconds: float) -> str:
    """Format seconds as H:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
```

## Testing

1. Run artist mode for a DJ with 3+ sets (ideally mix of YouTube and SoundCloud)
2. Open artist_summary.html → verify:
   - Set cards show thumbnail (YouTube sets) or gradient header (SoundCloud/other)
   - Mini-timeline bar appears with confidence-colored segments
   - Recognition rate percentage displays
   - Duration displays in H:MM:SS format
   - Sort buttons work: clicking "Most Tracks" reorders cards
   - Search filters sets by title
   - Typing a track name filters to sets containing that track
3. Test with a single set → grid should still look good (1 card)
4. Verify mobile responsiveness → cards stack vertically, thumbnails scale
