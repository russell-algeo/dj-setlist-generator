# Feature 02: Track Card Upgrades (Album Art, Audio Preview, Genre Tags)

## Context

Currently, track cards in the set-level HTML show: track number, timestamp, artist/title, confidence badge, detection stats, and platform link buttons. The cards are functional but text-heavy. Adding album art, audio previews, and genre tags would make them visually richer and more informative.

## Goal

- Display album art thumbnails on each track card (from Spotify)
- Add inline 30-second audio preview (from Spotify preview URL)
- Show BPM and musical key per track (from Spotify Audio Features API)
- Show genre tags as small chips on each card
- Expandable detection details: click to reveal a mini-timeline showing exactly which segments detected this track
- Drag to reorder: let users manually correct track order (persisted to localStorage)
- All new data must be captured during the enrichment phase and flowed through to the HTML

## Files to Modify

1. **`metadata_enricher.py`** — extend `enrich_track()` to fetch album art URL, preview URL, and genres from Spotify
2. **`output_formatter.py`** — extend `serialize_track()` to include the new fields
3. **`html_formatter.py`** — update `_render_track_cards()` CSS and HTML to display the new data

## Existing Code Understanding

### Metadata Enricher (metadata_enricher.py)
- `_search_spotify()` (line 119-162) searches Spotify, iterates results, scores matches, returns URL of best match
- It currently only returns the `external_urls.spotify` URL string
- The Spotify search response (`results['tracks']['items']`) contains much more data per track:
  - `album.images` — array of `{url, height, width}` objects (usually 3 sizes: 640, 300, 64)
  - `preview_url` — 30-second MP3 preview URL (can be `null`)
  - `artists[0].id` — needed to fetch artist genres
- Genre info is NOT on the track object; it's on the **artist** object. Would need `self.spotify.artist(artist_id)` → `artist['genres']`

### Enrichment Return Value
`enrich_track()` (line 58-90) returns:
```python
{'spotify_url': None, 'youtube_url': None, 'discogs_url': None}
```

### serialize_track (output_formatter.py:79-103)
Builds the plain dict from `item['track']` and `item['metadata']`:
```python
'spotify_url': meta.get('spotify_url'),
'youtube_url': meta.get('youtube_url'),
'discogs_url': meta.get('discogs_url'),
```

### Track Card HTML (html_formatter.py:66-137)
Grid layout: `grid-template-columns: 36px max-content 1fr auto`
Each card has: `.track-num`, `.track-time`, `.track-info`, `.track-actions`

## Implementation Plan

### Step 1: Extend Spotify Search to Return Rich Metadata

In `metadata_enricher.py`, modify `_search_spotify()` to return a **dict** instead of just a URL string. The returned dict should contain:

```python
{
    'url': 'https://open.spotify.com/track/...',
    'album_art_url': 'https://i.scdn.co/image/...',   # 300px size preferred
    'preview_url': 'https://p.scdn.co/mp3-preview/...',  # can be None
    'artist_id': 'spotify_artist_id',  # for genre lookup
}
```

**How to modify `_search_spotify()`:**

Currently the method builds `scored_results` as tuples of `(total_matches, observed_url, observed_artist, observed_title)`. Change this to also capture the full item:

```python
scored_results.append((total_matches, item))  # keep full Spotify item
```

Then from the best match `item`:
```python
best = scored_results[0][1]
album_images = best.get('album', {}).get('images', [])
# Pick the ~300px image (middle size), fallback to first
album_art = next((img['url'] for img in album_images if img.get('height') == 300),
                  album_images[0]['url'] if album_images else None)
return {
    'url': best['external_urls']['spotify'],
    'album_art_url': album_art,
    'preview_url': best.get('preview_url'),
    'artist_id': best['artists'][0]['id'] if best.get('artists') else None,
}
```

### Step 2: Fetch BPM and Key from Spotify Audio Features

Add a new method `_get_audio_features(self, track_id: str) -> dict`:

```python
def _get_audio_features(self, track_id: str) -> dict:
    """Fetch BPM (tempo) and musical key from Spotify Audio Features API.

    Args:
        track_id: Spotify track ID (extracted from URL)

    Returns:
        {'bpm': 128.0, 'key': 'Cm'} or empty dict on failure
    """
    if not track_id or not self.spotify:
        return {}
    try:
        features = self.spotify.audio_features([track_id])
        if not features or not features[0]:
            return {}
        f = features[0]
        # Spotify key is 0-11 (pitch class), mode is 0 (minor) or 1 (major)
        key_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        key_idx = f.get('key', -1)
        mode = f.get('mode', 0)  # 0=minor, 1=major
        key_str = ''
        if key_idx >= 0:
            key_str = key_names[key_idx] + ('m' if mode == 0 else '')
        return {
            'bpm': round(f.get('tempo', 0), 1),
            'key': key_str,
        }
    except Exception:
        return {}
```

Extract the track ID from the Spotify URL (split on `/` and `?`) before calling this method. The Spotify `audio_features` endpoint accepts batches of up to 100 track IDs — for performance, batch all track IDs in `enrich_all_tracks()` and call once:

```python
# In enrich_all_tracks(), after all individual enrichments:
track_ids = []
for item in enriched_tracks:
    url = item['metadata'].get('spotify_url')
    if url:
        tid = url.split('/')[-1].split('?')[0]
        track_ids.append(tid)
    else:
        track_ids.append(None)

# Batch fetch audio features (100 at a time)
all_features = []
for i in range(0, len(track_ids), 100):
    batch = [tid for tid in track_ids[i:i+100] if tid]
    if batch:
        try:
            features = self.spotify.audio_features(batch)
            all_features.extend(features)
        except Exception:
            all_features.extend([None] * len(batch))

# Map features back to enriched_tracks
feature_idx = 0
for item, tid in zip(enriched_tracks, track_ids):
    if tid and feature_idx < len(all_features) and all_features[feature_idx]:
        f = all_features[feature_idx]
        key_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        key_idx = f.get('key', -1)
        mode = f.get('mode', 0)
        key_str = key_names[key_idx] + ('m' if mode == 0 else '') if key_idx >= 0 else ''
        item['metadata']['spotify_bpm'] = round(f.get('tempo', 0), 1)
        item['metadata']['spotify_key'] = key_str
        feature_idx += 1
    elif tid:
        feature_idx += 1
```

### Step 3: Fetch Genre Tags from Spotify Artist

Add a new method `_get_artist_genres(self, artist_id: str) -> list[str]`:

```python
def _get_artist_genres(self, artist_id: str) -> list[str]:
    if not artist_id or not self.spotify:
        return []
    try:
        artist = self.spotify.artist(artist_id)
        return artist.get('genres', [])[:3]  # cap at 3 genres
    except Exception:
        return []
```

**Important:** Cache artist genres to avoid redundant API calls. Multiple tracks may share an artist. Use a simple `dict` cache:

```python
self._genre_cache = {}  # artist_id -> list of genres
```

Check cache before calling API.

### Step 4: Update enrich_track() Return Value

Modify `enrich_track()` to restructure:

```python
enriched = {
    'spotify_url': None,
    'spotify_album_art': None,
    'spotify_preview_url': None,
    'spotify_genres': [],
    'youtube_url': None,
    'discogs_url': None,
}

if self.spotify_enabled:
    spotify_data = self._search_spotify(track.title, track.artist)
    if spotify_data:
        enriched['spotify_url'] = spotify_data['url']
        enriched['spotify_album_art'] = spotify_data.get('album_art_url')
        enriched['spotify_preview_url'] = spotify_data.get('preview_url')
        artist_id = spotify_data.get('artist_id')
        enriched['spotify_genres'] = self._get_artist_genres(artist_id)
```

Also add the new BPM/key fields:
```python
    'spotify_bpm': None,
    'spotify_key': None,
```

These are populated by the batch audio features call in `enrich_all_tracks()` (Step 2).

**Backward compatibility note:** The `_search_spotify()` method is decorated with `@_platform_search("Spotify")` which wraps with error handling and expects the return to be `Optional[str]`. Since we're changing the return type to `Optional[dict]`, we need to update the caller in `enrich_track()` to handle both. OR better: create a separate internal method `_search_spotify_rich()` that returns the dict, and have `_search_spotify()` call it and extract just the URL. This preserves the decorator behavior.

**Cleaner approach:** Just update `enrich_track()` to not use `_search_spotify()` directly for the URL assignment. Instead, call a new `_search_spotify_full()` that returns the rich dict, and handle it all in `enrich_track()`.

### Step 5: Extend serialize_track()

In `output_formatter.py`, add the new fields to `serialize_track()`:

```python
'spotify_album_art': meta.get('spotify_album_art'),
'spotify_preview_url': meta.get('spotify_preview_url'),
'spotify_genres': meta.get('spotify_genres', []),
'spotify_bpm': meta.get('spotify_bpm'),
'spotify_key': meta.get('spotify_key'),
```

### Step 6: Update Track Card HTML

In `html_formatter.py`, modify `_render_track_cards()`:

**New grid layout** to accommodate album art:
```css
.track-card {
  grid-template-columns: 36px 48px max-content 1fr auto;
  /* num, art, time, info, actions */
}
```

**Album art cell** (between track-num and track-time):
```html
<div class="track-art">
  <img src="ALBUM_ART_URL" alt="" loading="lazy">
</div>
```
If no album art, render a placeholder:
```html
<div class="track-art track-art--empty">♪</div>
```

**CSS for album art:**
```css
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
```

**Genre tags** (in `.track-meta` row, after the confidence badge):
```html
<span class="genre-tag">House</span>
<span class="genre-tag">Techno</span>
```

```css
.genre-tag {
  padding: 1px 6px;
  border-radius: 8px;
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  font-size: 10px;
  color: #666;
  white-space: nowrap;
}
```

**BPM and key display** (in `.track-meta` row, after genre tags):
```html
<span class="track-bpm-key">128.0 BPM · Cm</span>
```
Only render when values are non-null/non-zero.

```css
.track-bpm-key {
  font-size: 10px;
  color: #555;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
```

**Expandable detection details** (after `.track-meta`, hidden by default):

Each track card gets an expand toggle and a hidden detail panel showing a mini-timeline of detection density. The detection data needed is `cluster_span` and `detection_count` (already in the track dict from `serialize_track()`). For the full segment-level view, we would need the raw segment indices — but these are NOT currently in the JSON output (only `cluster_span` and `detection_count` are). So instead, render a simplified visualization: a mini bar showing detection density as a filled proportion of the cluster span.

```html
<button class="btn btn-expand-details" onclick="toggleDetails(this)" title="Detection details">⋯</button>
<div class="track-details" hidden>
  <div class="detail-row">
    <span class="detail-label">Detection count:</span>
    <span class="detail-value">13</span>
  </div>
  <div class="detail-row">
    <span class="detail-label">Cluster span:</span>
    <span class="detail-value">17 segments</span>
  </div>
  <div class="detail-row">
    <span class="detail-label">Density:</span>
    <div class="detail-density-bar">
      <div class="detail-density-fill" style="width: 76%;"></div>
    </div>
    <span class="detail-value">76%</span>
  </div>
</div>
```

The `.track-details` div should span the full width of the card (grid-column: 1 / -1) and slide open with a CSS transition.

```css
.track-details {
  grid-column: 1 / -1;
  padding: 8px 14px;
  border-top: 1px solid #1e1e1e;
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 24px;
  font-size: 11px;
  color: #888;
}
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
```

JS for toggle:
```javascript
function toggleDetails(btn) {
  const card = btn.closest('.track-card');
  const details = card.querySelector('.track-details');
  details.hidden = !details.hidden;
}
```

**Audio preview button** (in `.track-actions`, only if preview_url exists):
```html
<button class="btn btn-preview" onclick="togglePreview(this, 'PREVIEW_URL')" title="30s preview">
  ♫ Preview
</button>
```

### Step 7: Audio Preview JS

Add a JS handler for the 30-second preview:

```javascript
let currentAudio = null;
let currentPreviewBtn = null;

function togglePreview(btn, url) {
  // If same button clicked again, stop playback
  if (currentAudio && currentPreviewBtn === btn) {
    currentAudio.pause();
    currentAudio = null;
    btn.textContent = '♫ Preview';
    btn.classList.remove('btn-preview--playing');
    currentPreviewBtn = null;
    return;
  }
  // Stop any existing playback
  if (currentAudio) {
    currentAudio.pause();
    currentPreviewBtn.textContent = '♫ Preview';
    currentPreviewBtn.classList.remove('btn-preview--playing');
  }
  // Start new playback
  currentAudio = new Audio(url);
  currentPreviewBtn = btn;
  btn.textContent = '■ Stop';
  btn.classList.add('btn-preview--playing');
  currentAudio.play();
  currentAudio.onended = function() {
    btn.textContent = '♫ Preview';
    btn.classList.remove('btn-preview--playing');
    currentAudio = null;
    currentPreviewBtn = null;
  };
}
```

```css
.btn-preview { color: #1db954; border-color: #1db954; }
.btn-preview--playing { background: #1db954; color: #000; }
```

### Step 8: Drag to Reorder

Allow users to manually drag track cards to reorder them. The reordered positions persist to `localStorage` so they're remembered on refresh.

**HTML:** Add `draggable="true"` to each `.track-card`:
```html
<div class="track-card" draggable="true" data-track-idx="1" ...>
```

**JS — Drag and Drop:**
```javascript
let dragSrcEl = null;

document.querySelectorAll('.track-card').forEach(card => {
  card.addEventListener('dragstart', function(e) {
    dragSrcEl = this;
    this.classList.add('track-card--dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', this.dataset.trackIdx);
  });

  card.addEventListener('dragover', function(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    this.classList.add('track-card--dragover');
  });

  card.addEventListener('dragleave', function() {
    this.classList.remove('track-card--dragover');
  });

  card.addEventListener('drop', function(e) {
    e.preventDefault();
    this.classList.remove('track-card--dragover');
    if (dragSrcEl !== this) {
      const tracklist = document.getElementById('tracklist');
      // Insert dragged element before or after target based on position
      const allCards = Array.from(tracklist.querySelectorAll('.track-card'));
      const srcIdx = allCards.indexOf(dragSrcEl);
      const tgtIdx = allCards.indexOf(this);
      if (srcIdx < tgtIdx) {
        tracklist.insertBefore(dragSrcEl, this.nextSibling);
      } else {
        tracklist.insertBefore(dragSrcEl, this);
      }
      // Renumber visible track numbers
      renumberTracks();
      saveTrackOrder();
    }
  });

  card.addEventListener('dragend', function() {
    this.classList.remove('track-card--dragging');
  });
});

function renumberTracks() {
  const cards = document.querySelectorAll('.track-card');
  cards.forEach((card, i) => {
    const numEl = card.querySelector('.track-num');
    if (numEl) numEl.textContent = i + 1;
  });
}

// Persist order to localStorage
function saveTrackOrder() {
  const order = Array.from(document.querySelectorAll('.track-card'))
    .map(c => c.dataset.trackIdx);
  const key = 'trackOrder_' + document.title;
  localStorage.setItem(key, JSON.stringify(order));
}

// Restore order on page load
function restoreTrackOrder() {
  const key = 'trackOrder_' + document.title;
  const saved = localStorage.getItem(key);
  if (!saved) return;
  try {
    const order = JSON.parse(saved);
    const tracklist = document.getElementById('tracklist');
    order.forEach(idx => {
      const card = tracklist.querySelector('.track-card[data-track-idx="' + idx + '"]');
      if (card) tracklist.appendChild(card);
    });
    renumberTracks();
  } catch (e) { /* invalid saved order, ignore */ }
}
restoreTrackOrder();
```

**CSS for drag states:**
```css
.track-card--dragging { opacity: 0.4; }
.track-card--dragover { border-color: #00e676 !important; background: #1a2a1a !important; }
.track-card { cursor: grab; }
.track-card:active { cursor: grabbing; }
```

Add a "Reset Order" button near the search controls that clears localStorage and reloads:
```html
<button class="btn btn-reset-order" onclick="localStorage.removeItem('trackOrder_' + document.title); location.reload();" title="Reset to original order">↺ Reset Order</button>
```

### Step 9: Responsive Adjustments

On mobile (existing `@media (max-width: 600px)` block):
- Hide album art to save space: `.track-art { display: none; }`
- Adjust grid: `grid-template-columns: 28px max-content 1fr;`

### Step 10: Update JSON Output

The new fields (`spotify_album_art`, `spotify_preview_url`, `spotify_genres`, `spotify_bpm`, `spotify_key`) will automatically flow into the JSON output since `save_setlist_json()` uses `serialize_track()`. No additional changes needed in `output_formatter.py` beyond Step 5.

## Testing

1. Process a DJ set with `ENABLE_SPOTIFY=true` → open HTML → verify:
   - Album art thumbnails appear on cards (or placeholder for tracks without Spotify match)
   - Genre tags display as chips below the confidence badge
   - BPM and key display next to genre tags (e.g., "128.0 BPM · Cm")
   - "Preview" button appears on tracks with preview URLs; clicking plays 30s audio
   - Clicking again stops playback; only one preview plays at a time
   - "⋯" button expands detection details (count, span, density bar)
   - Drag a track card up/down to reorder; track numbers update; refresh preserves order
   - "Reset Order" button restores original order
2. Process with `ENABLE_SPOTIFY=false` → verify cards render cleanly without art/preview/genres/BPM (no broken images, no empty spaces)
3. Check JSON output includes all new fields (`spotify_album_art`, `spotify_preview_url`, `spotify_genres`, `spotify_bpm`, `spotify_key`)
4. Test mobile view → album art hidden, layout still clean, drag still works via touch
5. Verify no extra API calls for same artist (genre cache working)
6. Verify audio features batch call works (check for 100+ track sets)
