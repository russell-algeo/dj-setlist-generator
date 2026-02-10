# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DJ Set Setlist Generator - automatically generates setlists from DJ mixes on YouTube/SoundCloud using Shazam for track recognition. Outputs JSON and Markdown with Spotify/YouTube/Discogs links, and can create a Spotify playlist from the recognized tracks.

Supports two modes:
- **URL mode**: Pass YouTube/SoundCloud URLs directly for processing
- **Artist discovery mode**: Pass a DJ name and the tool uses Claude API with web search to discover all their recorded sets, then processes each one

## Commands

```bash
# Artist discovery mode - find and process all sets by a DJ
python main.py "Dyed Soundorom"

# Limit number of sets to process
python main.py "Peggy Gou" --max-sets 5

# Basic usage (single URL)
python main.py "https://www.youtube.com/watch?v=xxxxx"

# Multiple URLs (processed sequentially)
python main.py "url1" "url2" "url3"

# Force restart (ignore checkpoints)
python main.py "https://www.youtube.com/watch?v=xxxxx" --no-resume

# Multiple URLs without resume
python main.py "url1" "url2" "url3" --no-resume
```

**Prerequisites**:
- FFmpeg must be installed (`brew install ffmpeg` on macOS)
- `ANTHROPIC_API_KEY` in `.env` (required for artist discovery mode)

## Architecture

### Pipeline Flow (main.py)

**Artist Discovery Mode** (when given a DJ name):
1. **Discover** - `dj_set_discovery.py` uses Claude API + web search to find all YouTube/SoundCloud URLs
2. **Process** - Each discovered URL goes through the standard pipeline below
3. **Summarize** - `artist_summary.py` generates aggregate analysis across all sets

**Standard Pipeline** (per URL):
1. **Download** - `audio_downloader.py` uses yt-dlp to fetch audio
2. **Segment** - `audio_segmenter.py` splits into 30-second overlapping chunks (15s overlap)
3. **Recognize** - `track_recognizer.py` uses shazamio (Shazam API) with concurrent processing (Semaphore + asyncio.gather)
4. **Build Setlist** - `setlist_builder.py` clusters and deduplicates detections
5. **Enrich** - `metadata_enricher.py` adds Spotify/YouTube/Discogs links
6. **Output** - `output_formatter.py` generates JSON and Markdown in `output/<mix_name>/`
7. **Spotify Playlist** (optional) - `spotify_playlist_creator.py` creates a Spotify playlist from tracks with Spotify URLs (prompts for confirmation unless `AUTO_CREATE_SPOTIFY_PLAYLIST=true`)

### DJ Set Discovery (dj_set_discovery.py)
Uses the Anthropic Python SDK to call Claude with the `web_search` tool. Claude intelligently searches across multiple platforms (YouTube, SoundCloud) and known DJ set channels (Boiler Room, HOR Berlin, Cercle, etc.) to find all recorded sets by a given artist. Results are cached to `checkpoints/<artist>/discovery.json` so re-runs don't repeat the search.

### Core Algorithm (setlist_builder.py)
The setlist building uses a clustering approach:
- Groups all detections of the same track (by `artist|title|shazam_id`)
- Resolves temporal overlaps using scoring: `detection_count * 2.0 + density * 20.0` (span excluded to prevent scattered detections from winning)
- Filters noise based on detection count and density thresholds
- Adds "Unknown Track" entries for unrecognized gaps (configurable via `MIN_UNKNOWN_GAP_SIZE`)

### Checkpoint System (checkpoint_manager.py)
Saves progress during long recognition runs. Checkpoints stored in `checkpoints/<mix_name>/`. Process can resume from any stage: `downloaded`, `segmented`, or `recognizing`.

## Configuration

All settings in `.env` file (see `config.py` for defaults):
- **API credentials**: `ANTHROPIC_API_KEY`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `DISCOGS_TOKEN`
- **Discovery**: `DISCOVERY_MODEL` (default: `claude-opus-4-6`), `MAX_SETS_PER_ARTIST`
- **Feature toggles**: `ENABLE_SPOTIFY`, `ENABLE_YOUTUBE`, `ENABLE_DISCOGS`, `ENABLE_SPOTIFY_PLAYLISTS`, `AUTO_CREATE_SPOTIFY_PLAYLIST`
- **Recognition**: `SEGMENT_DURATION`, `SEGMENT_OVERLAP`, `RECOGNITION_TIMEOUT`, `BASE_DELAY`
- **Retry (JitterRetry)**: `MAX_RETRIES`, `BACKOFF_DELAY`, `MAX_BACKOFF_DELAY`, `JITTER_INTERVAL_SIZE`
- **Concurrency**: `CONCURRENT_RECOGNITIONS` (parallel requests), `BATCH_SIZE` (segments per checkpoint)
- **Quota throttling**: `QUOTA_COOLDOWN_DURATION` (pause duration when rate limited)
- **Clustering**: `MIN_CLUSTER_SIZE`, `MIN_CLUSTER_DENSITY`, `MIN_UNKNOWN_GAP_SIZE`
- **Overlap resolution**: `OVERLAP_RESOLUTION_ENABLED`, `OVERLAP_THRESHOLD`

## Directory Structure

- `assets/<mix_name>/` - Downloaded audio and segments (temporary)
- `checkpoints/<mix_name>/` - Crash recovery state
- `checkpoints/<artist_name>/` - Artist-level checkpoints (discovery mode)
  - `discovery.json` - Cached discovery results
- `output/<mix_name>/` - Final JSON and Markdown output per set
- `output/<artist_name>/` - Artist-level output (discovery mode)
  - `artist_summary.md` - Aggregate analysis across all sets
  - `artist_summary.json` - Machine-readable aggregate data
