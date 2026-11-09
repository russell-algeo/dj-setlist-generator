"""Offline regression checks for narrowly scoped Preview bootstrap cookie reuse."""

import ast
from itertools import product
from pathlib import Path
import re
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "russell-algeo/dj-setlist-generator"
PREVIEW_REF = "refs/heads/preview"


def workflow_step(source, name):
    match = re.search(
        rf"^      - name: {re.escape(name)}\n(?:(?!^      - |^  \w).)*",
        source,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise AssertionError(f"Missing workflow step: {name}")
    return match.group()


def condition_matches(step, *, repository=REPOSITORY, ref=PREVIEW_REF,
                      target="development", succeeded=True, cookies="true"):
    """Evaluate only the boolean/string syntax used by these checked-in guards."""
    match = re.search(r"^        if: \$\{\{ (.+) \}\}$", step, re.MULTILINE)
    if not match:
        raise AssertionError("Missing explicit workflow condition")
    expression = match.group(1)
    values = {
        "github.repository": repository,
        "github.ref": ref,
        "github.event.inputs.deployment_target": target,
        "steps.youtube_auth.outputs.cookies_present": cookies,
    }
    for name, value in values.items():
        expression = expression.replace(name, repr(value))
    expression = expression.replace("success()", repr(succeeded))
    tree = ast.parse(expression.replace("&&", " and ").replace("||", " or "), mode="eval")

    def evaluate(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bool)):
            return node.value
        if isinstance(node, ast.BoolOp):
            values = [bool(evaluate(value)) for value in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)
        if (isinstance(node, ast.Compare) and len(node.ops) == 1
                and isinstance(node.ops[0], ast.Eq)):
            return evaluate(node.left) == evaluate(node.comparators[0])
        raise AssertionError(f"Unsupported condition syntax: {ast.dump(node)}")

    # GitHub applies success() implicitly when a step's condition has no status function.
    return succeeded and bool(evaluate(tree.body))


class YouTubeAuthWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.process = (ROOT / ".github/workflows/process-set.yml").read_text()
        cls.discovery = (ROOT / ".github/workflows/discover-artist.yml").read_text()

    def test_preparation_preserves_production_and_allows_only_exact_preview_scope(self):
        step = workflow_step(self.process, "Prepare YouTube auth")
        for repository, ref, target in product(
            [REPOSITORY, "someone/dj-setlist-generator", REPOSITORY + "-fork"],
            [PREVIEW_REF, "refs/heads/remote-deployment", "refs/heads/preview-test",
             "refs/tags/preview", "refs/pull/42/merge", ""],
            ["production", "development", "preview", "", "typo"],
        ):
            with self.subTest(repository=repository, ref=ref, target=target):
                expected = target == "production" or (
                    repository == REPOSITORY and ref == PREVIEW_REF and target == "development"
                )
                self.assertEqual(condition_matches(step, repository=repository, ref=ref,
                                                   target=target), expected)
        self.assertFalse(condition_matches(step, succeeded=False))

    def test_shared_secrets_are_prepared_only_in_bootstrap(self):
        step = workflow_step(self.process, "Prepare YouTube auth")
        self.assertIn("YOUTUBE_COOKIES_B64: ${{ secrets.YOUTUBE_COOKIES_B64 }}", step)
        self.assertIn("YOUTUBE_USER_AGENT: ${{ secrets.YOUTUBE_USER_AGENT }}", step)
        self.assertIn("run: ./.github/scripts/prepare-youtube-auth.sh", step)
        bootstrap, later_jobs = self.process.split("\n  recognize:", 1)
        self.assertIn(step, bootstrap)
        for name in ["YOUTUBE_COOKIES_B64", "YOUTUBE_USER_AGENT", "YTDLP_COOKIE_FILE"]:
            self.assertNotIn(name, later_jobs)
        self.assertEqual(self.process.count("secrets.YOUTUBE_COOKIES_B64"), 1)
        self.assertEqual(self.process.count("secrets.YOUTUBE_USER_AGENT"), 1)
        self.assertIn("            assets\n            .runtime/ffmpeg\n", self.process)
        self.assertNotIn("/tmp/yt-cookies.txt", self.process)

    def test_writeback_and_its_token_remain_production_only_in_both_workflows(self):
        for source in [self.process, self.discovery]:
            step = workflow_step(source, "Persist refreshed YouTube cookies")
            self.assertIn("GH_PAT: ${{ secrets.GH_PAT }}", step)
            self.assertIn("run: ./.github/scripts/persist-youtube-cookies.sh", step)
            self.assertNotIn("secrets.GH_PAT", source.replace(step, ""))
            for target, succeeded, cookies in product(
                ["production", "development", "preview", "", "typo"],
                [True, False], ["true", "false", ""],
            ):
                with self.subTest(target=target, succeeded=succeeded, cookies=cookies):
                    self.assertEqual(condition_matches(step, target=target, succeeded=succeeded,
                                                       cookies=cookies),
                                     target == "production" and succeeded and cookies == "true")

    def test_discovery_preparation_does_not_gain_preview_exception(self):
        step = workflow_step(self.discovery, "Prepare YouTube auth")
        self.assertFalse(condition_matches(step, target="development"))
        self.assertTrue(condition_matches(step, target="production"))

    def test_preview_downloader_uses_same_cookie_and_user_agent_for_metadata_and_audio(self):
        from audio_downloader import AudioDownloader

        # The cookie path and UA are synthetic; YoutubeDL is mocked and no file is read.
        env = {"WORKER_DEPLOYMENT_TARGET": "development",
               "YTDLP_COOKIE_FILE": "/tmp/synthetic-preview-cookies.txt",
               "YTDLP_USER_AGENT": "synthetic-preview-user-agent"}
        downloader = AudioDownloader.__new__(AudioDownloader)
        url = "https://www.youtube.com/watch?v=test"
        with patch.dict("os.environ", env, clear=True), patch("yt_dlp.YoutubeDL") as youtube:
            client = youtube.return_value.__enter__.return_value
            client.extract_info.return_value = {"title": "Synthetic", "duration": 60}
            downloader.get_video_info(url)
            with patch.object(Path, "exists", return_value=False):
                downloader.download(url, output_path=Path("/tmp/synthetic-preview-audio.mp3"))
            self.assertEqual(youtube.call_count, 2)
            for call in youtube.call_args_list:
                options = call.args[0]
                self.assertEqual(options["cookiefile"], env["YTDLP_COOKIE_FILE"])
                self.assertEqual(options["http_headers"]["User-Agent"], env["YTDLP_USER_AGENT"])
            client.extract_info.assert_called_once_with(url, download=False, process=False)
            client.download.assert_called_once_with([url])


if __name__ == "__main__":
    unittest.main()
