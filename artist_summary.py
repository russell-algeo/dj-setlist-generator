"""Generate aggregate artist summary across all processed DJ sets."""

import json
from pathlib import Path
from datetime import datetime
from collections import Counter


class ArtistSummarizer:
    """Generate aggregate artist summary across all processed DJ sets."""

    def __init__(self, artist_manager):
        self._artist_name = artist_manager.artist_name
        self._output_dir = artist_manager.output_dir

    def generate(self, results: list[dict]):
        """Generate artist_summary.md and artist_summary.json.

        Args:
            results: List of dicts with keys: url, status, mix_name, output_dir
        """
        successful = [r for r in results if r["status"] == "SUCCESS"]
        failed = [r for r in results if r["status"] != "SUCCESS"]

        all_tracks = []
        set_summaries = []

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

            tracks = data.get("tracks", [])
            mix_info = data.get("mix_info", {})
            metadata = data.get("metadata", {})

            set_summaries.append({
                "title": mix_info.get("title", result.get("mix_name", "Unknown")),
                "url": result["url"],
                "total_tracks": metadata.get("total_tracks", len(tracks)),
                "high_confidence": metadata.get("high_confidence_tracks", 0),
            })

            for track in tracks:
                if track.get("artist") != "Unknown" and track.get("title") != "Unknown Track":
                    all_tracks.append({
                        "artist": track["artist"],
                        "title": track["title"],
                        "spotify_url": track.get("spotify_url"),
                        "from_set": mix_info.get("title", "Unknown"),
                    })

        track_counter = Counter()
        track_info = {}
        for t in all_tracks:
            key = f"{t['artist']} - {t['title']}"
            track_counter[key] += 1
            if key not in track_info:
                track_info[key] = t

        _save_summary_markdown(
            self._artist_name, self._output_dir, set_summaries, track_counter,
            track_info, successful, failed
        )
        _save_summary_json(
            self._artist_name, self._output_dir, set_summaries, track_counter,
            track_info, all_tracks, successful, failed
        )


def _save_summary_markdown(
    artist_name, output_dir, set_summaries, track_counter,
    track_info, successful, failed
):
    """Write the artist_summary.md file."""
    lines = []
    lines.append(f"# {artist_name} - DJ Set Analysis")
    lines.append(f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Sets Analyzed:** {len(successful)} successful, {len(failed)} failed")
    lines.append(f"**Unique Tracks Found:** {len(track_counter)}")

    # Sets overview
    lines.append(f"\n---\n")
    lines.append(f"## Sets Analyzed\n")
    for i, s in enumerate(set_summaries, 1):
        lines.append(f"{i}. **{s['title']}** - {s['total_tracks']} tracks ({s['high_confidence']} high confidence)")
        lines.append(f"   Source: {s['url']}")

    # Most played tracks
    most_common = track_counter.most_common(30)
    if most_common:
        lines.append(f"\n---\n")
        lines.append(f"## Most Played Tracks\n")
        lines.append("Tracks that appear across multiple sets:\n")
        for rank, (track_key, count) in enumerate(most_common, 1):
            info = track_info[track_key]
            spotify = f" | [Spotify]({info['spotify_url']})" if info.get("spotify_url") else ""
            lines.append(f"{rank}. **{track_key}** - played in {count} set(s){spotify}")

    # Failed sets
    if failed:
        lines.append(f"\n---\n")
        lines.append(f"## Failed Sets\n")
        for r in failed:
            lines.append(f"- {r['url']}: {r['status']}")

    output_path = output_dir / "artist_summary.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nSaved artist summary: {output_path}")


def _save_summary_json(
    artist_name, output_dir, set_summaries, track_counter,
    track_info, all_tracks, successful, failed
):
    """Write the artist_summary.json file."""
    summary = {
        "artist": artist_name,
        "generated_at": datetime.now().isoformat(),
        "stats": {
            "sets_analyzed": len(successful),
            "sets_failed": len(failed),
            "unique_tracks": len(track_counter),
            "total_track_appearances": len(all_tracks),
        },
        "sets": set_summaries,
        "most_played_tracks": [
            {
                "artist": track_info[key]["artist"],
                "title": track_info[key]["title"],
                "appearances": count,
                "spotify_url": track_info[key].get("spotify_url"),
            }
            for key, count in track_counter.most_common(50)
        ],
        "failed_sets": [
            {"url": r["url"], "error": r["status"]}
            for r in failed
        ],
    }

    output_path = output_dir / "artist_summary.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"Saved artist summary JSON: {output_path}")
