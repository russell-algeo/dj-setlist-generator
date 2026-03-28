"""Audio download and normalization."""

import os
import yt_dlp
from pathlib import Path
from config import Config


YOUTUBE_CLIENT_STRATEGIES = (
    {"name": "default", "player_clients": None},
    {"name": "tv_android", "player_clients": ("tv", "android")},
    {"name": "android_sdkless_web", "player_clients": ("android_sdkless", "web")},
    {"name": "android_only", "player_clients": ("android",)},
    {"name": "android_sdkless_only", "player_clients": ("android_sdkless",)},
    {"name": "tv_only", "player_clients": ("tv",)},
    {"name": "tv_simply_only", "player_clients": ("tv_simply",)},
    {"name": "tv_downgraded_only", "player_clients": ("tv_downgraded",)},
    {"name": "tv_embedded_only", "player_clients": ("tv_embedded",)},
    {"name": "web_only", "player_clients": ("web",)},
    {"name": "web_safari_only", "player_clients": ("web_safari",)},
    {"name": "web_embedded_only", "player_clients": ("web_embedded",)},
    {"name": "web_music_only", "player_clients": ("web_music",)},
    {"name": "web_creator_only", "player_clients": ("web_creator",)},
    {"name": "ios_only", "player_clients": ("ios",)},
    {"name": "android_vr_only", "player_clients": ("android_vr",)},
    {"name": "mweb_only", "player_clients": ("mweb",)},
)

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
        self._preferred_youtube_strategy_name: str | None = None

    def _youtube_client_strategy_sequence(self) -> list[dict[str, tuple[str, ...] | str | None]]:
        """Prioritize the last successful strategy, then exhaust the documented client list."""
        strategies = [dict(strategy) for strategy in YOUTUBE_CLIENT_STRATEGIES]
        if not self._preferred_youtube_strategy_name:
            return strategies

        prioritized: list[dict[str, tuple[str, ...] | str | None]] = []
        for strategy in strategies:
            if strategy["name"] == self._preferred_youtube_strategy_name:
                prioritized.append(strategy)
                break
        prioritized.extend(
            strategy
            for strategy in strategies
            if strategy["name"] != self._preferred_youtube_strategy_name
        )
        return prioritized

    def _youtube_extractor_args(self, strategy: dict[str, tuple[str, ...] | str | None]) -> dict[str, dict[str, list[str]]]:
        """Build yt-dlp extractor args for one client strategy."""
        youtube_args = {
            "pot_trace": ["true"],
            "jsc_trace": ["true"],
        }
        player_clients = strategy.get("player_clients")
        if player_clients:
            youtube_args["player_client"] = list(player_clients)
        return {"youtube": youtube_args}

    def _log_yt_dlp_config(
        self,
        operation: str,
        ydl_opts: dict,
        strategy: dict[str, tuple[str, ...] | str | None],
        attempt_index: int,
        total_attempts: int,
    ) -> None:
        """Emit the yt-dlp knobs that matter for YouTube auth experiments."""
        extractor_args = ydl_opts.get("extractor_args") or {}
        youtube_args = extractor_args.get("youtube") or {}
        player_clients = ",".join(youtube_args.get("player_client", [])) or "default"
        print(
            "yt-dlp config "
            f"operation={operation} "
            f"strategy={strategy['name']} "
            f"attempt={attempt_index}/{total_attempts} "
            f"proxy={ydl_opts.get('proxy') or 'none'} "
            f"cookiefile={'set' if ydl_opts.get('cookiefile') else 'none'} "
            f"player_client={player_clients} "
            f"pot_trace={','.join(youtube_args.get('pot_trace', [])) or 'default'} "
            f"jsc_trace={','.join(youtube_args.get('jsc_trace', [])) or 'default'}"
        )

    def _is_bot_detection_error(self, error: Exception) -> bool:
        """Check if error is YouTube's bot detection."""
        error_str = str(error).lower()
        return (
            "sign in to confirm you're not a bot" in error_str
            or ("cookies" in error_str and "authentication" in error_str)
        )

    def _is_youtube_url(self, url: str) -> bool:
        lowered = url.lower()
        return "youtube.com" in lowered or "youtu.be" in lowered or "music.youtube.com" in lowered

    def _should_try_next_youtube_strategy(self, error: Exception) -> bool:
        """Continue trying documented clients only for extractor/client/auth failures."""
        error_str = str(error).lower()
        retryable_fragments = (
            "sign in to confirm you're not a bot",
            "login_required",
            "playability status",
            "no video formats found",
            "requested format is not available",
            "unplayable",
            "unsupported client",
            "po token",
            "visitor data",
            "this content isn't available",
            "this video is unavailable",
            "age-restricted",
            "members-only",
            "premium",
        )
        return any(fragment in error_str for fragment in retryable_fragments)

    def _summarize_error(self, error: Exception) -> str:
        summary = " ".join(str(error).split())
        if len(summary) > 220:
            return f"{summary[:217]}..."
        return summary

    def _run_with_youtube_client_strategies(self, operation: str, base_ydl_opts: dict, fn, *, probe_all: bool = False):
        """Try documented YouTube client strategies and log the outcome of each attempt."""
        strategies = self._youtube_client_strategy_sequence()
        results: list[tuple[str, str, str]] = []
        last_error: Exception | None = None
        first_success_result = None
        first_success_strategy_name: str | None = None

        for attempt_index, strategy in enumerate(strategies, start=1):
            ydl_opts = dict(base_ydl_opts)
            ydl_opts["extractor_args"] = self._youtube_extractor_args(strategy)
            self._log_yt_dlp_config(operation, ydl_opts, strategy, attempt_index, len(strategies))

            try:
                result = fn(ydl_opts)
                strategy_name = str(strategy["name"])
                results.append((strategy_name, "success", "ok"))
                print(
                    f"yt-dlp strategy result operation={operation} "
                    f"strategy={strategy_name} status=success"
                )
                if first_success_result is None:
                    first_success_result = result
                    first_success_strategy_name = strategy_name
                    self._preferred_youtube_strategy_name = strategy_name
                if not probe_all:
                    if attempt_index > 1:
                        self._log_youtube_strategy_summary(operation, results)
                    return result
            except Exception as error:
                strategy_name = str(strategy["name"])
                summary = self._summarize_error(error)
                results.append((strategy_name, "failed", summary))
                print(
                    f"yt-dlp strategy result operation={operation} "
                    f"strategy={strategy_name} status=failed error={summary}"
                )
                last_error = error
                if probe_all:
                    continue
                if not self._should_try_next_youtube_strategy(error):
                    self._log_youtube_strategy_summary(operation, results)
                    raise

        self._log_youtube_strategy_summary(operation, results)
        if first_success_result is not None:
            assert first_success_strategy_name is not None
            print(
                f"yt-dlp strategy probe selected operation={operation} "
                f"strategy={first_success_strategy_name}"
            )
            return first_success_result
        assert last_error is not None
        raise last_error

    def _log_youtube_strategy_summary(self, operation: str, results: list[tuple[str, str, str]]) -> None:
        print(f"yt-dlp strategy summary operation={operation} total_attempts={len(results)}")
        for strategy_name, status, detail in results:
            print(
                f"yt-dlp strategy summary operation={operation} "
                f"strategy={strategy_name} status={status} detail={detail}"
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
        }

        if proxy := os.environ.get("HTTPS_PROXY"):
            ydl_opts['proxy'] = proxy

        if cookie_file := os.environ.get("YTDLP_COOKIE_FILE"):
            ydl_opts['cookiefile'] = cookie_file

        print(f"Downloading audio from: {url}")

        if self._is_youtube_url(url):
            self._run_with_youtube_client_strategies(
                operation="download",
                base_ydl_opts=ydl_opts,
                fn=lambda options: _run_download_with_options(url, options),
            )
        else:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

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
        }

        if proxy := os.environ.get("HTTPS_PROXY"):
            ydl_opts['proxy'] = proxy

        if cookie_file := os.environ.get("YTDLP_COOKIE_FILE"):
            ydl_opts['cookiefile'] = cookie_file

        def _do_extract(options):
            with yt_dlp.YoutubeDL(options) as ydl:
                return ydl.extract_info(url, download=False)

        if self._is_youtube_url(url):
            info = self._run_with_youtube_client_strategies(
                operation="extract_info",
                base_ydl_opts=ydl_opts,
                fn=_do_extract,
                probe_all=True,
            )
        else:
            info = _do_extract(ydl_opts)
        return {
            'title': info.get('title', 'Unknown'),
            'duration': info.get('duration', 0),
            'uploader': info.get('uploader', 'Unknown'),
            'url': url,
        }


def _run_download_with_options(url: str, ydl_opts: dict) -> None:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
