"""Re-enrich existing JSON outputs with Spotify metadata (album art, preview, genres, BPM, key).

Reads each set's JSON file, finds tracks missing the new Spotify fields,
batch-fetches the data from Spotify, and writes the updated JSON back.

Usage:
    python backfill_enrichment.py                   # re-enrich ALL outputs
    python backfill_enrichment.py "Jay Tripwire"    # re-enrich one artist
    python backfill_enrichment.py --dry-run          # show what would be updated
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from metadata_enricher import MetadataEnricher


_SUMMARY_FILES = {"artist_summary.json", "artist_summary.md", "artist_summary.html"}

# Spotify pitch class → note name
_KEY_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def _needs_enrichment(track: dict) -> bool:
    """Return True if this track has a spotify_url but is missing new fields."""
    if not track.get("spotify_url"):
        return False
    return (
        not track.get("spotify_album_art")
        or track.get("spotify_bpm") is None
    )


def _enrich_json(json_path: Path, enricher: MetadataEnricher, dry_run: bool) -> bool:
    """Re-enrich a single JSON file with missing Spotify metadata.

    Returns True if the file was updated (or would be in dry-run mode).
    """
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  ERROR reading {json_path}: {e}")
        return False

    tracks = data.get("tracks", [])
    if not tracks:
        return False

    needs_update = [t for t in tracks if _needs_enrichment(t)]
    if not needs_update:
        return False

    print(f"  {json_path.parent.name}/{json_path.name}: {len(needs_update)} tracks need enrichment")

    if dry_run:
        return True

    if not enricher.spotify:
        print("  SKIP: Spotify client not available")
        return False

    # Phase 1: Re-search tracks missing album art / preview URL
    spotify_track_ids = []  # parallel to needs_update
    for t in needs_update:
        url = t.get("spotify_url", "")
        if url:
            # Extract track ID from existing URL
            tid = url.split("/")[-1].split("?")[0]
            spotify_track_ids.append(tid)
        else:
            spotify_track_ids.append(None)

    # Batch fetch full track objects for album art and preview
    valid_ids = [tid for tid in spotify_track_ids if tid]
    track_objects = {}  # id -> track object
    if valid_ids:
        for i in range(0, len(valid_ids), 50):
            batch = valid_ids[i:i + 50]
            try:
                results = enricher.spotify.tracks(batch)
                for item in results.get("tracks", []):
                    if item:
                        track_objects[item["id"]] = item
            except Exception as e:
                print(f"    Batch tracks fetch error: {e}")

    # Batch fetch audio features for BPM/key
    audio_features = {}  # id -> features
    if valid_ids:
        for i in range(0, len(valid_ids), 100):
            batch = valid_ids[i:i + 100]
            try:
                features = enricher.spotify.audio_features(batch)
                for feat in (features or []):
                    if feat:
                        audio_features[feat["id"]] = feat
            except Exception as e:
                print(f"    Batch audio_features fetch error: {e}")

    # Collect artist IDs for genre lookup
    artist_ids_needed = set()
    track_to_artist_id = {}  # track_id -> artist_id
    for tid, obj in track_objects.items():
        if obj.get("artists"):
            aid = obj["artists"][0]["id"]
            artist_ids_needed.add(aid)
            track_to_artist_id[tid] = aid

    # Apply enrichment to tracks
    updated_count = 0
    for t, tid in zip(needs_update, spotify_track_ids):
        if not tid:
            continue

        changed = False

        # Album art
        obj = track_objects.get(tid)
        if obj and not t.get("spotify_album_art"):
            images = obj.get("album", {}).get("images", [])
            art_url = next(
                (img["url"] for img in images if img.get("height") == 300),
                images[0]["url"] if images else None
            )
            if art_url:
                t["spotify_album_art"] = art_url
                changed = True

        # Preview URL
        if obj and not t.get("spotify_preview_url"):
            preview = obj.get("preview_url")
            if preview:
                t["spotify_preview_url"] = preview
                changed = True

        # BPM / Key
        feat = audio_features.get(tid)
        if feat:
            if t.get("spotify_bpm") is None:
                t["spotify_bpm"] = round(feat.get("tempo", 0), 1)
                changed = True
            if not t.get("spotify_key"):
                key_idx = feat.get("key", -1)
                mode = feat.get("mode", 0)
                if key_idx >= 0:
                    t["spotify_key"] = _KEY_NAMES[key_idx] + ("m" if mode == 0 else "")
                    changed = True

        # Genres
        aid = track_to_artist_id.get(tid)
        if aid and not t.get("spotify_genres"):
            genres = enricher._get_artist_genres(aid)
            if genres:
                t["spotify_genres"] = genres
                changed = True

        if changed:
            updated_count += 1

    if updated_count == 0:
        return False

    # Write updated JSON back
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"    Updated {updated_count} tracks")
        return True
    except OSError as e:
        print(f"  ERROR writing {json_path}: {e}")
        return False


def scan_and_enrich(output_dir: Path, target: str | None, dry_run: bool) -> None:
    """Walk output directory and re-enrich all JSON files."""
    if not output_dir.exists():
        print(f"Output directory not found: {output_dir}")
        return

    enricher = None
    if not dry_run:
        enricher = MetadataEnricher()
        if not enricher.spotify:
            print("ERROR: Spotify client required for enrichment. Check SPOTIFY_CLIENT_ID/SECRET.")
            return

    entries = sorted(output_dir.iterdir())
    if target:
        entries = [e for e in entries if e.is_dir() and e.name == target]
        if not entries:
            print(f"No directory named '{target}' found in {output_dir}")
            return

    total_updated = 0
    for entry in entries:
        if not entry.is_dir():
            continue

        # Check if artist-mode (has subdirectories with JSON)
        sub_dirs = [d for d in entry.iterdir() if d.is_dir()]
        has_sub_json = any(
            any(f.suffix == ".json" and f.name not in _SUMMARY_FILES for f in d.iterdir())
            for d in sub_dirs if d.is_dir()
        )

        if has_sub_json:
            # Artist mode
            print(f"\n[Artist] {entry.name}")
            for set_dir in sorted(sub_dirs):
                for json_path in sorted(set_dir.glob("*.json")):
                    if json_path.name in _SUMMARY_FILES:
                        continue
                    if _enrich_json(json_path, enricher, dry_run):
                        total_updated += 1
        else:
            # URL mode
            for json_path in sorted(entry.glob("*.json")):
                if json_path.name in _SUMMARY_FILES:
                    continue
                if _enrich_json(json_path, enricher, dry_run):
                    total_updated += 1

    print(f"\nDone. {'Would update' if dry_run else 'Updated'} {total_updated} JSON files.")
    if not dry_run and total_updated > 0:
        print("Run `python backfill_html.py` next to regenerate HTML from the updated JSON.")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Re-enrich existing JSON outputs with Spotify metadata."
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Name of a specific output directory to re-enrich (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Root output directory to scan (default: output/)",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    if args.dry_run:
        print("DRY RUN — no files will be written\n")

    scan_and_enrich(output_dir, target=args.target, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
