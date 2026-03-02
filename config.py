"""Configuration management for the setlist generator."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    """Application configuration."""
    
    # API Keys
    SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID', '')
    SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET', '')
    SPOTIFY_REDIRECT_URI = os.getenv('SPOTIFY_REDIRECT_URI', 'http://127.0.0.1:8888/callback')
    DISCOGS_TOKEN = os.getenv('DISCOGS_TOKEN', '')
    DISCOGS_CONSUMER_KEY = os.getenv('DISCOGS_CONSUMER_KEY', '')
    DISCOGS_CONSUMER_SECRET = os.getenv('DISCOGS_CONSUMER_SECRET', '')

    # DJ Set Discovery Settings
    DISCOVERY_RESULTS_PER_QUERY = int(os.getenv('DISCOVERY_RESULTS_PER_QUERY', '20'))
    MIN_SET_DURATION_MINUTES = int(os.getenv('MIN_SET_DURATION_MINUTES', '20'))
    MAX_SETS_PER_ARTIST = int(os.getenv('MAX_SETS_PER_ARTIST', '0'))  # 0 = no limit
    
    # Feature Toggles
    ENABLE_SPOTIFY = os.getenv('ENABLE_SPOTIFY', 'true').lower() == 'true'
    ENABLE_YOUTUBE = os.getenv('ENABLE_YOUTUBE', 'true').lower() == 'true'
    ENABLE_DISCOGS = os.getenv('ENABLE_DISCOGS', 'false').lower() == 'true'
    ENABLE_SPOTIFY_PLAYLISTS = os.getenv('ENABLE_SPOTIFY_PLAYLISTS', 'true').lower() == 'true'
    AUTO_CREATE_SPOTIFY_PLAYLIST = os.getenv('AUTO_CREATE_SPOTIFY_PLAYLIST', 'false').lower() == 'true'
    CREATE_SET_PLAYLISTS = os.getenv('CREATE_SET_PLAYLISTS', 'true').lower() == 'true'
    ENABLE_HTML_OUTPUT = os.getenv('ENABLE_HTML_OUTPUT', 'true').lower() == 'true'

    # Notifications (ntfy.sh)
    NTFY_TOPIC = os.getenv('NTFY_TOPIC', '')  # Set to your ntfy topic to enable notifications

    # Recognition Settings
    SEGMENT_DURATION = int(os.getenv('SEGMENT_DURATION', '30'))
    SEGMENT_OVERLAP = int(os.getenv('SEGMENT_OVERLAP', '15'))
    MIN_CONFIDENCE_THRESHOLD = int(os.getenv('MIN_CONFIDENCE_THRESHOLD', '8'))
    
    # Crash Recovery Settings
    ENABLE_CHECKPOINTS = os.getenv('ENABLE_CHECKPOINTS', 'true').lower() == 'true'
    CHECKPOINT_INTERVAL = int(os.getenv('CHECKPOINT_INTERVAL', '10'))
    
    # Shazam Recognition Settings
    RECOGNITION_TIMEOUT = int(os.getenv('RECOGNITION_TIMEOUT', '15'))
    BASE_DELAY = float(os.getenv('BASE_DELAY', '0.3'))  # Delay between requests

    # Retry Settings (for 429 rate limit handling with JitterRetry)
    MAX_RETRIES = int(os.getenv('MAX_RETRIES', '5'))
    MAX_BACKOFF_DELAY = float(os.getenv('MAX_BACKOFF_DELAY', '30.0'))  # Max backoff cap
    JITTER_INTERVAL_SIZE = float(os.getenv('JITTER_INTERVAL_SIZE', '4.0'))  # Random jitter range is (0, size^2)

    # Concurrency Settings
    CONCURRENT_RECOGNITIONS = int(os.getenv('CONCURRENT_RECOGNITIONS', '5'))  # Number of parallel requests
    BATCH_SIZE = int(os.getenv('BATCH_SIZE', '20'))  # Segments per batch for checkpointing

    # Quota-Aware Throttling Settings
    QUOTA_COOLDOWN_DURATION = int(os.getenv('QUOTA_COOLDOWN_DURATION', '180'))  # Seconds to wait when quota exhausted
    
    # Cleanup Settings
    CLEANUP_TEMP_FILES = os.getenv('CLEANUP_TEMP_FILES', 'true').lower() == 'true'
    CLEANUP_CHECKPOINTS = os.getenv('CLEANUP_CHECKPOINTS', 'true').lower() == 'true'
    
    # Advanced Clustering Settings
    MIN_CLUSTER_SIZE = int(os.getenv('MIN_CLUSTER_SIZE', '3'))
    MIN_CLUSTER_DENSITY = float(os.getenv('MIN_CLUSTER_DENSITY', '0.25'))
    MIN_UNKNOWN_GAP_SIZE = int(os.getenv('MIN_UNKNOWN_GAP_SIZE', '6'))

    # Temporal Overlap Resolution
    OVERLAP_RESOLUTION_ENABLED = os.getenv('OVERLAP_RESOLUTION_ENABLED', 'true').lower() == 'true'
    OVERLAP_THRESHOLD = float(os.getenv('OVERLAP_THRESHOLD', '0.3'))

    # Base Paths (changed from TEMP_DIR to ASSETS_DIR)
    ASSETS_DIR = Path('assets')
    OUTPUT_DIR = Path('output')
    CHECKPOINT_DIR = Path('checkpoints')
    
    @classmethod
    def validate(cls):
        """Validate configuration and return status."""
        issues = []
        
        if cls.ENABLE_SPOTIFY and (not cls.SPOTIFY_CLIENT_ID or not cls.SPOTIFY_CLIENT_SECRET):
            issues.append("Spotify enabled but credentials missing")
        
        if cls.ENABLE_DISCOGS and not cls.DISCOGS_TOKEN and not (cls.DISCOGS_CONSUMER_KEY and cls.DISCOGS_CONSUMER_SECRET):
            issues.append("Discogs enabled but credentials missing (set DISCOGS_TOKEN or DISCOGS_CONSUMER_KEY + DISCOGS_CONSUMER_SECRET)")

        return issues
    
    @classmethod
    def ensure_directories(cls):
        """Create necessary base directories."""
        cls.ASSETS_DIR.mkdir(exist_ok=True)
        cls.OUTPUT_DIR.mkdir(exist_ok=True)
        cls.CHECKPOINT_DIR.mkdir(exist_ok=True)
    
