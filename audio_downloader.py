"""Audio download and normalization."""

import os
import time
from pathlib import Path

import yt_dlp

from config import Config
from source_url_normalizer import resolve_canonical_source_url


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

    def _is_youtube_url(self, url: str) -> bool:
        lowered = url.lower()
        return "youtube.com" in lowered or "youtu.be" in lowered or "music.youtube.com" in lowered

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
                print(f"Retry attempt {attempt}/{MAX_BOT_RETRIES}...")
            try:
                return fn()
            except Exception as error:
                if not self._is_bot_detection_error(error):
                    raise
                if attempt >= MAX_BOT_RETRIES:
                    print(f"YouTube bot detection persisted after {MAX_BOT_RETRIES} attempts")
                    raise
                print(f"YouTube bot detection triggered. Cooling down for {Config.QUOTA_COOLDOWN_DURATION}s...")
                time.sleep(Config.QUOTA_COOLDOWN_DURATION)

    def _apply_auth_ydl_opts(self, ydl_opts: dict) -> dict:
        if proxy := os.environ.get("HTTPS_PROXY"):
            ydl_opts["proxy"] = proxy

        if cookie_file := os.environ.get("YTDLP_COOKIE_FILE"):
            ydl_opts["cookiefile"] = cookie_file

        if user_agent := os.environ.get("YTDLP_USER_AGENT"):
            headers = dict(ydl_opts.get("http_headers") or {})
            headers["User-Agent"] = user_agent
            ydl_opts["http_headers"] = headers

        return ydl_opts

    def _log_yt_dlp_config(self, operation: str, ydl_opts: dict) -> None:
        headers = ydl_opts.get("http_headers") or {}
        print(
            "yt-dlp config "
            f"operation={operation} "
            f"proxy={ydl_opts.get('proxy') or 'none'} "
            f"cookiefile={'set' if ydl_opts.get('cookiefile') else 'none'} "
            f"user_agent={'set' if headers.get('User-Agent') else 'none'}"
        )

    def download(self, url: str, output_path: Path = None) -> Path:
        """
        Download audio from URL and convert to MP3.

        Args:
            url: YouTube or SoundCloud URL
            output_path: Specific path to save to (if None, saves as mix.mp3 in assets_dir)

        Returns:
            Path to downloaded MP3 file
        """
        source_url = resolve_canonical_source_url(url)

        if output_path is None:
            output_path = self.assets_dir / "mix.mp3"

        if output_path.exists():
            print(f"Audio file already exists: {output_path}")
            return output_path

        output_template = str(output_path.with_suffix(""))
        ydl_opts = self._apply_auth_ydl_opts(
            {
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
                "outtmpl": output_template,
                "quiet": False,
                "no_warnings": False,
                "verbose": True,
            }
        )

        print(f"Downloading audio from: {source_url}")
        self._log_yt_dlp_config("download", ydl_opts)

        def _do_download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([source_url])

        if self._is_youtube_url(source_url):
            self._run_with_bot_retry(_do_download)
        else:
            _do_download()

        print(f"Download complete: {output_path}")
        return output_path

    def get_video_info(self, url: str) -> dict:
        """
        Get video metadata without downloading.

        Returns:
            Dictionary with title, duration, uploader, etc.
        """
        source_url = resolve_canonical_source_url(url)
        ydl_opts = self._apply_auth_ydl_opts(
            {
                "quiet": True,
                "no_warnings": True,
                "verbose": True,
            }
        )
        self._log_yt_dlp_config("extract_info", ydl_opts)

        def _do_extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Raw extraction avoids format resolution during bootstrap metadata lookup.
                return ydl.extract_info(source_url, download=False, process=False)

        info = self._run_with_bot_retry(_do_extract) if self._is_youtube_url(source_url) else _do_extract()
        canonical_url = resolve_canonical_source_url(
            info.get("webpage_url") or info.get("original_url") or source_url
        )
        return {
            "title": info.get("title", "Unknown"),
            "duration": info.get("duration", 0),
            "uploader": info.get("uploader", "Unknown"),
            "url": canonical_url,
        }
