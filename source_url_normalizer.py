"""Normalize source URLs before they are persisted or embedded."""

from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen


SOUNDCLOUD_SHORT_HOSTS = {"on.soundcloud.com", "snd.sc"}
SOUNDCLOUD_HOSTS = {"soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"}
SOUNDCLOUD_SHARE_PARAMS = {
    "c",
    "p",
    "ref",
    "si",
    "utm_campaign",
    "utm_medium",
    "utm_source",
}


def _host(source_url: str) -> str:
    try:
        parsed = urlparse(source_url)
        return parsed.hostname.lower() if parsed.hostname else ""
    except ValueError:
        return ""


def is_soundcloud_short_url(source_url: str) -> bool:
    """Return True for SoundCloud share links that redirect to a canonical URL."""

    return _host(source_url) in SOUNDCLOUD_SHORT_HOSTS


def is_soundcloud_url(source_url: str) -> bool:
    """Return True for canonical SoundCloud URLs."""

    return _host(source_url) in SOUNDCLOUD_HOSTS


def clean_soundcloud_url(source_url: str) -> str:
    """Strip SoundCloud sharing noise while preserving meaningful query params."""

    if not is_soundcloud_url(source_url):
        return source_url

    parsed = urlparse(source_url)
    hostname = parsed.hostname.lower() if parsed.hostname else parsed.netloc.lower()
    netloc = "soundcloud.com" if hostname in {"www.soundcloud.com", "m.soundcloud.com"} else hostname
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in SOUNDCLOUD_SHARE_PARAMS
        ],
        doseq=True,
    )

    return urlunparse(("https", netloc, parsed.path, "", query, ""))


def resolve_canonical_source_url(source_url: str, *, timeout: float = 8.0, opener=urlopen) -> str:
    """Resolve embeddable source URLs, currently focused on SoundCloud short links."""

    if is_soundcloud_url(source_url):
        return clean_soundcloud_url(source_url)

    if not is_soundcloud_short_url(source_url):
        return source_url

    resolved_url = source_url
    for method in ("HEAD", "GET"):
        request = Request(
            source_url,
            headers={"User-Agent": "Mozilla/5.0"},
            method=method,
        )

        try:
            with opener(request, timeout=timeout) as response:
                resolved_url = response.geturl()
            break
        except (HTTPError, URLError, TimeoutError, ValueError, OSError):
            continue

    if is_soundcloud_url(resolved_url):
        return clean_soundcloud_url(resolved_url)

    return source_url
