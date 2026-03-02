# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DJ Set Setlist Generator - automatically generates setlists from DJ mixes on YouTube/SoundCloud using Shazam for track recognition. Outputs JSON and Markdown with Spotify/YouTube/Discogs links, and can create a Spotify playlist from the recognized tracks.

Supports three modes:
- **URL mode**: Pass YouTube/SoundCloud URLs directly for processing
- **Artist discovery mode**: Pass a DJ name and the tool uses yt-dlp to search YouTube and SoundCloud directly for all their recorded sets, then processes each one
- **Curated artist mode**: Pass hand-picked URLs for a named artist using `--artist` + `--sets` flags. Useful for adding sets that discovery missed, or for obscure artists where search isn't effective. Outputs nest under the artist directory and the artist summary is regenerated.

## Commands

```bash
# Artist discovery mode - find and process all sets by a DJ
python main.py "Dyed Soundorom"

# Multiple artists (processed sequentially)
python main.py "Artist One" "Artist Two"

# Basic usage (single URL)
python main.py "https://www.youtube.com/watch?v=xxxxx"

# Multiple URLs (processed sequentially)
python main.py "url1" "url2" "url3"

# Force restart (ignore checkpoints)
python main.py "https://www.youtube.com/watch?v=xxxxx" --no-resume

# Multiple URLs without resume
python main.py "url1" "url2" "url3" --no-resume

# Curated artist mode - hand-picked URLs filed under an artist
python main.py --artist "Dyed Soundorom" --sets "url1" "url2"

# Curated artist mode without resume
python main.py --artist "Dyed Soundorom" --sets "url1" "url2" --no-resume
```

**Prerequisites**:
- FFmpeg must be installed (`brew install ffmpeg` on macOS)
- yt-dlp must be installed (`pip install yt-dlp`)

## Architecture

### Pipeline Flow (main.py)

**Artist Discovery Mode** (when given a DJ name):
1. **Discover** - `dj_set_discovery.py` uses yt-dlp search to find all YouTube/SoundCloud URLs
2. **Process** - Each discovered URL goes through the standard pipeline below
3. **Summarize** - `artist_summary.py` generates aggregate analysis across all sets

**Standard Pipeline** (per URL):
1. **Download** - `audio_downloader.py` uses yt-dlp to fetch audio
2. **Stream: Segment + Recognize** - `audio_segmenter.py` + `track_recognizer.py` work in a batch pipeline: each batch of segments is extracted on-the-fly via FFmpeg (no full-file RAM load), recognized with Shazam (Semaphore + asyncio.gather), then segment files are deleted immediately — only `BATCH_SIZE` segment files exist on disk at any time
3. **Build Setlist** - `setlist_builder.py` clusters and deduplicates detections
4. **Enrich** - `metadata_enricher.py` adds Spotify/YouTube/Discogs links; fetches BPM and key from ReccoBeats
5. **Output** - `output_formatter.py` generates JSON and Markdown; `html_formatter.py` generates an interactive HTML setlist (if `ENABLE_HTML_OUTPUT=true`) — all saved to `output/<mix_name>/`
6. **Spotify Playlist** (optional) - `spotify_playlist_creator.py` creates a Spotify playlist from tracks with Spotify URLs (prompts for confirmation unless `AUTO_CREATE_SPOTIFY_PLAYLIST=true`)
7. **Notify** (optional) - `notifier.py` sends a push notification via ntfy.sh when a set completes (if `NTFY_TOPIC` is configured)

**Curated Artist Mode** (when given `--artist` + `--sets`):
1. **Skip discovery** - Uses the hand-picked URLs directly
2. **Process** - Each URL goes through the standard pipeline, nested under the artist directory
3. **Summarize** - `artist_summary.py` regenerates the aggregate analysis (includes old + new sets)

**Utility scripts:**
- `backfill_html.py` - Regenerate HTML files from existing JSON outputs (e.g. after HTML changes or for sets processed before HTML output was added). Accepts an optional artist name argument or `--dry-run`.
- `backfill_enrichment.py` - Re-enrich existing JSON outputs with metadata from Spotify, ReccoBeats, and Discogs. Accepts an optional artist name argument or `--dry-run`.
- `master_summary.py` - Generate `output/index.html`, a master summary page across all artists. Called automatically after each artist run.

### DJ Set Discovery (dj_set_discovery.py)
Uses yt-dlp to search YouTube (`ytsearch`) and SoundCloud (`scsearch`) directly with multiple query strategies (generic searches, known DJ set channels like Boiler Room, HOR Berlin, Cercle, etc.). Results are filtered by duration (>= `MIN_SET_DURATION_MINUTES`) and title keywords to exclude non-sets. Results are cached to `checkpoints/<artist>/discovery.json` during processing and cleaned up after completion (controlled by `CLEANUP_CHECKPOINTS`).

### Core Algorithm (setlist_builder.py)
The setlist building uses a clustering approach:
- Groups all detections of the same track (by `artist|title|shazam_id`)
- Resolves temporal overlaps using scoring: `detection_count * 2.0 + density * 20.0` (span excluded to prevent scattered detections from winning)
- Filters noise based on detection count and density thresholds
- Adds "Unknown Track" entries for unrecognized gaps (configurable via `MIN_UNKNOWN_GAP_SIZE`)

### Checkpoint System (checkpoint_manager.py)
Saves progress during long recognition runs. Checkpoints stored in `checkpoints/<mix_name>/`. Valid stages: `downloaded` → `recognizing` (updated after each batch) → `recognized` → `completed`.

## Configuration

All settings in `.env` file (see `config.py` for defaults):
- **API credentials**: `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `DISCOGS_TOKEN` (or OAuth: `DISCOGS_CONSUMER_KEY` + `DISCOGS_CONSUMER_SECRET`)
- **Discovery**: `DISCOVERY_RESULTS_PER_QUERY` (default: `20`), `MIN_SET_DURATION_MINUTES` (default: `20`), `MAX_SETS_PER_ARTIST` (limit sets per artist; replaces the old `--max-sets` CLI flag)
- **Feature toggles**: `ENABLE_SPOTIFY`, `ENABLE_YOUTUBE`, `ENABLE_DISCOGS`, `ENABLE_SPOTIFY_PLAYLISTS`, `AUTO_CREATE_SPOTIFY_PLAYLIST`, `CREATE_SET_PLAYLISTS` (set to `false` to skip per-set playlists while still populating the artist playlist), `ENABLE_HTML_OUTPUT`
- **Notifications**: `NTFY_TOPIC` (ntfy.sh topic; leave empty to disable)
- **Recognition**: `SEGMENT_DURATION`, `SEGMENT_OVERLAP`, `RECOGNITION_TIMEOUT`, `BASE_DELAY`
- **Retry (JitterRetry)**: `MAX_RETRIES`, `MAX_BACKOFF_DELAY`, `JITTER_INTERVAL_SIZE`
- **Concurrency**: `CONCURRENT_RECOGNITIONS` (parallel requests), `BATCH_SIZE` (segments per checkpoint)
- **Quota throttling**: `QUOTA_COOLDOWN_DURATION` (pause duration when rate limited)
- **Clustering**: `MIN_CLUSTER_SIZE`, `MIN_CLUSTER_DENSITY`, `MIN_UNKNOWN_GAP_SIZE`
- **Overlap resolution**: `OVERLAP_RESOLUTION_ENABLED`, `OVERLAP_THRESHOLD`
- **Cleanup**: `CLEANUP_TEMP_FILES`, `CLEANUP_CHECKPOINTS`

## Git Workflow

- **Never commit design docs** (e.g. `docs/plans/`) unless explicitly asked. Writing a design doc is a planning artifact — it stays local until the user says to commit it.
- Only commit code changes when the user explicitly requests a commit.

## Directory Structure

**URL mode** (`python main.py "https://..."`)
- `assets/<mix_name>/` - Downloaded audio (segment files are transient; deleted after each batch)
- `checkpoints/<mix_name>/` - Crash recovery state
- `output/<mix_name>/` - Final JSON, Markdown, and HTML output

**Artist mode** (`python main.py "DJ Name"`) and **curated mode** (`--artist` + `--sets`) - everything nested under artist:
- `assets/<artist_name>/<mix_name>/` - Downloaded audio (segment files are transient)
- `checkpoints/<artist_name>/discovery.json` - Cached discovery results (cleaned up after processing; discovery mode only)
- `checkpoints/<artist_name>/<mix_name>/` - Per-set crash recovery state
- `output/<artist_name>/artist_summary.md` - Aggregate analysis across all sets
- `output/<artist_name>/artist_summary.json` - Machine-readable aggregate data
- `output/<artist_name>/artist_summary.html` - Interactive HTML artist summary page
- `output/<artist_name>/<mix_name>/` - Per-set JSON, Markdown, and HTML output

**Master summary:**
- `output/index.html` - Overview page across all artists (auto-generated after each artist/curated run)
