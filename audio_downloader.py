"""Audio download and normalization."""

import os
import time
import yt_dlp
from pathlib import Path
from config import Config

MAX_BOT_RETRIES = 10

class AudioDownloader:
    """Download audio from YouTube or SoundCloud."""
    
    def __init__(self, checkpoint_manager=None):
        """
        Initialize downloader.

        Args:
            checkpoint_manager: CheckpointManager instance. If None, falls back to Config.ASSETS_DIR.
        """
        self.assets_dir = checkpoint_manager.assets_dir if checkpoint_manager else Config.ASSETS_DIR
        self.assets_dir.mkdir(parents=True, exist_ok=True)

    def _youtube_extractor_args(self) -> dict[str, dict[str, list[str]]]:
        """Configure yt-dlp for the current WARP + mweb + browser-backed PO token experiment."""
        extractor_args: dict[str, dict[str, list[str]]] = {
            "youtube": {
                "player_client": ["mweb"],
                "fetch_pot": ["always"],
                "pot_trace": ["true"],
                "jsc_trace": ["true"],
            },
        }
        if browser_path := os.environ.get("YTDLP_BROWSER_PATH"):
            extractor_args["youtubepot-wpc"] = {
                "browser_path": [browser_path],
            }
        return extractor_args

    def _log_yt_dlp_config(self, operation: str, ydl_opts: dict) -> None:
        """Emit the yt-dlp knobs that matter for YouTube auth experiments."""
        extractor_args = ydl_opts.get("extractor_args") or {}
        youtube_args = extractor_args.get("youtube") or {}
        wpc_args = extractor_args.get("youtubepot-wpc") or {}
        print(
            "yt-dlp config "
            f"operation={operation} "
            f"proxy={ydl_opts.get('proxy') or 'none'} "
            f"cookiefile={'set' if ydl_opts.get('cookiefile') else 'none'} "
            f"player_client={','.join(youtube_args.get('player_client', [])) or 'default'} "
            f"fetch_pot={','.join(youtube_args.get('fetch_pot', [])) or 'default'} "
            f"pot_trace={','.join(youtube_args.get('pot_trace', [])) or 'default'} "
            f"jsc_trace={','.join(youtube_args.get('jsc_trace', [])) or 'default'} "
            f"wpc_browser_path={','.join(wpc_args.get('browser_path', [])) or 'auto'}"
        )

    def _is_bot_detection_error(self, error: Exception) -> bool:
        """Check if error is YouTube's bot detection."""
        error_str = str(error).lower()
        return (
            "sign in to confirm you're not a bot" in error_str
            or ("cookies" in error_str and "authentication" in error_str)
        )

    def _run_with_bot_retry(self, fn):
        """Run fn(), retrying up to MAX_BOT_RETRIES times on YouTube bot detection."""
        for attempt in range(1, MAX_BOT_RETRIES + 1):
            if attempt > 1:
                print(f"🔄 Retry attempt {attempt}/{MAX_BOT_RETRIES}...")
            try:
                return fn()
            except Exception as e:
                if self._is_bot_detection_error(e):
                    if attempt >= MAX_BOT_RETRIES:
                        print(f"🤖 YouTube bot detection persists after {MAX_BOT_RETRIES} attempts. Giving up.")
                        raise
                    print(f"🤖 YouTube bot detection triggered. Cooling down for {Config.QUOTA_COOLDOWN_DURATION}s...")
                    time.sleep(Config.QUOTA_COOLDOWN_DURATION)
                else:
                    raise

    def download(self, url: str, output_path: Path = None) -> Path:
        """
        Download audio from URL and convert to MP3.

        Args:
            url: YouTube or SoundCloud URL
            output_path: Specific path to save to (if None, saves as mix.mp3 in assets_dir)

        Returns:
            Path to downloaded MP3 file
        """
        if output_path is None:
            output_path = self.assets_dir / "mix.mp3"
        
        # If file already exists, skip download
        if output_path.exists():
            print(f"✓ Audio file already exists: {output_path}")
            return output_path
        
        output_template = str(output_path.with_suffix(''))
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': output_template,
            'quiet': False,
            'no_warnings': False,
            'verbose': True,
            'extractor_args': self._youtube_extractor_args(),
        }

        if proxy := os.environ.get("HTTPS_PROXY"):
            ydl_opts['proxy'] = proxy

        if cookie_file := os.environ.get("YTDLP_COOKIE_FILE"):
            ydl_opts['cookiefile'] = cookie_file

        print(f"Downloading audio from: {url}")
        self._log_yt_dlp_config("download", ydl_opts)

        def _do_download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

        self._run_with_bot_retry(_do_download)

        print(f"Download complete: {output_path}")
        return output_path
    
    def get_video_info(self, url: str) -> dict:
        """
        Get video metadata without downloading.
        
        Returns:
            Dictionary with title, duration, uploader, etc.
        """
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'verbose': True,
            'extractor_args': self._youtube_extractor_args(),
        }

        if proxy := os.environ.get("HTTPS_PROXY"):
            ydl_opts['proxy'] = proxy

        if cookie_file := os.environ.get("YTDLP_COOKIE_FILE"):
            ydl_opts['cookiefile'] = cookie_file

        self._log_yt_dlp_config("extract_info", ydl_opts)

        def _do_extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)

        info = self._run_with_bot_retry(_do_extract)
        return {
            'title': info.get('title', 'Unknown'),
            'duration': info.get('duration', 0),
            'uploader': info.get('uploader', 'Unknown'),
            'url': url,
        }
