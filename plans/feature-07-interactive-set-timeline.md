# Feature 07: Interactive Set Timeline (Artist Level)

## Context

The artist-level HTML shows sets in a grid layout but lacks a temporal/chronological view. This feature adds a horizontal scrollable timeline that shows all sets arranged chronologically (or by order of processing if dates aren't available), with expandable tracklists and visual indicators connecting the same track across different sets.

## Goal

- **Chronological timeline** of all sets, scrollable horizontally
- Each set is a node on the timeline showing: title, track count, mini-timeline, and can be expanded to reveal its tracklist inline
- **Track continuity lines**: Draw SVG lines/arcs connecting the same track across different set nodes on the timeline, making recurring tracks visually obvious even before expanding
- **Recurring track hover highlighting**: When hovering a track in an expanded tracklist, highlight all instances across other expanded tracklists
- Click-to-expand shows the full tracklist for a set without leaving the page

## Files to Modify

1. **`artist_summary.py`** — extend set data with full tracklists and ordering info
2. **`html_formatter.py`** — add interactive timeline section to `save_artist_summary_html()`

## Existing Code Understanding

### Data Available
In `artist_summary.py`, when reading each set's JSON:
- `tracks`: full list of tracks with `artist`, `title`, `start_time_formatted`, `end_time_formatted`, `confidence`, `spotify_url`, etc.
- `mix_info`: has `title`, `url`, `duration`
- `set_html_rel`: relative path to set HTML page

### Current Ordering
Sets are processed in the order discovered/provided. There's no date field in the JSON. YouTube video titles sometimes contain dates, but parsing them would be fragile. We'll use processing order as the default timeline order.

### Track Identity
Tracks are keyed by `"Artist - Title"` in track_counter/track_info. This same key can identify recurring tracks across sets.

## Implementation Plan

### Step 1: Extend Set Data with Full Tracklists

In `artist_summary.py`, when building set_summaries, also capture the full tracklist per set (currently only title/url/counts are captured):

```python
# In the loop building set_summaries (both for current-run and migrated sets):
set_tracks = []
for track in tracks:
    if track.get("title") != "Unknown Track":
        set_tracks.append({
            "artist": track.get("artist", "Unknown"),
            "title": track.get("title", "Unknown Track"),
            "start_time_formatted": track.get("start_time_formatted", ""),
            "confidence": track.get("confidence", "UNCERTAIN"),
            "spotify_url": track.get("spotify_url"),
            "track_key": f"{track.get('artist', 'Unknown')} - {track.get('title', 'Unknown Track')}",
        })

set_summaries[-1]["tracks"] = set_tracks
```

Also assign an index to each set for positioning:
```python
set_summaries[-1]["index"] = len(set_summaries) - 1
```

### Step 2: Build Recurring Track Map

After all set_summaries are built, create a map of track_key → list of set indices:

```python
recurring_map = {}  # track_key -> [set_index_0, set_index_1, ...]
for i, s in enumerate(set_summaries):
    for t in s.get("tracks", []):
        key = t["track_key"]
        if key not in recurring_map:
            recurring_map[key] = []
        recurring_map[key].append(i)
# Filter to only tracks in 2+ sets
recurring_map = {k: v for k, v in recurring_map.items() if len(v) > 1}
```

Pass `recurring_map` to the HTML formatter.

### Step 3: Render Timeline HTML

Add `_render_set_timeline(set_summaries, recurring_map) -> str` in `html_formatter.py`:

```html
<div class="stl-container">
  <!-- Horizontal scroll wrapper -->
  <div class="stl-scroll">
    <!-- Timeline axis -->
    <div class="stl-axis"></div>

    <!-- Set nodes -->
    <div class="stl-nodes">
      <div class="stl-node" data-set-idx="0">
        <div class="stl-node-dot"></div>
        <div class="stl-node-card">
          <div class="stl-node-title">Set Title Here</div>
          <div class="stl-node-meta">26 tracks · 1:54:25</div>
          <div class="stl-node-mini-timeline">
            <!-- mini colored bar segments -->
          </div>
          <button class="stl-expand-btn" onclick="toggleSetExpand(0)">
            ▼ Show Tracklist
          </button>
        </div>

        <!-- Expandable tracklist (hidden by default) -->
        <div class="stl-tracklist" id="stlTracklist0" hidden>
          <div class="stl-track" data-track-key="Artist - Title">
            <span class="stl-track-time">12:30</span>
            <span class="stl-track-name">
              <span class="stl-track-artist">Artist</span> —
              <span class="stl-track-title">Title</span>
            </span>
            <span class="stl-track-conf conf-high">HIGH</span>
          </div>
          ...
        </div>
      </div>

      <!-- more nodes... -->
    </div>
  </div>
</div>
```

### Step 4: Timeline CSS

```css
.stl-container {
  margin-bottom: 48px;
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

/* Expanded tracklist */
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

/* Recurring track highlight */
.stl-track--recurring {
  border-left: 2px solid #ffd740;
  padding-left: 4px;
}
.stl-track--recurring:hover {
  background: #1a1a0a;
}
```

### Step 5: Expand/Collapse JS

```javascript
function toggleSetExpand(idx) {
  const tracklist = document.getElementById('stlTracklist' + idx);
  const btn = tracklist.previousElementSibling.querySelector('.stl-expand-btn')
    || document.querySelector('.stl-node[data-set-idx="' + idx + '"] .stl-expand-btn');

  if (tracklist.hidden) {
    tracklist.hidden = false;
    btn.textContent = '▲ Hide Tracklist';
  } else {
    tracklist.hidden = true;
    btn.textContent = '▼ Show Tracklist';
  }
}
```

### Step 6: Recurring Track Highlighting

When hovering a track in an expanded tracklist that appears in other sets, highlight all instances across expanded tracklists:

```javascript
document.querySelectorAll('.stl-track[data-track-key]').forEach(track => {
  track.addEventListener('mouseenter', function() {
    const key = this.dataset.trackKey;
    document.querySelectorAll('.stl-track[data-track-key="' + CSS.escape(key) + '"]')
      .forEach(t => t.classList.add('stl-track--highlight'));
  });
  track.addEventListener('mouseleave', function() {
    document.querySelectorAll('.stl-track--highlight')
      .forEach(t => t.classList.remove('stl-track--highlight'));
  });
});
```

Mark recurring tracks with `class="stl-track stl-track--recurring"` based on the `recurring_map`.

```css
.stl-track--highlight {
  background: #2a2a0a !important;
  outline: 1px solid #ffd740;
}
```

### Step 7: Track Continuity Lines (SVG)

Draw SVG arcs between set nodes that share tracks. This makes recurring tracks visible at the timeline level before expanding any tracklist.

**Approach:** Overlay an absolutely-positioned SVG canvas on top of the timeline. For each recurring track, draw a curved line (quadratic bezier) connecting the node dots of the sets it appears in.

**HTML:** Add an SVG overlay inside `.stl-scroll`:
```html
<svg class="stl-arcs" id="stlArcs"></svg>
```

**CSS:**
```css
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
```

**JS — Draw arcs on page load:**

The arcs connect the center-top of each set node's dot element. Use `getBoundingClientRect()` relative to the scroll container to get positions.

```javascript
function drawContinuityArcs() {
  const svg = document.getElementById('stlArcs');
  const container = svg.parentElement;
  const containerRect = container.getBoundingClientRect();
  svg.innerHTML = ''; // clear previous

  // Build recurring_map from DOM data
  const nodes = document.querySelectorAll('.stl-node');
  const trackSets = {}; // track_key -> [{nodeIdx, dotX, dotY}]

  nodes.forEach((node, i) => {
    const dot = node.querySelector('.stl-node-dot');
    const dotRect = dot.getBoundingClientRect();
    const cx = dotRect.left + dotRect.width / 2 - containerRect.left + container.scrollLeft;
    const cy = dotRect.top + dotRect.height / 2 - containerRect.top + container.scrollTop;

    // Get all track keys for this node
    const tracks = node.querySelectorAll('.stl-track[data-track-key]');
    tracks.forEach(t => {
      const key = t.dataset.trackKey;
      if (!trackSets[key]) trackSets[key] = [];
      trackSets[key].push({ idx: i, x: cx, y: cy });
    });
  });

  // Draw arcs for tracks appearing in 2+ sets
  Object.entries(trackSets).forEach(([key, positions]) => {
    if (positions.length < 2) return;
    // Connect consecutive pairs with bezier curves
    for (let i = 0; i < positions.length - 1; i++) {
      const p1 = positions[i];
      const p2 = positions[i + 1];
      // Control point: midpoint X, raised above the dots
      const midX = (p1.x + p2.x) / 2;
      const arcHeight = Math.min(40, Math.abs(p2.x - p1.x) * 0.15);
      const midY = p1.y - arcHeight - 20;

      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', `M ${p1.x} ${p1.y} Q ${midX} ${midY} ${p2.x} ${p2.y}`);
      path.setAttribute('class', 'stl-arc');
      path.dataset.trackKey = key;
      svg.appendChild(path);
    }
  });
}

// Draw on load and on scroll/resize
drawContinuityArcs();
document.querySelector('.stl-scroll').addEventListener('scroll', drawContinuityArcs);
window.addEventListener('resize', drawContinuityArcs);
```

**Interactive highlight:** When hovering a track in an expanded tracklist, highlight its arcs:

```javascript
document.querySelectorAll('.stl-track[data-track-key]').forEach(track => {
  track.addEventListener('mouseenter', function() {
    const key = CSS.escape(this.dataset.trackKey);
    document.querySelectorAll('.stl-arc[data-track-key="' + key + '"]')
      .forEach(arc => arc.classList.add('stl-arc--highlight'));
  });
  track.addEventListener('mouseleave', function() {
    document.querySelectorAll('.stl-arc--highlight')
      .forEach(arc => arc.classList.remove('stl-arc--highlight'));
  });
});
```

**Performance note:** For DJs with many recurring tracks (50+), the SVG could get heavy. Limit arcs to tracks appearing in 3+ sets, or the top 20 most-recurring tracks, to keep it visually clean and performant.

### Step 8: Link to Full Set HTML

Make the set title in each node a link to the set's HTML page:

```html
<a class="stl-node-title" href="path/to/set.html">Set Title</a>
```

### Step 9: Insert Section into Artist Summary

Place the timeline section after the stats strip, before "Sets Analyzed":

```html
<section>
  <h2>Set Timeline</h2>
  {timeline_html}
</section>
```

### Step 10: Scroll Hint

Add visual scroll indicators (fade edges) to hint that the timeline is scrollable:

```css
.stl-container {
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
```

## Data Flow Summary

```
artist_summary.py generate()
  → reads JSON files for each set
  → builds set_summaries with full tracks list per set
  → builds recurring_map (track_key → [set indices])
  → passes to html_formatter.save_artist_summary_html()

html_formatter.py save_artist_summary_html()
  → calls _render_set_timeline(set_summaries, recurring_map)
  → outputs horizontal scrollable timeline with expandable nodes
```

**Note on function signature:** `save_artist_summary_html()` currently takes `(self, artist_name, set_summaries, track_counter, track_info, successful, failed)`. We need to add `recurring_map` as a parameter, or compute it inside the formatter from `set_summaries` (if we add tracks data to set_summaries in Step 1, the formatter can derive recurring_map itself).

**Recommended:** Compute `recurring_map` inside `_render_set_timeline()` from the `set_summaries[i]['tracks']` data. This avoids changing the function signature.

## Testing

1. Run artist mode for a DJ with 4+ sets
2. Open artist_summary.html → verify:
   - Timeline section appears with horizontal scrollable nodes
   - Each node shows set title, track count, mini-timeline
   - SVG arcs connect nodes that share recurring tracks (subtle yellow curves above the timeline axis)
   - Clicking "Show Tracklist" expands the track list
   - Recurring tracks have a yellow left border
   - Hovering a recurring track highlights all instances across expanded tracklists AND highlights corresponding SVG arcs
   - Set title links to the set's HTML page
   - Scroll hint gradient visible on right edge
3. Test with many sets (10+) → horizontal scrolling should work smoothly; arcs should not be overwhelming (limited to top 20 recurring tracks)
4. Test with 1 set → timeline shows single node, no arcs, still functional
5. Expand two sets that share a track → verify cross-highlight works on both track rows and SVG arcs
