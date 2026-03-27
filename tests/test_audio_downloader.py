import time
import unittest
from unittest.mock import MagicMock, patch, call


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


if __name__ == "__main__":
    unittest.main()
