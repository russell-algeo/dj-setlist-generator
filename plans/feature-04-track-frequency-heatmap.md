# Feature 04: Track Frequency Heatmap (Artist Level)

## Context

The artist-level HTML summary (`save_artist_summary_html()` in `html_formatter.py`) currently shows a "Most Played Tracks" list with text-based appearance chips per set. This feature replaces or supplements that with a visual heatmap grid — rows are tracks, columns are sets, cells are colored by confidence or presence. This makes it immediately obvious which tracks recur and how confident each detection was.

## Goal

- Add an interactive heatmap grid to the artist summary HTML
- Rows = top tracks (by appearance count), Columns = sets analyzed
- Cells colored by presence/confidence: green (HIGH), yellow (MEDIUM), orange (LOW), gray (UNCERTAIN), dark/empty (not detected)
- Hovering a cell shows: track name, set name, time range, confidence
- Clicking a cell navigates to the track in that set's HTML page

## Files to Modify

1. **`artist_summary.py`** — extend data passed to HTML formatter to include per-track-per-set confidence
2. **`html_formatter.py`** — add heatmap section to `save_artist_summary_html()`

## Existing Code Understanding

### Data Flow (artist_summary.py)
The `generate()` method (line 19-177) builds:
- `track_counter`: `Counter` of `"Artist - Title"` → count
- `track_info`: dict keyed by `"Artist - Title"` → `{artist, title, spotify_url, appearances: [...]}`
- Each appearance: `{set_title, time_range, source_deep_link, set_html_rel}`
- `set_summaries`: list of `{title, url, total_tracks, high_confidence, set_html_rel}`

### What's Missing for Heatmap
The current `track_info[key]['appearances']` stores which sets a track appeared in, but does NOT store the **confidence level** of each detection. We need to add this.

### Confidence Data Availability
In the JSON files read by `artist_summary.py` (line 43-87), each track has:
```json
{ "confidence": "HIGH", ... }
```
This is available at `track['confidence']` but is not currently captured into `all_tracks`.

### HTML Rendering (html_formatter.py:1291-1367)
The `save_artist_summary_html()` method receives: `artist_name, set_summaries, track_counter, track_info, successful, failed`.

### Color Scheme
Already defined in `CONFIDENCE_CONFIG` (line 12-17):
```python
'HIGH': '#00e676', 'MEDIUM': '#ffd740', 'LOW': '#ff9100', 'UNCERTAIN': '#757575'
```

## Implementation Plan

### Step 1: Capture Confidence in Appearances Data

In `artist_summary.py`, when building `all_tracks` (around line 74-87 and 131-145), add the confidence field:

```python
all_tracks.append({
    "artist": track["artist"],
    "title": track["title"],
    "spotify_url": track.get("spotify_url"),
    "from_set": set_title,
    "time_range": time_range,
    "source_deep_link": track.get("source_deep_link"),
    "set_html_rel": set_html_rel,
    "confidence": track.get("confidence", "UNCERTAIN"),  # NEW
})
```

This same addition must be made in BOTH places where `all_tracks.append()` is called (line ~79 for current-run sets, line ~139 for migrated sets).

Then when building `track_info[key]['appearances']` (line 159-164), include confidence:

```python
track_info[key]["appearances"].append({
    "set_title": t["from_set"],
    "time_range": t.get("time_range", ""),
    "source_deep_link": t.get("source_deep_link"),
    "set_html_rel": t.get("set_html_rel"),
    "confidence": t.get("confidence", "UNCERTAIN"),  # NEW
})
```

### Step 2: Build Heatmap Data Structure

Add a new function in `html_formatter.py`:

```python
def _build_heatmap_data(track_counter, track_info: dict, set_summaries: list) -> dict:
    """Build the data needed for the heatmap visualization.

    Returns:
        {
            'set_titles': ['Set A', 'Set B', ...],
            'set_html_rels': ['path/to/a.html', None, ...],
            'rows': [
                {
                    'track_key': 'Artist - Title',
                    'artist': 'Artist',
                    'title': 'Title',
                    'cells': [
                        {'present': True, 'confidence': 'HIGH', 'time_range': '12:30 – 15:45', 'deep_link': '...', 'set_html_rel': '...'},
                        {'present': False},
                        ...
                    ]
                },
                ...
            ]
        }
    """
```

Logic:
1. Build ordered list of set titles from `set_summaries`
2. For each of the top N tracks (from `track_counter.most_common(N)`, suggest N=30):
   - For each set, check if this track appears (by matching `set_title` in appearances)
   - If present, record confidence, time_range, deep_link
   - If not, mark as absent

### Step 3: Render Heatmap HTML

Add `_render_heatmap(heatmap_data: dict) -> str`:

**Structure:**
```html
<div class="heatmap-container">
  <!-- Column headers (set names) -->
  <div class="hm-header">
    <div class="hm-track-label"></div> <!-- spacer for track name column -->
    <div class="hm-set-labels">
      <div class="hm-set-label" style="transform: rotate(-45deg);">Set Name</div>
      ...
    </div>
  </div>

  <!-- Rows (one per track) -->
  <div class="hm-body">
    <div class="hm-row">
      <div class="hm-track-label">Artist — Title</div>
      <div class="hm-cells">
        <div class="hm-cell" style="background: #00e676;"
             data-track="..." data-set="..." data-time="..." data-conf="HIGH"
             onclick="navigateToTrack('path/to/set.html')"></div>
        <div class="hm-cell hm-cell--empty"></div>
        ...
      </div>
    </div>
    ...
  </div>
</div>
```

**CSS:**
```css
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
}

.hm-cell--empty {
  background: #1a1a1a;
  cursor: default;
}
.hm-cell--empty:hover {
  transform: none;
}
```

### Step 4: Heatmap Tooltip

Reuse the tooltip pattern from the set-level timeline. Add a tooltip div:

```html
<div id="hm-tooltip" class="hm-tooltip">
  <div class="hm-tip-track"></div>
  <div class="hm-tip-set"></div>
  <div class="hm-tip-time"></div>
  <div class="hm-tip-conf"></div>
</div>
```

JS to show/hide on hover (similar to the timeline tooltip logic already in the set-level HTML):

```javascript
const hmTooltip = document.getElementById('hm-tooltip');

document.querySelectorAll('.hm-cell:not(.hm-cell--empty)').forEach(cell => {
  cell.addEventListener('mouseenter', function(e) {
    hmTooltip.querySelector('.hm-tip-track').textContent = this.dataset.track;
    hmTooltip.querySelector('.hm-tip-set').textContent = this.dataset.set;
    hmTooltip.querySelector('.hm-tip-time').textContent = this.dataset.time || '';
    hmTooltip.querySelector('.hm-tip-conf').textContent = this.dataset.conf;
    hmTooltip.querySelector('.hm-tip-conf').style.color = getConfColor(this.dataset.conf);
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

function getConfColor(conf) {
  return { HIGH: '#00e676', MEDIUM: '#ffd740', LOW: '#ff9100', UNCERTAIN: '#757575' }[conf] || '#757575';
}

function positionHmTooltip(cx, cy) {
  // Same positioning logic as timeline tooltip
  const OFFSET = 14, vw = window.innerWidth, vh = window.innerHeight;
  const tw = hmTooltip.offsetWidth || 200, th = hmTooltip.offsetHeight || 80;
  let left = cx + OFFSET, top = cy + OFFSET;
  if (left + tw > vw - 8) left = cx - tw - OFFSET;
  if (top + th > vh - 8) top = cy - th - OFFSET;
  hmTooltip.style.left = Math.max(8, left) + 'px';
  hmTooltip.style.top = Math.max(8, top) + 'px';
}
```

### Step 5: Cell Click Navigation

When a heatmap cell is clicked, navigate to the track in that set's HTML page:

```javascript
function navigateToTrack(setHtmlRel) {
  if (setHtmlRel) window.open(setHtmlRel, '_self');
}
```

Add `data-href` to each cell with the `set_html_rel` value.

### Step 6: Insert into Artist Summary HTML

In `save_artist_summary_html()` (line 1291), add the heatmap section between the "Sets Analyzed" and "Most Played Tracks" sections:

```python
heatmap_data = _build_heatmap_data(track_counter, track_info, set_summaries)
heatmap_html = _render_heatmap(heatmap_data)
```

Then in the HTML template:
```html
<section>
  <h2>Track Frequency Heatmap</h2>
  {heatmap_html}
</section>
```

### Step 7: Add Heatmap CSS to _SUMMARY_CSS

Append the heatmap CSS to the `_SUMMARY_CSS` constant in `html_formatter.py`.

## Testing

1. Run in artist mode for a DJ with 3+ processed sets
2. Open artist_summary.html → verify:
   - Heatmap section appears between "Sets Analyzed" and "Most Played Tracks"
   - Rows show top 30 tracks, columns show all sets
   - Cells are correctly colored by confidence
   - Hovering a cell shows tooltip with track, set, time, confidence
   - Clicking a colored cell navigates to that set's HTML
   - Empty cells are dark and non-interactive
   - Horizontal scrolling works when there are many sets
3. Test with a DJ with only 1 set → heatmap should still render (1 column), though less useful
4. Verify the existing "Most Played Tracks" section still renders correctly
