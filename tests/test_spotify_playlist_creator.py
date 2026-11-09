"""Mock-only regressions for Spotify privacy and managed callback boundaries."""

import io
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from config import Config
from spotify_playlist_creator import (
    SPOTIFY_PLAYLIST_PRIVACY_NOTICE,
    SpotifyPlaylistCreator,
)

PREVIEW = "https://dj-setlist-generator-git-preview-russell-algeos-projects.vercel.app"


class ManagedSpotifyTokenTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.auth = patch("worker.config.load_saved_auth", return_value={})
        self.auth.start()
        self.addCleanup(self.auth.stop)
        self.creator = SpotifyPlaylistCreator.__new__(SpotifyPlaylistCreator)

    def managed_env(self, preview=True):
        os.environ.update({
            "SET_LIST_API_BASE_URL": PREVIEW,
            "SET_LIST_ACTIVE_SET_RUN_ID": "test-run",
            "INTERNAL_WORKER_SHARED_SECRET": "test-internal-secret",
            "WORKER_DEPLOYMENT_TARGET": "development" if preview else "production",
        })
        if preview:
            os.environ.update({
                "WORKER_EXPECTED_PREVIEW_ORIGIN": PREVIEW,
                "WORKER_VERCEL_OIDC_AUDIENCE": "https://github.com/russell-algeo",
                "ACTIONS_ID_TOKEN_REQUEST_URL": "https://oidc.actions.test/token",
                "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "test-runtime-token",
            })

    def response(self, status=200, payload=None):
        response = MagicMock(status_code=status)
        response.json.return_value = payload if payload is not None else {"access_token": "test-spotify-token"}
        return response

    def test_local_mode_does_not_request_managed_auth(self):
        with patch("requests.post") as request:
            self.assertIsNone(self.creator._fetch_managed_access_token())
            request.assert_not_called()

    def test_preview_uses_existing_oidc_headers_and_disables_redirects(self):
        self.managed_env()
        with patch("requests.post", return_value=self.response()) as request, patch(
            "worker.callbacks._open", return_value=io.BytesIO(b'{"value":"test-oidc-token"}')
        ):
            self.assertEqual(self.creator._fetch_managed_access_token(), "test-spotify-token")
        request.assert_called_once_with(
            PREVIEW + "/api/internal/spotify-token",
            headers={
                "x-internal-secret": "test-internal-secret",
                "x-vercel-trusted-oidc-idp-token": "test-oidc-token",
            },
            allow_redirects=False,
            json={"setRunId": "test-run"},
            timeout=30,
        )

    def test_production_preserves_shared_secret_without_oidc(self):
        self.managed_env(preview=False)
        with patch("requests.post", return_value=self.response()) as request, patch("worker.callbacks._open") as oidc:
            self.assertEqual(self.creator._fetch_managed_access_token(), "test-spotify-token")
            oidc.assert_not_called()
        self.assertEqual(request.call_args.kwargs["headers"], {"x-internal-secret": "test-internal-secret"})
        self.assertFalse(request.call_args.kwargs["allow_redirects"])

    def test_wrong_preview_origin_is_rejected_before_any_request(self):
        self.managed_env()
        for url in ["https://dj-setlist-generator-listened-preview.vercel.app", "https://dj-setlist-generator.vercel.app", PREVIEW + ".evil.test", PREVIEW + "/other"]:
            with self.subTest(url=url), patch.dict(os.environ, {"SET_LIST_API_BASE_URL": url}), patch(
                "requests.post"
            ) as request, patch("worker.callbacks._open") as oidc:
                with self.assertRaisesRegex(RuntimeError, "preview origin"):
                    self.creator._fetch_managed_access_token()
                request.assert_not_called()
                oidc.assert_not_called()

    def test_incomplete_managed_configuration_never_falls_back_to_local_auth(self):
        self.managed_env()
        keys = [
            "SET_LIST_ACTIVE_SET_RUN_ID", "SET_LIST_API_BASE_URL", "INTERNAL_WORKER_SHARED_SECRET",
            "WORKER_EXPECTED_PREVIEW_ORIGIN", "WORKER_VERCEL_OIDC_AUDIENCE",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
        ]
        for key in keys:
            with self.subTest(key=key), patch.dict(os.environ, {key: ""}), patch("requests.post") as request, patch(
                "worker.callbacks._open"
            ) as oidc, patch("spotify_playlist_creator.SpotifyOAuth") as oauth, patch.object(
                Config, "ENABLE_SPOTIFY_PLAYLISTS", True
            ), patch("builtins.print"):
                creator = SpotifyPlaylistCreator()
                self.assertIsNone(creator.spotify)
                oauth.assert_not_called()
                request.assert_not_called()
                oidc.assert_not_called()

    def test_redirect_rejected_without_following_or_retry(self):
        self.managed_env(preview=False)
        for code in [301, 302, 303, 307, 308]:
            with self.subTest(code=code), patch("requests.post", return_value=self.response(status=code)) as request:
                with self.assertRaisesRegex(RuntimeError, "redirects"):
                    self.creator._fetch_managed_access_token()
                request.assert_called_once()
                self.assertFalse(request.call_args.kwargs["allow_redirects"])

    def test_missing_connection_never_uses_local_oauth(self):
        self.managed_env(preview=False)
        with patch("requests.post", return_value=self.response(status=404)), patch(
            "spotify_playlist_creator.SpotifyOAuth"
        ) as oauth, patch.object(Config, "ENABLE_SPOTIFY_PLAYLISTS", True), patch("builtins.print"):
            creator = SpotifyPlaylistCreator()
        self.assertIsNone(creator.spotify)
        oauth.assert_not_called()

    def test_invalid_token_payloads_fail_closed(self):
        self.managed_env(preview=False)
        for payload in [{}, [], {"access_token": None}, {"access_token": 3}, {"access_token": " "},
                        {"access_token": "bad\ntoken"}, {"access_token": "bad\rtoken"}]:
            with self.subTest(payload=payload), patch("requests.post", return_value=self.response(payload=payload)):
                with self.assertRaisesRegex(RuntimeError, "valid access token"):
                    self.creator._fetch_managed_access_token()

    def test_http_failures_do_not_retry_or_return_a_token(self):
        self.managed_env(preview=False)
        response = self.response(status=403)
        response.raise_for_status.side_effect = RuntimeError("HTTP 403")
        with patch("requests.post", return_value=response) as request:
            with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                self.creator._fetch_managed_access_token()
        request.assert_called_once()
        response.json.assert_not_called()


class SpotifyPlaylistExportTests(unittest.TestCase):
    def setUp(self):
        self.creator = SpotifyPlaylistCreator.__new__(SpotifyPlaylistCreator)
        self.creator.spotify = MagicMock()
        self.creator.user_id = "test-user"
        self.creator.spotify.user_playlist_create.return_value = {
            "id": "test-playlist",
            "name": "Example",
            "external_urls": {"spotify": "https://open.spotify.com/playlist/test-playlist"},
        }
        self.tracks = [{
            "track": SimpleNamespace(title="Example"),
            "metadata": {"spotify_url": "https://open.spotify.com/track/test-track"},
        }]

    def test_set_export_requests_public_false_without_an_access_privacy_guarantee(self):
        # Spotify's public flag is not an access-control result. Export stays
        # functional even when the response reports public=True.
        self.creator.spotify.user_playlist_create.return_value["public"] = True
        with patch("builtins.print"):
            result = self.creator.create_playlist_from_setlist(self.tracks, {"title": "Example"})
        self.assertEqual(result["tracks_added"], 1)
        self.assertEqual(result["playlist_id"], "test-playlist")
        kwargs = self.creator.spotify.user_playlist_create.call_args.kwargs
        self.assertIs(kwargs["public"], False)
        self.assertEqual(set(kwargs), {"public", "description"})
        self.creator.spotify.playlist_add_items.assert_called_once_with("test-playlist", ["spotify:track:test-track"])

    def test_set_export_preserves_track_batches_and_artist_playlist_updates(self):
        with patch("builtins.print"):
            result = self.creator.create_playlist_from_setlist(
                self.tracks * 205, {"title": "Example"}, artist_playlist_id="artist-playlist",
            )
        self.assertEqual(result["tracks_added"], 205)
        self.assertEqual(result["tracks_failed"], 0)
        calls = self.creator.spotify.playlist_add_items.call_args_list
        self.assertEqual([len(call.args[1]) for call in calls], [100, 100, 100, 100, 5, 5])
        self.assertEqual([call.args[0] for call in calls], ["test-playlist", "artist-playlist"] * 3)

    def test_partial_track_failure_preserves_existing_report(self):
        self.creator.spotify.playlist_add_items.side_effect = [RuntimeError("test failure"), None]
        with patch("builtins.print"):
            result = self.creator.create_playlist_from_setlist(self.tracks * 101, {"title": "Example"})
        self.assertEqual(result["tracks_added"], 1)
        self.assertEqual(result["tracks_failed"], 100)

    def test_artist_lookup_reuses_existing_playlist(self):
        self.creator.spotify.current_user_playlists.return_value = {
            "items": [{"name": "Example Artist", "id": "existing-playlist"}], "next": None,
        }
        with patch("builtins.print"):
            self.assertEqual(self.creator.find_or_create_artist_playlist("Example Artist"), "existing-playlist")
        self.creator.spotify.user_playlist_create.assert_not_called()

    def test_artist_creation_requests_public_false(self):
        self.creator.spotify.current_user_playlists.return_value = {"items": [], "next": None}
        with patch("builtins.print"):
            self.assertEqual(self.creator.find_or_create_artist_playlist("Example Artist"), "test-playlist")
        self.assertIs(self.creator.spotify.user_playlist_create.call_args.kwargs["public"], False)

    def test_existing_artist_playlist_can_receive_tracks(self):
        with patch("builtins.print"):
            self.creator.add_tracks_to_artist_playlist(self.tracks, "existing-playlist")
        self.creator.spotify.playlist_add_items.assert_called_once_with("existing-playlist", ["spotify:track:test-track"])

    def test_confirmation_and_auto_mode_disclose_privacy_without_blocking_export(self):
        for automatic in [True, False]:
            self.creator.spotify.reset_mock()
            with self.subTest(automatic=automatic), patch.object(Config, "AUTO_CREATE_SPOTIFY_PLAYLIST", automatic), patch.object(
                Config, "CREATE_SET_PLAYLISTS", True
            ), patch("spotify_playlist_creator.SpotifyPlaylistCreator", return_value=self.creator) as initialize, patch(
                "builtins.input", return_value="y"
            ) as prompt, patch("builtins.print") as output:
                SpotifyPlaylistCreator.create_with_confirmation(self.tracks, {}, "Example")
                initialize.assert_called_once()
                if automatic:
                    prompt.assert_not_called()
                else:
                    prompt.assert_called_once()
                output.assert_any_call(SPOTIFY_PLAYLIST_PRIVACY_NOTICE)
                self.creator.spotify.user_playlist_create.assert_called_once()
                self.creator.spotify.playlist_add_items.assert_called_once()

    def test_declining_confirmation_does_not_construct_or_mutate(self):
        with patch.object(Config, "AUTO_CREATE_SPOTIFY_PLAYLIST", False), patch.object(
            Config, "CREATE_SET_PLAYLISTS", True
        ), patch("spotify_playlist_creator.SpotifyPlaylistCreator") as initialize, patch(
            "builtins.input", return_value="n"
        ), patch("builtins.print") as output:
            SpotifyPlaylistCreator.create_with_confirmation(self.tracks, {}, "Example")
        initialize.assert_not_called()
        self.assertEqual(self.creator.spotify.mock_calls, [])
        output.assert_any_call(SPOTIFY_PLAYLIST_PRIVACY_NOTICE)


if __name__ == "__main__":
    unittest.main()
