# Feature 03: Enhanced Spotify Integration in HTML

## Context

Currently, the HTML output has a "Spotify" button per track that opens the Spotify track page in a new tab. Playlist creation happens only via the CLI (`spotify_playlist_creator.py`). This feature adds in-page Spotify playlist creation — users can select tracks and create a playlist directly from the HTML page using the Spotify Web API.

## Goal

- **Per-track "Add to Spotify"**: One-click button on each track card to add that individual track to the user's Liked Songs or a default playlist
- **Bulk "Create Playlist from Selection"**: Checkboxes on each track, "Select All" / "Deselect All", and a "Create Spotify Playlist" button
- Uses Spotify's OAuth PKCE flow (client-side, no server needed) for authorization
- Show creation progress and result (playlist URL)
- **Spotify embed player**: For tracks with Spotify URLs, optionally embed the Spotify track player as an alternative audio source (small inline widget)

## Files to Modify

- **`html_formatter.py`** — add selection UI, Spotify auth flow JS, and playlist creation logic
- **`config.py`** — expose `SPOTIFY_CLIENT_ID` to the HTML (needed for OAuth)

## Existing Code Understanding

### Current Spotify Auth (spotify_playlist_creator.py)
Uses `spotipy.SpotifyOAuth` with `playlist-modify-public playlist-modify-private` scope, server-side flow with redirect URI `http://127.0.0.1:8888/callback`. This is a server-side flow that won't work in a static HTML file.

### Spotify Client ID
Available as `Config.SPOTIFY_CLIENT_ID` from `config.py` (line 14). This is a **public** client ID (safe to embed in HTML — it's not a secret). The client secret must NOT be embedded.

### Current Track Card HTML (html_formatter.py:66-137)
Each card has a grid layout with `.track-actions` div containing platform buttons.

### Track Data
Each track dict includes `spotify_url` (e.g., `https://open.spotify.com/track/7a5BhcK...`). The track ID can be extracted from this URL by splitting on `/` and `?`.

## Implementation Plan

### Step 1: Add Spotify Client ID to HTML

In `save_setlist_html()`, inject the Spotify client ID as a JS constant:

```javascript
const SPOTIFY_CLIENT_ID = 'CLIENT_ID_HERE';
```

Read from `Config.SPOTIFY_CLIENT_ID` in `html_formatter.py`. Only inject if the value is non-empty and at least one track has a `spotify_url`.

### Step 2: Add Track Selection Checkboxes

In `_render_track_cards()`, add a checkbox to each track card that has a `spotify_url`:

```html
<input type="checkbox" class="track-select" data-spotify-id="TRACK_ID" checked>
```

Extract the track ID from the spotify_url: `url.split('/')[-1].split('?')[0]`

CSS:
```css
.track-select {
  accent-color: #1db954;
  width: 16px;
  height: 16px;
  cursor: pointer;
  flex-shrink: 0;
}
```

Place the checkbox as the first element in `.track-actions`, before the platform buttons.

For tracks without a Spotify URL, don't render a checkbox.

### Step 3: Selection Controls Bar

Add a new control bar below the existing search/filter controls:

```html
<div class="playlist-controls" id="playlistControls">
  <div class="select-controls">
    <button class="btn btn-select" onclick="selectAll()">Select All</button>
    <button class="btn btn-select" onclick="deselectAll()">Deselect All</button>
    <span class="select-count" id="selectCount">0 tracks selected</span>
  </div>
  <button class="btn btn-create-playlist" id="createPlaylistBtn" onclick="startPlaylistCreation()">
    🎵 Create Spotify Playlist
  </button>
</div>
```

Only render this bar if `SPOTIFY_CLIENT_ID` is available and at least one track has a Spotify URL.

CSS:
```css
.playlist-controls {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 20px;
  padding: 12px 16px;
  background: #161616;
  border: 1px solid #222;
  border-radius: 8px;
}
.select-controls { display: flex; gap: 8px; align-items: center; }
.select-count { font-size: 12px; color: #888; }
.btn-select { color: #888; border-color: #333; }
.btn-create-playlist {
  color: #1db954;
  border-color: #1db954;
  font-size: 13px;
  padding: 8px 16px;
}
.btn-create-playlist:hover { background: #1db954; color: #000; }
```

### Step 4: Selection JS

```javascript
function selectAll() {
  document.querySelectorAll('.track-select').forEach(cb => cb.checked = true);
  updateSelectCount();
}
function deselectAll() {
  document.querySelectorAll('.track-select').forEach(cb => cb.checked = false);
  updateSelectCount();
}
function updateSelectCount() {
  const count = document.querySelectorAll('.track-select:checked').length;
  document.getElementById('selectCount').textContent = count + ' track' + (count !== 1 ? 's' : '') + ' selected';
}
// Update count when any checkbox changes
document.addEventListener('change', function(e) {
  if (e.target.classList.contains('track-select')) updateSelectCount();
});
// Initial count
updateSelectCount();
```

### Step 5: Spotify OAuth PKCE Flow (Client-Side)

This is the core complexity. Spotify supports the **Authorization Code with PKCE** flow for public clients (no client secret needed). The flow is:

1. Generate a `code_verifier` (random string) and `code_challenge` (SHA-256 hash of verifier, base64url encoded)
2. Redirect to Spotify auth URL with the challenge
3. User approves → Spotify redirects back with an `auth_code`
4. Exchange `auth_code` + `code_verifier` for an `access_token`

**Problem:** The redirect comes back to a URL. For a local HTML file opened via `file://`, the redirect URI won't work easily.

**Solution:** Use a **popup window** approach:
1. Open Spotify auth in a popup
2. Set redirect URI to a simple page that captures the code and sends it back via `window.opener.postMessage()`
3. Since we're generating self-contained HTML, we can set the redirect URI to a data URL or use Spotify's built-in redirect to `http://localhost` and capture it

**Simpler alternative:** Use the **Implicit Grant** flow (deprecated but simpler — returns token directly in URL fragment, no code exchange needed). However, Spotify is phasing this out.

**Recommended approach — PKCE with popup:**

```javascript
async function startPlaylistCreation() {
  const selected = getSelectedTrackIds();
  if (selected.length === 0) { alert('No tracks selected'); return; }

  // Check if we already have a valid token
  let token = sessionStorage.getItem('spotify_token');
  if (!token) {
    token = await authorizeSpotify();
    if (!token) return;
    sessionStorage.setItem('spotify_token', token);
  }

  await createPlaylist(token, selected);
}

async function authorizeSpotify() {
  const verifier = generateRandomString(128);
  const challenge = await sha256base64url(verifier);

  const params = new URLSearchParams({
    client_id: SPOTIFY_CLIENT_ID,
    response_type: 'code',
    redirect_uri: 'http://127.0.0.1:8888/callback',
    scope: 'playlist-modify-public playlist-modify-private',
    code_challenge_method: 'S256',
    code_challenge: challenge,
  });

  const authUrl = 'https://accounts.spotify.com/authorize?' + params.toString();

  // Open auth popup
  const popup = window.open(authUrl, 'spotify-auth', 'width=500,height=700');

  // Wait for redirect with code
  const code = await waitForAuthCode(popup);
  if (!code) return null;

  // Exchange code for token
  const tokenResponse = await fetch('https://accounts.spotify.com/api/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: SPOTIFY_CLIENT_ID,
      grant_type: 'authorization_code',
      code: code,
      redirect_uri: 'http://127.0.0.1:8888/callback',
      code_verifier: verifier,
    }),
  });

  const data = await tokenResponse.json();
  return data.access_token;
}

function waitForAuthCode(popup) {
  return new Promise((resolve) => {
    const interval = setInterval(() => {
      try {
        if (popup.closed) { clearInterval(interval); resolve(null); return; }
        const url = popup.location.href;
        if (url.startsWith('http://127.0.0.1:8888/callback')) {
          const code = new URL(url).searchParams.get('code');
          popup.close();
          clearInterval(interval);
          resolve(code);
        }
      } catch (e) { /* cross-origin, keep waiting */ }
    }, 500);
  });
}
```

**Helper functions:**
```javascript
function generateRandomString(length) {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  return Array.from(crypto.getRandomValues(new Uint8Array(length)))
    .map(x => chars[x % chars.length]).join('');
}

async function sha256base64url(plain) {
  const encoder = new TextEncoder();
  const data = encoder.encode(plain);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return btoa(String.fromCharCode(...new Uint8Array(digest)))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
```

### Step 6: Create Playlist via Spotify Web API

```javascript
async function createPlaylist(token, trackIds) {
  const btn = document.getElementById('createPlaylistBtn');
  btn.textContent = 'Creating...';
  btn.disabled = true;

  try {
    // Get user ID
    const meResp = await fetch('https://api.spotify.com/v1/me', {
      headers: { 'Authorization': 'Bearer ' + token }
    });
    const me = await meResp.json();

    // Create playlist
    const title = document.querySelector('.header h1').textContent;
    const createResp = await fetch('https://api.spotify.com/v1/users/' + me.id + '/playlists', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        name: title,
        description: 'Generated from DJ set setlist',
        public: false
      })
    });
    const playlist = await createResp.json();

    // Add tracks in batches of 100
    const uris = trackIds.map(id => 'spotify:track:' + id);
    for (let i = 0; i < uris.length; i += 100) {
      await fetch('https://api.spotify.com/v1/playlists/' + playlist.id + '/tracks', {
        method: 'POST',
        headers: {
          'Authorization': 'Bearer ' + token,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ uris: uris.slice(i, i + 100) })
      });
    }

    // Show success
    showPlaylistResult(playlist.external_urls.spotify, trackIds.length);

  } catch (e) {
    alert('Failed to create playlist: ' + e.message);
  } finally {
    btn.textContent = '🎵 Create Spotify Playlist';
    btn.disabled = false;
  }
}

function showPlaylistResult(url, count) {
  const container = document.getElementById('playlistControls');
  const result = document.createElement('div');
  result.className = 'playlist-result';
  result.innerHTML = '✓ Playlist created with ' + count + ' tracks! ' +
    '<a href="' + url + '" target="_blank" style="color:#1db954;">Open in Spotify →</a>';
  container.appendChild(result);
}
```

### Step 7: Helper to Get Selected Track IDs

```javascript
function getSelectedTrackIds() {
  return Array.from(document.querySelectorAll('.track-select:checked'))
    .map(cb => cb.dataset.spotifyId);
}
```

### Step 8: Per-Track "Add to Spotify" Button

In addition to checkboxes for bulk selection, add a per-track button that adds that single track to the user's Liked Songs (uses the `user-library-modify` scope).

**Update the OAuth scope** to include `user-library-modify`:
```javascript
scope: 'playlist-modify-public playlist-modify-private user-library-modify',
```

**Add button to each track card** (in `.track-actions`, next to the existing Spotify link button):
```html
<button class="btn btn-add-spotify" onclick="addToSpotify(this, 'TRACK_ID')" data-spotify-id="TRACK_ID" title="Save to Liked Songs">
  + Save
</button>
```

Only render for tracks with a `spotify_url`.

**JS handler:**
```javascript
async function addToSpotify(btn, trackId) {
  let token = sessionStorage.getItem('spotify_token');
  if (!token) {
    token = await authorizeSpotify();
    if (!token) return;
    sessionStorage.setItem('spotify_token', token);
  }

  btn.textContent = '...';
  btn.disabled = true;
  try {
    const resp = await fetch('https://api.spotify.com/v1/me/tracks', {
      method: 'PUT',
      headers: {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ ids: [trackId] })
    });
    if (resp.ok) {
      btn.textContent = '✓ Saved';
      btn.classList.add('btn-add-spotify--saved');
    } else {
      btn.textContent = '✗ Error';
    }
  } catch (e) {
    btn.textContent = '✗ Error';
  }
}
```

**CSS:**
```css
.btn-add-spotify { color: #1db954; border-color: #1db954; font-size: 10px; padding: 3px 8px; }
.btn-add-spotify--saved { background: #1db954; color: #000; border-color: #1db954; cursor: default; }
```

### Step 9: Spotify Embed Player Widget

For each track with a Spotify URL, add an optional inline Spotify embed player. This serves as an alternative audio preview — fuller than the 30-second preview from Feature 02.

**Spotify provides an embed iframe:**
```html
<iframe style="border-radius:12px"
  src="https://open.spotify.com/embed/track/TRACK_ID?utm_source=generator&theme=0"
  width="100%" height="80" frameBorder="0"
  allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
  loading="lazy">
</iframe>
```

**Implementation:** Don't embed all players at once (too heavy). Instead, add a "▶ Spotify Player" toggle button per card. Clicking it lazily injects the iframe below the track card:

```javascript
function toggleSpotifyEmbed(btn, trackId) {
  const card = btn.closest('.track-card');
  let embed = card.querySelector('.spotify-embed');
  if (embed) {
    embed.remove();
    btn.textContent = '▶ Spotify';
    return;
  }
  embed = document.createElement('div');
  embed.className = 'spotify-embed';
  embed.style.gridColumn = '1 / -1';
  embed.style.marginTop = '8px';
  embed.innerHTML = '<iframe style="border-radius:8px" src="https://open.spotify.com/embed/track/' + trackId + '?utm_source=generator&theme=0" width="100%" height="80" frameBorder="0" allow="autoplay; clipboard-write; encrypted-media" loading="lazy"></iframe>';
  card.appendChild(embed);
  btn.textContent = '✕ Close';
}
```

**CSS:**
```css
.spotify-embed { grid-column: 1 / -1; }
.btn-spotify-embed { color: #1db954; border-color: #1db954; font-size: 10px; }
```

### Step 10: Conditional Rendering

In `save_setlist_html()`, only include the playlist controls and Spotify JS if:
1. `Config.SPOTIFY_CLIENT_ID` is non-empty
2. At least one track in `tracks` has a `spotify_url`

If neither condition is met, skip all playlist-related HTML/JS entirely.

## Security Notes

- Only the `SPOTIFY_CLIENT_ID` is embedded (public, not a secret)
- The `SPOTIFY_CLIENT_SECRET` is NEVER embedded in HTML
- PKCE flow is specifically designed for public clients
- Token stored in `sessionStorage` (cleared when tab closes)
- The redirect URI (`http://127.0.0.1:8888/callback`) must be registered in the Spotify Developer Dashboard (it already is per `config.py` line 16)

## Testing

1. Open a generated HTML with Spotify-enriched tracks
2. Check "Select All" selects all tracks with Spotify URLs, count updates
3. Click "Create Spotify Playlist" → Spotify auth popup should open
4. After authorizing → playlist should be created → success message with link
5. Verify the playlist in Spotify contains the correct tracks in order
6. Click "+ Save" on a single track → should add to Liked Songs → button changes to "✓ Saved"
7. Click "▶ Spotify" on a track → inline Spotify embed player appears below card
8. Click again → embed closes
9. Test with no SPOTIFY_CLIENT_ID → playlist controls, add buttons, and embed toggles should not appear
10. Test with tracks that have no Spotify URLs → no checkboxes, no add button, no embed toggle
11. Verify token persists in sessionStorage for subsequent operations in same tab
12. Verify the OAuth scope includes `user-library-modify` for the save-to-liked feature
