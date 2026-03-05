"""Aggregate artist summary across all processed DJ sets."""

import json
from pathlib import Path
from collections import Counter
from urllib.parse import urlparse, parse_qs

from output_formatter import OutputFormatter
from artist_explorer_formatter import save_artist_explorer_html


def _extract_youtube_id(url: str) -> str | None:
    """Extract YouTube video ID from URL."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower().removeprefix('www.').removeprefix('m.')
        if host == 'youtube.com':
            return parse_qs(parsed.query).get('v', [None])[0]
        if host == 'youtu.be':
            return parsed.path.lstrip('/')
    except Exception:
        pass
    return None


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

        all_tracks = []
        set_summaries = []

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

            tracks = data.get("tracks", [])
            mix_info = data.get("mix_info", {})
            metadata = data.get("metadata", {})

            # Find per-set HTML file and compute its path relative to the
            # artist summary page so set cards can link to it directly.
            html_files = list(Path(set_output_dir).glob("*.html"))
            set_html_rel = None
            if html_files:
                try:
                    set_html_rel = str(html_files[0].relative_to(self._output_dir))
                except ValueError:
                    pass  # output_dir outside expected tree — skip relative link

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

            # Extra fields for improved set grid (Feature 6)
            duration = mix_info.get("duration", 0)
            total_tracks_count = metadata.get("total_tracks", len(tracks))
            recognized = sum(1 for t in tracks if t.get("title") != "Unknown Track")
            recognition_rate = (recognized / total_tracks_count * 100) if total_tracks_count else 0
            confidence_counts = {
                "HIGH": metadata.get("high_confidence_tracks", 0),
                "MEDIUM": metadata.get("medium_confidence_tracks", 0),
                "LOW": metadata.get("low_confidence_tracks", 0),
                "UNCERTAIN": metadata.get("uncertain_tracks", 0),
            }
            mini_timeline = []
            for t in tracks:
                if duration and t.get("start_time") is not None:
                    start = t["start_time"]
                    end = t.get("end_time") or duration
                    start_pct = start / duration * 100
                    width_pct = max(0.5, (end - start) / duration * 100)
                    mini_timeline.append({
                        "start_pct": start_pct,
                        "width_pct": width_pct,
                        "confidence": t.get("confidence", "UNCERTAIN"),
                    })
            set_url = result["url"] or mix_info.get("url", "")
            video_id = _extract_youtube_id(set_url)
            thumbnail_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg" if video_id else None
            track_search_text = " ".join(
                f"{t.get('artist', '')} {t.get('title', '')}".lower()
                for t in tracks
                if t.get("title") != "Unknown Track"
            )

            set_summaries.append({
                "title": mix_info.get("title", result.get("mix_name", "Unknown")),
                "url": result["url"],
                "total_tracks": total_tracks_count,
                "high_confidence": metadata.get("high_confidence_tracks", 0),
                "set_html_rel": set_html_rel,
                "tracks": set_tracks,
                "index": len(set_summaries),
                # NEW fields for Feature 6
                "duration": duration,
                "recognition_rate": recognition_rate,
                "confidence_counts": confidence_counts,
                "mini_timeline": mini_timeline,
                "thumbnail_url": thumbnail_url,
                "track_search_text": track_search_text,
                # Canonical set-level artist profile fields (already confidence-gated upstream).
                "artist_profile_image": mix_info.get("artist_profile_image"),
                "artist_profile_name": mix_info.get("artist_profile_name"),
                "artist_profile_url": mix_info.get("artist_profile_url"),
                "artist_profile_source": mix_info.get("artist_profile_source"),
                "artist_profile_confidence": mix_info.get("artist_profile_confidence"),
                "artist_profile_genre_overlap": mix_info.get("artist_profile_genre_overlap"),
                "artist_profile_rejected_reason": mix_info.get("artist_profile_rejected_reason"),
            })

            set_title = mix_info.get("title", "Unknown")
            for pos, track in enumerate(tracks, 1):
                if track.get("artist") != "Unknown" and track.get("title") != "Unknown Track":
                    start_fmt = track.get("start_time_formatted", "")
                    end_fmt   = track.get("end_time_formatted") or ""
                    time_range = f"{start_fmt} \u2013 {end_fmt}" if end_fmt else start_fmt
                    all_tracks.append({
                        "artist":            track["artist"],
                        "title":             track["title"],
                        "spotify_url":       track.get("spotify_url"),
                        "spotify_album_art": track.get("spotify_album_art"),
                        "spotify_artist_name": track.get("spotify_artist_name"),
                        "spotify_artist_url": track.get("spotify_artist_url"),
                        "spotify_artist_profile_image": (
                            track.get("spotify_artist_profile_image") or track.get("spotify_artist_image")
                        ),
                        "spotify_artist_image": (
                            track.get("spotify_artist_image") or track.get("spotify_artist_profile_image")
                        ),
                        "from_set":          set_title,
                        "time_range":        time_range,
                        "source_deep_link":  track.get("source_deep_link"),
                        "set_html_rel":      set_html_rel,
                        "confidence":        track.get("confidence", "UNCERTAIN"),
                        "genres":            ((track.get("discogs_styles") or []) + (track.get("spotify_genres") or [])) or (track.get("discogs_genres") or []),
                        "track_position":    pos,
                        "discogs_label":     track.get("discogs_label"),
                        "discogs_label_url": track.get("discogs_label_url"),
                    })

        # Include manually-migrated sets that weren't part of this discovery run.
        # Scan the artist output directory for set subdirectories with JSON output
        # that weren't already processed above.
        SUMMARY_FILES = {"artist_summary.json", "artist_summary.md", "artist_summary.html"}
        for set_dir in sorted(self._output_dir.iterdir()):
            if not set_dir.is_dir() or set_dir.resolve() in covered_output_dirs:
                continue

            json_files = [
                f for f in set_dir.glob("*.json")
                if f.name not in SUMMARY_FILES
            ]
            if not json_files:
                continue

            try:
                with open(json_files[0]) as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            tracks = data.get("tracks", [])
            mix_info = data.get("mix_info", {})
            metadata = data.get("metadata", {})
            url = mix_info.get("url", "")

            html_files = list(set_dir.glob("*.html"))
            set_html_rel = None
            if html_files:
                try:
                    set_html_rel = str(html_files[0].relative_to(self._output_dir))
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

            # Extra fields for improved set grid (Feature 6)
            duration = mix_info.get("duration", 0)
            total_tracks_count = metadata.get("total_tracks", len(tracks))
            recognized = sum(1 for t in tracks if t.get("title") != "Unknown Track")
            recognition_rate = (recognized / total_tracks_count * 100) if total_tracks_count else 0
            confidence_counts = {
                "HIGH": metadata.get("high_confidence_tracks", 0),
                "MEDIUM": metadata.get("medium_confidence_tracks", 0),
                "LOW": metadata.get("low_confidence_tracks", 0),
                "UNCERTAIN": metadata.get("uncertain_tracks", 0),
            }
            mini_timeline = []
            for t in tracks:
                if duration and t.get("start_time") is not None:
                    start = t["start_time"]
                    end = t.get("end_time") or duration
                    start_pct = start / duration * 100
                    width_pct = max(0.5, (end - start) / duration * 100)
                    mini_timeline.append({
                        "start_pct": start_pct,
                        "width_pct": width_pct,
                        "confidence": t.get("confidence", "UNCERTAIN"),
                    })
            video_id = _extract_youtube_id(url)
            thumbnail_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg" if video_id else None
            track_search_text = " ".join(
                f"{t.get('artist', '')} {t.get('title', '')}".lower()
                for t in tracks
                if t.get("title") != "Unknown Track"
            )

            set_summaries.append({
                "title": mix_info.get("title", set_dir.name),
                "url": url,
                "total_tracks": total_tracks_count,
                "high_confidence": metadata.get("high_confidence_tracks", 0),
                "set_html_rel": set_html_rel,
                "tracks": set_tracks,
                "index": len(set_summaries),
                # NEW fields for Feature 6
                "duration": duration,
                "recognition_rate": recognition_rate,
                "confidence_counts": confidence_counts,
                "mini_timeline": mini_timeline,
                "thumbnail_url": thumbnail_url,
                "track_search_text": track_search_text,
                # Canonical set-level artist profile fields (already confidence-gated upstream).
                "artist_profile_image": mix_info.get("artist_profile_image"),
                "artist_profile_name": mix_info.get("artist_profile_name"),
                "artist_profile_url": mix_info.get("artist_profile_url"),
                "artist_profile_source": mix_info.get("artist_profile_source"),
                "artist_profile_confidence": mix_info.get("artist_profile_confidence"),
                "artist_profile_genre_overlap": mix_info.get("artist_profile_genre_overlap"),
                "artist_profile_rejected_reason": mix_info.get("artist_profile_rejected_reason"),
            })

            set_title = mix_info.get("title", set_dir.name)
            for pos, track in enumerate(tracks, 1):
                if track.get("artist") != "Unknown" and track.get("title") != "Unknown Track":
                    start_fmt = track.get("start_time_formatted", "")
                    end_fmt   = track.get("end_time_formatted") or ""
                    time_range = f"{start_fmt} \u2013 {end_fmt}" if end_fmt else start_fmt
                    all_tracks.append({
                        "artist":            track["artist"],
                        "title":             track["title"],
                        "spotify_url":       track.get("spotify_url"),
                        "spotify_album_art": track.get("spotify_album_art"),
                        "spotify_artist_name": track.get("spotify_artist_name"),
                        "spotify_artist_url": track.get("spotify_artist_url"),
                        "spotify_artist_profile_image": (
                            track.get("spotify_artist_profile_image") or track.get("spotify_artist_image")
                        ),
                        "spotify_artist_image": (
                            track.get("spotify_artist_image") or track.get("spotify_artist_profile_image")
                        ),
                        "from_set":          set_title,
                        "time_range":        time_range,
                        "source_deep_link":  track.get("source_deep_link"),
                        "set_html_rel":      set_html_rel,
                        "confidence":        track.get("confidence", "UNCERTAIN"),
                        "genres":            ((track.get("discogs_styles") or []) + (track.get("spotify_genres") or [])) or (track.get("discogs_genres") or []),
                        "track_position":    pos,
                        "discogs_label":     track.get("discogs_label"),
                        "discogs_label_url": track.get("discogs_label_url"),
                    })

        track_counter = Counter()
        track_info = {}
        _genre_counters: dict = {}
        for t in all_tracks:
            key = f"{t['artist']} - {t['title']}"
            track_counter[key] += 1
            if key not in track_info:
                track_info[key] = {
                    "artist":            t["artist"],
                    "title":             t["title"],
                    "spotify_url":       t.get("spotify_url"),
                    "spotify_album_art": t.get("spotify_album_art"),
                    "spotify_artist_name": t.get("spotify_artist_name"),
                    "spotify_artist_url": t.get("spotify_artist_url"),
                    "spotify_artist_profile_image": (
                        t.get("spotify_artist_profile_image") or t.get("spotify_artist_image")
                    ),
                    "spotify_artist_image": (
                        t.get("spotify_artist_image") or t.get("spotify_artist_profile_image")
                    ),
                    "appearances":       [],
                    "genres":            [],
                    "discogs_label":     None,
                    "discogs_label_url": None,
                }
                _genre_counters[key] = Counter()
            # Take first non-None label/art values encountered
            if not track_info[key]["discogs_label"] and t.get("discogs_label"):
                track_info[key]["discogs_label"]     = t["discogs_label"]
                track_info[key]["discogs_label_url"] = t.get("discogs_label_url")
            if not track_info[key]["spotify_album_art"] and t.get("spotify_album_art"):
                track_info[key]["spotify_album_art"] = t["spotify_album_art"]
            if not track_info[key]["spotify_artist_name"] and t.get("spotify_artist_name"):
                track_info[key]["spotify_artist_name"] = t["spotify_artist_name"]
            if not track_info[key]["spotify_artist_url"] and t.get("spotify_artist_url"):
                track_info[key]["spotify_artist_url"] = t["spotify_artist_url"]
            if not track_info[key]["spotify_artist_profile_image"] and t.get("spotify_artist_profile_image"):
                track_info[key]["spotify_artist_profile_image"] = t["spotify_artist_profile_image"]
            if not track_info[key]["spotify_artist_image"] and t.get("spotify_artist_image"):
                track_info[key]["spotify_artist_image"] = t["spotify_artist_image"]
            track_info[key]["appearances"].append({
                "set_title":        t["from_set"],
                "time_range":       t.get("time_range", ""),
                "source_deep_link": t.get("source_deep_link"),
                "set_html_rel":     t.get("set_html_rel"),
                "confidence":       t.get("confidence", "UNCERTAIN"),
                "track_position":   t.get("track_position"),
            })
            for genre in t.get("genres", []):
                normalized = genre.title()
                if normalized == "House":
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
