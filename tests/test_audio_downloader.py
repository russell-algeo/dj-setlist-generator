import unittest
from unittest.mock import MagicMock, patch


class BotRetryTests(unittest.TestCase):
    def _make_downloader(self):
        from audio_downloader import AudioDownloader
        d = AudioDownloader.__new__(AudioDownloader)
        d.assets_dir = MagicMock()
        return d

    def test_raises_after_10_bot_detection_attempts(self):
        downloader = self._make_downloader()
        bot_error = Exception("Sign in to confirm you're not a bot")
        fn = MagicMock(side_effect=bot_error)

        with patch("time.sleep"):
            with self.assertRaises(Exception) as ctx:
                downloader._run_with_bot_retry(fn)

        self.assertIn("not a bot", str(ctx.exception))
        self.assertEqual(fn.call_count, 10)

    def test_does_not_retry_non_bot_errors(self):
        downloader = self._make_downloader()
        fn = MagicMock(side_effect=ValueError("some other error"))

        with self.assertRaises(ValueError):
            downloader._run_with_bot_retry(fn)

        self.assertEqual(fn.call_count, 1)

    def test_returns_on_success_before_limit(self):
        downloader = self._make_downloader()
        bot_error = Exception("Sign in to confirm you're not a bot")
        fn = MagicMock(side_effect=[bot_error, bot_error, "result"])

        with patch("time.sleep"):
            result = downloader._run_with_bot_retry(fn)

        self.assertEqual(result, "result")
        self.assertEqual(fn.call_count, 3)


class ProxyInjectionTests(unittest.TestCase):
    def test_download_passes_proxy_to_ydl_opts(self):
        from audio_downloader import AudioDownloader

        with patch.dict("os.environ", {"HTTPS_PROXY": "http://localhost:8080"}):
            with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
                mock_ctx = MagicMock()
                mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ctx)
                mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
                mock_ctx.download = MagicMock()

                d = AudioDownloader.__new__(AudioDownloader)
                d.assets_dir = MagicMock()

                from pathlib import Path
                with patch.object(Path, "exists", return_value=False):
                    with patch.object(Path, "with_suffix", return_value=Path("/tmp/mix")):
                        try:
                            d.download("https://youtube.com/watch?v=test", output_path=Path("/tmp/mix.mp3"))
                        except Exception:
                            pass

                opts_passed = mock_ydl_cls.call_args[0][0]
                self.assertEqual(opts_passed.get("proxy"), "http://localhost:8080")

    def test_download_omits_proxy_when_env_not_set(self):
        from audio_downloader import AudioDownloader
        import os

        with patch.dict("os.environ", {}, clear=True):
            os.environ.pop("HTTPS_PROXY", None)

            with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
                mock_ctx = MagicMock()
                mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ctx)
                mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
                mock_ctx.download = MagicMock()

                d = AudioDownloader.__new__(AudioDownloader)
                d.assets_dir = MagicMock()

                from pathlib import Path
                with patch.object(Path, "exists", return_value=False):
                    with patch.object(Path, "with_suffix", return_value=Path("/tmp/mix")):
                        try:
                            d.download("https://youtube.com/watch?v=test", output_path=Path("/tmp/mix.mp3"))
                        except Exception:
                            pass

                opts_passed = mock_ydl_cls.call_args[0][0]
                self.assertNotIn("proxy", opts_passed)

    def test_download_passes_cookiefile_and_user_agent(self):
        from audio_downloader import AudioDownloader

        env = {
            "YTDLP_COOKIE_FILE": "/tmp/yt-cookies.txt",
            "YTDLP_USER_AGENT": "Mozilla/5.0 test-agent",
        }

        with patch.dict("os.environ", env, clear=True):
            with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
                mock_ctx = MagicMock()
                mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ctx)
                mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)
                mock_ctx.download = MagicMock()

                d = AudioDownloader.__new__(AudioDownloader)
                d.assets_dir = MagicMock()

                from pathlib import Path

                with patch.object(Path, "exists", return_value=False):
                    with patch.object(Path, "with_suffix", return_value=Path("/tmp/mix")):
                        d.download("https://youtube.com/watch?v=test", output_path=Path("/tmp/mix.mp3"))

                opts_passed = mock_ydl_cls.call_args[0][0]
                self.assertEqual(opts_passed.get("cookiefile"), "/tmp/yt-cookies.txt")
                self.assertEqual(
                    opts_passed.get("http_headers", {}).get("User-Agent"),
                    "Mozilla/5.0 test-agent",
                )

    def test_get_video_info_passes_proxy_to_ydl_opts(self):
        from audio_downloader import AudioDownloader

        with patch.dict("os.environ", {"HTTPS_PROXY": "http://localhost:8080"}):
            with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
                mock_ctx = MagicMock()
                mock_ctx.extract_info = MagicMock(return_value={
                    "title": "Test", "duration": 3600, "uploader": "DJ Test"
                })
                mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ctx)
                mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)

                d = AudioDownloader.__new__(AudioDownloader)
                d.assets_dir = MagicMock()
                d.get_video_info("https://youtube.com/watch?v=test")

                opts_passed = mock_ydl_cls.call_args[0][0]
                self.assertEqual(opts_passed.get("proxy"), "http://localhost:8080")
                mock_ctx.extract_info.assert_called_once_with(
                    "https://youtube.com/watch?v=test",
                    download=False,
                    process=False,
                )

    def test_get_video_info_passes_cookiefile_and_user_agent(self):
        from audio_downloader import AudioDownloader

        env = {
            "YTDLP_COOKIE_FILE": "/tmp/yt-cookies.txt",
            "YTDLP_USER_AGENT": "Mozilla/5.0 test-agent",
        }

        with patch.dict("os.environ", env, clear=True):
            with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
                mock_ctx = MagicMock()
                mock_ctx.extract_info = MagicMock(
                    return_value={"title": "Test", "duration": 3600, "uploader": "DJ Test"}
                )
                mock_ydl_cls.return_value.__enter__ = MagicMock(return_value=mock_ctx)
                mock_ydl_cls.return_value.__exit__ = MagicMock(return_value=False)

                d = AudioDownloader.__new__(AudioDownloader)
                d.assets_dir = MagicMock()
                d.get_video_info("https://youtube.com/watch?v=test")

                opts_passed = mock_ydl_cls.call_args[0][0]
                self.assertEqual(opts_passed.get("cookiefile"), "/tmp/yt-cookies.txt")
                self.assertEqual(
                    opts_passed.get("http_headers", {}).get("User-Agent"),
                    "Mozilla/5.0 test-agent",
                )
                mock_ctx.extract_info.assert_called_once_with(
                    "https://youtube.com/watch?v=test",
                    download=False,
                    process=False,
                )


if __name__ == "__main__":
    unittest.main()
