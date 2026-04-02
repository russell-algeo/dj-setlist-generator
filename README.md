# DJ Set Setlist Generator

Automatically generate setlists from DJ mixes on YouTube or SoundCloud, complete with Spotify/YouTube/Discogs links.

## Features

- Download audio from YouTube and SoundCloud
- Automatic track recognition using Shazam
- DJ artist discovery mode — pass a DJ name and auto-discover all their recorded sets
- Curated artist mode — hand-pick URLs for a named artist (for sets discovery missed or obscure artists)
- Multiple confidence levels (HIGH/MEDIUM/LOW) based on detection count and density
- Handles unknown/unrecognized tracks
- Spotify/YouTube/Discogs link enrichment (toggleable)
- YouTube and SoundCloud timestamp deep-links
- Crash recovery with automatic checkpointing
- Outputs in JSON, Markdown, and interactive HTML formats
- Explorer UI — redesigned liquid glass master index, artist pages, and set detail views with search, sort, and facet filtering
- Artist profile images fetched from Spotify and Discogs, validated via genre overlap
- Resume from where you left off after crashes
- Push notifications via ntfy.sh (optional)

## Installation

### 1. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 2. Install FFmpeg

- **macOS:** `brew install ffmpeg`
- **Ubuntu/Debian:** `sudo apt-get install ffmpeg`
- **Windows:** Download from [ffmpeg.org](https://ffmpeg.org/download.html)

### 3. Configure API credentials

Copy the example environment file and fill in your credentials:
```bash
cp .env.example .env
```

Edit `.env` and add your credentials:

#### Spotify (Required for Spotify links)
Get credentials from: https://developer.spotify.com/dashboard
- Create an app
- Copy Client ID and Client Secret
- Add to `.env`

#### Discogs (Optional)
Get credentials from: https://www.discogs.com/settings/developers
- Option A: Generate a personal access token → set `DISCOGS_TOKEN`
- Option B: Create an OAuth app → set `DISCOGS_CONSUMER_KEY` + `DISCOGS_CONSUMER_SECRET`

## GitHub Actions YouTube Auth

The current CI bootstrap path uses direct runner egress plus authenticated yt-dlp requests:

- `YOUTUBE_COOKIES_B64`: Base64-encoded Netscape cookie export from a burner YouTube account
- `YOUTUBE_USER_AGENT`: matching browser user agent from the same session
- `GH_PAT`: optional fine-grained token with repo secrets write access so CI can rotate `YOUTUBE_COOKIES_B64` after a successful run
- `PROCESS_SET_MAX_ACTIVE_RUNS`: app-side cap for how many `process-set` workflow runs may be active at once (default `10`)

`process-set` now runs without the WARP proxy by default. On March 28, 2026, direct-egress bootstrap succeeded on three development test runs for:

- `https://www.youtube.com/watch?v=UOhLcspytqo`
- `https://www.youtube.com/watch?v=5Ud1afYDzFU`
- `https://youtu.be/3CCFIMrPpDY?si=X6QGDK7yfi554xW4`

If YouTube bot-detection starts failing again in GitHub-hosted runners, re-add WARP to the `bootstrap` job in `.github/workflows/process-set.yml`:

```yaml
services:
  warp:
    image: ghcr.io/mon-ius/docker-warp-socks:v5
    ports:
      - 9091:9091
    options: >-
      --health-cmd "curl -fsSx socks5h://127.0.0.1:9091 https://cloudflare.com/cdn-cgi/trace | grep -q warp=on"
      --health-interval 10s
      --health-timeout 5s
      --health-start-period 30s
      --health-retries 6
```

Then set the bootstrap step proxy env:

```yaml
- name: Bootstrap set run
  env:
    HTTPS_PROXY: socks5h://localhost:9091
  run: python -m worker.jobs.process_set --phase bootstrap --set-run-id "${{ github.event.inputs.set_run_id }}"
```

## Usage

### Process a single URL
```bash
python main.py "https://www.youtube.com/watch?v=xxxxx"
```

### Process multiple URLs
```bash
python main.py "url1" "url2" "url3"
```

### Artist discovery mode — find and process all sets by a DJ
```bash
python main.py "Dyed Soundorom"
```

### Multiple artists
```bash
python main.py "Artist One" "Artist Two"
```

### Curated artist mode — hand-picked URLs for a named artist
```bash
python main.py --artist "Dyed Soundorom" --sets "url1" "url2"
```

Outputs nest under the artist directory (same as discovery mode). If the artist already has sets from a previous discovery run, the new sets are added and the artist summary is regenerated to include everything.

### Force restart (ignore checkpoints)
```bash
python main.py "https://www.youtube.com/watch?v=xxxxx" --no-resume
```

## Crash Recovery

The tool automatically saves progress as it runs — after each batch of segments is recognized and after the download completes.

If the script crashes or you interrupt it (Ctrl+C):

1. Simply run the same command again
2. It will automatically resume from the last saved batch
3. It will skip already-completed work and continue from where it left off

Example:
```bash
# First run - crashes mid-recognition
python main.py "https://www.youtube.com/watch?v=xxxxx"

# Second run - automatically resumes
python main.py "https://www.youtube.com/watch?v=xxxxx"
```

Checkpoints are stored in the `checkpoints/` directory and are automatically cleaned up after successful completion.

## Configuration

Edit `.env` to customize behavior:

### Feature Toggles
```bash
ENABLE_SPOTIFY=true                   # Spotify link enrichment (requires API credentials)
ENABLE_YOUTUBE=true                   # YouTube link enrichment (no API key needed!)
ENABLE_DISCOGS=false                  # Discogs link enrichment (requires token)
ENABLE_SPOTIFY_PLAYLISTS=true         # Enable Spotify playlist creation
AUTO_CREATE_SPOTIFY_PLAYLIST=false    # Skip prompt, auto-create playlist
CREATE_SET_PLAYLISTS=true             # Set to false to skip per-set playlists; artist playlist still gets populated
ENABLE_HTML_OUTPUT=true               # Generate interactive HTML setlist
```

### Artist Profile Settings
```bash
ARTIST_IMAGE_MIN_GENRE_OVERLAP=0.2    # Minimum genre overlap ratio to accept an artist profile image (0.0–1.0)
```

### Notifications (ntfy.sh)
```bash
NTFY_TOPIC=                           # Set to your ntfy.sh topic to enable push notifications
```

### Artist Discovery Settings
```bash
DISCOVERY_RESULTS_PER_QUERY=20        # Results fetched per search query
MIN_SET_DURATION_MINUTES=20           # Minimum set duration to include
MAX_SETS_PER_ARTIST=0                 # Max sets per artist (0 = no limit)
```

### Recognition Settings
```bash
SEGMENT_DURATION=30           # Seconds per recognition segment
SEGMENT_OVERLAP=15            # Overlap between segments (catches transitions)
MIN_CONFIDENCE_THRESHOLD=8    # Detection count threshold for confidence scoring
```

### Crash Recovery Settings
```bash
ENABLE_CHECKPOINTS=true       # Enable crash recovery
CHECKPOINT_INTERVAL=10        # Save progress every N recognitions
```

### Shazam Recognition Settings
```bash
RECOGNITION_TIMEOUT=15        # Seconds before timeout per segment
BASE_DELAY=0.3                # Random delay range (0 to BASE_DELAY) between requests
```

### Retry Settings (JitterRetry for 429 handling)
```bash
MAX_RETRIES=5                 # Retry attempts before giving up
MAX_BACKOFF_DELAY=30          # Maximum backoff cap in seconds
JITTER_INTERVAL_SIZE=4.0      # Random jitter range is (0, size^2) seconds
```

### Concurrency Settings
```bash
CONCURRENT_RECOGNITIONS=5     # Number of parallel Shazam requests
BATCH_SIZE=20                 # Segments processed per checkpoint
```

### Quota Throttling
```bash
QUOTA_COOLDOWN_DURATION=180   # Seconds to pause when rate limited (default: 3 min)
```

### Cleanup Settings
```bash
CLEANUP_TEMP_FILES=true       # Delete downloaded audio after completion
CLEANUP_CHECKPOINTS=true      # Delete checkpoint files after completion
```

### False-Positive Suppression
- Known bad tracks live in `false_positive_rules.json` at the project root.
- `setlist_builder.py` loads that file and removes any matching clustered track before overlap resolution.
- Matching prefers `shazam_track_id`; if no ID rule matches, it falls back to normalized `artist` + `title`.
- Checkpoints remain raw: Shazam hits still get saved there, and suppression only affects setlist building and downstream outputs.

## Output

The tool generates three files per set in the `output/` directory:

### 1. JSON file
Structured data with all track information and metadata.

### 2. Markdown file
Human-readable setlist with timestamps and clickable links.

### 3. HTML file
Interactive setlist using the explorer UI: embedded YouTube/SoundCloud player, clickable mix timeline, track cards with timestamp deep-links, search, sort (timeline, BPM, artist, confidence), facet filtering by genre/label, compact density toggle, and a floating playback pill. Open in any browser.

Example markdown output:

    # DJ Set Name

    **By:** DJ Name
    **Duration:** 1:30:00

    ## Tracklist

    ### 1. Artist - Track Name 🟢
    **Time:** 0:00 – 6:30
    **Confidence:** HIGH (15 detections)
    **Links:** [Spotify](https://...) • [YouTube](https://...) • [Discogs](https://...)

## Confidence Levels

Confidence is calculated from detection count and cluster density:

- 🟢 **HIGH** - 15+ detections, or 10+ detections, or 8+ detections with high density
- 🟡 **MEDIUM** - 5+ detections with high density, or 3+ detections with very high density
- 🟠 **LOW** - Fewer detections or sparse recognition pattern
- ⚪ **UNCERTAIN** - Unknown track / unrecognized gap

## How It Works

1. **Download** audio and convert to MP3
2. **Stream: Segment + Recognize** — FFmpeg extracts segments on-the-fly (no full-file RAM load); each batch is recognized via Shazam in parallel, then segment files are immediately deleted. Only `BATCH_SIZE` (~20) segment files exist on disk at any time
3. **Save checkpoints** after each batch
4. **Build setlist** — cluster and deduplicate detections, suppress known false positives, resolve overlaps, fill gaps with Unknown Track entries
5. **Enrich and output** — add Spotify/YouTube/Discogs links, save JSON, Markdown, and HTML files

## Artist Discovery Mode

Pass a DJ name instead of a URL to auto-discover and process all their recorded sets:

```bash
python main.py "Dyed Soundorom"
```

The tool will:
1. Search YouTube and SoundCloud for recorded sets (Boiler Room, HOR, Cercle, etc.)
2. Filter by minimum duration (`MIN_SET_DURATION_MINUTES`)
3. Process each set through the full pipeline
4. Generate a combined artist summary (`artist_summary.md`, `artist_summary.html`)

Limit the number of sets processed with `MAX_SETS_PER_ARTIST` in `.env`.

## Utility Scripts

### backfill_html.py
Regenerate HTML files from existing JSON outputs (useful after HTML changes, or for sets processed before HTML output was added):

```bash
python backfill_html.py                 # Regenerate all outputs
python backfill_html.py "Jay Tripwire"  # Regenerate one artist by name
python backfill_html.py --dry-run       # Preview without writing
```

### backfill_enrichment.py
Re-enrich existing JSON outputs with metadata from Spotify, ReccoBeats, and Discogs (useful after adding new API credentials or when enrichment sources have been updated):

```bash
python backfill_enrichment.py                           # Re-enrich all outputs
python backfill_enrichment.py "Jay Tripwire"            # Re-enrich one artist
python backfill_enrichment.py --dry-run                  # Preview without writing
python backfill_enrichment.py --set-artist-profiles-only # Only backfill set-level artist profile metadata
```

### master_summary.py
Generate a master summary page (`output/index.html`) across all artists. Called automatically after each artist/curated run, but can also be run manually:

```bash
python master_summary.py                # Generate output/index.html
```

### Web archive staging and deploy
The Next.js app serves checked-in HTML from `apps/web/public`, not the git-ignored `output/` directory. After regenerating any archive HTML in `output/`, restage the public artifacts before deploying:

```bash
python3 backfill_html.py --master       # or regenerate other output/*.html files first
APP_BASE_URL=https://dj-setlist-generator.vercel.app pnpm --filter web archive:stage
```

Notes:
- `output/` is git-ignored, so a Git-triggered Vercel build will not see local backfilled files unless the staged `apps/web/public` artifacts are updated and committed.
- `pnpm --filter web archive:stage` rewrites social preview metadata on every staged HTML file. If `APP_BASE_URL` is missing, it will fall back to root-relative social URLs and create a large diff across `apps/web/public/**/*.html`.
- Deploy using the existing Vercel project configured for `apps/web` (`dj-setlist-generator`). Do not run `vercel` from the repository root, or Vercel may create a separate root-level project by mistake.

## File Structure

    setlist-generator/
    ├── .env.example               # Template configuration (copy to .env)
    ├── .env                      # Your configuration (git-ignored)
    ├── requirements.txt          # Python dependencies
    ├── README.md                 # This file
    ├── main.py                   # Main entry point
    ├── config.py                 # Configuration management
    ├── checkpoint_manager.py     # Crash recovery system
    ├── audio_downloader.py       # Download audio from YouTube/SoundCloud
    ├── audio_segmenter.py        # FFmpeg-based segment extraction (streaming)
    ├── track_recognizer.py       # Shazam recognition with streaming batch pipeline
    ├── setlist_builder.py        # Build setlist from recognitions
    ├── metadata_enricher.py      # Fetch Spotify/YouTube/Discogs links
    ├── output_formatter.py       # Generate JSON and Markdown outputs
    ├── explorer_formatter.py     # Generate explorer master index HTML
    ├── artist_explorer_formatter.py # Generate explorer artist-level detail HTML
    ├── set_explorer_formatter.py # Generate explorer set-level detail HTML
    ├── detail_explorer_common.py # Shared CSS and utilities for explorer views
    ├── detail_explorer_theme.py  # Theme definitions for explorer UI
    ├── spotify_playlist_creator.py # Create Spotify playlist from setlist
    ├── dj_set_discovery.py       # Discover DJ sets via yt-dlp search
    ├── artist_summary.py         # Generate artist-level summary across all sets
    ├── master_summary.py         # Generate master index page across all artists
    ├── notifier.py               # Push notifications via ntfy.sh
    ├── backfill_html.py          # Regenerate HTML from existing JSON outputs
    ├── backfill_enrichment.py    # Re-enrich JSON outputs with metadata
    ├── assets/                   # Downloaded audio (segment files are transient)
    ├── checkpoints/              # Crash recovery checkpoints
    └── output/                   # Generated setlists and summaries
        ├── index.html            # Master summary across all artists
        ├── <artist_name>/        # Artist-level directory (discovery/curated modes)
        │   ├── artist_summary.*  # Aggregate analysis (md, json, html)
        │   └── <mix_name>/       # Per-set output (json, md, html)
        └── <mix_name>/           # Per-set output (URL mode, no artist)
