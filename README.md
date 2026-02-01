# DJ Set Setlist Generator

Automatically generate setlists from DJ mixes on YouTube or SoundCloud, complete with Spotify/YouTube/Discogs links.

## Features

- 🎵 Download audio from YouTube and SoundCloud
- 🔍 Automatic track recognition using Shazam
- 📊 Confidence scoring (HIGH/MEDIUM/LOW) based on multiple detections
- 🎯 Handles unknown/unrecognized tracks
- 🔗 Spotify/YouTube/Discogs link enrichment (toggleable)
- 💾 Crash recovery with automatic checkpointing
- 📄 Outputs in JSON and Markdown formats
- ⚡ Resume from where you left off after crashes

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

Edit `.env` and add your credentials:

#### Spotify (Required for Spotify links)
Get credentials from: https://developer.spotify.com/dashboard
- Create an app
- Copy Client ID and Client Secret
- Add to `.env`

#### Discogs (Optional)
Get token from: https://www.discogs.com/settings/developers
- Generate a personal access token
- Add to `.env`

## Usage

### Basic usage (with crash recovery)
```bash
python main.py "https://www.youtube.com/watch?v=xxxxx"
```

### With custom output name
```bash
python main.py "https://www.youtube.com/watch?v=xxxxx" my_favorite_mix
```

### Force restart (ignore checkpoints)
```bash
python main.py "https://www.youtube.com/watch?v=xxxxx" --no-resume
```

## Crash Recovery

The tool automatically saves progress as it runs:

- **Every 10 recognitions** (configurable)
- **After downloading** audio
- **After segmenting** audio
- **During recognition** phase

If the script crashes or you interrupt it (Ctrl+C):

1. Simply run the same command again
2. It will ask if you want to resume
3. It will skip already-completed work
4. It will continue from where it left off

Example:
```bash
# First run - crashes after 164 segments
python main.py "https://www.youtube.com/watch?v=xxxxx"

# Second run - automatically resumes from segment 165
python main.py "https://www.youtube.com/watch?v=xxxxx"
```

Checkpoints are stored in the `checkpoints/` directory and are automatically cleaned up after successful completion.

## Configuration

Edit `.env` to customize behavior:

### Feature Toggles
```bash
ENABLE_SPOTIFY=true      # Spotify link enrichment (requires API credentials)
ENABLE_YOUTUBE=true      # YouTube link enrichment (no API key needed!)
ENABLE_DISCOGS=false     # Discogs link enrichment (requires token)
```

### Recognition Settings
```bash
SEGMENT_DURATION=30           # Seconds per recognition segment
SEGMENT_OVERLAP=15            # Overlap between segments (catches transitions)
MIN_CONFIDENCE_THRESHOLD=2    # Detections needed for HIGH confidence
```

### Crash Recovery Settings
```bash
ENABLE_CHECKPOINTS=true       # Enable crash recovery
CHECKPOINT_INTERVAL=10        # Save progress every N recognitions
```

### Shazam Recognition Settings
```bash
RECOGNITION_TIMEOUT=30        # Seconds before timeout per segment
MAX_RETRIES=3                 # Retry attempts on timeout/error
BASE_DELAY=1.0                # Seconds between successful recognitions
BACKOFF_DELAY=5.0             # Seconds to wait after errors before retry
```

## Output

The tool generates two files in the `output/` directory:

### 1. JSON file
Structured data with all track information and metadata

### 2. Markdown file
Human-readable setlist with timestamps and clickable links

Example markdown output:

    # DJ Set Name
    
    **By:** DJ Name
    **Duration:** 60:00
    
    ## Tracklist
    
    ### 1. Artist - Track Name 🟢
    **Time:** 0:00
    **Confidence:** HIGH (5 detections)
    **Links:** [Spotify](https://...) • [YouTube](https://...) • [Discogs](https://...)

## Confidence Levels

The tool uses multiple detections to determine track confidence:

- 🟢 **HIGH** - 3+ consecutive detections (very reliable)
- 🟡 **MEDIUM** - 2 consecutive detections (likely correct)
- 🟠 **LOW** - 1 detection only (uncertain)
- ⚪ **UNCERTAIN** - Unknown track or conflicting results

Confidence is based on how many consecutive 30-second segments recognized the same track. More detections = higher confidence.

## How It Works

1. **Download** audio and convert to MP3
2. **Segment** into 30-second overlapping chunks (15-second overlap)
3. **Recognize** each segment using Shazam API
4. **Save checkpoints** every 10 recognitions
5. **Deduplicate** consecutive same-track detections
6. **Calculate confidence** based on detection count
7. **Enrich** with metadata from enabled platforms (Spotify/YouTube/Discogs)
8. **Output** formatted JSON and Markdown files

## File Structure

    setlist-generator/
    ├── .env                      # Your configuration (create from .env.example)
    ├── .env.example              # Example configuration
    ├── requirements.txt          # Python dependencies
    ├── README.md                 # This file
    ├── main.py                   # Main entry point
    ├── config.py                 # Configuration management
    ├── checkpoint_manager.py     # Crash recovery system
    ├── audio_downloader.py       # Download audio from YouTube/SoundCloud
    ├── audio_segmenter.py        # Split audio into segments
    ├── track_recognizer.py       # Shazam recognition with retry logic
    ├── setlist_builder.py        # Build setlist from recognitions
    ├── metadata_enricher.py      # Fetch Spotify/YouTube/Discogs links
    ├── output_formatter.py       # Generate JSON and Markdown outputs
    ├── temp/                     # Temporary audio and segment files
    ├── checkpoints/              # Crash recovery checkpoints
    └── output/                   # Generated setlists (JSON and Markdown)
