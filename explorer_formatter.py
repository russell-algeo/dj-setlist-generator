"""Generate a redesigned master explorer HTML experience for DJ set data."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from detail_explorer_common import (
    CONFIDENCE_LEVELS,
    EXCLUDED_GENRES,
    blank_confidence_counts as _blank_confidence_counts,
    merge_confidence_counts as _merge_confidence_counts,
    normalize_confidence as _normalize_confidence,
    primary_confidence as _primary_confidence,
)


def _uniq_ordered(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    _excluded_lower = {g.lower() for g in EXCLUDED_GENRES}
    for value in values:
        if not value:
            continue
        v = value.strip()
        if not v:
            continue
        if v.lower() in _excluded_lower:
            continue
        if v not in seen:
            seen.add(v)
            output.append(v)
    return output


def _build_track_set_refs(track: dict) -> list[dict]:
    refs: list[dict] = []
    sets = track.get("sets") or []
    link_map = track.get("set_link_map") or {}
    for set_title in sets:
        info = link_map.get(set_title, {})
        href = info.get("html_master_rel") or ""
        pos = info.get("track_position")
        conf = str(info.get("confidence") or "UNCERTAIN").upper()
        conf = conf if conf in CONFIDENCE_LEVELS else "UNCERTAIN"
        if href and pos:
            href = f"{href}#track-{pos}"
        refs.append(
            {
                "title": set_title,
                "href": href,
                "track_position": pos,
                "confidence": conf,
            }
        )
    return refs


def _build_client_data(master_data: dict) -> dict:
    """Convert master summary internals into a frontend-focused payload."""
    artists_payload: list[dict] = []
    track_catalog: dict[str, dict] = {}
    global_confidence: Counter = Counter()

    for artist in master_data.get("artists", []):
        label_counter: Counter = Counter()
        genre_counter: Counter = Counter()
        tracks_payload: list[dict] = []

        for track in artist.get("tracks", {}).values():
            genres = _uniq_ordered([g.title() for g in track.get("genres", [])])
            label = track.get("discogs_label")
            appearances = int(track.get("appearances", 0))
            set_refs = _build_track_set_refs(track)
            confidence_counts = _blank_confidence_counts()
            raw_conf_counts = track.get("confidence_counts") or {}
            for level in CONFIDENCE_LEVELS:
                confidence_counts[level] = int(raw_conf_counts.get(level, 0))
            confidence = _primary_confidence(confidence_counts)

            if label:
                label_counter[label] += max(1, appearances)
            for genre in genres:
                genre_counter[genre] += max(1, appearances)

            track_entry = {
                "track_key": track.get("track_key"),
                "artist": track.get("display_artist", "Unknown"),
                "title": track.get("display_title", "Unknown"),
                "spotify_url": track.get("spotify_url"),
                "album_art": track.get("spotify_album_art"),
                "artist_profile_image": track.get("spotify_artist_profile_image"),
                "artist_image": track.get("spotify_artist_profile_image"),
                "label": label,
                "label_url": track.get("discogs_label_url"),
                "genres": genres,
                "appearances": appearances,
                "confidence": confidence,
                "confidence_counts": confidence_counts,
                "sets": track.get("sets", []),
                "set_refs": set_refs,
            }
            tracks_payload.append(track_entry)

            key = track_entry["track_key"]
            if not key:
                continue

            if key not in track_catalog:
                track_catalog[key] = {
                    "track_key": key,
                    "artist": track_entry["artist"],
                    "title": track_entry["title"],
                    "spotify_url": track_entry["spotify_url"],
                    "album_art": track_entry["album_art"],
                    "artist_profile_image": track_entry["artist_profile_image"],
                    "artist_image": track_entry["artist_image"],
                    "label": track_entry["label"],
                    "label_url": track_entry["label_url"],
                    "genres": list(track_entry["genres"]),
                    "artist_refs": [],
                    "artists_count": 0,
                    "total_appearances": 0,
                    "confidence": confidence,
                    "confidence_counts": dict(confidence_counts),
                }

            catalog_entry = track_catalog[key]
            if not catalog_entry.get("album_art") and track_entry.get("album_art"):
                catalog_entry["album_art"] = track_entry["album_art"]
            if not catalog_entry.get("artist_profile_image") and track_entry.get("artist_profile_image"):
                catalog_entry["artist_profile_image"] = track_entry["artist_profile_image"]
            if not catalog_entry.get("artist_image") and track_entry.get("artist_image"):
                catalog_entry["artist_image"] = track_entry["artist_image"]
            if not catalog_entry.get("spotify_url") and track_entry.get("spotify_url"):
                catalog_entry["spotify_url"] = track_entry["spotify_url"]
            if not catalog_entry.get("label") and track_entry.get("label"):
                catalog_entry["label"] = track_entry["label"]
                catalog_entry["label_url"] = track_entry["label_url"]

            catalog_entry["genres"] = _uniq_ordered(
                catalog_entry.get("genres", []) + track_entry["genres"]
            )
            catalog_entry["confidence_counts"] = _merge_confidence_counts(
                catalog_entry.get("confidence_counts") or _blank_confidence_counts(),
                track_entry.get("confidence_counts") or _blank_confidence_counts(),
            )
            catalog_entry["confidence"] = _primary_confidence(catalog_entry["confidence_counts"])
            catalog_entry["artist_refs"].append(
                {
                    "artist_name": artist.get("name", "Unknown"),
                    "dir_name": artist.get("dir_name", ""),
                    "appearances": appearances,
                    "sets": track_entry.get("sets", []),
                    "set_refs": set_refs,
                }
            )
            catalog_entry["artists_count"] = len(
                {a["artist_name"] for a in catalog_entry["artist_refs"]}
            )
            catalog_entry["total_appearances"] += appearances

        tracks_payload.sort(
            key=lambda t: (t["appearances"], t["artist"], t["title"]), reverse=True
        )

        set_payload = []
        for s in artist.get("sets", []):
            confidence_counts = s.get("confidence_counts", {}) or {}
            global_confidence.update(
                {
                    "HIGH": int(confidence_counts.get("HIGH", 0)),
                    "MEDIUM": int(confidence_counts.get("MEDIUM", 0)),
                    "LOW": int(confidence_counts.get("LOW", 0)),
                    "UNCERTAIN": int(confidence_counts.get("UNCERTAIN", 0)),
                }
            )

            tracks = []
            for idx, t in enumerate(s.get("tracks", []) or [], start=1):
                pos = t.get("position") or idx
                set_href = s.get("set_html_master_rel") or ""
                track_href = f"{set_href}#track-{pos}" if set_href else ""
                tracks.append(
                    {
                        "position": pos,
                        "artist": t.get("artist", "Unknown"),
                        "title": t.get("title", "Unknown"),
                        "start_time_formatted": t.get("start_time_formatted", ""),
                        "confidence": t.get("confidence", "UNCERTAIN"),
                        "spotify_url": t.get("spotify_url"),
                        "track_key": t.get("track_key"),
                        "track_href": track_href,
                    }
                )

            set_payload.append(
                {
                    "title": s.get("title", "Unknown Set"),
                    "url": s.get("url"),
                    "duration": s.get("duration", 0),
                    "total_tracks": s.get("total_tracks", 0),
                    "recognition_rate": round(float(s.get("recognition_rate", 0.0)), 1),
                    "confidence_counts": confidence_counts,
                    "thumbnail_url": s.get("thumbnail_url"),
                    "set_html_master_rel": s.get("set_html_master_rel"),
                    "artist_html_rel": artist.get("html_rel", ""),
                    "tracks": tracks,
                    "track_search_text": s.get("track_search_text", ""),
                }
            )

        artist_profile_image = artist.get("artist_profile_image") or artist.get("artist_image")
        artist_image = artist_profile_image
        cover_image = artist_profile_image or next(
            (s.get("thumbnail_url") for s in set_payload if s.get("thumbnail_url")), None
        )

        top_labels = [
            {"name": name, "count": count} for name, count in label_counter.most_common(10)
        ]
        top_genres = [
            {"name": name, "count": count} for name, count in genre_counter.most_common(10)
        ]

        artists_payload.append(
            {
                "name": artist.get("name", "Unknown"),
                "dir_name": artist.get("dir_name", ""),
                "html_rel": artist.get("html_rel", ""),
                "sets_analyzed": int(artist.get("sets_analyzed", 0)),
                "unique_tracks": int(artist.get("unique_tracks", 0)),
                "total_appearances": int(artist.get("total_appearances", 0)),
                "signature_score": float(artist.get("signature_score", 0.0)),
                "top_genres": artist.get("top_genres", []),
                "top_connections": artist.get("top_connections", []),
                "top_labels": top_labels,
                "genre_profile": top_genres,
                "artist_profile_image": artist_profile_image,
                "artist_image": artist_image,
                "artist_profile_name": artist.get("artist_profile_name"),
                "artist_profile_url": artist.get("artist_profile_url"),
                "cover_image": cover_image,
                "tracks": tracks_payload,
                "sets": set_payload,
            }
        )

    similarity_list = []
    for pair in master_data.get("similarity_list", []):
        similarity_list.append(
            {
                "artist_a": pair.get("artist_a"),
                "artist_b": pair.get("artist_b"),
                "score": int(pair.get("score", 0)),
                "normalized_score": int(pair.get("normalized_score", 0)),
                "shared_tracks_count": len(pair.get("shared_tracks", [])),
                "shared_labels_count": len(pair.get("shared_labels", [])),
                "shared_artists_count": len(pair.get("shared_music_artists", [])),
                "shared_genres_count": len(pair.get("shared_genres", [])),
                "shared_tracks": [
                    {
                        "track_key": t.get("track_key"),
                        "display_artist": t.get("display_artist"),
                        "display_title": t.get("display_title"),
                        "spotify_url": t.get("spotify_url"),
                        "spotify_album_art": t.get("spotify_album_art"),
                        "spotify_artist_profile_image": t.get("spotify_artist_profile_image"),
                        "discogs_label": t.get("discogs_label"),
                        "discogs_label_url": t.get("discogs_label_url"),
                        "genres": _uniq_ordered([g.title() for g in t.get("genres", [])]),
                        "confidence": _normalize_confidence(t.get("confidence")),
                        "confidence_counts": {
                            level: int((t.get("confidence_counts") or {}).get(level, 0))
                            for level in CONFIDENCE_LEVELS
                        },
                        "appearances_a": int(t.get("appearances_a", 0)),
                        "appearances_b": int(t.get("appearances_b", 0)),
                        "sets_a": t.get("sets_a", []) or [],
                        "sets_b": t.get("sets_b", []) or [],
                    }
                    for t in pair.get("shared_tracks", [])
                ],
                "shared_labels": pair.get("shared_labels", []) or [],
                "shared_music_artists": pair.get("shared_music_artists", []) or [],
                "shared_genres": pair.get("shared_genres", []) or [],
            }
        )
    similarity_list.sort(key=lambda x: x.get("normalized_score", 0), reverse=True)

    catalog_list = sorted(
        track_catalog.values(),
        key=lambda t: (t.get("artists_count", 0), t.get("total_appearances", 0)),
        reverse=True,
    )

    all_sets_payload = []
    for s in master_data.get("all_sets", []):
        tracks = []
        for idx, t in enumerate((s.get("tracks") or []), start=1):
            pos = t.get("position") or idx
            set_href = s.get("set_html_master_rel") or ""
            track_href = f"{set_href}#track-{pos}" if set_href else ""
            tracks.append(
                {
                    "position": pos,
                    "artist": t.get("artist", "Unknown"),
                    "title": t.get("title", "Unknown"),
                    "start_time_formatted": t.get("start_time_formatted", ""),
                    "confidence": t.get("confidence", "UNCERTAIN"),
                    "spotify_url": t.get("spotify_url"),
                    "track_key": t.get("track_key"),
                    "track_href": track_href,
                }
            )
        all_sets_payload.append(
            {
                "title": s.get("title", "Unknown Set"),
                "url": s.get("url"),
                "duration": s.get("duration", 0),
                "total_tracks": s.get("total_tracks", 0),
                "high_confidence": s.get("high_confidence", 0),
                "recognition_rate": round(float(s.get("recognition_rate", 0.0)), 1),
                "confidence_counts": s.get("confidence_counts", {}) or {},
                "mini_timeline": s.get("mini_timeline", []) or [],
                "thumbnail_url": s.get("thumbnail_url"),
                "set_html_master_rel": s.get("set_html_master_rel"),
                "artist_name": s.get("artist_name", ""),
                "artist_html_rel": s.get("artist_html_rel", ""),
                "tracks": tracks,
                "track_search_text": s.get("track_search_text", ""),
            }
        )

    confidence_total = sum(global_confidence.values()) or 1
    unknown_ratio = global_confidence.get("UNCERTAIN", 0) / confidence_total

    global_stats = dict(master_data.get("global_stats", {}))
    global_stats["confidence_breakdown"] = {
        "HIGH": int(global_confidence.get("HIGH", 0)),
        "MEDIUM": int(global_confidence.get("MEDIUM", 0)),
        "LOW": int(global_confidence.get("LOW", 0)),
        "UNCERTAIN": int(global_confidence.get("UNCERTAIN", 0)),
    }
    global_stats["unknown_ratio"] = round(unknown_ratio, 4)

    return {
        "generated_at": master_data.get("generated_at"),
        "global_stats": global_stats,
        "artists": artists_payload,
        "similarity": similarity_list,
        "genre_totals": master_data.get("genre_totals", []),
        "label_totals": master_data.get("label_totals", []),
        "most_played_tracks": master_data.get("most_played_tracks", []),
        "track_catalog": catalog_list,
        "all_sets": all_sets_payload,
    }


def _render_html(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)

    html = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Set Signal Explorer</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet" />
  <style>
    :root {
      --bg: #0a0a0a;
      --paper: #111111;
      --paper-2: #161616;
      --ink: #f3f3f3;
      --muted: #ababab;
      --lime: #d8ff5a;
      --violet: #7f51ff;
      --line: #2c2c2c;
      --line-soft: #242424;
      --radius: 4px;
      --gutter: clamp(16px, 2vw, 28px);
      --section-pad: clamp(24px, 4.8vw, 72px);
      --section-pad-y: clamp(16px, 3.2vw, 44px);
    }

    * { box-sizing: border-box; }

    html, body {
      margin: 0;
      padding: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: 'Manrope', sans-serif;
      scroll-behavior: smooth;
    }

    a { color: inherit; text-decoration: none; }

    .shell { max-width: 1480px; margin: 0 auto; padding: 0 var(--gutter) 72px; }

    .topbar {
      position: sticky;
      top: 0;
      z-index: 40;
      background: rgba(10, 10, 10, 0.96);
      border-bottom: 1px solid var(--line-soft);
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px var(--section-pad);
      margin: 0 calc(var(--gutter) * -1);
      backdrop-filter: blur(8px);
    }

    .logo {
      font-family: 'Space Mono', monospace;
      font-size: 11px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: #d8d8d8;
    }

    .topnav {
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
      font-family: 'Space Mono', monospace;
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .topnav a {
      color: #cfcfcf;
      border-bottom: 1px solid transparent;
      padding-bottom: 2px;
      transition: color 0.2s ease, border-color 0.2s ease;
    }

    .topnav a:hover { color: #fff; border-color: var(--lime); }

    .section {
      border: 1px solid var(--line);
      background: var(--paper);
      margin-top: var(--gutter);
    }

    .section.dark { background: #0f0f0f; }

    .section-inner { padding: var(--section-pad-y) var(--section-pad); }

    .section-head {
      display: grid;
      grid-template-columns: 1.5fr 1fr;
      gap: 20px;
      align-items: end;
      margin-bottom: 18px;
    }

    .section-head h2 {
      margin: 0;
      font-size: clamp(38px, 7.6vw, 82px);
      line-height: 0.88;
      letter-spacing: -0.04em;
      text-transform: uppercase;
      color: #fff;
    }

    .section-head p {
      margin: 0;
      justify-self: end;
      max-width: 460px;
      font-size: 13px;
      line-height: 1.6;
      color: #c0c0c0;
    }

    .kicker {
      display: inline-flex;
      border: 1px solid var(--line);
      padding: 5px 10px;
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.09em;
      text-transform: uppercase;
      margin-bottom: 10px;
      color: #d8d8d8;
    }

    .hero {
      background: #101010;
      border: 1px solid #2a2a2a;
      margin-top: var(--gutter);
      position: relative;
      overflow: hidden;
    }

    .hero-grid {
      display: grid;
      grid-template-columns: 1.6fr 1fr;
      gap: 12px;
      align-items: start;
    }

    .hero-main {
      display: grid;
      grid-template-rows: minmax(0, 1fr) auto;
      min-height: 0;
    }

    .hero-visual {
      height: clamp(250px, 34vh, 360px);
      min-height: 0;
      position: relative;
      border: 1px solid var(--line);
      background: #0d0d0d;
      overflow: hidden;
    }

    .hero-visual::after {
      content: '';
      position: absolute;
      inset: 0;
      background: linear-gradient(to top, rgba(0, 0, 0, 0.62) 0%, rgba(0, 0, 0, 0.16) 52%, rgba(0, 0, 0, 0.05) 100%);
      pointer-events: none;
      z-index: 1;
    }

    .hero-visual img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      object-position: center 24%;
      filter: grayscale(20%);
      display: block;
      position: relative;
      z-index: 0;
    }

    .hero-title-overlay {
      position: absolute;
      left: clamp(14px, 3vw, 36px);
      bottom: clamp(14px, 3vw, 34px);
      margin: 0;
      font-size: clamp(68px, 16vw, 200px);
      line-height: 0.8;
      text-transform: uppercase;
      letter-spacing: -0.06em;
      color: #fff;
      mix-blend-mode: normal;
      text-shadow: 0 2px 8px rgba(0, 0, 0, 0.52);
      font-weight: 800;
      -webkit-text-fill-color: #fff;
      opacity: 1;
      z-index: 3;
      pointer-events: none;
    }

    .hero-title-overlay span {
      display: block;
      transform: translateX(0);
    }

    .hero-side {
      position: relative;
      border: 1px solid var(--line);
      background: #0f0f0f;
      min-height: 0;
      height: clamp(420px, 52vw, 760px);
      overflow: hidden;
    }

    .hero-side::before,
    .hero-side::after {
      content: '';
      position: absolute;
      left: 0;
      right: 0;
      height: 44px;
      pointer-events: none;
      z-index: 6;
    }

    .hero-side::before {
      top: 0;
      background: linear-gradient(to bottom, rgba(12, 12, 12, 0.86), rgba(12, 12, 12, 0));
    }

    .hero-side::after {
      bottom: 0;
      background: linear-gradient(to top, rgba(12, 12, 12, 0.9), rgba(12, 12, 12, 0));
    }

    .hero-side-viewport {
      height: 100%;
      overflow: auto;
      scrollbar-width: none;
      -ms-overflow-style: none;
      position: relative;
      z-index: 2;
    }

    .hero-side-viewport::-webkit-scrollbar {
      display: none;
    }

    .hero-side-track {
      display: grid;
      gap: 10px;
      padding: 10px;
    }

    .hero-card {
      border: 1px solid var(--line);
      background: #0f0f0f;
      min-height: 180px;
      display: block;
      color: inherit;
      text-decoration: none;
      position: relative;
      overflow: hidden;
      transition: transform 0.25s ease, border-color 0.25s ease, box-shadow 0.25s ease;
    }

    .hero-card img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      filter: grayscale(18%);
      display: block;
      transition: transform 0.35s ease, filter 0.35s ease;
    }

    .hero-card:hover {
      border-color: #f0f0f0;
      transform: translateY(-2px);
      box-shadow: 0 12px 28px rgba(0, 0, 0, 0.38);
    }

    .hero-card:hover img {
      transform: scale(1.035);
      filter: grayscale(6%);
    }

    .hero-card:focus-visible {
      outline: 1px solid #f0f0f0;
      outline-offset: -1px;
      border-color: #f0f0f0;
    }

    .hero-card-meta {
      position: absolute;
      left: 10px;
      right: 10px;
      bottom: 10px;
      border: 1px solid #2f2f2f;
      background: rgba(0, 0, 0, 0.76);
      color: #f3f3f3;
      padding: 7px 8px;
      display: grid;
      gap: 4px;
      backdrop-filter: blur(1.6px);
    }

    .hero-card-artist {
      margin: 0;
      font-family: 'Space Mono', monospace;
      font-size: 9px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: #d8ff5a;
    }

    .hero-card-title {
      margin: 0;
      font-size: 12px;
      line-height: 1.25;
      color: #f5f5f5;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .hero-card-match {
      margin: 0;
      font-family: 'Space Mono', monospace;
      font-size: 9px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: #d0d0d0;
    }

    .hero-empty {
      position: absolute;
      left: 12px;
      bottom: 12px;
      border: 1px solid #313131;
      background: rgba(0, 0, 0, 0.72);
      padding: 6px 8px;
      color: #ececec;
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }

    .hero-stats {
      margin-top: 8px;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
    }

    .stat-card {
      border: 1px solid var(--line);
      background: #0f0f0f;
      padding: 10px;
      min-height: 72px;
    }

    .stat-card.accent {
      background: var(--lime);
      color: #090909;
      border-color: #bddd45;
    }

    .stat-label {
      margin: 0 0 6px;
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.09em;
      text-transform: uppercase;
      color: inherit;
      opacity: 0.85;
    }

    .stat-value {
      margin: 0;
      font-size: clamp(20px, 2.6vw, 36px);
      line-height: 0.92;
      letter-spacing: -0.03em;
      font-weight: 700;
      color: inherit;
    }

    .marquee {
      margin-top: 8px;
      border: 1px solid var(--line);
      background: #0d0d0d;
      overflow: hidden;
      white-space: nowrap;
    }

    .marquee-track {
      display: inline-flex;
      gap: 18px;
      padding: 7px 0;
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #cbcbcb;
      animation: ticker 42s linear infinite;
    }

    @media (min-width: 1321px) {
      .hero-visual {
        height: clamp(280px, 38vh, 420px);
      }
    }

    @keyframes ticker {
      0% { transform: translateX(0); }
      100% { transform: translateX(-50%); }
    }

    .atlas-layout {
      display: grid;
      grid-template-columns: minmax(240px, 0.55fr) minmax(620px, 1.45fr);
      gap: 12px;
      align-items: start;
      height: auto;
    }

    .artist-stack {
      border: 1px solid var(--line);
      background: #101010;
      padding: 10px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      min-height: 0;
      height: auto;
      max-height: none;
      align-self: start;
      overflow: hidden;
    }

    .artist-grid {
      --artist-card-height: 160px;
      --artist-card-overlap: 114px;
      --artist-card-step: calc(var(--artist-card-height) - var(--artist-card-overlap));
      --artist-cards-visible: 10;
      display: flex;
      flex-direction: column;
      flex: 0 0 auto;
      min-height: 0;
      height: calc(var(--artist-card-height) + (var(--artist-cards-visible) - 1) * var(--artist-card-step));
      max-height: calc(var(--artist-card-height) + (var(--artist-cards-visible) - 1) * var(--artist-card-step));
      overflow: auto;
      overscroll-behavior: contain;
      padding: 2px 10px 80px 2px;
      scroll-snap-type: y proximity;
    }

    .artist-card {
      border: 1px solid var(--line);
      background: #0f0f0f;
      height: var(--artist-card-height);
      margin-top: calc(-1 * var(--artist-card-overlap));
      flex: 0 0 auto;
      overflow: hidden;
      position: relative;
      cursor: pointer;
      transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
      will-change: transform;
      scroll-snap-align: start;
    }

    .artist-card:first-child {
      margin-top: 0;
    }

    .artist-card,
    .artist-grid:hover .artist-card,
    .artist-card:hover,
    .artist-card.hover-latched {
      opacity: 1 !important;
    }

    .artist-grid:hover .artist-card {
      opacity: 1;
    }

    .artist-card:hover {
      transform: translateY(12px);
      border-color: #fff;
      opacity: 1;
      z-index: 400 !important;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
    }

    .artist-card.hover-latched {
      transform: translateY(12px);
      border-color: #fff;
      opacity: 1;
      z-index: 400 !important;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
    }

    .artist-card.focus {
      border-color: var(--lime);
      outline: 2px solid var(--lime);
      outline-offset: -2px;
    }

    .artist-card.selected {
      border-color: var(--lime);
      box-shadow: inset 0 0 0 1px var(--lime);
    }

    @media (hover: hover) and (pointer: fine) {
      .artist-grid.selected-dock .artist-card.selected {
        transform: none;
        box-shadow: inset 0 0 0 1px var(--lime);
      }
    }

    .artist-card img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
      filter: grayscale(14%);
    }

    .artist-detail {
      position: absolute;
      left: 8px;
      right: 8px;
      bottom: 8px;
      background: rgba(38, 38, 38, 0.82);
      border: 1px solid #585858;
      padding: 8px;
      display: grid;
      gap: 4px;
      opacity: 1;
      transform: none;
      transition: border-color 0.2s ease, background 0.2s ease;
      pointer-events: auto;
      backdrop-filter: blur(1.4px);
    }

    .artist-card:hover .artist-detail {
      border-color: #d0d0d0;
      background: rgba(46, 46, 46, 0.86);
    }

    .artist-card.hover-latched .artist-detail {
      border-color: #d0d0d0;
      background: rgba(46, 46, 46, 0.86);
    }

    .artist-card.selected .artist-detail {
      border-color: var(--lime);
    }

    .artist-detail h3 {
      margin: 0;
      font-size: 20px;
      line-height: 0.92;
      letter-spacing: -0.02em;
      text-transform: uppercase;
      color: #fff;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .artist-detail p {
      margin: 0;
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: #d3d3d3;
      white-space: nowrap;
    }

    .artist-meta-row {
      display: flex;
      align-items: center;
      justify-content: flex-start;
      gap: 6px;
      min-width: 0;
    }

    .artist-card .card-actions {
      display: flex;
      justify-content: flex-start;
      gap: 4px;
      flex: 0 0 auto;
      flex-wrap: nowrap;
    }

    .artist-card .card-actions .chip-btn {
      white-space: nowrap;
      font-size: 9px;
      padding: 3px 6px;
    }

    .artist-card .card-actions .chip-btn.active {
      border-color: var(--line);
      color: #f1f1f1;
    }

    .chip-btn {
      border: 1px solid var(--line);
      background: #171717;
      color: #f1f1f1;
      font-size: 10px;
      letter-spacing: 0.07em;
      text-transform: uppercase;
      padding: 5px 8px;
      font-family: 'Space Mono', monospace;
      cursor: pointer;
    }

    .chip-btn:hover { border-color: #fff; }
    .chip-btn.active { border-color: var(--violet); color: var(--violet); }
    .chip-btn.lime { border-color: var(--lime); color: var(--lime); }

    .atlas-panel {
      border: 1px solid var(--line);
      background: var(--paper-2);
      padding: 12px;
      display: grid;
      gap: 10px;
      align-content: start;
      min-height: 0;
      height: auto;
      overflow: visible;
    }

    .focus-header {
      border: 1px solid var(--line);
      background: #101010;
      padding: 10px;
      display: grid;
      gap: 8px;
    }

    .focus-names {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: flex-end;
    }

    .focus-names.single {
      display: block;
    }

    .focus-names.single .focus-name {
      display: inline-flex;
      align-items: center;
      margin: 0;
      font-size: clamp(28px, 4vw, 62px);
      line-height: 0.85;
      letter-spacing: -0.04em;
      text-transform: uppercase;
      color: #fff;
      border: none;
      background: transparent;
      padding: 0;
    }

    .focus-names.multi {
      font-size: clamp(28px, 3.4vw, 56px);
      line-height: 0.86;
      letter-spacing: -0.04em;
      text-transform: uppercase;
    }

    .focus-names.multi .focus-name {
      display: inline-flex;
      align-items: flex-start;
      gap: 4px;
      margin: 0;
      font-size: 1em;
      line-height: inherit;
      letter-spacing: inherit;
      text-transform: inherit;
      color: #fff;
      border: none;
      background: transparent;
      padding: 0;
    }

    .focus-sep {
      font-size: 1em;
      line-height: inherit;
      letter-spacing: inherit;
      color: #bdbdbd;
      margin: 0 2px;
      user-select: none;
    }

    .focus-names.multi.compact {
      font-size: clamp(20px, 2.5vw, 38px);
    }

    .focus-remove {
      border: 1px solid #333333;
      background: rgba(18, 18, 18, 0.75);
      color: #8a8a8a;
      width: 14px;
      height: 14px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-family: 'Space Mono', monospace;
      font-size: 9px;
      line-height: 1;
      padding: 0;
      margin-top: 5px;
      cursor: pointer;
      text-transform: uppercase;
      opacity: 0.96;
    }

    .focus-remove:hover {
      color: #d2d2d2;
      border-color: #5a5a5a;
      opacity: 1;
    }

    .focus-toolbar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }

    .focus-mode {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    .focus-summary {
      margin: 0;
      font-size: 12px;
      color: #bbbbbb;
      line-height: 1.45;
    }

    .focus-stats {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
    }

    .focus-tile {
      border: 1px solid var(--line);
      background: #0f0f0f;
      padding: 8px;
    }

    .focus-tile p {
      margin: 0 0 6px;
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: #bdbdbd;
    }

    .focus-tile h4 {
      margin: 0;
      font-size: 18px;
      line-height: 1;
      letter-spacing: -0.02em;
    }

    .taxonomy-panel,
    .evidence-panel,
    .network-panel,
    .pair-panel,
    .set-panel {
      border: 1px solid var(--line);
      background: #101010;
      padding: 10px;
    }

    .taxonomy-workbench {
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
      align-items: start;
    }

    .evidence-panel {
      display: none;
    }

    .evidence-panel.open {
      display: block;
    }

    .panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 8px;
    }

    .panel-title {
      margin: 0;
      font-size: 18px;
      text-transform: uppercase;
      letter-spacing: -0.01em;
    }

    .panel-copy {
      margin: 0;
      font-size: 12px;
      color: #bababa;
      line-height: 1.45;
    }

    .selected-chips,
    .lens-tabs,
    .pill-row,
    .row-meta,
    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    .chip {
      border: 1px solid var(--line);
      background: #161616;
      color: #e4e4e4;
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: 4px 7px;
    }

    .controls-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin-top: 8px;
    }

    .taxonomy-controls-bar {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: nowrap;
      overflow-x: auto;
      overflow-y: hidden;
      margin-top: 6px;
      padding-bottom: 4px;
      margin-bottom: 6px;
      border-bottom: 1px solid #2a2a2a;
    }

    .taxonomy-head {
      flex-wrap: nowrap;
      overflow-x: auto;
      overflow-y: hidden;
      padding-bottom: 2px;
    }

    .taxonomy-head .panel-title {
      flex: 0 0 auto;
    }

    .taxonomy-head .lens-tabs {
      flex: 1 1 auto;
      flex-wrap: nowrap;
      justify-content: flex-end;
    }

    .taxonomy-head .chip-btn {
      white-space: nowrap;
      flex: 0 0 auto;
    }

    .taxonomy-controls-bar .pill-row {
      flex-wrap: nowrap;
      flex: 0 0 auto;
      gap: 4px;
    }

    .taxonomy-controls-bar .chip-btn {
      white-space: nowrap;
      flex: 0 0 auto;
      padding: 3px 6px;
      font-size: 9px;
    }

    .threshold-stepper {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      flex: 0 0 auto;
    }

    .threshold-stepper .threshold-arrow {
      width: 20px;
      min-width: 20px;
      padding: 3px 0;
      text-align: center;
      font-size: 10px;
      line-height: 1;
    }

    .threshold-stepper .threshold-value {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 82px;
      border-color: #3a3a3a;
      color: #f0f0f0;
      pointer-events: none;
      cursor: default;
    }

    .threshold-stepper .threshold-arrow:disabled {
      opacity: 0.35;
      cursor: not-allowed;
    }

    .taxonomy-controls-row {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: nowrap;
      margin-left: auto;
      flex: 0 0 auto;
      min-width: 0;
    }

    .taxonomy-search-control {
      flex: 0 0 clamp(170px, 24vw, 260px);
      min-width: 0;
    }

    .taxonomy-controls-row .control {
      min-width: 0;
      display: flex;
      align-items: center;
      gap: 4px;
      flex: 0 0 clamp(120px, 16vw, 170px);
    }

    .taxonomy-controls-bar .control input,
    .taxonomy-controls-bar .control select {
      height: 18px;
      min-height: 18px;
      padding: 0 6px;
      font-size: 10px;
      line-height: 18px;
    }

    .taxonomy-controls-row input,
    .taxonomy-controls-row select {
      height: 18px;
      padding: 0 6px;
      font-size: 10px;
    }

    .taxonomy-sort-icon {
      color: #c6c6c6;
      font-family: 'Space Mono', monospace;
      font-size: 12px;
      line-height: 1;
      flex: 0 0 auto;
      user-select: none;
    }

    .control {
      display: grid;
      gap: 5px;
    }

    .control label {
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.07em;
      text-transform: uppercase;
      color: #c3c3c3;
    }

    .control input,
    .control select {
      border: 1px solid var(--line);
      background: #171717;
      color: #f0f0f0;
      height: 34px;
      padding: 6px 8px;
      font-size: 13px;
      border-radius: 0;
      width: 100%;
    }

    .control input:focus,
    .control select:focus {
      outline: none;
      border-color: var(--lime);
    }

    .rows {
      display: grid;
      gap: 6px;
      max-height: none;
      overflow: visible;
      padding-right: 0;
    }

    .quant-row {
      border: 1px solid var(--line);
      background: #131313;
      padding: 5px 7px;
      display: grid;
      gap: 4px;
      cursor: default;
    }

    .quant-row:hover { border-color: #f0f0f0; }
    .quant-row.active { border-color: var(--lime); }

    .row-hit {
      border: 0;
      background: transparent;
      padding: 0;
      margin: 0;
      width: 100%;
      text-align: left;
      color: inherit;
      display: block;
      cursor: pointer;
      font: inherit;
    }

    .row-line {
      display: grid;
      grid-template-columns: clamp(120px, 16vw, 180px) minmax(0, 1fr) auto;
      align-items: center;
      gap: 6px;
    }

    .row-name {
      font-size: 13px;
      line-height: 1.1;
      color: #fff;
      min-width: 0;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .row-count {
      font-family: 'Space Mono', monospace;
      font-size: 11px;
      color: #cfcfcf;
      letter-spacing: 0.05em;
    }

    .bar {
      height: 6px;
      border: 1px solid #2e2e2e;
      background: #0d0d0d;
      position: relative;
      overflow: hidden;
    }

    .bar > span {
      position: absolute;
      inset: 0 auto 0 0;
      background: var(--lime);
      width: 0;
    }

    .inline-evidence {
      margin-top: 8px;
      border-top: 1px solid #2f3b1a;
      padding-top: 8px;
      display: grid;
      gap: 8px;
      background: #0f1210;
      border: 1px solid #273122;
      padding: 8px;
    }

    .inline-evidence .evidence-grid {
      grid-auto-columns: calc((100% - 24px) / 5);
      gap: 6px;
    }

    .inline-evidence .track-body {
      padding: 6px;
      gap: 5px;
    }

    .inline-evidence .track-title {
      font-size: 12px;
      line-height: 1.2;
    }

    .inline-evidence .muted {
      font-size: 10px;
      line-height: 1.35;
    }

    .inline-evidence .chip {
      font-size: 9px;
      padding: 2px 4px;
    }

    .inline-evidence .actions {
      gap: 4px;
    }

    .inline-evidence .actions a,
    .inline-evidence .actions button {
      font-size: 9px;
      padding: 3px 5px;
    }

    .inline-evidence .inline-head {
      margin: 0;
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: #bfc5b2;
    }

    .inline-evidence .inline-head-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
      flex-wrap: wrap;
    }

    .inline-evidence .inline-head-actions {
      display: flex;
      align-items: center;
      gap: 4px;
    }

    .inline-evidence .inline-head-actions a {
      border: 1px solid var(--line);
      background: #171717;
      color: #f0f0f0;
      font-family: 'Space Mono', monospace;
      font-size: 9px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: 3px 5px;
      text-decoration: none;
    }

    .inline-evidence .inline-head-actions a:hover {
      border-color: #fff;
    }

    .inline-evidence .inline-head-actions a.discogs {
      border-color: #7db8f2;
      color: #7db8f2;
    }

    .pager {
      margin-top: 8px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
    }

    .pager .info {
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      color: #bdbdbd;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }

    .pager button,
    .small-btn,
    .text-btn {
      border: 1px solid var(--line);
      background: #171717;
      color: #ececec;
      height: 30px;
      padding: 0 10px;
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      cursor: pointer;
    }

    .pager button:hover,
    .small-btn:hover,
    .text-btn:hover { border-color: #fff; }

    .evidence-grid {
      display: grid;
      grid-auto-flow: column;
      grid-auto-columns: minmax(260px, 330px);
      overflow-x: auto;
      overflow-y: visible;
      padding-bottom: 6px;
      gap: 10px;
    }

    .pair-track-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }

    .set-grid {
      column-count: 4;
      column-gap: 10px;
    }

    .track-card,
    .pair-track-card,
    .set-card {
      border: 1px solid var(--line);
      background: #0f0f0f;
      overflow: hidden;
    }

    .set-card {
      display: inline-block;
      width: 100%;
      margin: 0 0 10px;
      break-inside: avoid;
      vertical-align: top;
      position: relative;
      overflow: visible;
    }

    .track-art,
    .set-thumb {
      aspect-ratio: 1 / 1;
      border-bottom: 1px solid var(--line);
      background: #141414;
      position: relative;
      overflow: hidden;
    }

    .track-art img,
    .set-thumb img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
      filter: grayscale(18%);
    }

    .set-title a,
    .set-thumb a {
      color: inherit;
      text-decoration: none;
    }

    .set-thumb a {
      display: block;
      width: 100%;
      height: 100%;
    }

    .set-title a {
      border-bottom: 1px solid transparent;
    }

    .set-title a:hover {
      border-color: var(--lime);
    }

    .track-body,
    .set-body,
    .pair-track-body {
      padding: 10px;
      display: grid;
      gap: 8px;
    }

    .track-card .track-body {
      position: relative;
    }

    .track-title,
    .set-title,
    .pair-track-title {
      margin: 0;
      font-size: 16px;
      line-height: 1.25;
      color: #fff;
    }

    .muted {
      margin: 0;
      color: #bdbdbd;
      font-size: 12px;
      line-height: 1.45;
    }

    .muted a {
      color: #d8d8d8;
      text-decoration: underline;
      text-decoration-color: #323232;
      text-underline-offset: 2px;
    }

    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    .actions a,
    .actions button {
      border: 1px solid var(--line);
      background: #171717;
      color: #f0f0f0;
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: 5px 8px;
      cursor: pointer;
      text-decoration: none;
    }

    .actions a:hover,
    .actions button:hover { border-color: #fff; }

    .actions .spotify {
      border-color: #1db954;
      color: #1db954;
    }

    .source-panel {
      border-top: 1px solid var(--line);
      margin-top: 8px;
      padding-top: 8px;
      display: none;
      gap: 8px;
    }

    .source-panel.open { display: grid; }

    .source-group {
      border: 1px solid var(--line);
      background: #151515;
      padding: 8px;
      display: grid;
      gap: 6px;
    }

    .source-group h5 {
      margin: 0;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: #d8d8d8;
      font-family: 'Space Mono', monospace;
    }

    .source-group h5 a {
      color: inherit;
      text-decoration: underline;
      text-decoration-color: #343434;
      text-underline-offset: 2px;
    }

    .source-list {
      margin: 0;
      padding-left: 18px;
      display: grid;
      gap: 4px;
    }

    .source-list li {
      color: #d8d8d8;
      font-size: 12px;
      line-height: 1.35;
    }

    .source-list li::marker {
      color: var(--lime);
    }

    .source-list a {
      color: #efefef;
      text-decoration: underline;
      text-decoration-color: #343434;
      text-underline-offset: 2px;
    }

    .source-empty {
      margin: 0;
      color: #a9a9a9;
      font-size: 12px;
    }

    .spotify-embed {
      grid-column: 1 / -1;
      margin-top: 8px;
      border: 0;
      background: transparent;
      padding: 0;
    }

    .spotify-embed iframe {
      border: 0;
      width: 100%;
      height: 160px;
      border-radius: 14px;
    }

    .evidence-grid .track-card.embed-open,
    .inline-evidence .track-card.embed-open,
    .evidence-grid .track-card.sources-open,
    .inline-evidence .track-card.sources-open {
      width: calc(200% + 10px);
      height: var(--open-card-height, auto);
      overflow: hidden;
      z-index: 40;
    }

    .track-card.embed-open .track-art,
    .track-card.sources-open .track-art {
      aspect-ratio: auto;
      height: var(--open-art-height, 260px);
    }

    .track-card.embed-open .track-body {
      height: var(--open-body-height, auto);
      padding: 0;
      overflow: hidden;
      display: grid;
      grid-template-rows: auto var(--open-embed-height, 91.2px);
      gap: 0;
      align-content: start;
    }

    .track-card.sources-open .track-body {
      height: var(--open-body-height, auto);
      padding: 0;
      overflow: hidden;
      display: grid;
      grid-template-rows: auto var(--open-source-height, 91.2px);
      gap: 0;
      align-content: start;
    }

    .track-card.embed-open .track-body > .track-title,
    .track-card.embed-open .track-body > .muted,
    .track-card.embed-open .track-body > .source-panel {
      display: none;
    }

    .track-card.sources-open .track-body > .track-title,
    .track-card.sources-open .track-body > .muted {
      display: none;
    }

    .track-card.embed-open .track-body > .actions,
    .track-card.sources-open .track-body > .actions {
      margin: 0;
      padding: 6px 6px 4px;
      border-bottom: 1px solid var(--line);
      background: #0f0f0f;
      gap: 6px;
      flex-wrap: nowrap;
      overflow-x: auto;
      z-index: 3;
    }

    .track-card .track-body .spotify-embed {
      display: none;
      margin: 0;
      height: 100%;
      position: relative;
      overflow: hidden;
    }

    .track-card.embed-open .track-body .spotify-embed {
      display: block;
      padding: 0;
      width: 100%;
      height: var(--open-embed-height, 91.2px);
      display: flex;
      align-items: flex-start;
    }

    .track-card.sources-open .track-body .source-panel {
      display: none;
    }

    .track-card.sources-open .track-body .source-panel.open {
      display: grid;
      margin: 0;
      padding: 6px;
      border-top: 0;
      width: 100%;
      height: var(--open-source-height, 91.2px);
      overflow-y: auto;
      overflow-x: hidden;
      gap: 6px;
      align-content: start;
      box-sizing: border-box;
    }

    .evidence-grid .track-card.embed-open:nth-child(even),
    .inline-evidence .track-card.embed-open:nth-child(even),
    .evidence-grid .track-card.sources-open:nth-child(even),
    .inline-evidence .track-card.sources-open:nth-child(even) {
      margin-left: calc(-100% - 10px);
    }

    .track-card.embed-open .track-body .spotify-embed iframe {
      width: 100%;
      height: var(--open-embed-height, 91.2px);
      display: block;
      margin: 0;
      border-radius: 0;
    }

    .pair-track-card.embed-open .spotify-embed iframe {
      height: 196px;
    }

    .network-wrap {
      border: 1px solid var(--line);
      background: #0f0f0f;
      min-height: 560px;
      position: relative;
      overflow: hidden;
    }

    .network-svg {
      width: 100%;
      height: 560px;
      display: block;
    }

    .network-node {
      cursor: pointer;
      transition: r 0.2s ease;
    }

    .network-node:hover { r: 14; }
    .network-node.focus { stroke: var(--lime); stroke-width: 3; }
    .network-node.selected { stroke: var(--violet); stroke-width: 3; }

    .network-controls {
      display: flex;
      align-items: flex-end;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 0;
      margin-bottom: 10px;
    }

    .network-controls .control {
      flex: 0 1 clamp(180px, 24vw, 320px);
      min-width: 0;
    }

    .network-controls .network-clear-wrap {
      margin-left: auto;
      flex: 0 0 auto;
    }

    .pair-grid {
      display: grid;
      gap: 8px;
    }

    .pair-rows {
      display: grid;
      gap: 6px;
      max-height: none;
      overflow: visible;
      padding-right: 0;
    }

    .pair-row {
      border: 1px solid var(--line);
      background: #131313;
      padding: 5px 7px;
      display: grid;
      gap: 4px;
      cursor: pointer;
    }

    .pair-row:hover { border-color: #fff; }
    .pair-row.active { border-color: var(--lime); }

    .set-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
    }

    .set-pill {
      border: 1px solid #2c2c2c;
      background: #171717;
      color: #dcdcdc;
      font-size: 10px;
      font-family: 'Space Mono', monospace;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: 4px 6px;
    }

    .set-tracklist {
      position: absolute;
      left: 0;
      width: 100%;
      top: 100%;
      border: 1px solid var(--line);
      background: #101010;
      box-shadow: 0 18px 36px rgba(0, 0, 0, 0.45);
      padding: 10px;
      display: none;
      gap: 6px;
      max-height: 260px;
      overflow: auto;
      padding-right: 2px;
      z-index: 40;
      box-sizing: border-box;
    }

    .set-tracklist.open { display: grid; }

    .set-track {
      border: 1px solid var(--line);
      background: #161616;
      padding: 6px;
      display: grid;
      grid-template-columns: auto 1fr auto;
      gap: 6px;
      align-items: center;
      font-size: 12px;
    }

    .set-track-time {
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      color: #cbcbcb;
      min-width: 48px;
    }

    .set-track-conf {
      font-family: 'Space Mono', monospace;
      font-size: 10px;
      padding: 2px 5px;
      border: 1px solid #333;
      color: #cfcfcf;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }

    .footer {
      border: 1px solid var(--line);
      background: #111;
      padding: var(--section-pad);
      margin-top: var(--gutter);
    }

    .footer h2 {
      margin: 0;
      font-size: clamp(32px, 8vw, 120px);
      line-height: 0.88;
      letter-spacing: -0.04em;
      text-transform: uppercase;
    }

    .footer p {
      margin: 10px 0 0;
      max-width: 780px;
      font-size: 13px;
      color: #c6c6c6;
      line-height: 1.6;
    }

    .empty {
      border: 1px solid var(--line);
      background: #131313;
      color: #bcbcbc;
      padding: 12px;
      font-size: 12px;
      line-height: 1.45;
    }

    .reveal {
      opacity: 1;
      transform: none;
      transition: opacity 0.45s ease, transform 0.45s ease;
    }

    .reveal.in {
      opacity: 1;
      transform: translateY(0);
    }

    @media (max-width: 1320px) {
      .taxonomy-workbench { grid-template-columns: 1fr; }
      .pair-track-grid { grid-template-columns: 1fr; }
      .set-grid { column-count: 2; }
      .hero-grid { grid-template-columns: 1fr; }
      .hero-side {
        height: auto !important;
        min-height: clamp(280px, 58vw, 430px);
      }
      .focus-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .controls-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }

    @media (max-width: 980px) {
      .section-head { grid-template-columns: 1fr; }
      .section-head p { justify-self: start; max-width: 100%; }
      .atlas-layout { grid-template-columns: 1fr; align-items: start; height: auto; }
      .artist-stack,
      .atlas-panel { height: auto; }
      .atlas-panel { overflow: visible; }
      .artist-grid { max-height: 210px; }
      .hero-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .set-grid { column-count: 2; }
      .topnav { display: none; }
    }

    @media (max-width: 680px) {
      .hero-side {
        min-height: clamp(240px, 72vw, 340px);
      }
      .artist-grid {
        --artist-card-height: 132px;
        --artist-card-overlap: 74px;
      }
      .evidence-grid {
        grid-auto-columns: minmax(240px, 82vw);
      }
      .pair-track-grid { grid-template-columns: 1fr; }
      .set-grid { column-count: 1; }
      .controls-grid { grid-template-columns: 1fr; }
      .focus-stats { grid-template-columns: 1fr 1fr; }
      .section-head h2 { font-size: clamp(34px, 15vw, 58px); }
      .hero-title-overlay { font-size: clamp(58px, 22vw, 120px); }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <div class="logo">[SET SIGNAL ARCHIVE]</div>
      <nav class="topnav">
        <a href="#artists">Artist Atlas</a>
        <a href="#network">Artist Network</a>
        <a href="#sets">Set Library</a>
      </nav>
    </header>

    <section class="hero reveal" id="top">
      <div class="section-inner">
        <span class="kicker">Outcome-Driven Music Intelligence</span>
        <div class="hero-grid">
          <div class="hero-main">
            <div class="hero-visual" id="heroVisual"></div>
            <div class="hero-stats" id="heroStats"></div>
          </div>
          <div class="hero-side" id="heroSide"></div>
        </div>
        <div class="marquee"><div class="marquee-track" id="heroTicker"></div></div>
      </div>
    </section>

    <section class="section reveal" id="artists">
      <div class="section-inner">
        <div class="section-head">
          <h2>ARTIST ATLAS</h2>
          <p>
            Select artists to compare and drill into the right-side taxonomy atlas to investigate genres, labels, artists, and tracks.
          </p>
        </div>

        <div class="atlas-layout">
          <div class="artist-stack">
            <div class="control">
              <label for="artistSearch">Search Artists</label>
              <input id="artistSearch" type="text" placeholder="find artist cards" />
            </div>
            <div class="artist-grid" id="artistGrid"></div>
          </div>

          <aside class="atlas-panel">
            <div class="focus-header" id="focusHeader"></div>

            <div class="taxonomy-workbench">
              <div class="taxonomy-panel">
                <div class="panel-head taxonomy-head">
                  <h3 class="panel-title">Taxonomy Atlas</h3>
                  <div class="lens-tabs" id="taxonomyTabs"></div>
                </div>

                <div class="taxonomy-controls-bar">
                  <div class="control taxonomy-search-control">
                    <input id="taxonomySearch" type="text" placeholder="search" aria-label="Search taxonomy entries" />
                  </div>
                  <div class="taxonomy-controls-row">
                    <div class="pill-row" id="taxonomyThresholds"></div>
                    <div class="pill-row" id="taxonomyTrackConfFilters"></div>
                    <div class="control taxonomy-sort-control">
                      <span class="taxonomy-sort-icon" aria-hidden="true">&#8597;</span>
                      <select id="taxonomySort" aria-label="Sort taxonomy entries">
                        <option value="count">Highest Usage</option>
                        <option value="alpha">Alphabetical</option>
                      </select>
                    </div>
                  </div>
                </div>

                <div class="rows" id="taxonomyRows"></div>
                <div class="pager" id="taxonomyPager"></div>
              </div>

              <div class="evidence-panel" id="taxonomyEvidencePanel">
                <div class="panel-head">
                  <h3 class="panel-title">Evidence Tracks</h3>
                  <p class="panel-copy" id="evidenceSummary"></p>
                </div>
                <div class="evidence-grid" id="taxonomyEvidence"></div>
                <div class="pager" id="evidencePager"></div>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </section>

    <section class="section dark reveal" id="network">
      <div class="section-inner">
        <div class="section-head">
          <h2>ARTIST CONNECTION MAP</h2>
          <p>
            Any-to-any comparison map. Click nodes to add/remove artists in the compare basket. Click edges to open pair analysis.
          </p>
        </div>

        <div class="network-panel">
          <div class="network-controls">
            <div class="control">
              <label for="networkMinScore">Min Connection Score</label>
              <input id="networkMinScore" type="range" min="0" max="100" value="15" />
            </div>
            <div class="control">
              <label for="networkSearch">Find Artist</label>
              <input id="networkSearch" type="text" placeholder="search artist nodes" />
            </div>
            <div class="network-clear-wrap">
              <button id="networkClear" class="chip-btn" type="button" data-action="network-clear">Clear</button>
            </div>
          </div>

          <div class="network-wrap" id="networkWrap"></div>
        </div>

        <div class="pair-panel" style="margin-top: 12px;">
          <div class="panel-head taxonomy-head">
            <h3 class="panel-title" id="pairTitle">Pair Analysis Workspace</h3>
            <div class="lens-tabs" id="pairTabs"></div>
          </div>
          <p class="panel-copy" id="pairSummary"></p>

          <div class="taxonomy-controls-bar">
            <div class="control taxonomy-search-control">
              <input id="pairSearch" type="text" placeholder="search pair entries" aria-label="Search pair entries" />
            </div>
            <div class="taxonomy-controls-row">
              <div class="pill-row" id="pairThresholds"></div>
              <div class="pill-row" id="pairTrackConfFilters"></div>
              <div class="control taxonomy-sort-control">
                <span class="taxonomy-sort-icon" aria-hidden="true">&#8597;</span>
                <select id="pairSort" aria-label="Sort pair entries">
                  <option value="count">Highest Usage</option>
                  <option value="alpha">Alphabetical</option>
                </select>
              </div>
            </div>
          </div>

          <div class="rows" id="pairRows"></div>
          <div class="pager" id="pairPager"></div>
        </div>
      </div>
    </section>

    <section class="section reveal" id="sets">
      <div class="section-inner">
        <div class="section-head">
          <h2>FULL SET LIBRARY</h2>
          <p>
            Search across all processed sets, filter by artist, and inspect tracklists.
          </p>
        </div>

        <div class="set-panel">
          <div class="controls-grid" style="margin-top: 0; margin-bottom: 10px;">
            <div class="control">
              <label for="setSearch">Search Sets</label>
              <input id="setSearch" type="text" placeholder="set title, artist, track" />
            </div>
            <div class="control">
              <label for="setArtistFilter">Artist Filter</label>
              <select id="setArtistFilter"></select>
            </div>
            <div class="control">
              <label for="setSort">Sort</label>
              <select id="setSort">
                <option value="default">Default</option>
                <option value="rate">Recognition Rate</option>
                <option value="tracks">Track Count</option>
                <option value="duration">Duration</option>
              </select>
            </div>
          </div>

          <div class="set-grid" id="setGrid"></div>
          <div class="pager" id="setPager"></div>
        </div>
      </div>
    </section>

    <footer class="footer reveal">
      <h2>FOLLOW THE CURATION SIGNAL</h2>
      <p>
        Generated from local archive data on <span id="generatedAt"></span>.
        This experience is designed for investigation depth: compare artists, inspect overlap logic, and follow evidence to concrete tracks and sets.
      </p>
    </footer>
  </div>

  <script>
    window.EXPLORER_DATA = __PAYLOAD__;
  </script>
  <script>
    const DATA = window.EXPLORER_DATA;

    const PAGE = {
      taxonomy: 10,
      evidence: 9,
      pairRows: 10,
      sets: 24,
    };

    const CONF_COLOR = {
      HIGH: '#00e676',
      MEDIUM: '#ffd740',
      LOW: '#ff9100',
      UNCERTAIN: '#757575',
    };

    const STATE = {
      focusArtist: DATA.artists[0] ? DATA.artists[0].name : null,
      selectedArtists: new Set(DATA.artists[0] ? [DATA.artists[0].name] : []),
      dockedSelectedArtists: new Set(DATA.artists[0] ? [DATA.artists[0].name] : []),
      hoverLatchedArtist: null,
      artistPanePointerInside: false,
      artistQuery: '',
      compareMode: 'union',
      taxonomyLens: 'genres',
      taxonomyQuery: '',
      taxonomySort: 'count',
      taxonomyMinUsage: 1,
      taxonomyTrackConf: 'all',
      taxonomyPage: 0,
      taxonomyActiveName: null,
      taxonomyEvidencePage: 0,
      networkMinScore: 15,
      networkSearch: '',
      networkSelectedArtists: new Set(),
      pair: null,
      pairLens: 'genres',
      pairQuery: '',
      pairSort: 'count',
      pairMinUsage: 1,
      pairTrackConf: 'all',
      pairPage: 0,
      pairActiveName: null,
      setQuery: '',
      setArtist: 'ALL',
      setSort: 'default',
      setPage: 0,
      expandedSets: new Set(),
    };

    let heroRailRaf = 0;
    let heroRailLastTs = 0;

    const $ = (id) => document.getElementById(id);
    const fmt = (n) => Number(n || 0).toLocaleString();
    const CONF_FILTER_LEVELS = ['HIGH', 'MEDIUM', 'LOW'];
    const THRESHOLD_LEVELS = [1, 2, 3, 5, 8, 12];

    function isHoverCapablePointer() {
      return window.matchMedia('(hover: hover) and (pointer: fine)').matches;
    }

    const artistsByName = new Map(DATA.artists.map((a) => [a.name, a]));

    const similarityByKey = new Map();
    for (const row of DATA.similarity || []) {
      if (!row.artist_a || !row.artist_b) continue;
      similarityByKey.set(pairKey(row.artist_a, row.artist_b), row);
    }

    function pairKey(a, b) {
      return a < b ? `${a}|||${b}` : `${b}|||${a}`;
    }

    function escapeHtml(value) {
      return String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    const EXTERNAL_HREF_RE = /^[a-zA-Z][a-zA-Z0-9+.-]*:/;
    const FRAGMENT_ID_RE = /^[A-Za-z][\w:-]*$/;

    function encodeLocalHref(value) {
      const raw = String(value == null ? '' : value).trim();
      if (!raw) return '';
      if (EXTERNAL_HREF_RE.test(raw) || raw.startsWith('//')) return raw;

      let base = raw;
      let fragment = '';
      const hashIdx = raw.lastIndexOf('#');
      if (hashIdx >= 0) {
        const tail = raw.slice(hashIdx + 1);
        if (FRAGMENT_ID_RE.test(tail)) {
          base = raw.slice(0, hashIdx);
          fragment = `#${tail}`;
        }
      }

      return encodeURI(base).replace(/#/g, '%23') + fragment;
    }

    function extractSpotifyId(url) {
      if (!url) return '';
      const m = String(url).match(/track\/([A-Za-z0-9]+)/);
      return m ? m[1] : '';
    }

    function normalizeConfidence(value) {
      const conf = String(value || 'UNCERTAIN').toUpperCase();
      return Object.prototype.hasOwnProperty.call(CONF_COLOR, conf) ? conf : 'UNCERTAIN';
    }

    function primaryConfidenceFromCounts(confCounts) {
      const ordered = ['HIGH', 'MEDIUM', 'LOW', 'UNCERTAIN'];
      let best = 'UNCERTAIN';
      let bestCount = -1;
      for (const level of ordered) {
        const count = Number((confCounts || {})[level] || 0);
        if (count > bestCount) {
          best = level;
          bestCount = count;
        }
      }
      return best;
    }

    function trackHasConfidence(track, level) {
      const target = normalizeConfidence(level);
      const counts = track && typeof track === 'object' ? (track.confidence_counts || {}) : {};
      const hasCounts = counts && typeof counts === 'object' && Object.keys(counts).length > 0;
      if (hasCounts) {
        return Number(counts[target] || 0) > 0;
      }
      return normalizeConfidence(track?.confidence) === target;
    }

    function trackMatchesConfidence(track, confFilter) {
      if (confFilter === 'all') return true;
      return trackHasConfidence(track, confFilter);
    }

    function filterTracksByConfidence(tracks, confFilter) {
      return (tracks || []).filter((track) => trackMatchesConfidence(track, confFilter));
    }

    function normalizeConfFilter(confFilter) {
      const raw = String(confFilter || 'all').toUpperCase();
      if (raw === 'ALL') return 'all';
      return CONF_FILTER_LEVELS.includes(raw) ? raw : 'all';
    }

    function filterSetRefsByConfidence(setRefs, confFilter) {
      const target = normalizeConfFilter(confFilter);
      if (target === 'all') return Array.isArray(setRefs) ? setRefs.slice() : [];
      return (setRefs || []).filter((setRef) => normalizeConfidence(setRef?.confidence) === target);
    }

    function projectTrackByConfidence(track, confFilter) {
      const target = normalizeConfFilter(confFilter);
      if (!track) return null;

      const refs = [];
      let selectedAppearances = 0;
      const confCounts = { HIGH: 0, MEDIUM: 0, LOW: 0, UNCERTAIN: 0 };

      for (const ref of (track.selected_refs || [])) {
        const setRefs = filterSetRefsByConfidence(ref?.set_refs || [], target);
        if (!setRefs.length) continue;
        refs.push({
          ...ref,
          set_refs: setRefs,
          appearances: setRefs.length,
        });
        for (const setRef of setRefs) {
          const conf = normalizeConfidence(setRef?.confidence);
          confCounts[conf] = Number(confCounts[conf] || 0) + 1;
          selectedAppearances += 1;
        }
      }

      if (selectedAppearances <= 0) return null;

      let confidence = normalizeConfidence(track.confidence);
      if (target === 'all') {
        confidence = primaryConfidenceFromCounts(confCounts);
      } else {
        for (const level of Object.keys(confCounts)) confCounts[level] = 0;
        confCounts[target] = selectedAppearances;
        confidence = target;
      }

      return {
        ...track,
        selected_refs: refs,
        selected_appearances: Number(selectedAppearances || 0),
        selected_artist_count: refs.length,
        confidence_counts: confCounts,
        confidence,
      };
    }

    function tracksWithConfidenceProjection(tracks, confFilter) {
      const out = [];
      for (const track of tracks || []) {
        const projected = projectTrackByConfidence(track, confFilter);
        if (!projected) continue;
        out.push(projected);
      }
      return out;
    }

    function trackMergeKey(track) {
      return String(track?.track_key || `${track?.artist || 'Unknown'} - ${track?.title || 'Unknown'}`).trim().toLowerCase();
    }

    function collectUniqueTracks(rows) {
      const merged = new Map();
      for (const row of rows || []) {
        for (const track of (row?.tracks || [])) {
          const key = trackMergeKey(track);
          if (!merged.has(key)) merged.set(key, track);
        }
      }
      return Array.from(merged.values());
    }

    function confidenceCountsFromTracks(tracks) {
      const counts = { HIGH: 0, MEDIUM: 0, LOW: 0 };
      for (const track of tracks || []) {
        for (const level of CONF_FILTER_LEVELS) {
          if (trackHasConfidence(track, level)) counts[level] += 1;
        }
      }
      return counts;
    }

    function normalizeThresholdValue(value, levels) {
      const options = (levels || []).map((v) => Number(v)).filter((v) => Number.isFinite(v) && v > 0).sort((a, b) => a - b);
      if (!options.length) return 1;
      const current = Number(value);
      if (Number.isFinite(current) && options.includes(current)) return current;
      if (!Number.isFinite(current)) return options[0];
      let fallback = options[0];
      for (const option of options) {
        if (option <= current) fallback = option;
      }
      return fallback;
    }

    function stepThresholdValue(value, levels, direction) {
      const options = (levels || []).map((v) => Number(v)).filter((v) => Number.isFinite(v) && v > 0).sort((a, b) => a - b);
      if (!options.length) return 1;
      const current = normalizeThresholdValue(value, options);
      const idx = options.indexOf(current);
      const nextIdx = Math.max(0, Math.min(options.length - 1, idx + (direction > 0 ? 1 : -1)));
      return options[nextIdx];
    }

    function renderThresholdStepper(containerId, downAction, upAction, currentValue, levels) {
      const mount = $(containerId);
      if (!mount) return;
      const options = (levels || []).map((v) => Number(v)).filter((v) => Number.isFinite(v) && v > 0).sort((a, b) => a - b);
      if (!options.length) {
        mount.innerHTML = '';
        return;
      }
      const current = normalizeThresholdValue(currentValue, options);
      const idx = options.indexOf(current);
      const canDown = idx > 0;
      const canUp = idx < options.length - 1;
      mount.innerHTML = `
        <div class="threshold-stepper">
          <button class="chip-btn threshold-arrow" data-action="${downAction}" ${canDown ? '' : 'disabled'} aria-label="Decrease set threshold">▼</button>
          <span class="chip-btn threshold-value">${fmt(current)}+ SETS</span>
          <button class="chip-btn threshold-arrow" data-action="${upAction}" ${canUp ? '' : 'disabled'} aria-label="Increase set threshold">▲</button>
        </div>
      `;
    }

    function renderConfidenceFilterButtons(containerId, action, active, tracks) {
      const mount = $(containerId);
      if (!mount) return;
      const total = (tracks || []).length;
      const buttons = [
        `<button class="chip-btn ${active === 'all' ? 'active' : ''}" data-action="${action}" data-conf="all">All (${fmt(total)})</button>`,
      ];
      for (const level of CONF_FILTER_LEVELS) {
        buttons.push(
          `<button class="chip-btn ${active === level ? 'active' : ''}" data-action="${action}" data-conf="${level}">${level}</button>`
        );
      }
      mount.innerHTML = buttons.join('');
    }

    function hashString(value) {
      let hash = 0;
      const str = String(value || '');
      for (let i = 0; i < str.length; i += 1) {
        hash = ((hash << 5) - hash) + str.charCodeAt(i);
        hash |= 0;
      }
      return Math.abs(hash);
    }

    function buildFallbackSvg(bg, fg, accent) {
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 800">
        <rect width="800" height="800" fill="${bg}"/>
        <rect x="40" y="44" width="720" height="26" fill="${fg}" opacity="0.65"/>
        <rect x="40" y="106" width="540" height="18" fill="${fg}" opacity="0.45"/>
        <rect x="40" y="158" width="640" height="10" fill="${fg}" opacity="0.25"/>
        <rect x="40" y="230" width="180" height="180" fill="${accent}" opacity="0.9"/>
        <rect x="248" y="230" width="512" height="180" fill="${fg}" opacity="0.2"/>
        <rect x="40" y="438" width="720" height="14" fill="${fg}" opacity="0.3"/>
        <rect x="40" y="478" width="420" height="92" fill="${fg}" opacity="0.22"/>
        <rect x="488" y="478" width="272" height="92" fill="${accent}" opacity="0.8"/>
        <rect x="40" y="608" width="720" height="150" fill="${fg}" opacity="0.15"/>
      </svg>`;
      return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
    }

    const FALLBACK_MEDIA = [
      buildFallbackSvg('#0b0b0b', '#f2f2f2', '#d8ff5a'),
      buildFallbackSvg('#101114', '#eceef2', '#7f51ff'),
      buildFallbackSvg('#0e1011', '#e4f4ff', '#d8ff5a'),
      buildFallbackSvg('#12100e', '#f6efe4', '#7f51ff'),
      buildFallbackSvg('#0c0f13', '#f1f5ff', '#d8ff5a'),
      buildFallbackSvg('#0f0c12', '#f3edf9', '#7f51ff'),
      buildFallbackSvg('#0f1110', '#e9f4e8', '#d8ff5a'),
      buildFallbackSvg('#100f0d', '#f3efe8', '#7f51ff'),
    ];

    function fallbackMedia(seed) {
      return FALLBACK_MEDIA[hashString(seed) % FALLBACK_MEDIA.length];
    }

    function captureArtistCardRects(grid) {
      const rects = new Map();
      if (!grid) return rects;
      grid.querySelectorAll('.artist-card[data-artist]').forEach((card) => {
        const name = card.dataset.artist;
        if (!name) return;
        rects.set(name, card.getBoundingClientRect());
      });
      return rects;
    }

    function animateArtistCardReflow(grid, beforeRects) {
      if (!grid || !beforeRects || !beforeRects.size || !isHoverCapablePointer()) return;
      grid.querySelectorAll('.artist-card[data-artist]').forEach((card) => {
        const name = card.dataset.artist;
        if (!name) return;
        const before = beforeRects.get(name);
        if (!before) return;
        const after = card.getBoundingClientRect();
        const dx = before.left - after.left;
        const dy = before.top - after.top;
        if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;

        card.style.transition = 'none';
        card.style.translate = `${dx}px ${dy}px`;
        card.getBoundingClientRect();
        card.style.transition = 'translate 320ms cubic-bezier(0.22, 1, 0.36, 1)';
        card.style.translate = '0px 0px';
        card.addEventListener('transitionend', () => {
          card.style.removeProperty('transition');
          card.style.removeProperty('translate');
        }, { once: true });
      });
    }

    function shuffledCopy(items) {
      const out = [...(items || [])];
      for (let i = out.length - 1; i > 0; i -= 1) {
        const j = Math.floor(Math.random() * (i + 1));
        const tmp = out[i];
        out[i] = out[j];
        out[j] = tmp;
      }
      return out;
    }

    function stopHeroRail() {
      if (heroRailRaf) {
        cancelAnimationFrame(heroRailRaf);
        heroRailRaf = 0;
      }
      heroRailLastTs = 0;
    }

    function syncHeroRailHeight() {
      const main = document.querySelector('.hero-main');
      const visual = $('heroVisual');
      const stats = $('heroStats');
      const side = $('heroSide');
      if (!main || !side) return;

      side.style.removeProperty('height');
      if (window.matchMedia('(max-width: 1320px)').matches) return;

      const mainH = main.getBoundingClientRect().height;
      const visualH = visual ? visual.getBoundingClientRect().height : 0;
      const statsH = stats ? stats.getBoundingClientRect().height : 0;
      const statsMarginTop = stats ? parseFloat(getComputedStyle(stats).marginTop || '0') : 0;
      const h = Math.round(visualH + statsMarginTop + statsH) || Math.round(mainH);
      if (h > 0 && h < 2200) {
        side.style.height = `${h}px`;
      }
    }

    function fitHeroToViewport() {
      const hero = document.querySelector('.hero');
      const visual = $('heroVisual');
      const kicker = hero?.querySelector('.kicker');
      const marquee = hero?.querySelector('.marquee');
      if (!hero || !visual || !kicker || !marquee) return;

      if (window.matchMedia('(max-width: 1320px)').matches) {
        visual.style.removeProperty('height');
        return;
      }

      const kickerRect = kicker.getBoundingClientRect();
      const marqueeRect = marquee.getBoundingClientRect();
      const visualRect = visual.getBoundingClientRect();
      if (visualRect.height <= 0) return;

      const currentSpan = marqueeRect.bottom - kickerRect.top;
      const desiredSpan = window.innerHeight - kickerRect.top - 2;
      const targetVisualHeight = visualRect.height + (desiredSpan - currentSpan);
      const clamped = Math.max(300, Math.min(620, targetVisualHeight));

      if (Number.isFinite(clamped)) {
        visual.style.height = `${Math.round(clamped)}px`;
      }
    }

    function startHeroRail() {
      stopHeroRail();
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      if (window.matchMedia('(max-width: 1320px)').matches) return;

      const viewport = $('heroSideViewport');
      const track = $('heroSideTrack');
      if (!viewport || !track) return;

      const cycleHeight = track.scrollHeight / 2;
      if (cycleHeight <= viewport.clientHeight + 4) return;

      if (!viewport.dataset.bound) {
        viewport.addEventListener('mouseenter', () => stopHeroRail());
        viewport.addEventListener('mouseleave', () => startHeroRail());
        viewport.dataset.bound = '1';
      }

      let scrollPos = viewport.scrollTop % cycleHeight;
      viewport.scrollTop = scrollPos;

      const pxPerSecond = 12;
      const tick = (ts) => {
        if (!heroRailRaf) return;
        if (!heroRailLastTs) heroRailLastTs = ts;
        const dt = (ts - heroRailLastTs) / 1000;
        heroRailLastTs = ts;
        scrollPos += pxPerSecond * dt;
        if (scrollPos >= cycleHeight) {
          scrollPos -= cycleHeight;
        }
        viewport.scrollTop = scrollPos;
        heroRailRaf = requestAnimationFrame(tick);
      };

      heroRailRaf = requestAnimationFrame(tick);
    }

    function selectedArtistsList() {
      const valid = Array.from(STATE.selectedArtists).filter((name) => artistsByName.has(name));
      if (!valid.length && STATE.focusArtist && artistsByName.has(STATE.focusArtist)) {
        valid.push(STATE.focusArtist);
        STATE.selectedArtists.add(STATE.focusArtist);
      }
      return valid;
    }

    function syncDockedSelectedArtists(commitAdds = false) {
      const next = new Set(
        Array.from(STATE.dockedSelectedArtists).filter((name) => STATE.selectedArtists.has(name))
      );
      if (commitAdds) {
        for (const name of STATE.selectedArtists) {
          if (artistsByName.has(name)) next.add(name);
        }
      }
      STATE.dockedSelectedArtists = next;
    }

    function networkSelectedArtistsList() {
      return Array.from(STATE.networkSelectedArtists).filter((name) => artistsByName.has(name));
    }

    function currentArtistScope() {
      const selected = selectedArtistsList();
      if (selected.length >= 2) return selected;
      if (STATE.focusArtist && artistsByName.has(STATE.focusArtist)) return [STATE.focusArtist];
      return selected;
    }

    function filteredArtists() {
      const q = STATE.artistQuery.trim().toLowerCase();
      return (DATA.artists || []).filter((artist) => {
        if (!q) return true;
        return String(artist.name || '').toLowerCase().includes(q);
      });
    }

    function buildHero() {
      const stats = DATA.global_stats || {};
      const allSets = DATA.all_sets || [];
      const candidateSets = allSets.filter((s) => (s.thumbnail_url || '').trim());
      const shuffledSets = shuffledCopy(candidateSets.length ? candidateSets : allSets);
      const railBase = shuffledSets;

      const railSets = [];
      if (railBase.length) {
        const targetCount = Math.max(8, Math.min(12, railBase.length * 2));
        for (let i = 0; i < targetCount; i += 1) {
          railSets.push(railBase[i % railBase.length]);
        }
      }

      const artistImagePool = (DATA.artists || [])
        .map((artist) => {
          const image = (artist.artist_profile_image || artist.artist_image || '').trim();
          if (!image) return null;
          return {
            name: artist.name || 'Artist',
            image,
          };
        })
        .filter(Boolean);
      const heroArtist = artistImagePool.length
        ? artistImagePool[Math.floor(Math.random() * artistImagePool.length)]
        : null;

      const heroImage = heroArtist?.image
        || DATA.artists.find((a) => a.cover_image)?.cover_image
        || DATA.track_catalog.find((t) => t.album_art)?.album_art;
      const heroAlt = heroArtist
        ? `${heroArtist.name} artist profile image`
        : 'Set signal visual';

      $('heroVisual').innerHTML = `
        ${heroImage ? `<img src="${heroImage}" alt="${escapeHtml(heroAlt)}" loading="eager" />` : ''}
        <h1 class="hero-title-overlay"><span>SET</span><span>SIGNAL</span></h1>
      `;

      const cards = [
        { label: 'Artists mapped', value: fmt(stats.total_artists), accent: true },
        { label: 'Sets analyzed', value: fmt(stats.total_sets) },
        { label: 'Unique tracks', value: fmt(stats.total_unique_tracks) },
        { label: 'Track appearances', value: fmt(stats.total_appearances) },
      ];

      $('heroStats').innerHTML = cards.map((card) => `
        <article class="stat-card ${card.accent ? 'accent' : ''}">
          <p class="stat-label">${card.label}</p>
          <p class="stat-value">${card.value}</p>
        </article>
      `).join('');

      const renderHeroSetCard = (s, idx) => {
        const setHref = encodeLocalHref(s.set_html_master_rel || '');
        const cardInner = `
          <img src="${s.thumbnail_url || fallbackMedia(`hero:${s.artist_name || ''}:${s.title || ''}:${idx}`)}" alt="${escapeHtml(s.title || 'Set')}" loading="lazy" />
          <div class="hero-card-meta">
            <p class="hero-card-artist">${escapeHtml(s.artist_name || 'Unknown Artist')}</p>
            <p class="hero-card-title">${escapeHtml(s.title || 'Unknown Set')}</p>
            <p class="hero-card-match">${Math.round(Number(s.recognition_rate || 0))}% match</p>
          </div>
        `;
        if (setHref) {
          return `
            <a class="hero-card" href="${escapeHtml(setHref)}" target="_blank" rel="noopener noreferrer" title="Open set page">
              ${cardInner}
            </a>
          `;
        }
        return `
          <article class="hero-card">
            ${cardInner}
          </article>
        `;
      };

      if (railSets.length) {
        const oneLoop = railSets.map((s, idx) => renderHeroSetCard(s, idx)).join('');
        $('heroSide').innerHTML = `
          <div class="hero-side-viewport" id="heroSideViewport">
            <div class="hero-side-track" id="heroSideTrack">
              ${oneLoop}
              ${oneLoop}
            </div>
          </div>
        `;
      } else {
        $('heroSide').innerHTML = '<article class="hero-card"><span class="hero-empty">No media preview yet</span></article>';
      }

      const tickerBase = [
        `Artists ${fmt(stats.total_artists)}`,
        `Sets ${fmt(stats.total_sets)}`,
        `Unique tracks ${fmt(stats.total_unique_tracks)}`,
        `Appearances ${fmt(stats.total_appearances)}`,
        `Connection edges ${fmt((DATA.similarity || []).filter((s) => Number(s.score || 0) > 0).length)}`,
      ];
      const repeated = [...tickerBase, ...tickerBase, ...tickerBase];
      $('heroTicker').innerHTML = repeated.map((item) => `<span>${escapeHtml(item)}</span>`).join('');

      $('generatedAt').textContent = DATA.generated_at || 'N/A';
      syncHeroRailHeight();
      fitHeroToViewport();
      syncHeroRailHeight();
      startHeroRail();
    }

    function renderArtistGrid() {
      const grid = $('artistGrid');
      const beforeRects = captureArtistCardRects(grid);
      const visibleArtists = filteredArtists();
      const selectedNames = new Set(selectedArtistsList());
      const totalArtists = artistsByName.size;
      const allSelected = totalArtists > 0 && selectedNames.size === totalArtists;

      if (!visibleArtists.length) {
        grid.classList.remove('selected-dock');
        grid.innerHTML = '<div class="empty">No artist cards match this search.</div>';
        return;
      }

      if (!allSelected && !visibleArtists.some((a) => a.name === STATE.focusArtist)) {
        STATE.focusArtist = visibleArtists[0].name;
      }

      if (STATE.hoverLatchedArtist && !visibleArtists.some((a) => a.name === STATE.hoverLatchedArtist)) {
        STATE.hoverLatchedArtist = null;
      }

      syncDockedSelectedArtists(false);

      const visibleDockedSelected = allSelected
        ? []
        : visibleArtists.filter((a) => STATE.dockedSelectedArtists.has(a.name));
      const shouldDockSelected = visibleDockedSelected.length > 0;
      grid.classList.toggle('selected-dock', shouldDockSelected);

      const orderedArtists = shouldDockSelected
        ? [...visibleDockedSelected, ...visibleArtists.filter((a) => !STATE.dockedSelectedArtists.has(a.name))]
        : visibleArtists;

      grid.innerHTML = orderedArtists.map((artist, idx) => {
        const focus = !allSelected && artist.name === STATE.focusArtist;
        const selected = selectedNames.has(artist.name);
        const selectedVisual = selected && !allSelected;
        const compareLabel = allSelected ? 'In Scope' : (selected ? 'In Compare' : 'Add to Compare');
        const hoverLatched = artist.name === STATE.hoverLatchedArtist;
        const image = artist.artist_profile_image || artist.artist_image || artist.cover_image || fallbackMedia(`artist:${artist.name}`);
        const z = orderedArtists.length - idx;
        return `
          <article class="artist-card ${focus ? 'focus' : ''} ${selectedVisual ? 'selected' : ''} ${hoverLatched ? 'hover-latched' : ''}" data-artist="${escapeHtml(artist.name)}" data-action="focus-artist" style="z-index:${z};">
            ${image ? `<img src="${image}" alt="${escapeHtml(artist.name)}" loading="lazy" />` : ''}
            <div class="artist-detail">
              <div class="artist-meta-row">
                <div class="card-actions">
                  <button class="chip-btn ${selectedVisual ? 'active' : ''}" data-action="toggle-compare-artist" data-artist="${escapeHtml(artist.name)}">${compareLabel}</button>
                  <a class="chip-btn" href="${encodeLocalHref(artist.html_rel || '') || '#'}" target="_blank" rel="noopener noreferrer">Artist Page</a>
                </div>
              </div>
              <h3>${escapeHtml(artist.name)}</h3>
            </div>
          </article>
        `;
      }).join('');

      animateArtistCardReflow(grid, beforeRects);
    }

    function computeSelectionStats(scopeNames) {
      if (!scopeNames.length) {
        return { setsCount: 0, uniqueTracks: 0, totalAppearances: 0 };
      }
      if (scopeNames.length === 1) {
        const artist = artistsByName.get(scopeNames[0]);
        if (!artist) return { setsCount: 0, uniqueTracks: 0, totalAppearances: 0 };
        return {
          setsCount: Number(artist.sets_analyzed || 0),
          uniqueTracks: Number(artist.unique_tracks || 0),
          totalAppearances: Number(artist.total_appearances || 0),
        };
      }

      const scopeSet = new Set(scopeNames);
      let uniqueTracks = 0;
      let totalAppearances = 0;
      const setKeys = new Set();

      for (const track of DATA.track_catalog || []) {
        const refs = (track.artist_refs || []).filter((r) => scopeSet.has(r.artist_name));
        if (!refs.length) continue;
        const covered = new Set(refs.map((r) => r.artist_name));
        const include = STATE.compareMode === 'intersection'
          ? covered.size === scopeNames.length
          : covered.size > 0;
        if (!include) continue;

        uniqueTracks += 1;
        totalAppearances += refs.reduce((sum, ref) => sum + Number(ref.appearances || 0), 0);

        refs.forEach((ref) => {
          (ref.set_refs || []).forEach((s) => {
            const key = `${ref.artist_name}::${s.title || ''}`;
            setKeys.add(key);
          });
          (ref.sets || []).forEach((title) => {
            const key = `${ref.artist_name}::${title || ''}`;
            setKeys.add(key);
          });
        });
      }

      return {
        setsCount: setKeys.size,
        uniqueTracks,
        totalAppearances,
      };
    }

    function renderFocusHeader() {
      const selected = selectedArtistsList();
      const scopeNames = currentArtistScope();
      const multi = selected.length > 1;
      const totalArtists = (DATA.artists || []).length;
      const allSelected = totalArtists > 0 && selected.length === totalArtists;
      const stats = computeSelectionStats(scopeNames);

      if (!scopeNames.length) {
        $('focusHeader').innerHTML = '<div class="empty">No artist selected.</div>';
        return;
      }

      const namesClass = allSelected
        ? 'focus-names single'
        : (multi && selected.length > 2 ? 'focus-names multi compact' : (multi ? 'focus-names multi' : 'focus-names single'));
      const namesMarkup = allSelected
        ? '<span class="focus-name">All Artists</span>'
        : (multi
          ? selected.map((name, idx) => `
              <span class="focus-name">
                <span class="focus-label">${escapeHtml(name)}</span>
                <button class="focus-remove" data-action="toggle-compare-artist" data-artist="${escapeHtml(name)}" aria-label="Remove ${escapeHtml(name)}">x</button>
              </span>${idx < selected.length - 1 ? '<span class="focus-sep">&</span>' : ''}
            `).join('')
          : `<span class="focus-name">${escapeHtml(scopeNames[0])}</span>`);

      const mode = STATE.compareMode === 'intersection' ? 'intersection' : 'union';
      const summary = multi
        ? (allSelected
          ? `${mode === 'intersection' ? 'Intersection' : 'Union'} scope across all artists.`
          : `${fmt(selected.length)} artists selected. ${mode === 'intersection' ? 'Intersection' : 'Union'} scope.`)
        : 'Single artist focus. Add more artists to compare overlap.';

      const modeButtons = totalArtists > 1 ? `
        <div class="focus-mode">
          ${multi ? `<button class="chip-btn ${STATE.compareMode === 'union' ? 'active' : ''}" data-action="compare-mode" data-mode="union">Union</button>` : ''}
          ${multi ? `<button class="chip-btn ${STATE.compareMode === 'intersection' ? 'active' : ''}" data-action="compare-mode" data-mode="intersection">Intersection</button>` : ''}
          <button class="chip-btn ${allSelected ? 'active' : ''}" data-action="compare-all">${allSelected ? 'All Artists' : 'Select All'}</button>
          ${multi ? '<button class="chip-btn" data-action="compare-solo">Solo Focus</button>' : ''}
        </div>
      ` : '';

      $('focusHeader').innerHTML = `
        <div class="${namesClass}">${namesMarkup}</div>
        <div class="focus-toolbar">
          <p class="focus-summary">${summary}</p>
          ${modeButtons}
        </div>
        <div class="focus-stats">
          <article class="focus-tile"><p>Sets</p><h4>${fmt(stats.setsCount)}</h4></article>
          <article class="focus-tile"><p>Unique Tracks</p><h4>${fmt(stats.uniqueTracks)}</h4></article>
          <article class="focus-tile"><p>Appearances</p><h4>${fmt(stats.totalAppearances)}</h4></article>
          <article class="focus-tile"><p>Artists</p><h4>${fmt(selected.length)}</h4></article>
        </div>
      `;
    }

    function getCompositeTracks() {
      const selected = currentArtistScope();
      if (!selected.length) return [];
      const selectedSet = new Set(selected);

      const out = [];
      for (const track of DATA.track_catalog || []) {
        const refs = (track.artist_refs || []).filter((r) => selectedSet.has(r.artist_name));
        if (!refs.length) continue;

        const covered = new Set(refs.map((r) => r.artist_name));
        const include = STATE.compareMode === 'intersection'
          ? covered.size === selected.length
          : covered.size > 0;
        if (!include) continue;

        const selectedAppearances = refs.reduce((sum, ref) => sum + Number(ref.appearances || 0), 0);
        if (selectedAppearances < Number(STATE.taxonomyMinUsage || 1)) continue;
        out.push({
          ...track,
          selected_refs: refs,
          selected_appearances: selectedAppearances,
          selected_artist_count: covered.size,
        });
      }

      out.sort((a, b) => {
        return (Number(b.selected_appearances || 0) - Number(a.selected_appearances || 0))
          || (Number(b.selected_artist_count || 0) - Number(a.selected_artist_count || 0))
          || String(a.artist || '').localeCompare(String(b.artist || ''));
      });

      return out;
    }

    function taxonomyLenses() {
      return [
        { id: 'genres', label: 'Genres' },
        { id: 'labels', label: 'Labels' },
        { id: 'track-artists', label: 'Artists' },
        { id: 'tracks', label: 'Tracks' },
      ];
    }

    function buildTaxonomyRows(compositeTracks, confFilter = 'all') {
      const lens = STATE.taxonomyLens;
      const bucket = new Map();
      const scopedTracks = tracksWithConfidenceProjection(compositeTracks, confFilter);

      function put(name, track) {
        const key = (name || '').trim() || 'Unknown';
        if (!bucket.has(key)) {
          bucket.set(key, { name: key, tracksMap: new Map(), plays: 0 });
        }
        const row = bucket.get(key);
        const trackId = track.track_key || `${track.artist || 'Unknown'} - ${track.title || 'Unknown'}`;
        if (!row.tracksMap.has(trackId)) {
          row.tracksMap.set(trackId, track);
        }
        row.plays += Number(track.selected_appearances || 0);
      }

      for (const track of scopedTracks) {
        if (lens === 'genres') {
          const genres = (track.genres || []).length ? track.genres : ['Unknown Genre'];
          for (const g of genres) put(g, track);
        } else if (lens === 'labels') {
          put(track.label || 'Unknown Label', track);
        } else if (lens === 'track-artists') {
          put(track.artist || 'Unknown Artist', track);
        } else {
          put(`${track.artist || 'Unknown'} - ${track.title || 'Unknown'}`, track);
        }
      }

      let rows = Array.from(bucket.values()).map((row) => {
        const tracks = Array.from(row.tracksMap.values());
        const count = lens === 'tracks' ? Number(row.plays || 0) : tracks.length;
        return {
          name: row.name,
          tracks,
          count,
        };
      });
      const q = STATE.taxonomyQuery.trim().toLowerCase();
      if (q) {
        rows = rows.filter((row) => row.name.toLowerCase().includes(q));
      }

      if (STATE.taxonomySort === 'alpha') {
        rows.sort((a, b) => a.name.localeCompare(b.name));
      } else {
        rows.sort((a, b) => (Number(b.count || 0) - Number(a.count || 0)) || a.name.localeCompare(b.name));
      }

      return rows;
    }

    function renderTaxonomy() {
      const composite = getCompositeTracks();
      const rowsAll = buildTaxonomyRows(composite, 'all');
      const rows = buildTaxonomyRows(composite, STATE.taxonomyTrackConf);
      const isTracksLens = STATE.taxonomyLens === 'tracks';

      $('taxonomyTabs').innerHTML = taxonomyLenses().map((lens) => {
        const active = lens.id === STATE.taxonomyLens;
        return `<button class="chip-btn ${active ? 'active' : ''}" data-action="taxonomy-lens" data-lens="${lens.id}">${lens.label}</button>`;
      }).join('');

      STATE.taxonomyMinUsage = normalizeThresholdValue(STATE.taxonomyMinUsage, THRESHOLD_LEVELS);
      renderThresholdStepper('taxonomyThresholds', 'taxonomy-threshold-down', 'taxonomy-threshold-up', STATE.taxonomyMinUsage, THRESHOLD_LEVELS);
      const allTaxonomyTracks = collectUniqueTracks(rowsAll);
      renderConfidenceFilterButtons(
        'taxonomyTrackConfFilters',
        'taxonomy-conf',
        STATE.taxonomyTrackConf,
        allTaxonomyTracks,
      );

      if (isTracksLens) {
        STATE.taxonomyActiveName = null;
        const tracksUniverse = rowsAll.map((row) => (row.tracks || [])[0]).filter(Boolean);
        const tracks = rows.map((row) => (row.tracks || [])[0]).filter(Boolean);
        const countLabel = STATE.taxonomyTrackConf === 'all'
          ? `${fmt(tracks.length)} matching tracks`
          : `${fmt(tracks.length)} / ${fmt(tracksUniverse.length)} matching tracks`;
        if (!tracks.length) {
          $('taxonomyRows').innerHTML = '<div class="empty">No tracks match current scope, query, and confidence filter.</div>';
        } else {
          $('taxonomyRows').innerHTML = `
            <div class="inline-evidence">
              <p class="inline-head">Tracks | ${countLabel}</p>
              <div class="evidence-grid">${tracks.map((track) => renderTaxonomyTrackCard(track)).join('')}</div>
            </div>
          `;
        }
        $('taxonomyPager').innerHTML = '';
        const evidencePanel = $('taxonomyEvidencePanel');
        if (evidencePanel) evidencePanel.classList.remove('open');
        $('taxonomyEvidence').innerHTML = '';
        $('evidenceSummary').textContent = '';
        $('evidencePager').innerHTML = '';
        return;
      }

      const maxCount = rows.length ? Math.max(...rows.map((r) => Number(r.count || 0))) : 1;
      const totalPages = Math.max(1, Math.ceil(rows.length / PAGE.taxonomy));
      if (STATE.taxonomyPage >= totalPages) STATE.taxonomyPage = totalPages - 1;
      if (STATE.taxonomyPage < 0) STATE.taxonomyPage = 0;

      const start = STATE.taxonomyPage * PAGE.taxonomy;
      const pageRows = rows.slice(start, start + PAGE.taxonomy);

      const activeExists = rows.some((r) => r.name === STATE.taxonomyActiveName);
      if (!activeExists) {
        STATE.taxonomyActiveName = null;
        STATE.taxonomyEvidencePage = 0;
      }

      if (!rows.length) {
        $('taxonomyRows').innerHTML = '<div class="empty">No taxonomy entries match current scope and query.</div>';
      } else {
        $('taxonomyRows').innerHTML = pageRows.map((row) => {
          const pct = maxCount ? ((Number(row.count || 0) / maxCount) * 100) : 0;
          const active = row.name === STATE.taxonomyActiveName;
          const base = `
            <div class="row-line">
              <span class="row-name" title="${escapeHtml(row.name)}">${escapeHtml(row.name)}</span>
              <div class="bar"><span style="width:${pct}%;"></span></div>
              <span class="row-count">${fmt(row.count)}</span>
            </div>
          `;
          const trigger = isTracksLens
            ? base
            : `<button class="row-hit" data-action="taxonomy-row" data-name="${escapeHtml(row.name)}">${base}</button>`;
          const inline = (!isTracksLens && active) ? renderInlineTaxonomyEvidence(row) : '';
          return `
            <article class="quant-row ${active ? 'active' : ''}">
              ${trigger}
              ${inline}
            </article>
          `;
        }).join('');
      }

      $('taxonomyPager').innerHTML = `
        <button data-action="taxonomy-page" data-delta="-1" ${STATE.taxonomyPage <= 0 ? 'disabled' : ''}>Prev</button>
        <span class="info">Page ${STATE.taxonomyPage + 1} / ${totalPages}</span>
        <button data-action="taxonomy-page" data-delta="1" ${STATE.taxonomyPage >= totalPages - 1 ? 'disabled' : ''}>Next</button>
      `;

      renderTaxonomyEvidence(rows, rowsAll);
      syncAtlasHeights();
    }

    function artistTrackQueryHref(dirName, track) {
      if (!dirName) return '';
      const q = encodeURIComponent(`${track.artist || ''} ${track.title || ''}`.trim());
      return `${dirName}/artist_summary.html?q=${q}#sets-section`;
    }

    function buildTaxonomyTrackSourceGroups(track) {
      return (track.selected_refs || []).map((ref) => {
        const artistHref = artistTrackQueryHref(ref.dir_name || '', track);
        const setLinks = (ref.set_refs || []).slice(0, 8).map((s) => {
          const href = encodeLocalHref(s.href || '');
          if (href) {
            return `<li><a href="${href}" target="_blank" rel="noopener noreferrer">${escapeHtml(s.title || 'Set')}</a></li>`;
          }
          return `<li>${escapeHtml(s.title || 'Set')}</li>`;
        }).join('');
        return `
          <div class="source-group">
            <h5>${artistHref ? `<a href="${artistHref}" target="_blank" rel="noopener noreferrer">${escapeHtml(ref.artist_name || 'Artist')}</a>` : escapeHtml(ref.artist_name || 'Artist')}</h5>
            ${setLinks ? `<ul class="source-list">${setLinks}</ul>` : '<p class="source-empty">No set links</p>'}
          </div>
        `;
      }).join('');
    }

    function renderTaxonomyTrackCard(track) {
      const image = track.album_art || track.artist_image || '';
      const spotifyId = extractSpotifyId(track.spotify_url);
      const conf = normalizeConfidence(track.confidence);
      const confColor = CONF_COLOR[conf] || '#757575';
      const selectedRefs = track.selected_refs || [];
      const sourceDjs = selectedRefs.length;
      const sourceSets = selectedRefs.reduce((sum, ref) => {
        return sum + ((ref.set_refs || []).length || 0);
      }, 0);
      const sourceLabel = `Sets (${fmt(sourceDjs)} DJs, ${fmt(sourceSets)} Sets)`;
      const sourceOpenLabel = 'Hide Sets';
      const sourceGroups = buildTaxonomyTrackSourceGroups(track);

      return `
        <article class="track-card" data-track-key="${escapeHtml(track.track_key || '')}">
          <div class="track-art">${image ? `<img src="${image}" alt="${escapeHtml(track.title || 'Track')}" loading="lazy" />` : ''}</div>
          <div class="track-body">
            <h4 class="track-title">${escapeHtml(track.artist || 'Unknown')} - ${escapeHtml(track.title || 'Unknown')}</h4>
            <p class="muted">Confidence <span class="set-track-conf" style="border-color:${confColor}; color:${confColor};">${escapeHtml(conf)}</span></p>
            <div class="actions">
              ${spotifyId ? `<button data-action="spotify-embed" data-url="${track.spotify_url}">Spotify</button>` : ''}
              <button data-action="toggle-sources" data-closed-label="${escapeHtml(sourceLabel)}" data-open-label="${escapeHtml(sourceOpenLabel)}">${escapeHtml(sourceLabel)}</button>
            </div>
            <div class="source-panel">${sourceGroups || '<div class="empty">No provenance rows.</div>'}</div>
          </div>
        </article>
      `;
    }

    function resolveLabelDiscogsUrl(row) {
      if (STATE.taxonomyLens !== 'labels') return '';
      const target = String(row.name || '').trim().toLowerCase();
      if (!target || target === 'unknown label') return '';
      const isHttpUrl = (url) => url.startsWith('http://') || url.startsWith('https://');

      const tracks = row.tracks || [];
      const matching = tracks.find((track) => {
        const name = String(track.label || '').trim().toLowerCase();
        const url = String(track.label_url || '').trim();
        return name === target && isHttpUrl(url);
      });
      if (matching) return String(matching.label_url || '').trim();

      const fallback = tracks.find((track) => {
        const url = String(track.label_url || '').trim();
        return isHttpUrl(url);
      });
      return fallback ? String(fallback.label_url || '').trim() : '';
    }

    function renderInlineTaxonomyEvidence(row) {
      const tracksAll = [...(row.tracks || [])].sort((a, b) => {
        return (Number(b.selected_appearances || 0) - Number(a.selected_appearances || 0))
          || (Number(b.selected_artist_count || 0) - Number(a.selected_artist_count || 0))
          || String(a.artist || '').localeCompare(String(b.artist || ''));
      });
      const tracks = filterTracksByConfidence(tracksAll, STATE.taxonomyTrackConf);
      const labelDiscogsUrl = resolveLabelDiscogsUrl(row);
      const headActions = labelDiscogsUrl
        ? `<div class="inline-head-actions"><a class="discogs" href="${escapeHtml(labelDiscogsUrl)}" target="_blank" rel="noopener noreferrer">Label Page</a></div>`
        : '';
      const countLabel = STATE.taxonomyTrackConf === 'all'
        ? `${fmt(tracks.length)} matching tracks`
        : `${fmt(tracks.length)} / ${fmt(tracksAll.length)} matching tracks`;
      const head = `
        <div class="inline-head-row">
          <p class="inline-head">${escapeHtml(row.name)} | ${countLabel}</p>
          ${headActions}
        </div>
      `;

      if (!tracks.length) {
        return `
          <div class="inline-evidence">
            ${head}
            <div class="empty">No evidence tracks match the selected confidence filter.</div>
          </div>
        `;
      }

      return `
        <div class="inline-evidence">
          ${head}
          <div class="evidence-grid">${tracks.map((track) => renderTaxonomyTrackCard(track)).join('')}</div>
        </div>
      `;
    }

    function renderTaxonomyEvidence(rows, rowsAll = rows) {
      const evidencePanel = $('taxonomyEvidencePanel');

      if (STATE.taxonomyLens !== 'tracks') {
        if (evidencePanel) evidencePanel.classList.remove('open');
        $('taxonomyEvidence').innerHTML = '';
        $('evidenceSummary').textContent = '';
        $('evidencePager').innerHTML = '';
        return;
      }

      if (STATE.taxonomyLens === 'tracks') {
        if (evidencePanel) evidencePanel.classList.add('open');
        const merged = new Map();
        for (const row of rows) {
          for (const track of row.tracks || []) {
            const k = track.track_key || `${track.artist || 'Unknown'} - ${track.title || 'Unknown'}`;
            if (!merged.has(k)) merged.set(k, track);
          }
        }

        const tracks = Array.from(merged.values()).sort((a, b) => {
          return (Number(b.selected_appearances || 0) - Number(a.selected_appearances || 0))
            || (Number(b.selected_artist_count || 0) - Number(a.selected_artist_count || 0))
            || String(a.artist || '').localeCompare(String(b.artist || ''));
        });
        const mergedAll = new Map();
        for (const row of rowsAll || []) {
          for (const track of row.tracks || []) {
            const k = track.track_key || `${track.artist || 'Unknown'} - ${track.title || 'Unknown'}`;
            if (!mergedAll.has(k)) mergedAll.set(k, track);
          }
        }
        const tracksAll = Array.from(mergedAll.values());

        const totalPages = Math.max(1, Math.ceil(tracks.length / PAGE.evidence));
        if (STATE.taxonomyEvidencePage >= totalPages) STATE.taxonomyEvidencePage = totalPages - 1;
        if (STATE.taxonomyEvidencePage < 0) STATE.taxonomyEvidencePage = 0;

        const start = STATE.taxonomyEvidencePage * PAGE.evidence;
        const page = tracks.slice(start, start + PAGE.evidence);

        if (STATE.taxonomyTrackConf === 'all') {
          $('evidenceSummary').textContent = `${fmt(tracks.length)} tracks sorted by plays.`;
        } else {
          $('evidenceSummary').textContent = `${fmt(tracks.length)} / ${fmt(tracksAll.length)} tracks for ${STATE.taxonomyTrackConf} confidence.`;
        }

        if (!tracks.length) {
          $('taxonomyEvidence').innerHTML = '<div class="empty">No tracks match the current scope and confidence filter.</div>';
        } else {
          $('taxonomyEvidence').innerHTML = page.map((track) => renderTaxonomyTrackCard(track)).join('');
        }

        $('evidencePager').innerHTML = `
          <button data-action="evidence-page" data-delta="-1" ${STATE.taxonomyEvidencePage <= 0 ? 'disabled' : ''}>Prev</button>
          <span class="info">Page ${STATE.taxonomyEvidencePage + 1} / ${totalPages}</span>
          <button data-action="evidence-page" data-delta="1" ${STATE.taxonomyEvidencePage >= totalPages - 1 ? 'disabled' : ''}>Next</button>
        `;
        return;
      }
    }

    function edgesForNetwork() {
      const minScore = Number(STATE.networkMinScore || 0);
      const q = STATE.networkSearch.trim().toLowerCase();
      const selected = networkSelectedArtistsList();
      return (DATA.similarity || []).filter((row) => {
        const score = Number(row.normalized_score || 0);
        if (score < minScore) return false;

        if (selected.length === 1) {
          const target = selected[0];
          if (row.artist_a !== target && row.artist_b !== target) return false;
        } else if (selected.length >= 2) {
          const a = selected[0];
          const b = selected[1];
          const matchPair = (row.artist_a === a && row.artist_b === b)
            || (row.artist_a === b && row.artist_b === a);
          if (!matchPair) return false;
        }

        if (!q) return true;
        return String(row.artist_a || '').toLowerCase().includes(q)
          || String(row.artist_b || '').toLowerCase().includes(q);
      });
    }

    function renderNetwork() {
      const wrap = $('networkWrap');
      const width = Math.max(860, wrap.clientWidth || 860);
      const height = 560;
      const cx = width / 2;
      const cy = height / 2;

      const artists = [...(DATA.artists || [])].sort((a, b) => a.name.localeCompare(b.name));
      const n = artists.length || 1;
      const radius = Math.min(width, height) * 0.38;

      const positions = new Map();
      artists.forEach((artist, idx) => {
        const angle = (Math.PI * 2 * idx) / n - Math.PI / 2;
        positions.set(artist.name, {
          x: cx + Math.cos(angle) * radius,
          y: cy + Math.sin(angle) * radius,
          r: 8 + Math.min(8, Math.sqrt(Number(artist.sets_analyzed || 0)) * 0.7),
          sets: Number(artist.sets_analyzed || 0),
        });
      });

      const edges = edgesForNetwork();

      const edgeSvg = edges.map((row) => {
        const a = positions.get(row.artist_a);
        const b = positions.get(row.artist_b);
        if (!a || !b) return '';
        const score = Number(row.normalized_score || 0);
        const stroke = `rgba(216,255,90,${Math.max(0.08, score / 120).toFixed(3)})`;
        const sw = (0.6 + score / 25).toFixed(2);
        return `
          <line x1="${a.x.toFixed(2)}" y1="${a.y.toFixed(2)}" x2="${b.x.toFixed(2)}" y2="${b.y.toFixed(2)}"
            stroke="${stroke}" stroke-width="${sw}" data-action="network-edge" data-a="${escapeHtml(row.artist_a)}" data-b="${escapeHtml(row.artist_b)}"></line>
        `;
      }).join('');

      const nodeSvg = artists.map((artist) => {
        const p = positions.get(artist.name);
        if (!p) return '';
        const selected = STATE.networkSelectedArtists.has(artist.name);
        const fill = selected ? '#7f51ff' : '#d8ff5a';
        const cls = `network-node ${selected ? 'selected' : ''}`;
        return `
          <g>
            <circle class="${cls}" cx="${p.x.toFixed(2)}" cy="${p.y.toFixed(2)}" r="${p.r.toFixed(2)}"
              fill="${fill}" data-action="network-node" data-artist="${escapeHtml(artist.name)}"></circle>
            <text x="${(p.x + p.r + 4).toFixed(2)}" y="${(p.y + 3).toFixed(2)}"
              fill="#f1f1f1" font-size="11" font-family="Space Mono, monospace" letter-spacing="0.02em">${escapeHtml(artist.name)}</text>
          </g>
        `;
      }).join('');

      wrap.innerHTML = `
        <svg class="network-svg" viewBox="0 0 ${width} ${height}" aria-label="Artist connection map">
          <rect x="0" y="0" width="${width}" height="${height}" fill="#0f0f0f"></rect>
          ${edgeSvg}
          ${nodeSvg}
        </svg>
      `;
    }

    function activePairData() {
      let pair = STATE.pair;
      if (!pair) {
        const selected = networkSelectedArtistsList();
        if (selected.length === 2) {
          pair = [selected[0], selected[1]];
        }
      }
      if (!pair || pair.length !== 2) return null;
      const row = similarityByKey.get(pairKey(pair[0], pair[1]));
      if (!row) return null;
      return { pair, row };
    }

    function pairLenses() {
      return [
        { id: 'genres', label: 'Genres' },
        { id: 'labels', label: 'Labels' },
        { id: 'artists', label: 'Artists' },
        { id: 'tracks', label: 'Tracks' },
      ];
    }

    function pairTrackToTaxonomyTrack(sharedTrack, aName, bName, confFilter = 'all') {
      const target = normalizeConfFilter(confFilter);
      const refs = [];
      const setsA = Array.isArray(sharedTrack.sets_a) ? sharedTrack.sets_a : [];
      const setsB = Array.isArray(sharedTrack.sets_b) ? sharedTrack.sets_b : [];
      const scopedSetsA = filterSetRefsByConfidence(setsA, target);
      const scopedSetsB = filterSetRefsByConfidence(setsB, target);
      const appA = scopedSetsA.length;
      const appB = scopedSetsB.length;
      const aDir = (artistsByName.get(aName) || {}).dir_name || '';
      const bDir = (artistsByName.get(bName) || {}).dir_name || '';

      if (scopedSetsA.length || appA > 0) {
        refs.push({
          artist_name: aName,
          dir_name: aDir,
          appearances: appA,
          set_refs: scopedSetsA,
        });
      }
      if (scopedSetsB.length || appB > 0) {
        refs.push({
          artist_name: bName,
          dir_name: bDir,
          appearances: appB,
          set_refs: scopedSetsB,
        });
      }

      const confidenceCounts = { HIGH: 0, MEDIUM: 0, LOW: 0, UNCERTAIN: 0 };
      for (const setRef of [...scopedSetsA, ...scopedSetsB]) {
        const conf = normalizeConfidence(setRef?.confidence);
        confidenceCounts[conf] = Number(confidenceCounts[conf] || 0) + 1;
      }
      const selectedAppearances = appA + appB;
      if (selectedAppearances <= 0) return null;
      let confidence = normalizeConfidence(sharedTrack.confidence);
      if (target === 'all') {
        confidence = primaryConfidenceFromCounts(confidenceCounts);
      } else {
        for (const level of Object.keys(confidenceCounts)) confidenceCounts[level] = 0;
        confidenceCounts[target] = selectedAppearances;
        confidence = target;
      }

      return {
        track_key: sharedTrack.track_key || `${sharedTrack.display_artist || 'Unknown'} - ${sharedTrack.display_title || 'Unknown'}`,
        artist: sharedTrack.display_artist || 'Unknown',
        title: sharedTrack.display_title || 'Unknown',
        confidence,
        confidence_counts: confidenceCounts,
        spotify_url: sharedTrack.spotify_url || '',
        album_art: sharedTrack.spotify_album_art || '',
        artist_profile_image: sharedTrack.spotify_artist_profile_image || '',
        artist_image: sharedTrack.spotify_artist_profile_image || '',
        label: sharedTrack.discogs_label || '',
        label_url: sharedTrack.discogs_label_url || '',
        genres: sharedTrack.genres || [],
        selected_refs: refs,
        selected_appearances: selectedAppearances,
        selected_artist_count: refs.length,
        _pair_counts: { a: appA, b: appB },
      };
    }

    function buildPairRows(pairRow, aName, bName, confFilter = 'all') {
      const sharedTracks = pairRow.shared_tracks || [];
      const tracksByKey = new Map();
      for (const t of sharedTracks) {
        const key = t.track_key || `${t.display_artist || 'Unknown'} - ${t.display_title || 'Unknown'}`;
        const mapped = pairTrackToTaxonomyTrack(t, aName, bName, confFilter);
        if (mapped && Number(mapped.selected_appearances || 0) > 0) {
          tracksByKey.set(key, mapped);
        }
      }

      const lens = STATE.pairLens;
      let rows = [];

      if (lens === 'tracks') {
        rows = sharedTracks.map((t) => {
          const key = t.track_key || `${t.display_artist || 'Unknown'} - ${t.display_title || 'Unknown'}`;
          const mappedTrack = tracksByKey.get(key);
          if (!mappedTrack) return null;
          const total = Number(mappedTrack.selected_appearances || 0);
          const counts = mappedTrack._pair_counts || { a: 0, b: 0 };
          return {
            id: key,
            name: `${t.display_artist || 'Unknown'} - ${t.display_title || 'Unknown'}`,
            count: total,
            tracks: mappedTrack ? [mappedTrack] : [],
            meta: `${aName} ${fmt(counts.a)} | ${bName} ${fmt(counts.b)}`,
          };
        }).filter(Boolean);
      } else if (lens === 'genres') {
        rows = (pairRow.shared_genres || []).map((g) => {
          const keys = g.track_keys || [];
          const tracks = keys.map((k) => tracksByKey.get(k)).filter(Boolean);
          return {
            id: g.genre || 'Unknown Genre',
            name: g.genre || 'Unknown Genre',
            count: tracks.length,
            tracks,
            meta: `${aName} ${fmt(g.count_a)} | ${bName} ${fmt(g.count_b)}`,
          };
        });
      } else if (lens === 'labels') {
        rows = (pairRow.shared_labels || []).map((l) => {
          const keys = l.track_keys || [];
          const tracks = keys.map((k) => tracksByKey.get(k)).filter(Boolean);
          return {
            id: l.label || 'Unknown Label',
            name: l.label || 'Unknown Label',
            count: tracks.length,
            tracks,
            meta: `${aName} ${fmt(l.count_a)} | ${bName} ${fmt(l.count_b)}`,
          };
        });
      } else {
        rows = (pairRow.shared_music_artists || []).map((m) => {
          const keys = m.track_keys || [];
          const tracks = keys.map((k) => tracksByKey.get(k)).filter(Boolean);
          return {
            id: m.music_artist || 'Unknown Artist',
            name: m.music_artist || 'Unknown Artist',
            count: tracks.length,
            tracks,
            meta: `${aName} ${fmt(m.count_a)} | ${bName} ${fmt(m.count_b)}`,
          };
        });
      }

      const q = STATE.pairQuery.trim().toLowerCase();
      if (q) {
        rows = rows.filter((it) => String(it.name || '').toLowerCase().includes(q));
      }

      rows = rows.filter((it) => Number(it.count || 0) >= Number(STATE.pairMinUsage || 1));

      if (STATE.pairSort === 'alpha') {
        rows.sort((x, y) => String(x.name || '').localeCompare(String(y.name || '')));
      } else {
        rows.sort((x, y) => (Number(y.count || 0) - Number(x.count || 0)) || String(x.name || '').localeCompare(String(y.name || '')));
      }

      return rows;
    }

    function resolvePairLabelDiscogsUrl(row) {
      if (STATE.pairLens !== 'labels') return '';
      const target = String(row.name || '').trim().toLowerCase();
      if (!target || target === 'unknown label') return '';
      const isHttpUrl = (url) => url.startsWith('http://') || url.startsWith('https://');

      const tracks = row.tracks || [];
      const matching = tracks.find((track) => {
        const name = String(track.label || '').trim().toLowerCase();
        const url = String(track.label_url || '').trim();
        return name === target && isHttpUrl(url);
      });
      if (matching) return String(matching.label_url || '').trim();

      const fallback = tracks.find((track) => {
        const url = String(track.label_url || '').trim();
        return isHttpUrl(url);
      });
      return fallback ? String(fallback.label_url || '').trim() : '';
    }

    function renderInlinePairEvidence(row) {
      const tracksAll = [...(row.tracks || [])].sort((a, b) => {
        return (Number(b.selected_appearances || 0) - Number(a.selected_appearances || 0))
          || (Number(b.selected_artist_count || 0) - Number(a.selected_artist_count || 0))
          || String(a.artist || '').localeCompare(String(b.artist || ''));
      });
      const tracks = filterTracksByConfidence(tracksAll, STATE.pairTrackConf);
      const labelDiscogsUrl = resolvePairLabelDiscogsUrl(row);
      const headActions = labelDiscogsUrl
        ? `<div class="inline-head-actions"><a class="discogs" href="${escapeHtml(labelDiscogsUrl)}" target="_blank" rel="noopener noreferrer">Label Page</a></div>`
        : '';
      const meta = row.meta ? ` | ${escapeHtml(row.meta)}` : '';
      const countLabel = STATE.pairTrackConf === 'all'
        ? `${fmt(tracks.length)} shared tracks`
        : `${fmt(tracks.length)} / ${fmt(tracksAll.length)} shared tracks`;
      const head = `
        <div class="inline-head-row">
          <p class="inline-head">${escapeHtml(row.name)} | ${countLabel}${meta}</p>
          ${headActions}
        </div>
      `;

      if (!tracks.length) {
        return `
          <div class="inline-evidence">
            ${head}
            <div class="empty">No evidence tracks match the selected confidence filter.</div>
          </div>
        `;
      }

      return `
        <div class="inline-evidence">
          ${head}
          <div class="evidence-grid">${tracks.map((track) => renderTaxonomyTrackCard(track)).join('')}</div>
        </div>
      `;
    }

    function renderPairWorkspace() {
      const active = activePairData();
      if (!active) {
        $('pairTitle').textContent = 'Pair Analysis Workspace';
        $('pairSummary').textContent = 'Pick an edge in the network or select exactly two artists.';
        $('pairTabs').innerHTML = '';
        $('pairThresholds').innerHTML = '';
        $('pairTrackConfFilters').innerHTML = '';
        $('pairRows').innerHTML = '<div class="empty">No active pair selected.</div>';
        $('pairPager').innerHTML = '';
        return;
      }

      const [aName, bName] = active.pair;
      const pairRow = active.row;

      $('pairTitle').textContent = `Pair Analysis Workspace: ${aName} x ${bName}`;
      $('pairSummary').textContent =
        `Score ${fmt(pairRow.normalized_score)} | ${fmt(pairRow.shared_tracks_count)} tracks | ${fmt(pairRow.shared_labels_count)} labels | ${fmt(pairRow.shared_genres_count)} genres`;

      $('pairTabs').innerHTML = pairLenses().map((lens) => {
        const activeLens = lens.id === STATE.pairLens;
        return `<button class="chip-btn ${activeLens ? 'active' : ''}" data-action="pair-lens" data-lens="${lens.id}">${lens.label}</button>`;
      }).join('');

      STATE.pairMinUsage = normalizeThresholdValue(STATE.pairMinUsage, THRESHOLD_LEVELS);
      renderThresholdStepper('pairThresholds', 'pair-threshold-down', 'pair-threshold-up', STATE.pairMinUsage, THRESHOLD_LEVELS);

      $('pairSort').value = STATE.pairSort;

      const rowsAll = buildPairRows(pairRow, aName, bName, 'all');
      const rows = buildPairRows(pairRow, aName, bName, STATE.pairTrackConf);
      const allPairTracks = collectUniqueTracks(rowsAll);
      renderConfidenceFilterButtons(
        'pairTrackConfFilters',
        'pair-conf',
        STATE.pairTrackConf,
        allPairTracks,
      );

      if (STATE.pairLens === 'tracks') {
        STATE.pairActiveName = null;
        const tracksUniverse = rowsAll.map((row) => (row.tracks || [])[0]).filter(Boolean);
        const tracks = rows.map((row) => (row.tracks || [])[0]).filter(Boolean);
        const countLabel = STATE.pairTrackConf === 'all'
          ? `${fmt(tracks.length)} matching tracks`
          : `${fmt(tracks.length)} / ${fmt(tracksUniverse.length)} matching tracks`;
        if (!tracks.length) {
          $('pairRows').innerHTML = '<div class="empty">No tracks match current controls and confidence filter.</div>';
        } else {
          $('pairRows').innerHTML = `
            <div class="inline-evidence">
              <p class="inline-head">Tracks | ${countLabel}</p>
              <div class="evidence-grid">${tracks.map((track) => renderTaxonomyTrackCard(track)).join('')}</div>
            </div>
          `;
        }
        $('pairPager').innerHTML = '';
        return;
      }

      const totalPages = Math.max(1, Math.ceil(rows.length / PAGE.pairRows));
      if (STATE.pairPage >= totalPages) STATE.pairPage = totalPages - 1;
      if (STATE.pairPage < 0) STATE.pairPage = 0;

      const start = STATE.pairPage * PAGE.pairRows;
      const pageRows = rows.slice(start, start + PAGE.pairRows);
      const maxCount = rows.length ? Math.max(...rows.map((it) => Number(it.count || 0))) : 1;

      const activeExists = rows.some((r) => r.id === STATE.pairActiveName);
      if (!activeExists) {
        STATE.pairActiveName = null;
      }

      if (!rows.length) {
        $('pairRows').innerHTML = '<div class="empty">No pair entries match current controls.</div>';
      } else {
        $('pairRows').innerHTML = pageRows.map((row) => {
          const pct = maxCount ? ((Number(row.count || 0) / maxCount) * 100) : 0;
          const activeRow = row.id === STATE.pairActiveName;
          const base = `
            <div class="row-line">
              <span class="row-name" title="${escapeHtml(row.name)}">${escapeHtml(row.name)}</span>
              <div class="bar"><span style="width:${pct}%;"></span></div>
              <span class="row-count">${fmt(row.count)}</span>
            </div>
          `;
          const inline = activeRow ? renderInlinePairEvidence(row) : '';
          return `
            <article class="quant-row ${activeRow ? 'active' : ''}">
              <button class="row-hit" data-action="pair-row" data-name="${escapeHtml(row.id)}">${base}</button>
              ${inline}
            </article>
          `;
        }).join('');
      }

      $('pairPager').innerHTML = `
        <button data-action="pair-page" data-delta="-1" ${STATE.pairPage <= 0 ? 'disabled' : ''}>Prev</button>
        <span class="info">Page ${STATE.pairPage + 1} / ${totalPages}</span>
        <button data-action="pair-page" data-delta="1" ${STATE.pairPage >= totalPages - 1 ? 'disabled' : ''}>Next</button>
      `;
    }

    function filteredSets() {
      const q = STATE.setQuery.trim().toLowerCase();
      let rows = (DATA.all_sets || []).filter((s) => {
        if (STATE.setArtist !== 'ALL' && String(s.artist_name || '') !== STATE.setArtist) return false;
        if (!q) return true;
        const trackText = (s.tracks || []).map((t) => `${t.artist || ''} ${t.title || ''}`).join(' ');
        const hay = `${s.title || ''} ${s.artist_name || ''} ${s.track_search_text || ''} ${trackText}`.toLowerCase();
        return hay.includes(q);
      });

      rows = rows.slice();
      rows.sort((a, b) => {
        if (STATE.setSort === 'rate') {
          return Number(b.recognition_rate || 0) - Number(a.recognition_rate || 0);
        }
        if (STATE.setSort === 'tracks') {
          return Number(b.total_tracks || 0) - Number(a.total_tracks || 0);
        }
        if (STATE.setSort === 'duration') {
          return Number(b.duration || 0) - Number(a.duration || 0);
        }
        return String(a.artist_name || '').localeCompare(String(b.artist_name || ''))
          || String(a.title || '').localeCompare(String(b.title || ''));
      });

      return rows;
    }

    function formatDuration(seconds) {
      const s = Number(seconds || 0);
      const h = Math.floor(s / 3600);
      const m = Math.floor((s % 3600) / 60);
      if (h > 0) return `${h}h ${m}m`;
      return `${m}m`;
    }

    function renderSetLibrary() {
      const artistOptions = ['ALL', ...(DATA.artists || []).map((a) => a.name)];
      $('setArtistFilter').innerHTML = artistOptions.map((name) => {
        return `<option value="${escapeHtml(name)}">${name === 'ALL' ? 'All Artists' : escapeHtml(name)}</option>`;
      }).join('');
      $('setArtistFilter').value = STATE.setArtist;
      $('setSort').value = STATE.setSort;

      const rows = filteredSets();
      const totalPages = Math.max(1, Math.ceil(rows.length / PAGE.sets));
      if (STATE.setPage >= totalPages) STATE.setPage = totalPages - 1;
      if (STATE.setPage < 0) STATE.setPage = 0;

      const start = STATE.setPage * PAGE.sets;
      const pageRows = rows.slice(start, start + PAGE.sets);

      if (!rows.length) {
        $('setGrid').innerHTML = '<div class="empty">No sets match current filters.</div>';
      } else {
        $('setGrid').innerHTML = pageRows.map((s, idx) => {
          const setKey = `${start + idx}:${s.artist_name || ''}:${s.title || ''}`;
          const expanded = STATE.expandedSets.has(setKey);
          const thumb = s.thumbnail_url || fallbackMedia(`set:${s.artist_name || ''}:${s.title || ''}`);
          const setHref = encodeLocalHref(s.set_html_master_rel || '');
          const artistHref = encodeLocalHref(s.artist_html_rel || '');
          const trackRows = (s.tracks || []).map((t, tIdx) => {
            const href = encodeLocalHref(t.track_href || '');
            const trackName = `${t.artist || 'Unknown'} - ${t.title || 'Unknown'}`;
            const conf = (t.confidence || 'UNCERTAIN').toUpperCase();
            const cc = CONF_COLOR[conf] || '#757575';
            return `
              <div class="set-track">
                <span class="set-track-time">${escapeHtml(t.start_time_formatted || '')}</span>
                <span>${href ? `<a href="${href}" target="_blank" rel="noopener noreferrer">${escapeHtml(trackName)}</a>` : escapeHtml(trackName)}</span>
                <span class="set-track-conf" style="border-color:${cc}; color:${cc};">${escapeHtml(conf)}</span>
              </div>
            `;
          }).join('');

          return `
            <article class="set-card">
              <div class="set-thumb">
                ${setHref
                  ? `<a href="${setHref}" target="_blank" rel="noopener noreferrer"><img src="${thumb}" alt="${escapeHtml(s.title || 'Set')}" loading="lazy" /></a>`
                  : `<img src="${thumb}" alt="${escapeHtml(s.title || 'Set')}" loading="lazy" />`}
              </div>
              <div class="set-body">
                <h4 class="set-title">${setHref
                  ? `<a href="${setHref}" target="_blank" rel="noopener noreferrer">${escapeHtml(s.title || 'Unknown Set')}</a>`
                  : escapeHtml(s.title || 'Unknown Set')}</h4>
                <p class="muted">${artistHref
                  ? `<a href="${artistHref}" target="_blank" rel="noopener noreferrer">${escapeHtml(s.artist_name || '')}</a>`
                  : escapeHtml(s.artist_name || '')}</p>
                <div class="set-meta">
                  <span class="set-pill">${fmt(s.total_tracks)} tracks</span>
                  <span class="set-pill">${Math.round(Number(s.recognition_rate || 0))}% match</span>
                  <span class="set-pill">${formatDuration(s.duration)}</span>
                </div>
                <div class="actions">
                  ${setHref ? `<a href="${setHref}" target="_blank" rel="noopener noreferrer">Open Set Page</a>` : ''}
                  ${s.url ? `<a href="${s.url}" target="_blank" rel="noopener noreferrer">Source</a>` : ''}
                  <button data-action="toggle-set" data-key="${escapeHtml(setKey)}">${expanded ? 'Hide Tracklist' : 'Show Tracklist'}</button>
                </div>
                <div class="set-tracklist ${expanded ? 'open' : ''}">${trackRows || '<div class="empty">No recognized tracks in this set.</div>'}</div>
              </div>
            </article>
          `;
        }).join('');
      }

      $('setPager').innerHTML = `
        <button data-action="set-page" data-delta="-1" ${STATE.setPage <= 0 ? 'disabled' : ''}>Prev</button>
        <span class="info">Page ${STATE.setPage + 1} / ${totalPages} | ${fmt(rows.length)} sets</span>
        <button data-action="set-page" data-delta="1" ${STATE.setPage >= totalPages - 1 ? 'disabled' : ''}>Next</button>
      `;
    }

    function renderAll() {
      renderArtistGrid();
      renderFocusHeader();
      renderTaxonomy();
      renderNetwork();
      renderPairWorkspace();
      renderSetLibrary();
      syncAtlasHeights();
    }

    function syncAtlasHeights() {
      const left = document.querySelector('.artist-stack');
      const right = document.querySelector('.atlas-panel');
      if (!left || !right) return;

      left.style.removeProperty('height');
      if (window.matchMedia('(max-width: 980px)').matches) return;

      const rightHeight = right.getBoundingClientRect().height;
      if (rightHeight > 0) {
        left.style.height = `${rightHeight}px`;
      }
    }

    function toggleArtistSelection(name) {
      if (!name || !artistsByName.has(name)) return;
      if (STATE.selectedArtists.has(name)) {
        if (STATE.selectedArtists.size > 1) {
          STATE.selectedArtists.delete(name);
        }
      } else {
        STATE.selectedArtists.add(name);
      }
      if (!STATE.selectedArtists.size && STATE.focusArtist && artistsByName.has(STATE.focusArtist)) {
        STATE.selectedArtists.add(STATE.focusArtist);
      }
      if (!STATE.selectedArtists.has(STATE.focusArtist)) {
        const fallback = Array.from(STATE.selectedArtists)[0] || null;
        if (fallback) STATE.focusArtist = fallback;
      }
      syncDockedSelectedArtists(false);
      STATE.taxonomyPage = 0;
      STATE.taxonomyEvidencePage = 0;
      STATE.taxonomyActiveName = null;
    }

    function bind() {
      $('artistSearch').addEventListener('input', (ev) => {
        STATE.artistQuery = ev.target.value || '';
        renderArtistGrid();
      });

      $('artistGrid').addEventListener('pointerenter', () => {
        if (!isHoverCapablePointer()) return;
        STATE.artistPanePointerInside = true;
      });

      $('artistGrid').addEventListener('pointermove', (ev) => {
        if (isHoverCapablePointer()) {
          STATE.artistPanePointerInside = true;
        }
        if (!STATE.hoverLatchedArtist) return;
        const target = ev.target;
        const card = target instanceof Element ? target.closest('.artist-card') : null;
        const hoveredArtist = card ? card.dataset.artist : null;
        if (hoveredArtist === STATE.hoverLatchedArtist) return;
        STATE.hoverLatchedArtist = null;
        renderArtistGrid();
      });

      $('artistGrid').addEventListener('pointerleave', () => {
        if (!isHoverCapablePointer()) return;
        STATE.artistPanePointerInside = false;
        STATE.hoverLatchedArtist = null;
        syncDockedSelectedArtists(true);
        renderArtistGrid();
        if (STATE.dockedSelectedArtists.size) {
          $('artistGrid').scrollTo({ top: 0, behavior: 'smooth' });
        }
      });

      $('taxonomySearch').addEventListener('input', (ev) => {
        STATE.taxonomyQuery = ev.target.value || '';
        STATE.taxonomyPage = 0;
        STATE.taxonomyEvidencePage = 0;
        renderTaxonomy();
      });

      $('taxonomySort').addEventListener('change', (ev) => {
        STATE.taxonomySort = ev.target.value || 'count';
        STATE.taxonomyPage = 0;
        renderTaxonomy();
      });

      $('networkMinScore').addEventListener('input', (ev) => {
        STATE.networkMinScore = Number(ev.target.value || 0);
        renderNetwork();
      });

      $('networkSearch').addEventListener('input', (ev) => {
        STATE.networkSearch = ev.target.value || '';
        renderNetwork();
      });

      $('pairSearch').addEventListener('input', (ev) => {
        STATE.pairQuery = ev.target.value || '';
        STATE.pairPage = 0;
        STATE.pairActiveName = null;
        renderPairWorkspace();
      });

      $('pairSort').addEventListener('change', (ev) => {
        STATE.pairSort = ev.target.value || 'count';
        STATE.pairPage = 0;
        STATE.pairActiveName = null;
        renderPairWorkspace();
      });

      $('setSearch').addEventListener('input', (ev) => {
        STATE.setQuery = ev.target.value || '';
        STATE.setPage = 0;
        renderSetLibrary();
      });

      $('setArtistFilter').addEventListener('change', (ev) => {
        STATE.setArtist = ev.target.value || 'ALL';
        STATE.setPage = 0;
        renderSetLibrary();
      });

      $('setSort').addEventListener('change', (ev) => {
        STATE.setSort = ev.target.value || 'default';
        STATE.setPage = 0;
        renderSetLibrary();
      });

      document.addEventListener('click', (ev) => {
        const actionEl = ev.target.closest('[data-action]');
        if (!actionEl) return;

        const action = actionEl.dataset.action;

        if (action === 'focus-artist') {
          const name = actionEl.dataset.artist || actionEl.closest('[data-artist]')?.dataset.artist;
          if (!name) return;
          const additive = ev.shiftKey || ev.metaKey || ev.ctrlKey;
          const hoverCapable = isHoverCapablePointer();
          const deferDockAdds = hoverCapable && STATE.artistPanePointerInside;
          STATE.hoverLatchedArtist = hoverCapable ? name : null;
          STATE.focusArtist = name;
          if (additive) {
            STATE.selectedArtists.add(name);
          } else {
            STATE.selectedArtists = new Set([name]);
          }
          syncDockedSelectedArtists(!deferDockAdds);
          STATE.taxonomyPage = 0;
          STATE.taxonomyEvidencePage = 0;
          STATE.taxonomyActiveName = null;
          renderAll();
          return;
        }

        if (action === 'toggle-compare-artist') {
          ev.preventDefault();
          ev.stopPropagation();
          const name = actionEl.dataset.artist;
          const deferDockAdds = isHoverCapablePointer()
            && STATE.artistPanePointerInside
            && Boolean(actionEl.closest('#artistGrid'));
          toggleArtistSelection(name);
          if (!deferDockAdds) {
            syncDockedSelectedArtists(true);
          }
          renderAll();
          return;
        }

        if (action === 'compare-all') {
          const names = (DATA.artists || [])
            .map((artist) => artist.name)
            .filter((name) => name && artistsByName.has(name));
          if (!names.length) return;
          STATE.selectedArtists = new Set(names);
          STATE.focusArtist = null;
          STATE.hoverLatchedArtist = null;
          STATE.dockedSelectedArtists = new Set();
          syncDockedSelectedArtists(true);
          STATE.taxonomyPage = 0;
          STATE.taxonomyEvidencePage = 0;
          STATE.taxonomyActiveName = null;
          renderAll();
          return;
        }

        if (action === 'compare-mode') {
          const mode = actionEl.dataset.mode;
          if (mode === 'union' || mode === 'intersection') {
            STATE.compareMode = mode;
            STATE.taxonomyPage = 0;
            STATE.taxonomyEvidencePage = 0;
            STATE.taxonomyActiveName = null;
            renderAll();
          }
          return;
        }

        if (action === 'compare-solo') {
          if (STATE.focusArtist && artistsByName.has(STATE.focusArtist)) {
            STATE.selectedArtists = new Set([STATE.focusArtist]);
          }
          syncDockedSelectedArtists(true);
          STATE.taxonomyPage = 0;
          STATE.taxonomyEvidencePage = 0;
          STATE.taxonomyActiveName = null;
          renderAll();
          return;
        }

        if (action === 'artist-prev' || action === 'artist-next') {
          const list = filteredArtists();
          if (!list.length) return;
          let idx = list.findIndex((a) => a.name === STATE.focusArtist);
          if (idx < 0) idx = 0;
          const delta = action === 'artist-next' ? 1 : -1;
          const next = list[(idx + delta + list.length) % list.length];
          if (!next) return;
          STATE.focusArtist = next.name;
          STATE.selectedArtists = new Set([next.name]);
          syncDockedSelectedArtists(true);
          STATE.taxonomyPage = 0;
          STATE.taxonomyEvidencePage = 0;
          STATE.taxonomyActiveName = null;
          renderAll();
          return;
        }

        if (action === 'taxonomy-lens') {
          const lens = actionEl.dataset.lens;
          if (!lens) return;
          STATE.taxonomyLens = lens;
          STATE.taxonomyPage = 0;
          STATE.taxonomyEvidencePage = 0;
          STATE.taxonomyActiveName = null;
          renderTaxonomy();
          return;
        }

        if (action === 'taxonomy-threshold') {
          const v = Number(actionEl.dataset.threshold || 1);
          STATE.taxonomyMinUsage = Number.isFinite(v) && v > 0 ? v : 1;
          STATE.taxonomyPage = 0;
          STATE.taxonomyEvidencePage = 0;
          STATE.taxonomyActiveName = null;
          renderTaxonomy();
          return;
        }

        if (action === 'taxonomy-threshold-down' || action === 'taxonomy-threshold-up') {
          const direction = action === 'taxonomy-threshold-up' ? 1 : -1;
          STATE.taxonomyMinUsage = stepThresholdValue(STATE.taxonomyMinUsage, THRESHOLD_LEVELS, direction);
          STATE.taxonomyPage = 0;
          STATE.taxonomyEvidencePage = 0;
          STATE.taxonomyActiveName = null;
          renderTaxonomy();
          return;
        }

        if (action === 'taxonomy-conf') {
          const conf = String(actionEl.dataset.conf || 'all').toUpperCase();
          STATE.taxonomyTrackConf = conf === 'ALL' ? 'all' : (CONF_FILTER_LEVELS.includes(conf) ? conf : 'all');
          STATE.taxonomyEvidencePage = 0;
          renderTaxonomy();
          return;
        }

        if (action === 'taxonomy-page') {
          STATE.taxonomyPage += Number(actionEl.dataset.delta || 0);
          renderTaxonomy();
          return;
        }

        if (action === 'taxonomy-row') {
          const name = actionEl.dataset.name || null;
          STATE.taxonomyActiveName = (STATE.taxonomyActiveName === name) ? null : name;
          STATE.taxonomyEvidencePage = 0;
          renderTaxonomy();
          return;
        }

        if (action === 'evidence-page') {
          STATE.taxonomyEvidencePage += Number(actionEl.dataset.delta || 0);
          renderTaxonomy();
          return;
        }

        if (action === 'toggle-sources') {
          const card = actionEl.closest('.track-card');
          const panel = card ? card.querySelector('.source-panel') : null;
          if (!panel) return;
          const closedLabel = actionEl.dataset.closedLabel || 'Sets';
          const openLabel = actionEl.dataset.openLabel || 'Hide Sets';
          const isOpen = card.classList.contains('sources-open');
          if (isOpen) {
            panel.classList.remove('open');
            card.classList.remove('sources-open');
            card.style.removeProperty('--open-art-height');
            card.style.removeProperty('--open-card-height');
            card.style.removeProperty('--open-body-height');
            card.style.removeProperty('--open-source-height');
            actionEl.textContent = closedLabel;
            return;
          }

          const existingEmbed = card.querySelector('.spotify-embed');
          if (existingEmbed) {
            existingEmbed.remove();
            card.classList.remove('embed-open');
            card.style.removeProperty('--open-embed-height');
            card.querySelectorAll('[data-action="spotify-embed"]').forEach((btn) => {
              if (!btn.closest('.spotify-embed')) btn.textContent = 'Spotify';
            });
          }

          const art = card.querySelector('.track-art');
          const body = card.querySelector('.track-body');
          const actions = body ? body.querySelector('.actions') : null;
          const cardHeight = Math.round(card.getBoundingClientRect().height);
          if (cardHeight > 0) {
            const targetSourceHeight = 91.2;
            const controls = actions || body;
            const actionsHeight = controls ? Math.max(28, Math.round(controls.getBoundingClientRect().height)) : 32;
            const bodyHeight = Math.min(cardHeight, actionsHeight + targetSourceHeight);
            const artHeight = Math.max(0, cardHeight - bodyHeight);
            const sourceHeight = Math.max(0, bodyHeight - actionsHeight);
            card.style.setProperty('--open-card-height', `${cardHeight}px`);
            card.style.setProperty('--open-art-height', `${Math.max(0, artHeight)}px`);
            card.style.setProperty('--open-body-height', `${Math.max(0, bodyHeight)}px`);
            card.style.setProperty('--open-source-height', `${Math.max(0, sourceHeight)}px`);
          } else if (art) {
            card.style.setProperty('--open-art-height', `${Math.round(art.getBoundingClientRect().height)}px`);
          }

          panel.classList.add('open');
          card.classList.add('sources-open');
          actionEl.textContent = openLabel;
          return;
        }

        if (action === 'spotify-embed') {
          const card = actionEl.closest('.track-card, .pair-track-card');
          if (!card) return;
          const isTrackCard = card.classList.contains('track-card');
          if (isTrackCard && card.classList.contains('sources-open')) {
            const panel = card.querySelector('.source-panel');
            if (panel) panel.classList.remove('open');
            card.classList.remove('sources-open');
            card.style.removeProperty('--open-art-height');
            card.style.removeProperty('--open-card-height');
            card.style.removeProperty('--open-body-height');
            card.style.removeProperty('--open-source-height');
            card.querySelectorAll('[data-action="toggle-sources"]').forEach((btn) => {
              btn.textContent = btn.dataset.closedLabel || 'Sets';
            });
          }
          const existing = card.querySelector('.spotify-embed');
          if (existing) {
            existing.remove();
            card.classList.remove('embed-open');
            if (isTrackCard) {
              card.style.removeProperty('--open-art-height');
              card.style.removeProperty('--open-card-height');
              card.style.removeProperty('--open-body-height');
              card.style.removeProperty('--open-embed-height');
              card.style.removeProperty('--open-source-height');
            }
            card.querySelectorAll('[data-action="spotify-embed"]').forEach((btn) => {
              if (!btn.closest('.spotify-embed')) btn.textContent = 'Spotify';
            });
            return;
          }
          const id = extractSpotifyId(actionEl.dataset.url || '');
          if (!id) return;
          if (isTrackCard) {
            const art = card.querySelector('.track-art');
            const body = card.querySelector('.track-body');
            const actions = body ? body.querySelector('.actions') : null;
            const cardHeight = Math.round(card.getBoundingClientRect().height);
            if (cardHeight > 0) {
              const targetEmbedHeight = 91.2;
              const controls = actions || body;
              const actionsHeight = controls ? Math.max(28, Math.round(controls.getBoundingClientRect().height)) : 32;
              const bodyHeight = Math.min(cardHeight, actionsHeight + targetEmbedHeight);
              const artHeight = Math.max(0, cardHeight - bodyHeight);
              const embedHeight = Math.max(0, bodyHeight - actionsHeight);
              card.style.setProperty('--open-card-height', `${cardHeight}px`);
              card.style.setProperty('--open-art-height', `${Math.max(0, artHeight)}px`);
              card.style.setProperty('--open-body-height', `${Math.max(0, bodyHeight)}px`);
              card.style.setProperty('--open-embed-height', `${Math.max(0, embedHeight)}px`);
            } else {
              if (art) card.style.setProperty('--open-art-height', `${Math.round(art.getBoundingClientRect().height)}px`);
            }
          }
          const div = document.createElement('div');
          div.className = 'spotify-embed';
          if (isTrackCard) {
            div.innerHTML = `<iframe src="https://open.spotify.com/embed/track/${id}?utm_source=generator&theme=0" allow="autoplay; clipboard-write; encrypted-media"></iframe>`;
          } else {
            div.innerHTML = `<iframe src="https://open.spotify.com/embed/track/${id}?utm_source=generator&theme=0" allow="autoplay; clipboard-write; encrypted-media"></iframe>`;
          }
          const mount = isTrackCard ? card.querySelector('.track-body') : card;
          if (!mount) return;
          mount.appendChild(div);
          card.classList.add('embed-open');
          actionEl.textContent = 'Hide Spotify';
          return;
        }

        if (action === 'network-node') {
          const name = actionEl.dataset.artist;
          if (!name) return;
          if (STATE.networkSelectedArtists.has(name)) {
            STATE.networkSelectedArtists.delete(name);
          } else {
            if (STATE.networkSelectedArtists.size >= 2) {
              STATE.networkSelectedArtists = new Set([name]);
            } else {
              STATE.networkSelectedArtists.add(name);
            }
          }

          const selectedNow = networkSelectedArtistsList();
          STATE.pair = selectedNow.length === 2 ? [selectedNow[0], selectedNow[1]] : null;
          STATE.pairPage = 0;
          STATE.pairActiveName = null;
          renderNetwork();
          renderPairWorkspace();
          return;
        }

        if (action === 'network-clear') {
          STATE.networkSelectedArtists = new Set();
          STATE.pair = null;
          STATE.pairPage = 0;
          STATE.pairActiveName = null;
          renderNetwork();
          renderPairWorkspace();
          return;
        }

        if (action === 'network-edge') {
          const a = actionEl.dataset.a;
          const b = actionEl.dataset.b;
          if (!a || !b) return;
          STATE.pair = [a, b];
          STATE.pairLens = 'genres';
          STATE.pairPage = 0;
          STATE.pairActiveName = null;
          STATE.networkSelectedArtists = new Set([a, b]);
          renderNetwork();
          renderPairWorkspace();
          const networkSection = $('network');
          if (networkSection) networkSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
          return;
        }

        if (action === 'pair-lens') {
          const lens = actionEl.dataset.lens;
          if (!lens) return;
          STATE.pairLens = lens;
          STATE.pairPage = 0;
          STATE.pairActiveName = null;
          renderPairWorkspace();
          return;
        }

        if (action === 'pair-threshold') {
          const v = Number(actionEl.dataset.threshold || 1);
          STATE.pairMinUsage = Number.isFinite(v) && v > 0 ? v : 1;
          STATE.pairPage = 0;
          STATE.pairActiveName = null;
          renderPairWorkspace();
          return;
        }

        if (action === 'pair-threshold-down' || action === 'pair-threshold-up') {
          const direction = action === 'pair-threshold-up' ? 1 : -1;
          STATE.pairMinUsage = stepThresholdValue(STATE.pairMinUsage, THRESHOLD_LEVELS, direction);
          STATE.pairPage = 0;
          STATE.pairActiveName = null;
          renderPairWorkspace();
          return;
        }

        if (action === 'pair-conf') {
          const conf = String(actionEl.dataset.conf || 'all').toUpperCase();
          STATE.pairTrackConf = conf === 'ALL' ? 'all' : (CONF_FILTER_LEVELS.includes(conf) ? conf : 'all');
          renderPairWorkspace();
          return;
        }

        if (action === 'pair-page') {
          STATE.pairPage += Number(actionEl.dataset.delta || 0);
          renderPairWorkspace();
          return;
        }

        if (action === 'pair-row') {
          const name = actionEl.dataset.name || null;
          STATE.pairActiveName = (STATE.pairActiveName === name) ? null : name;
          renderPairWorkspace();
          return;
        }

        if (action === 'toggle-set') {
          const key = actionEl.dataset.key;
          if (!key) return;
          if (STATE.expandedSets.has(key)) {
            STATE.expandedSets.delete(key);
          } else {
            STATE.expandedSets = new Set([key]);
          }
          renderSetLibrary();
          return;
        }

        if (action === 'set-page') {
          STATE.setPage += Number(actionEl.dataset.delta || 0);
          renderSetLibrary();
          $('setGrid').scrollIntoView({ behavior: 'smooth', block: 'start' });
          return;
        }
      });
    }

    function setupReveal() {
      const observer = new IntersectionObserver((entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) entry.target.classList.add('in');
        }
      }, { threshold: 0.08 });

      document.querySelectorAll('.reveal').forEach((el) => observer.observe(el));
    }

    buildHero();
    bind();
    renderAll();
    setupReveal();
    const handleResize = () => {
      syncAtlasHeights();
      syncHeroRailHeight();
      fitHeroToViewport();
      syncHeroRailHeight();
      startHeroRail();
    };
    window.addEventListener('resize', handleResize);
    window.addEventListener('load', handleResize);
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        stopHeroRail();
      } else {
        startHeroRail();
      }
    });
  </script>
</body>
</html>
"""

    return html.replace("__PAYLOAD__", payload)


def save_master_explorer_html(master_data: dict, output_root: str | Path) -> Path:
    """Write redesigned explorer HTML to output/index.html and return its path."""
    output_dir = Path(output_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    client_data = _build_client_data(master_data)
    html = _render_html(client_data)

    output_path = output_dir / "index.html"
    output_path.write_text(html, encoding="utf-8")

    data_path = output_dir / "explorer_data.json"
    data_path.write_text(json.dumps(client_data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Saved explorer HTML: {output_path}")
    print(f"Saved explorer data: {data_path}")
    return output_path
