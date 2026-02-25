"""Re-enrich existing JSON outputs with metadata from Spotify, ReccoBeats, and Discogs.

Reads each set's JSON file, finds tracks missing enrichment fields,
batch-fetches data from the appropriate APIs, and writes the updated JSON back.

Data sources:
- Spotify: album art, preview URL, artist-level genres (existing)
- ReccoBeats: BPM/tempo, musical key, energy, danceability (replaces deprecated Spotify audio_features)
- Discogs: release-level genres, styles, label, full URL

Usage:
    python backfill_enrichment.py                   # re-enrich ALL outputs
    python backfill_enrichment.py "Jay Tripwire"    # re-enrich one artist
    python backfill_enrichment.py --dry-run          # show what would be updated
"""

import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from metadata_enricher import MetadataEnricher, _RECCOBEATS_BASE, _KEY_NAMES


_SUMMARY_FILES = {"artist_summary.json", "artist_summary.md", "artist_summary.html"}


def _needs_enrichment(track: dict) -> bool:
    """Return True if this track is missing any enrichment fields."""
    has_spotify = bool(track.get("spotify_url"))
    has_artist_title = track.get("artist") and track.get("title") != "Unknown Track"

    if not has_spotify and not has_artist_title:
        return False

    # Check for missing Spotify metadata (album art, preview)
    if has_spotify and not track.get("spotify_album_art"):
        return True

    # Check for missing audio features (BPM/key from ReccoBeats)
    if has_spotify and track.get("bpm") is None and track.get("spotify_bpm") is None:
        return True

    # Check for missing Discogs metadata
    if has_artist_title and not track.get("discogs_genres"):
        return True

    return False


def _batch_fetch_reccobeats(spotify_ids: list[str]) -> dict:
    """Fetch audio features from ReccoBeats for a list of Spotify track IDs.

    Returns:
        Dict mapping track_id -> features dict.
    """
    all_features = {}
    batch_size = 50
    for i in range(0, len(spotify_ids), batch_size):
        batch = spotify_ids[i:i + batch_size]
        try:
            ids_param = ",".join(batch)
            resp = requests.get(
                f"{_RECCOBEATS_BASE}/audio-features",
                params={"ids": ids_param},
                timeout=15,
            )
            if resp.status_code == 429:
                print("    [ReccoBeats] Rate limited, waiting 2s...")
                time.sleep(2)
                resp = requests.get(
                    f"{_RECCOBEATS_BASE}/audio-features",
                    params={"ids": ids_param},
                    timeout=15,
                )
            resp.raise_for_status()
            data = resp.json()
            features_list = data.get("content", data if isinstance(data, list) else [])
            for feat in features_list:
                if feat and isinstance(feat, dict):
                    fid = feat.get("id") or feat.get("trackId")
                    if fid:
                        all_features[fid] = feat
                    elif len(batch) == 1:
                        all_features[batch[0]] = feat
        except Exception as e:
            print(f"    [ReccoBeats] Batch fetch error: {e}")
        if i + batch_size < len(spotify_ids):
            time.sleep(0.5)
    return all_features


def _enrich_json(json_path: Path, enricher: MetadataEnricher, dry_run: bool) -> bool:
    """Re-enrich a single JSON file with missing metadata.

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

    # --- Phase 1: Spotify album art, preview, artist genres ---
    spotify_track_ids = []  # parallel to needs_update
    for t in needs_update:
        url = t.get("spotify_url", "")
        if url:
            tid = url.split("/")[-1].split("?")[0]
            spotify_track_ids.append(tid)
        else:
            spotify_track_ids.append(None)

    # Batch fetch full track objects for album art and preview
    valid_spotify_ids = [tid for tid in spotify_track_ids if tid]
    track_objects = {}  # id -> track object
    if valid_spotify_ids and enricher.spotify:
        for i in range(0, len(valid_spotify_ids), 50):
            batch = valid_spotify_ids[i:i + 50]
            try:
                results = enricher.spotify.tracks(batch)
                for item in results.get("tracks", []):
                    if item:
                        track_objects[item["id"]] = item
            except Exception as e:
                print(f"    Batch tracks fetch error: {e}")

    # Collect artist IDs for genre lookup
    track_to_artist_id = {}  # track_id -> artist_id
    for tid, obj in track_objects.items():
        if obj.get("artists"):
            track_to_artist_id[tid] = obj["artists"][0]["id"]

    # --- Phase 2: ReccoBeats audio features (BPM, key, energy, danceability) ---
    reccobeats_features = {}
    ids_needing_audio = [
        tid for t, tid in zip(needs_update, spotify_track_ids)
        if tid and t.get("bpm") is None and t.get("spotify_bpm") is None
    ]
    if ids_needing_audio:
        print(f"    Fetching audio features from ReccoBeats for {len(ids_needing_audio)} tracks...")
        reccobeats_features = _batch_fetch_reccobeats(ids_needing_audio)

    # --- Phase 3: Discogs enrichment (genres, styles, label, URL) ---
    discogs_enabled = Config.ENABLE_DISCOGS and Config.DISCOGS_TOKEN

    # --- Apply all enrichment ---
    updated_count = 0
    for t, tid in zip(needs_update, spotify_track_ids):
        changed = False

        # Spotify album art
        if tid:
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

            # Spotify preview URL
            if obj and not t.get("spotify_preview_url"):
                preview = obj.get("preview_url")
                if preview:
                    t["spotify_preview_url"] = preview
                    changed = True

            # Spotify artist genres
            aid = track_to_artist_id.get(tid)
            if aid and not t.get("spotify_genres") and enricher.spotify:
                genres = enricher._get_artist_genres(aid)
                if genres:
                    t["spotify_genres"] = genres
                    changed = True

        # ReccoBeats BPM / key / energy / danceability
        if tid and tid in reccobeats_features:
            feat = reccobeats_features[tid]

            if t.get("bpm") is None and t.get("spotify_bpm") is None:
                tempo = feat.get("tempo")
                if tempo:
                    t["bpm"] = round(float(tempo), 1)
                    changed = True

            if not t.get("key") and not t.get("spotify_key"):
                key_idx = feat.get("key")
                mode = feat.get("mode")
                if key_idx is not None and int(key_idx) >= 0:
                    key_str = _KEY_NAMES[int(key_idx)]
                    if mode is not None and int(mode) == 0:
                        key_str += 'm'
                    t["key"] = key_str
                    changed = True

            if t.get("energy") is None and feat.get("energy") is not None:
                t["energy"] = round(float(feat["energy"]), 3)
                changed = True

            if t.get("danceability") is None and feat.get("danceability") is not None:
                t["danceability"] = round(float(feat["danceability"]), 3)
                changed = True

        # Discogs genres, styles, label, URL
        if discogs_enabled and not t.get("discogs_genres"):
            artist = t.get("artist", "")
            title = t.get("title", "")
            if artist and title != "Unknown Track":
                discogs_data = enricher._search_discogs_rich(title, artist)
                if discogs_data:
                    if not t.get("discogs_url"):
                        t["discogs_url"] = discogs_data["url"]
                        changed = True
                    if discogs_data.get("genres"):
                        t["discogs_genres"] = discogs_data["genres"]
                        changed = True
                    if discogs_data.get("styles"):
                        t["discogs_styles"] = discogs_data["styles"]
                        changed = True
                    if discogs_data.get("label") and not t.get("discogs_label"):
                        t["discogs_label"] = discogs_data["label"]
                        changed = True

        # Migrate legacy field names (spotify_bpm/spotify_key → bpm/key)
        if t.get("spotify_bpm") is not None and t.get("bpm") is None:
            t["bpm"] = t["spotify_bpm"]
            changed = True
        if t.get("spotify_key") and not t.get("key"):
            t["key"] = t["spotify_key"]
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
        description="Re-enrich existing JSON outputs with metadata (Spotify, ReccoBeats, Discogs)."
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
