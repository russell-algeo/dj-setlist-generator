"""Authentication for internal worker callbacks, including protected previews."""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from worker.config import WorkerSettings, get_settings
from worker.isolation import validate_database_target


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open(request: Request, *, timeout: int):
    return build_opener(_NoRedirects()).open(request, timeout=timeout)


def validate_callback_settings(settings: WorkerSettings) -> None:
    if not settings.api_base_url or not settings.internal_secret:
        raise RuntimeError("APP_BASE_URL and INTERNAL_WORKER_SHARED_SECRET are required for callbacks")
    if os.getenv("WORKER_DEPLOYMENT_TARGET") == "development":
        expected = os.getenv("WORKER_EXPECTED_PREVIEW_ORIGIN")
        if not expected or settings.api_base_url != expected.rstrip("/"):
            raise RuntimeError("Development callbacks must use the configured preview origin")
        if not os.getenv("WORKER_VERCEL_OIDC_AUDIENCE"):
            raise RuntimeError("Development callbacks require Vercel OIDC authentication")


def callback_headers(settings: WorkerSettings) -> dict[str, str]:
    validate_callback_settings(settings)
    headers = {"x-internal-secret": settings.internal_secret}
    audience = os.getenv("WORKER_VERCEL_OIDC_AUDIENCE")
    if not audience:
        return headers
    if urlsplit(settings.api_base_url).scheme != "https":
        raise RuntimeError("Protected callbacks require HTTPS")
    request_url = os.getenv("ACTIONS_ID_TOKEN_REQUEST_URL")
    request_token = os.getenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
    if not request_url or not request_token:
        raise RuntimeError("GitHub OIDC is unavailable; the job requires id-token: write")
    parts = urlsplit(request_url)
    if parts.scheme != "https":
        raise RuntimeError("GitHub OIDC token requests require HTTPS")
    query = [(key, value) for key, value in parse_qsl(parts.query) if key != "audience"]
    query.append(("audience", audience))
    request = Request(
        urlunsplit(parts._replace(query=urlencode(query))),
        headers={"Authorization": f"Bearer {request_token}"},
    )
    # Mint per callback: recognition/discovery can outlive a five-minute OIDC token.
    try:
        with _open(request, timeout=30) as response:
            payload = json.load(response)
            token = payload.get("value") if isinstance(payload, dict) else None
    except (HTTPError, URLError, ValueError):
        raise RuntimeError("Could not obtain GitHub OIDC token for preview callback") from None
    if not isinstance(token, str) or not token or "\n" in token or "\r" in token:
        raise RuntimeError("GitHub OIDC response did not contain a valid token")
    headers["x-vercel-trusted-oidc-idp-token"] = token
    return headers


def post_callback(settings: WorkerSettings, path: str, **kwargs):
    import requests

    response = requests.post(
        f"{settings.api_base_url}{path}",
        headers=callback_headers(settings),
        allow_redirects=False,
        **kwargs,
    )
    if 300 <= response.status_code < 400:
        raise RuntimeError("Internal callback redirects are not allowed")
    return response


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    validate_callback_settings(settings)
    if args.check:
        if settings.database_url:
            validate_database_target(settings.database_url)
        return
    if not args.path or not args.path.startswith("/api/internal/") or "?" in args.path:
        parser.error("an /api/internal/ callback path is required")
    payload = sys.stdin.read().strip()
    if payload:
        json.loads(payload)
    headers = {**callback_headers(settings), "content-type": "application/json"}
    request = Request(settings.api_base_url + args.path, data=payload.encode(), headers=headers, method="POST")
    try:
        with _open(request, timeout=120) as response:
            print(f"Internal callback completed (HTTP {response.status})")
    except HTTPError as exc:
        raise SystemExit(f"Internal callback failed (HTTP {exc.code})") from None
    except URLError:
        raise SystemExit("Internal callback connection failed") from None


if __name__ == "__main__":
    main()
