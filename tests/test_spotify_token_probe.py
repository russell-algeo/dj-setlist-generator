"""Mock-only diagnostics regressions. These tests never contact Spotify or GitHub."""

import contextlib
import io
import os
from pathlib import Path
import re
import unittest
from unittest.mock import MagicMock, patch

from spotify_playlist_creator import SpotifyPlaylistCreator
from worker import spotify_token_probe as probe


SET_RUN_ID = "00000000-0000-4000-8000-000000000001"
TOKEN = "diagnostic-test-token-never-print"


class SpotifyTokenProbeTests(unittest.TestCase):
    def setUp(self):
        values = {
            "GITHUB_ACTIONS": "true",
            "GITHUB_REPOSITORY": probe.REPOSITORY,
            "GITHUB_REF": probe.PREVIEW_REF,
            "GITHUB_WORKFLOW_REF": f"{probe.REPOSITORY}/.github/workflows/process-set.yml@{probe.PREVIEW_REF}",
            "WORKER_DEPLOYMENT_TARGET": "development",
            "APP_BASE_URL": probe.PREVIEW_ORIGIN,
            "WORKER_EXPECTED_PREVIEW_ORIGIN": probe.PREVIEW_ORIGIN,
            "WORKER_VERCEL_OIDC_AUDIENCE": "https://github.com/russell-algeo",
            "SET_LIST_ACTIVE_SET_RUN_ID": SET_RUN_ID,
            "INTERNAL_WORKER_SHARED_SECRET": "diagnostic-test-internal-secret",
            "ACTIONS_ID_TOKEN_REQUEST_URL": "https://oidc.actions.test/token",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "diagnostic-test-runtime-token",
        }
        env = patch.dict(os.environ, values, clear=True)
        env.start()
        self.addCleanup(env.stop)
        auth = patch("worker.config.load_saved_auth", return_value={})
        auth.start()
        self.addCleanup(auth.stop)

    def test_real_managed_parser_without_constructor_or_spotify_client(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"access_token": TOKEN}
        output = io.StringIO()
        with patch("requests.post", return_value=response) as request, patch(
            "worker.callbacks._open", return_value=io.BytesIO(b'{"value":"test-oidc-token"}')
        ), patch.object(SpotifyPlaylistCreator, "__init__", side_effect=AssertionError("No constructor")), patch(
            "spotify_playlist_creator.spotipy.Spotify", side_effect=AssertionError("No Spotify client")
        ), patch("spotify_playlist_creator.SpotifyOAuth", side_effect=AssertionError("No OAuth")), contextlib.redirect_stdout(output):
            probe.main()
        request.assert_called_once_with(
            probe.PREVIEW_ORIGIN + "/api/internal/spotify-token",
            headers={"x-internal-secret": "diagnostic-test-internal-secret", "x-vercel-trusted-oidc-idp-token": "test-oidc-token"},
            allow_redirects=False,
            json={"setRunId": SET_RUN_ID},
            timeout=30,
        )
        response.json.assert_called_once()
        self.assertIn("callback verified", output.getvalue())
        self.assertNotIn(TOKEN, output.getvalue())

    def test_production_and_wrong_context_rejected_before_any_callback(self):
        invalid = {
            "WORKER_DEPLOYMENT_TARGET": "production",
            "GITHUB_ACTIONS": "false",
            "GITHUB_REPOSITORY": "someone/else",
            "GITHUB_REF": "refs/heads/remote-deployment",
            "GITHUB_WORKFLOW_REF": "another-workflow",
            "APP_BASE_URL": "https://dj-setlist-generator.vercel.app",
            "WORKER_EXPECTED_PREVIEW_ORIGIN": "https://other.example",
            "WORKER_VERCEL_OIDC_AUDIENCE": "https://other.example",
            "SET_LIST_ACTIVE_SET_RUN_ID": "not-a-uuid",
            "SET_LIST_API_BASE_URL": "https://dj-setlist-generator.vercel.app",
            "INTERNAL_WORKER_SHARED_SECRET": "",
        }
        for key, value in invalid.items():
            with self.subTest(key=key), patch.dict(os.environ, {key: value}), patch.object(
                SpotifyPlaylistCreator, "_fetch_managed_access_token"
            ) as fetch:
                with self.assertRaises((RuntimeError, ValueError)):
                    probe.run()
                fetch.assert_not_called()

    def test_malformed_token_fails_real_parser_with_sanitized_message(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"access_token": "bad\ntoken"}
        with patch("requests.post", return_value=response), patch(
            "worker.callbacks._open", return_value=io.BytesIO(b'{"value":"test-oidc-token"}')
        ):
            with self.assertRaises(SystemExit) as failure:
                probe.main()
        self.assertEqual(str(failure.exception), "Preview Spotify token diagnostic failed; response details suppressed")

    def test_provider_exception_never_appears_in_output(self):
        output = io.StringIO()
        error_output = io.StringIO()
        with patch.object(SpotifyPlaylistCreator, "_fetch_managed_access_token", side_effect=RuntimeError(TOKEN)), contextlib.redirect_stdout(output), contextlib.redirect_stderr(error_output):
            with self.assertRaises(SystemExit) as failure:
                probe.main()
        self.assertNotIn(TOKEN, str(failure.exception) + output.getvalue() + error_output.getvalue())

    def test_http_4xx_and_5xx_fail_once_without_stdout_or_stderr_details(self):
        for status in [400, 401, 403, 404, 429, 500, 502, 503]:
            with self.subTest(status=status):
                response = MagicMock(status_code=status)
                response.raise_for_status.side_effect = RuntimeError(f"HTTP {status} {TOKEN}")
                output, error_output = io.StringIO(), io.StringIO()
                with patch("requests.post", return_value=response) as request, patch(
                    "worker.callbacks._open", return_value=io.BytesIO(b'{"value":"test-oidc-token"}')
                ), contextlib.redirect_stdout(output), contextlib.redirect_stderr(error_output):
                    with self.assertRaises(SystemExit) as failure:
                        probe.main()
                request.assert_called_once()
                response.json.assert_not_called()
                self.assertEqual(output.getvalue() + error_output.getvalue(), "")
                self.assertNotIn(TOKEN, str(failure.exception))

    def test_tokenless_response_fails_real_parser_without_response_details(self):
        for payload in [{}, [], {"access_token": None}, {"access_token": ""}, {"access_token": " "}]:
            with self.subTest(payload=payload):
                response = MagicMock(status_code=200)
                response.json.return_value = payload
                output, error_output = io.StringIO(), io.StringIO()
                with patch("requests.post", return_value=response) as request, patch(
                    "worker.callbacks._open", return_value=io.BytesIO(b'{"value":"test-oidc-token"}')
                ), contextlib.redirect_stdout(output), contextlib.redirect_stderr(error_output):
                    with self.assertRaises(SystemExit) as failure:
                        probe.main()
                request.assert_called_once()
                response.json.assert_called_once()
                self.assertEqual(output.getvalue() + error_output.getvalue(), "")
                self.assertEqual(str(failure.exception), "Preview Spotify token diagnostic failed; response details suppressed")


class ProbeWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).resolve().parents[1] / ".github/workflows/process-set.yml").read_text()
        cls.jobs = dict(re.findall(r"^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)", cls.source.split("\njobs:\n", 1)[1], re.MULTILINE | re.DOTALL))

    def condition(self, job, flag, resume, bootstrap):
        expression = re.search(r"^    if: \$\{\{ (.*?) \}\}$", self.jobs[job], re.MULTILINE).group(1)
        for key, value in {
            "github.event.inputs.spotify_token_probe": flag,
            "github.event.inputs.resume_mode": resume,
            "needs.bootstrap.result": bootstrap,
        }.items():
            expression = expression.replace(key, repr(value))
        expression = expression.replace("always()", "True").replace("&&", " and ").replace("||", " or ")
        return eval(expression, {"__builtins__": {}}, {})

    def test_probe_mode_excludes_every_normal_job_for_all_resume_outcomes(self):
        self.assertEqual(set(self.jobs), {"spotify-token-probe", "bootstrap", "recognize", "publish", "finalize"})
        for resume in ["full", "publish_only", ""]:
            for bootstrap in ["success", "failure", "cancelled", "skipped"]:
                self.assertTrue(self.condition("spotify-token-probe", "true", resume, bootstrap))
                for job in ["bootstrap", "recognize", "publish", "finalize"]:
                    with self.subTest(job=job, resume=resume, bootstrap=bootstrap):
                        self.assertFalse(self.condition(job, "true", resume, bootstrap))

    def test_absent_or_false_probe_flag_preserves_all_default_conditions(self):
        for flag in ["", "false"]:
            for resume in ["full", "publish_only", ""]:
                for bootstrap in ["success", "failure", "cancelled", "skipped"]:
                    expected = {"bootstrap": resume != "publish_only", "recognize": resume != "publish_only",
                        "publish": resume == "publish_only" or bootstrap == "success", "finalize": True, "spotify-token-probe": False}
                    for job, should_run in expected.items():
                        self.assertEqual(self.condition(job, flag, resume, bootstrap), should_run)

    def test_probe_is_development_only_has_no_database_or_production_secrets(self):
        job = self.jobs["spotify-token-probe"]
        self.assertIn('"$WORKER_DEPLOYMENT_TARGET" != "development"', job)
        self.assertIn('"$GITHUB_REF" != "refs/heads/preview"', job)
        self.assertLess(job.index("Reject non-Preview diagnostics"), job.index("actions/checkout"))
        self.assertEqual(re.findall(r"secrets\.([A-Z_]+)", job), ["DEVELOPMENT_APP_BASE_URL", "DEVELOPMENT_INTERNAL_WORKER_SHARED_SECRET"])
        self.assertNotIn("DATABASE_URL", job)
        self.assertNotIn("SPOTIFY_CLIENT_SECRET", job)
        self.assertNotIn("worker.jobs.process_set", job)
        self.assertNotIn("/api/internal/finalize", job)
        self.assertIn("id-token: write", job)

    def test_probe_cannot_cancel_normal_job_via_concurrency_group(self):
        self.assertIn("${{ github.event.inputs.spotify_token_probe == 'true' && '-spotify-token-probe' || '' }}", self.source)
        self.assertRegex(self.source, r"spotify_token_probe:\n(?:.*\n){2}        default: false\n        type: boolean")


if __name__ == "__main__":
    unittest.main()
