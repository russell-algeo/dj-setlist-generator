"""Audio download and normalization."""

import time
import yt_dlp
from pathlib import Path
from config import Config

class AudioDownloader:
    """Download audio from YouTube or SoundCloud."""
    
    def __init__(self, assets_dir: Path = None):
        """
        Initialize downloader.
        
        Args:
            assets_dir: Directory to save downloaded audio (if None, uses Config.ASSETS_DIR)
        """
        self.assets_dir = assets_dir or Config.ASSETS_DIR
        self.assets_dir.mkdir(parents=True, exist_ok=True)

    def _is_bot_detection_error(self, error: Exception) -> bool:
        """Check if error is YouTube's bot detection."""
        error_str = str(error).lower()
        return (
            "sign in to confirm you're not a bot" in error_str
            or ("cookies" in error_str and "authentication" in error_str)
        )

    def download(self, url: str, output_path: Path = None, output_filename: str = 'mix') -> Path:
        """
        Download audio from URL and convert to MP3.
        
        Args:
            url: YouTube or SoundCloud URL
            output_path: Specific path to save to (if provided)
            output_filename: Name for output file (without extension)
        
        Returns:
            Path to downloaded MP3 file
        """
        if output_path is None:
            output_path = self.assets_dir / f"{output_filename}.mp3"
        
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
        }
        
        print(f"Downloading audio from: {url}")

        attempt = 0
        while True:
            attempt += 1
            if attempt > 1:
                print(f"🔄 Retry attempt {attempt}...")

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                break  # Success - exit loop
            except Exception as e:
                if self._is_bot_detection_error(e):
                    print(f"🤖 YouTube bot detection triggered. Cooling down for {Config.QUOTA_COOLDOWN_DURATION}s...")
                    time.sleep(Config.QUOTA_COOLDOWN_DURATION)
                    continue  # Retry
                else:
                    raise  # Non-bot errors fail immediately

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
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                'title': info.get('title', 'Unknown'),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Unknown'),
                'url': url,
            }