"""Preview-only diagnostic of the real managed token parser; never publish."""

from __future__ import annotations

import os
from uuid import UUID

from worker.callbacks import validate_callback_settings
from worker.config import get_settings


PREVIEW_ORIGIN = "https://dj-setlist-generator-git-preview-russell-algeos-projects.vercel.app"
REPOSITORY = "russell-algeo/dj-setlist-generator"
PREVIEW_REF = "refs/heads/preview"


def run() -> None:
    required = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REF": PREVIEW_REF,
        "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/.github/workflows/process-set.yml@{PREVIEW_REF}",
        "WORKER_DEPLOYMENT_TARGET": "development",
        "APP_BASE_URL": PREVIEW_ORIGIN,
        "WORKER_EXPECTED_PREVIEW_ORIGIN": PREVIEW_ORIGIN,
        "WORKER_VERCEL_OIDC_AUDIENCE": "https://github.com/russell-algeo",
    }
    if any(os.getenv(key) != value for key, value in required.items()):
        raise RuntimeError("Token diagnostic requires the existing Preview workflow context")
    UUID(os.environ["SET_LIST_ACTIVE_SET_RUN_ID"])
    settings = get_settings()
    validate_callback_settings(settings)

    from spotify_playlist_creator import SpotifyPlaylistCreator

    # Deliberately bypass __init__: it creates a Spotify client and calls /me.
    # This exact parser already uses the shared callback/OIDC/no-redirect path.
    creator = SpotifyPlaylistCreator.__new__(SpotifyPlaylistCreator)
    token = creator._fetch_managed_access_token()
    if not isinstance(token, str) or not token.strip():
        raise RuntimeError("Managed Spotify token was not returned")
    # Do not return, log, persist, or use the token for any other request.
    del token


def main() -> None:
    try:
        run()
    except Exception:
        # Exceptions from HTTP clients/providers can include response details.
        raise SystemExit("Preview Spotify token diagnostic failed; response details suppressed") from None
    print("Preview managed Spotify token callback verified; no media, playlist, or publishing calls")


if __name__ == "__main__":
    main()
