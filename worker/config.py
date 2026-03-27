"""Shared worker configuration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


AUTH_PATH = Path.home() / ".config" / "set_list_worker" / "auth.json"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _first_env(*keys: str) -> str | None:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    return None


@dataclass(slots=True)
class WorkerSettings:
    api_base_url: str | None
    api_token: str | None
    internal_secret: str | None
    database_url: str | None
    import_full_archive: bool


def load_saved_auth() -> dict[str, str]:
    if not AUTH_PATH.exists():
        return {}

    try:
        return json.loads(AUTH_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def save_auth(token: str, base_url: str | None = None) -> None:
    AUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = load_saved_auth()
    payload["token"] = token
    if base_url:
        payload["base_url"] = base_url.rstrip("/")
    AUTH_PATH.write_text(json.dumps(payload, indent=2))


def clear_auth() -> None:
    if AUTH_PATH.exists():
        AUTH_PATH.unlink()


def get_settings(explicit_base_url: str | None = None) -> WorkerSettings:
    saved = load_saved_auth()

    api_base_url = (
        explicit_base_url
        or _first_env("SET_LIST_API_BASE_URL", "APP_BASE_URL")
        or saved.get("base_url")
    )

    return WorkerSettings(
        api_base_url=api_base_url.rstrip("/") if api_base_url else None,
        api_token=_first_env("DJSET_API_TOKEN") or saved.get("token"),
        internal_secret=_first_env("INTERNAL_WORKER_SHARED_SECRET"),
        database_url=_first_env(
            "DATABASE_URL_DIRECT",
            "DATABASE_URL_MIGRATIONS",
            "DEVELOPMENT_DATABASE_URL_DIRECT",
            "PRODUCTION_DATABASE_URL_DIRECT",
        ),
        import_full_archive=_first_env("WORKER_IMPORT_FULL_ARCHIVE", "IMPORT_FULL_ARCHIVE") != "false",
    )
