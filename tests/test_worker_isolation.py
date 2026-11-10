import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from worker.config import get_settings
from worker.db import connect
from worker.isolation import DEVELOPMENT_DATABASE_HOST, validate_database_target


ROOT = Path(__file__).resolve().parents[1]
DEV_URL = f"postgresql://set_list_dev_worker:test-password@{DEVELOPMENT_DATABASE_HOST}/neondb?sslmode=require"


class WorkerIsolationTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"WORKER_DEPLOYMENT_TARGET": "development"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_development_database_identity_is_accepted(self):
        validate_database_target(DEV_URL)

    def test_wrong_database_or_privileged_role_is_rejected_before_connection(self):
        wrong_urls = [
            DEV_URL.replace(DEVELOPMENT_DATABASE_HOST, "ep-rough-dust-a4q90lxc.us-east-1.aws.neon.tech"),
            DEV_URL.replace("set_list_dev_worker", "set_list_dev_migrator"),
            DEV_URL.replace("set_list_dev_worker", "neondb_owner"),
            DEV_URL.replace("/neondb", "/other"),
            DEV_URL.replace(DEVELOPMENT_DATABASE_HOST, DEVELOPMENT_DATABASE_HOST + ".attacker.test"),
            "host=production.test user=owner password=test-password dbname=neondb",
            DEV_URL + "&hostaddr=127.0.0.1",
            DEV_URL + "&host=production.test",
            DEV_URL + "&user=owner",
            DEV_URL + "&service=production",
            DEV_URL + "&options=endpoint%3Dep-production",
            DEV_URL + "&sslmode=disable",
            DEV_URL.replace("?sslmode=require", ""),
        ]
        for url in wrong_urls:
            with self.subTest(url=url), patch.dict(os.environ, {"DATABASE_URL_DIRECT": url}), patch("worker.config.load_saved_auth", return_value={}), patch("worker.db.pg_connect") as database:
                with self.assertRaisesRegex(RuntimeError, "isolated database") as error:
                    with connect():
                        self.fail("Connection must not be opened")
                database.assert_not_called()
                self.assertNotIn("test-password", str(error.exception))

    def test_libpq_environment_override_is_rejected(self):
        for name in ["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"]:
            with self.subTest(name=name), patch.dict(os.environ, {name: "override"}):
                with self.assertRaises(RuntimeError):
                    validate_database_target(DEV_URL)

    def test_missing_development_database_does_not_use_production_or_migrator(self):
        with patch("worker.config.load_saved_auth", return_value={}), patch.dict(os.environ, {
            "PRODUCTION_DATABASE_URL_DIRECT": "production-test-dsn",
            "DATABASE_URL_MIGRATIONS": "migration-test-dsn",
        }):
            self.assertIsNone(get_settings().database_url)
            with patch("worker.db.pg_connect") as database:
                with self.assertRaises(RuntimeError):
                    with connect():
                        self.fail("Connection must not be opened")
                database.assert_not_called()

    def test_production_configuration_is_not_restricted_to_development(self):
        with patch.dict(os.environ, {"WORKER_DEPLOYMENT_TARGET": "production"}):
            validate_database_target("postgresql://production:test@production.test/neondb")

    def test_cookie_script_cannot_write_from_development_even_with_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "gh-called"
            # Consume the pipe like gh does; an early exit races the writer under pipefail.
            (root / "gh").write_text('#!/bin/sh\ncat >/dev/null\nprintf called > "$GH_MARKER"\n')
            (root / "gh").chmod(0o700)
            cookie = root / "cookies"
            cookie.write_text("synthetic-cookie")
            env = {"PATH": str(root) + ":/usr/bin:/bin", "GH_MARKER": str(marker),
                   "GH_PAT": "synthetic-token", "YTDLP_COOKIE_FILE": str(cookie),
                   "GH_REPO": "test/repo"}
            script = ROOT / ".github/scripts/persist-youtube-cookies.sh"
            for target in ["development", "", "typo"]:
                result = subprocess.run(["bash", str(script)], env={**env, "WORKER_DEPLOYMENT_TARGET": target}, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(marker.exists())
                self.assertEqual(cookie.read_text(), "synthetic-cookie")
            # Prove the fake actuator is reachable for the explicit production path.
            result = subprocess.run(["bash", str(script)], env={**env, "WORKER_DEPLOYMENT_TARGET": "production"}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(marker.exists())

    def test_concurrency_cannot_collide_across_targets_or_branches(self):
        text = (ROOT / ".github/workflows/process-set.yml").read_text()
        template = re.search(r"^  group: (.+)$", text, re.MULTILINE).group(1)

        expected = "${{ github.event.inputs.resume_mode == 'private_queue' && 'process-set-private-queue-preview' || github.event.inputs.private_analysis == 'true' && format('process-set-private-analysis-{0}', github.event.inputs.set_run_id) || format('process-set-{0}-{1}-{2}', github.ref, github.event.inputs.deployment_target, github.event.inputs.set_run_id) }}"
        self.assertEqual(template, expected)
        def group(branch, target, private=False):
            return "process-set-private-analysis-same-set-id" if private else f"process-set-{branch}-{target}-same-set-id"
        self.assertEqual(group("refs/heads/preview", "development", True), "process-set-private-analysis-same-set-id")
        self.assertNotEqual(group("refs/heads/preview", "development", True), group("refs/heads/preview", "development"))
        self.assertIn("cancel-in-progress: ${{ github.event.inputs.private_analysis != 'true' }}", text)

        self.assertNotEqual("process-set-private-queue-preview", group("refs/heads/preview", "development", True))
        production = group("refs/heads/remote-deployment", "production")
        self.assertNotEqual(production, group("refs/heads/remote-deployment", "development"))
        self.assertNotEqual(production, group("refs/heads/codex/preview-worker-isolation", "production"))
        self.assertNotEqual(production, group("refs/heads/codex/preview-worker-isolation", "development"))
        self.assertEqual(production, group("refs/heads/remote-deployment", "production"))


if __name__ == "__main__":
    unittest.main()
