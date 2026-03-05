"""Re-enrich existing JSON outputs with metadata from Spotify, ReccoBeats, and Discogs.

Reads each set's JSON file, finds tracks missing enrichment fields,
batch-fetches data from the appropriate APIs, and writes the updated JSON back.

Data sources:
- Spotify: album art, preview URL, artist-level genres, artist profile image
- ReccoBeats: BPM/tempo, musical key, energy, danceability (replaces deprecated Spotify audio_features)
- Discogs: release-level genres, styles, label, full URL

Usage:
    python backfill_enrichment.py                   # re-enrich ALL outputs
    python backfill_enrichment.py "Jay Tripwire"    # re-enrich one artist
    python backfill_enrichment.py --dry-run          # show what would be updated
    python backfill_enrichment.py --set-artist-profiles-only
        # only backfill set-level artist profile metadata
"""

import json
import re
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
    if has_spotify and (
        not track.get("spotify_artist_id")
        or not track.get("spotify_artist_name")
        or not track.get("spotify_artist_url")
    ):
        return True
    profile_image = track.get("spotify_artist_profile_image")
    legacy_image = track.get("spotify_artist_image")
    if has_spotify and not profile_image and not legacy_image:
        return True
    if has_spotify and bool(profile_image) != bool(legacy_image):
        return True

    # Check for missing audio features (BPM/key from ReccoBeats)
    if has_spotify and track.get("bpm") is None and track.get("spotify_bpm") is None:
        return True

    # Check for missing Discogs metadata
    if has_artist_title and not track.get("discogs_genres"):
        return True

    # Check for missing Discogs label URL (added after initial enrichment)
    if has_artist_title and track.get("discogs_label") and not track.get("discogs_label_url"):
        return True

    return False


def _is_valid_artist_image_url(url: str | None) -> bool:
    """Return True when image URL appears usable for artist-card artwork."""
    if not url:
        return False
    lower = str(url).strip().lower()
    if not lower.startswith("http"):
        return False
    if "spacer.gif" in lower:
        return False
    return True


def _normalize_name(value: str) -> str:
    """Lowercase alphanumeric normalization for loose artist-name matching."""
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _is_low_res_discogs_image_url(url: str | None) -> bool:
    """Detect thumbnail-style Discogs image URLs so we can upgrade to higher quality."""
    if not url:
        return False
    lower = str(url).strip().lower()
    return "discogs.com" in lower and ("/h:150/w:150/" in lower or "uri150" in lower)


def _infer_expected_genres_from_tracks(tracks: list[dict]) -> list[str]:
    """Infer expected artist genres from serialized set track metadata."""
    metadata_rows: list[dict] = []
    for track in tracks or []:
        metadata_rows.append(
            {
                "discogs_styles": track.get("discogs_styles", []),
                "discogs_genres": track.get("discogs_genres", []),
                "spotify_genres": track.get("spotify_genres", []),
            }
        )
    return MetadataEnricher.infer_genre_profile(metadata_rows)


def _needs_set_artist_profile_enrichment(mix_info: dict, artist_name: str | None) -> bool:
    """Return True if set-level artist profile metadata should be backfilled."""
    if not artist_name:
        return False
    if mix_info.get("artist_name") != artist_name:
        return True
    expected = _normalize_name(artist_name)
    observed = _normalize_name(mix_info.get("artist_profile_name") or "")
    if observed and observed != expected:
        return True

    artist_profile_image = mix_info.get("artist_profile_image")
    if not _is_valid_artist_image_url(artist_profile_image):
        return True

    source = (mix_info.get("artist_profile_source") or "").strip().lower()
    if source == "discogs" and _is_low_res_discogs_image_url(artist_profile_image):
        return True

    if not mix_info.get("artist_profile_source"):
        return True
    if not mix_info.get("artist_profile_name"):
        return True
    if not mix_info.get("artist_profile_url"):
        return True
    if mix_info.get("artist_profile_confidence") is None:
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
                    # ReccoBeats returns a UUID as "id"; Spotify track ID is in "href"
                    href = feat.get("href", "")
                    fid = href.split("/")[-1].split("?")[0] if href else None
                    if fid:
                        all_features[fid] = feat
                    elif len(batch) == 1:
                        all_features[batch[0]] = feat
        except Exception as e:
            print(f"    [ReccoBeats] Batch fetch error: {e}")
        if i + batch_size < len(spotify_ids):
            time.sleep(0.5)
    return all_features


def _enrich_json(
    json_path: Path,
    enricher: MetadataEnricher,
    dry_run: bool,
    set_artist_name: str | None = None,
    set_artist_profiles_only: bool = False,
    force_set_artist_profile: bool = False,
    expected_genres: list[str] | None = None,
) -> bool:
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
    mix_info = data.setdefault("mix_info", {})
    if not tracks:
        return False

    needs_update = [] if set_artist_profiles_only else [t for t in tracks if _needs_enrichment(t)]
    needs_set_artist_profile = (
        bool(set_artist_name) and force_set_artist_profile
    ) or _needs_set_artist_profile_enrichment(mix_info, set_artist_name)
    if not needs_update and not needs_set_artist_profile:
        return False

    print(
        f"  {json_path.parent.name}/{json_path.name}: "
        f"{len(needs_update)} tracks need enrichment"
        + (" + set-artist profile" if needs_set_artist_profile else "")
    )

    if dry_run:
        return True

    set_artist_changed = False
    if set_artist_name:
        mix_info["artist_name"] = set_artist_name
        if needs_set_artist_profile:
            profile = enricher.enrich_set_artist_profile(
                set_artist_name,
                expected_genres=expected_genres or [],
            )
            mix_info["artist_profile_name"] = profile.get("artist_profile_name")
            mix_info["artist_profile_image"] = profile.get("artist_profile_image")
            mix_info["artist_profile_url"] = profile.get("artist_profile_url")
            mix_info["artist_profile_source"] = profile.get("artist_profile_source")
            mix_info["artist_profile_confidence"] = profile.get("artist_profile_confidence")
            mix_info["artist_profile_genre_overlap"] = profile.get("artist_profile_genre_overlap")
            mix_info["artist_profile_expected_genres"] = profile.get("artist_profile_expected_genres")
            mix_info["artist_profile_provider_genres"] = profile.get("artist_profile_provider_genres")
            mix_info["artist_profile_rejected_reason"] = profile.get("artist_profile_rejected_reason")
            mix_info["spotify_artist_profile_name"] = profile.get("spotify_artist_profile_name")
            mix_info["spotify_artist_profile_image"] = profile.get("spotify_artist_profile_image")
            mix_info["spotify_artist_profile_url"] = profile.get("spotify_artist_profile_url")
            mix_info["spotify_artist_profile_genres"] = profile.get("spotify_artist_profile_genres")
            mix_info["discogs_artist_profile_name"] = profile.get("discogs_artist_profile_name")
            mix_info["discogs_artist_profile_image"] = profile.get("discogs_artist_profile_image")
            mix_info["discogs_artist_profile_url"] = profile.get("discogs_artist_profile_url")
            mix_info["discogs_artist_profile_genres"] = profile.get("discogs_artist_profile_genres")
            set_artist_changed = True

    # --- Phase 1: Spotify album art, preview, artist profile fields ---
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

    # Batch fetch primary artist objects (name, url, image, genres)
    artist_objects = {}  # artist_id -> artist object
    if enricher.spotify and track_to_artist_id:
        unique_artist_ids = sorted({aid for aid in track_to_artist_id.values() if aid})
        for i in range(0, len(unique_artist_ids), 50):
            batch = unique_artist_ids[i:i + 50]
            try:
                results = enricher.spotify.artists(batch)
                for artist_obj in results.get("artists", []):
                    if artist_obj and artist_obj.get("id"):
                        artist_objects[artist_obj["id"]] = artist_obj
            except Exception as e:
                print(f"    Batch artists fetch error: {e}")

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
    discogs_enabled = Config.ENABLE_DISCOGS and (Config.DISCOGS_TOKEN or (Config.DISCOGS_CONSUMER_KEY and Config.DISCOGS_CONSUMER_SECRET))

    # --- Apply all enrichment ---
    updated_count = 0
    for t, tid in zip(needs_update, spotify_track_ids):
        changed = False

        # Keep old/new profile-image keys synchronized.
        if t.get("spotify_artist_profile_image") and not t.get("spotify_artist_image"):
            t["spotify_artist_image"] = t["spotify_artist_profile_image"]
            changed = True
        if t.get("spotify_artist_image") and not t.get("spotify_artist_profile_image"):
            t["spotify_artist_profile_image"] = t["spotify_artist_image"]
            changed = True

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

            # Spotify artist profile (genres/name/url/image)
            aid = track_to_artist_id.get(tid)
            artist_obj = artist_objects.get(aid) if aid else None
            if aid and not t.get("spotify_artist_id"):
                t["spotify_artist_id"] = aid
                changed = True
            if artist_obj:
                genres = artist_obj.get("genres", [])[:3]
                if genres and not t.get("spotify_genres"):
                    t["spotify_genres"] = genres
                    changed = True
                if not t.get("spotify_artist_name") and artist_obj.get("name"):
                    t["spotify_artist_name"] = artist_obj["name"]
                    changed = True
                artist_url = (artist_obj.get("external_urls") or {}).get("spotify")
                if not t.get("spotify_artist_url") and artist_url:
                    t["spotify_artist_url"] = artist_url
                    changed = True
                if not t.get("spotify_artist_profile_image") and not t.get("spotify_artist_image"):
                    images = artist_obj.get("images", [])
                    image_url = next(
                        (img.get("url") for img in images if img.get("height") == 320),
                        images[0].get("url") if images else None
                    )
                    if image_url:
                        t["spotify_artist_profile_image"] = image_url
                        t["spotify_artist_image"] = image_url
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

        # Discogs genres, styles, label, URL, label URL
        needs_discogs = discogs_enabled and (
            not t.get("discogs_genres")
            or (t.get("discogs_label") and not t.get("discogs_label_url"))
        )
        if needs_discogs:
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
                    if discogs_data.get("label_url") and not t.get("discogs_label_url"):
                        t["discogs_label_url"] = discogs_data["label_url"]
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

    if updated_count == 0 and not set_artist_changed:
        return False

    # Write updated JSON back
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        if set_artist_changed:
            print(f"    Updated {updated_count} tracks + set artist profile")
        else:
            print(f"    Updated {updated_count} tracks")
        return True
    except OSError as e:
        print(f"  ERROR writing {json_path}: {e}")
        return False


def scan_and_enrich(
    output_dir: Path,
    target: str | None,
    dry_run: bool,
    set_artist_profiles_only: bool = False,
    force_set_artist_profile: bool = False,
) -> None:
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
            artist_tracks: list[dict] = []
            for set_dir in sorted(sub_dirs):
                for json_path in sorted(set_dir.glob("*.json")):
                    if json_path.name in _SUMMARY_FILES:
                        continue
                    try:
                        with open(json_path, encoding="utf-8") as f:
                            payload = json.load(f)
                        artist_tracks.extend(payload.get("tracks", []) or [])
                    except Exception:
                        continue
            artist_expected_genres = _infer_expected_genres_from_tracks(artist_tracks)

            for set_dir in sorted(sub_dirs):
                for json_path in sorted(set_dir.glob("*.json")):
                    if json_path.name in _SUMMARY_FILES:
                        continue
                    if _enrich_json(
                        json_path,
                        enricher,
                        dry_run,
                        set_artist_name=entry.name,
                        set_artist_profiles_only=set_artist_profiles_only,
                        force_set_artist_profile=force_set_artist_profile,
                        expected_genres=artist_expected_genres,
                    ):
                        total_updated += 1
        else:
            # URL mode
            for json_path in sorted(entry.glob("*.json")):
                if json_path.name in _SUMMARY_FILES:
                    continue
                try:
                    with open(json_path, encoding="utf-8") as f:
                        payload = json.load(f)
                    expected_genres = _infer_expected_genres_from_tracks(payload.get("tracks", []) or [])
                except Exception:
                    expected_genres = []
                if _enrich_json(
                    json_path,
                    enricher,
                    dry_run,
                    set_artist_profiles_only=set_artist_profiles_only,
                    force_set_artist_profile=force_set_artist_profile,
                    expected_genres=expected_genres,
                ):
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
    parser.add_argument(
        "--set-artist-profiles-only",
        action="store_true",
        help="Only backfill set-level artist profile metadata in mix_info (no track-level enrichment).",
    )
    parser.add_argument(
        "--force-set-artist-profile",
        action="store_true",
        help="Force refresh of set-level artist profile metadata even if fields look complete.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    if args.dry_run:
        print("DRY RUN — no files will be written\n")

    scan_and_enrich(
        output_dir,
        target=args.target,
        dry_run=args.dry_run,
        set_artist_profiles_only=args.set_artist_profiles_only,
        force_set_artist_profile=args.force_set_artist_profile,
    )


if __name__ == "__main__":
    main()
