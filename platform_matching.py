"""Evidence and presentation policy for enriched links (no network access)."""

import re

from spotify_matching import (
    candidate_artist_names,
    candidate_title,
    discogs_artist_text,
    discogs_corroborates_title,
    has_expected_artist_evidence,
    title_match_score,
)


LINK_MATCHING_VERSION = 2


def match_evidence(item, reason, *, artist=None, title=None):
    """Persist the actual provider identity, rather than just a playable URL."""
    return {
        "status": "matched",
        "reason": reason,
        "title": title or candidate_title(item),
        "artists": [artist] if artist else candidate_artist_names(item),
    }


def select_youtube_candidate(artist, title, entries, *, discogs_data=None):
    """Validate video titles; search rank and uploader name are not identity."""
    corroborated_artist = discogs_artist_text(discogs_data)
    # Discogs searches can return a different release. Its artist credit is
    # usable only if the release title contains this complete track title.
    if not discogs_corroborates_title(title, discogs_data):
        corroborated_artist = ""
    matches = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        video_title = str(entry.get("title") or "")
        parts = re.split(r"\s+[-–—]\s+", video_title, maxsplit=1)
        if len(parts) != 2 or not entry.get("id"):
            continue
        video_artist, recording_title = parts
        eligible, score = title_match_score(title, recording_title)
        if not eligible:
            continue
        shaped = {"artist": video_artist}
        reason = "artist_title"
        if not has_expected_artist_evidence(artist, shaped):
            if not corroborated_artist or not has_expected_artist_evidence(corroborated_artist, shaped):
                continue
            reason = "discogs_artist_title"
        evidence = match_evidence(entry, reason, artist=video_artist, title=recording_title)
        if reason == "discogs_artist_title":
            evidence["corroboration"] = {"provider": "discogs", "url": discogs_data.get("url"), "title": discogs_data.get("title")}
        matches.append((score, entry, evidence))
    if not matches:
        return None
    matches.sort(key=lambda match: match[0], reverse=True)
    _, entry, evidence = matches[0]
    url = f"https://www.youtube.com/watch?v={entry['id']}"
    return {"url": url, "match": {**evidence, "url": url}}


def primary_track_platform(metadata):
    """Prefer confirmed links over legacy links; reject explicit non-matches."""
    for confirmed_only in (True, False):
        for platform in ("spotify", "youtube", "discogs"):
            if not usable_platform_url(metadata, platform):
                continue
            if platform == "spotify" and not re.match(r"https://open\.spotify\.com/track/[^/?#]+", metadata[f"{platform}_url"]):
                continue
            match = (metadata.get("platform_matches") or {}).get(platform)
            if confirmed_only and not match:
                continue
            return platform
    return None


def usable_platform_url(metadata, platform):
    """Legacy URLs remain unknown; an explicit rejection always wins."""
    url = metadata.get(f"{platform}_url")
    match = (metadata.get("platform_matches") or {}).get(platform)
    if match:
        return url if match.get("status") == "matched" and match.get("url") == url else None
    if metadata.get("link_matching_version") and platform != "discogs":
        return None
    return url
