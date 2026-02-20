"""Aggregate artist summary across all processed DJ sets."""

import json
from pathlib import Path
from collections import Counter

from output_formatter import OutputFormatter
from html_formatter import HtmlFormatter


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

            set_summaries.append({
                "title": mix_info.get("title", result.get("mix_name", "Unknown")),
                "url": result["url"],
                "total_tracks": metadata.get("total_tracks", len(tracks)),
                "high_confidence": metadata.get("high_confidence_tracks", 0),
                "set_html_rel": set_html_rel,
            })

            set_title = mix_info.get("title", "Unknown")
            for track in tracks:
                if track.get("artist") != "Unknown" and track.get("title") != "Unknown Track":
                    start_fmt = track.get("start_time_formatted", "")
                    end_fmt   = track.get("end_time_formatted") or ""
                    time_range = f"{start_fmt} \u2013 {end_fmt}" if end_fmt else start_fmt
                    all_tracks.append({
                        "artist":          track["artist"],
                        "title":           track["title"],
                        "spotify_url":     track.get("spotify_url"),
                        "from_set":        set_title,
                        "time_range":      time_range,
                        "source_deep_link": track.get("source_deep_link"),
                        "set_html_rel":    set_html_rel,
                        "confidence":      track.get("confidence", "UNCERTAIN"),
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

            set_summaries.append({
                "title": mix_info.get("title", set_dir.name),
                "url": url,
                "total_tracks": metadata.get("total_tracks", len(tracks)),
                "high_confidence": metadata.get("high_confidence_tracks", 0),
                "set_html_rel": set_html_rel,
            })

            set_title = mix_info.get("title", set_dir.name)
            for track in tracks:
                if track.get("artist") != "Unknown" and track.get("title") != "Unknown Track":
                    start_fmt = track.get("start_time_formatted", "")
                    end_fmt   = track.get("end_time_formatted") or ""
                    time_range = f"{start_fmt} \u2013 {end_fmt}" if end_fmt else start_fmt
                    all_tracks.append({
                        "artist":          track["artist"],
                        "title":           track["title"],
                        "spotify_url":     track.get("spotify_url"),
                        "from_set":        set_title,
                        "time_range":      time_range,
                        "source_deep_link": track.get("source_deep_link"),
                        "set_html_rel":    set_html_rel,
                        "confidence":      track.get("confidence", "UNCERTAIN"),
                    })

        track_counter = Counter()
        track_info = {}
        for t in all_tracks:
            key = f"{t['artist']} - {t['title']}"
            track_counter[key] += 1
            if key not in track_info:
                track_info[key] = {
                    "artist":      t["artist"],
                    "title":       t["title"],
                    "spotify_url": t.get("spotify_url"),
                    "appearances": [],
                }
            track_info[key]["appearances"].append({
                "set_title":       t["from_set"],
                "time_range":      t.get("time_range", ""),
                "source_deep_link": t.get("source_deep_link"),
                "set_html_rel":    t.get("set_html_rel"),
                "confidence":      t.get("confidence", "UNCERTAIN"),
            })

        output_fmt = OutputFormatter(artist_manager=self._artist_manager)
        html_fmt   = HtmlFormatter(artist_manager=self._artist_manager)

        output_fmt.save_artist_summary_markdown(
            self._artist_name, set_summaries, track_counter, track_info, successful, failed
        )
        output_fmt.save_artist_summary_json(
            self._artist_name, set_summaries, track_counter, track_info, all_tracks, successful, failed
        )
        html_fmt.save_artist_summary_html(
            self._artist_name, set_summaries, track_counter, track_info, successful, failed
        )
