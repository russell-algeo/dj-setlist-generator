"""Aggregate artist summary across all processed DJ sets."""

import json
from collections import Counter
from pathlib import Path

from detail_explorer_common import (
    EXCLUDED_GENRES,
    SUMMARY_FILES as _SUMMARY_FILES,
    build_mini_timeline,
    build_track_search_text,
    extract_youtube_id as _extract_youtube_id,
    merge_track_metadata,
    youtube_thumbnail_url,
)
from false_positive_policy import is_false_positive_track
from output_formatter import OutputFormatter
from artist_explorer_formatter import save_artist_explorer_html


def _process_set_json(
    data: dict,
    set_output_dir: Path,
    artist_output_dir: Path,
    url: str,
    title_fallback: str,
    set_index: int,
) -> tuple[dict, list[dict]]:
    """Process a single set's JSON data into a set summary and track list.

    Returns (set_summary, track_entries) where track_entries is the list of
    individual track dicts ready for aggregation into all_tracks.
    """
    tracks = [
        track for track in data.get("tracks", [])
        if not is_false_positive_track(track)
    ]
    mix_info = data.get("mix_info", {})

    html_files = list(set_output_dir.glob("*.html"))
    set_html_rel = None
    if html_files:
        try:
            set_html_rel = str(html_files[0].relative_to(artist_output_dir))
        except ValueError:
            pass

    set_tracks = []
    for track in tracks:
        if track.get("title") != "Unknown Track":
            set_tracks.append({
                "artist": track.get("artist", "Unknown"),
                "title": track.get("title", "Unknown Track"),
                "start_time_formatted": track.get("start_time_formatted", ""),
                "confidence": track.get("confidence", "UNCERTAIN"),
                "spotify_url": track.get("spotify_url"),
                "track_key": f"{track.get('artist', 'Unknown')} - {track.get('title', 'Unknown Track')}",
            })

    duration = mix_info.get("duration", 0)
    total_tracks_count = len(tracks)
    recognized = sum(1 for t in tracks if t.get("title") != "Unknown Track")
    recognition_rate = (recognized / total_tracks_count * 100) if total_tracks_count else 0
    confidence_counter = Counter(str(t.get("confidence", "UNCERTAIN")).upper() for t in tracks)
    confidence_counts = {
        "HIGH": confidence_counter.get("HIGH", 0),
        "MEDIUM": confidence_counter.get("MEDIUM", 0),
        "LOW": confidence_counter.get("LOW", 0),
        "UNCERTAIN": confidence_counter.get("UNCERTAIN", 0),
    }
    mini_timeline = build_mini_timeline(tracks, duration)

    set_url = url or mix_info.get("url", "")
    video_id = _extract_youtube_id(set_url)
    thumbnail_url = youtube_thumbnail_url(video_id)
    track_search_text = build_track_search_text(tracks)

    set_summary = {
        "title": mix_info.get("title", title_fallback),
        "url": set_url,
        "total_tracks": total_tracks_count,
        "high_confidence": confidence_counts["HIGH"],
        "set_html_rel": set_html_rel,
        "tracks": set_tracks,
        "index": set_index,
        "duration": duration,
        "recognition_rate": recognition_rate,
        "confidence_counts": confidence_counts,
        "mini_timeline": mini_timeline,
        "thumbnail_url": thumbnail_url,
        "track_search_text": track_search_text,
        "artist_profile_image": mix_info.get("artist_profile_image"),
        "artist_profile_name": mix_info.get("artist_profile_name"),
        "artist_profile_url": mix_info.get("artist_profile_url"),
        "artist_profile_source": mix_info.get("artist_profile_source"),
        "artist_profile_confidence": mix_info.get("artist_profile_confidence"),
        "artist_profile_genre_overlap": mix_info.get("artist_profile_genre_overlap"),
        "artist_profile_rejected_reason": mix_info.get("artist_profile_rejected_reason"),
    }

    set_title = mix_info.get("title", title_fallback)
    track_entries: list[dict] = []
    for pos, track in enumerate(tracks, 1):
        if track.get("artist") != "Unknown" and track.get("title") != "Unknown Track":
            start_fmt = track.get("start_time_formatted", "")
            end_fmt = track.get("end_time_formatted") or ""
            time_range = f"{start_fmt} \u2013 {end_fmt}" if end_fmt else start_fmt
            track_entries.append({
                "artist": track["artist"],
                "title": track["title"],
                "spotify_url": track.get("spotify_url"),
                "spotify_album_art": track.get("spotify_album_art"),
                "spotify_artist_name": track.get("spotify_artist_name"),
                "spotify_artist_url": track.get("spotify_artist_url"),
                "spotify_artist_profile_image": track.get("spotify_artist_profile_image"),
                "from_set": set_title,
                "time_range": time_range,
                "source_deep_link": track.get("source_deep_link"),
                "set_html_rel": set_html_rel,
                "confidence": track.get("confidence", "UNCERTAIN"),
                "genres": ((track.get("discogs_styles") or []) + (track.get("spotify_genres") or [])) or (track.get("discogs_genres") or []),
                "track_position": track.get("position", pos),
                "discogs_label": track.get("discogs_label"),
                "discogs_label_url": track.get("discogs_label_url"),
            })

    return set_summary, track_entries


class ArtistSummarizer:
    """Aggregate data across all processed DJ sets and delegate to formatters."""

    def __init__(self, artist_manager):
        self._artist_manager = artist_manager
        self._artist_name = artist_manager.artist_name
        self._output_dir = artist_manager.output_dir

    def generate(self, results: list[dict]):
        """Aggregate per-set data and write artist summary outputs.

        Args:
            results: List of dicts with keys: url, status, mix_name, output_dir
        """
        successful = [r for r in results if r["status"] == "SUCCESS"]
        failed = [r for r in results if r["status"] != "SUCCESS"]

        all_tracks: list[dict] = []
        set_summaries: list[dict] = []

        # Track which output directories were covered by the current discovery run
        covered_output_dirs: set[Path] = set()

        for result in successful:
            set_output_dir = result.get("output_dir")
            if not set_output_dir:
                continue

            json_files = list(Path(set_output_dir).glob("*.json"))
            if not json_files:
                continue

            try:
                with open(json_files[0]) as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            covered_output_dirs.add(Path(set_output_dir).resolve())

            summary, track_entries = _process_set_json(
                data,
                Path(set_output_dir),
                self._output_dir,
                url=result["url"],
                title_fallback=result.get("mix_name", "Unknown"),
                set_index=len(set_summaries),
            )
            set_summaries.append(summary)
            all_tracks.extend(track_entries)

        # Include manually-migrated sets that weren't part of this discovery run.
        for set_dir in sorted(self._output_dir.iterdir()):
            if not set_dir.is_dir() or set_dir.resolve() in covered_output_dirs:
                continue

            json_files = [
                f for f in set_dir.glob("*.json")
                if f.name not in _SUMMARY_FILES
            ]
            if not json_files:
                continue

            try:
                with open(json_files[0]) as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            mix_info = data.get("mix_info", {})

            summary, track_entries = _process_set_json(
                data,
                set_dir,
                self._output_dir,
                url=mix_info.get("url", ""),
                title_fallback=set_dir.name,
                set_index=len(set_summaries),
            )
            set_summaries.append(summary)
            all_tracks.extend(track_entries)

        track_counter = Counter()
        track_info = {}
        _genre_counters: dict = {}
        _excluded_genres = {g.title() for g in EXCLUDED_GENRES}
        for t in all_tracks:
            key = f"{t['artist']} - {t['title']}"
            track_counter[key] += 1
            if key not in track_info:
                track_info[key] = {
                    "artist": t["artist"],
                    "title": t["title"],
                    "spotify_url": t.get("spotify_url"),
                    "spotify_album_art": t.get("spotify_album_art"),
                    "spotify_artist_name": t.get("spotify_artist_name"),
                    "spotify_artist_url": t.get("spotify_artist_url"),
                    "spotify_artist_profile_image": t.get("spotify_artist_profile_image"),
                    "appearances": [],
                    "genres": [],
                    "discogs_label": None,
                    "discogs_label_url": None,
                }
                _genre_counters[key] = Counter()
            # Take first non-None label/art values encountered
            if not track_info[key]["discogs_label"] and t.get("discogs_label"):
                track_info[key]["discogs_label_url"] = t.get("discogs_label_url")
            merge_track_metadata(track_info[key], t, [
                "spotify_album_art", "spotify_artist_name",
                "spotify_artist_url", "spotify_artist_profile_image",
                "discogs_label",
            ])
            track_info[key]["appearances"].append({
                "set_title": t["from_set"],
                "time_range": t.get("time_range", ""),
                "source_deep_link": t.get("source_deep_link"),
                "set_html_rel": t.get("set_html_rel"),
                "confidence": t.get("confidence", "UNCERTAIN"),
                "track_position": t.get("track_position"),
            })
            for genre in t.get("genres", []):
                normalized = genre.title()
                if normalized in _excluded_genres:
                    continue
                _genre_counters[key][normalized] += 1

        # Materialise genre lists (most-common first) from per-track counters
        for key in track_info:
            track_info[key]["genres"] = [g for g, _ in _genre_counters[key].most_common(5)]

        output_fmt = OutputFormatter(artist_manager=self._artist_manager)

        output_fmt.save_artist_summary_markdown(
            self._artist_name, set_summaries, track_counter, track_info, successful, failed
        )
        output_fmt.save_artist_summary_json(
            self._artist_name, set_summaries, track_counter, track_info, all_tracks, successful, failed
        )
        save_artist_explorer_html(
            self._artist_manager.output_dir, self._artist_name, set_summaries, track_counter, track_info, successful, failed
        )
