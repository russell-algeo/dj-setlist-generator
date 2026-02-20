"""Regenerate HTML files from existing JSON outputs.

Usage:
    python backfill_html.py                   # regenerate ALL outputs
    python backfill_html.py "Jay Tripwire"    # regenerate one dir by name
    python backfill_html.py --dry-run         # show what would run, no writes
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

from html_formatter import HtmlFormatter
from artist_summary import ArtistSummarizer


_SUMMARY_FILES = {"artist_summary.json", "artist_summary.md", "artist_summary.html"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class _ManagerStub:
    """Minimal stub satisfying HtmlFormatter and ArtistSummarizer __init__."""

    def __init__(self, output_dir: Path, artist_name: str = ""):
        self.output_dir = Path(output_dir)
        self.artist_name = artist_name


def _json_to_enriched_tracks(tracks_data: list[dict]) -> list[dict]:
    """Reconstruct enriched_tracks format from a JSON track list.

    serialize_track() accesses item['track'] as an object with attributes,
    so we wrap each dict in SimpleNamespace. Only the 8 fields used by
    serialize_track() are needed; shazam_track_id and segment_indices are
    not accessed by the HTML path.
    """
    enriched = []
    for t in tracks_data:
        track = SimpleNamespace(
            title=t["title"],
            artist=t["artist"],
            start_time=t["start_time"],
            end_time=t["end_time"],
            confidence=t["confidence"],
            detection_count=t["detection_count"],
            cluster_density=t["cluster_density"],
            cluster_span=t["cluster_span"],
        )
        enriched.append({
            "track": track,
            "metadata": {
                "spotify_url": t.get("spotify_url"),
                "youtube_url": t.get("youtube_url"),
                "discogs_url": t.get("discogs_url"),
            },
        })
    return enriched


def _count_set_dirs(artist_dir: Path) -> list[dict]:
    """Build a dummy successful list by counting set subdirs with JSON files."""
    stubs = []
    for d in artist_dir.iterdir():
        if d.is_dir() and any(d.glob("*.json")):
            stubs.append({"url": "", "status": "SUCCESS"})
    return stubs


# ---------------------------------------------------------------------------
# Public regeneration functions
# ---------------------------------------------------------------------------

def regenerate_set_html(json_path: Path) -> bool:
    """Regenerate set-level HTML from a per-set JSON file.

    Args:
        json_path: Path to the set's *.json file.

    Returns:
        True on success, False on error.
    """
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  ERROR reading {json_path.name}: {e}")
        return False

    mix_info = data.get("mix_info", {})
    tracks_data = data.get("tracks", [])

    if not mix_info:
        print(f"  SKIP {json_path.name}: missing mix_info")
        return False

    enriched_tracks = _json_to_enriched_tracks(tracks_data)
    fmt = HtmlFormatter(checkpoint_manager=_ManagerStub(json_path.parent))
    fmt.save_setlist_html(enriched_tracks, mix_info, filename=json_path.stem)
    return True


def regenerate_artist_html(artist_dir: Path) -> bool:
    """Regenerate artist_summary.html by scanning existing per-set JSON files.

    Reads artist_summary.json to reconstruct the `successful` and `failed`
    lists that ArtistSummarizer.generate() needs for rendering the
    "Sets Analyzed" stat and the failed-sets section correctly.

    Dummy successful entries carry no `output_dir` key, so generate() skips
    them in its first loop and falls through to the directory scan, which
    picks up all real set subdirs. The list length is what sets the stat.

    Args:
        artist_dir: Path to the artist's output directory.

    Returns:
        True on success, False on error.
    """
    artist_name = artist_dir.name
    summary_json = artist_dir / "artist_summary.json"

    if summary_json.exists():
        try:
            with open(summary_json, encoding="utf-8") as f:
                summary = json.load(f)
            successful_dummy = [
                {"url": s.get("url", ""), "status": "SUCCESS"}
                for s in summary.get("sets", [])
            ]
            failed_results = [
                {"url": f.get("url", ""), "status": f.get("error", "FAILED")}
                for f in summary.get("failed_sets", [])
            ]
        except (json.JSONDecodeError, OSError) as e:
            print(f"  WARNING: could not read {summary_json.name}: {e} — using dir scan")
            successful_dummy = _count_set_dirs(artist_dir)
            failed_results = []
    else:
        successful_dummy = _count_set_dirs(artist_dir)
        failed_results = []

    stub = _ManagerStub(artist_dir, artist_name=artist_name)
    summarizer = ArtistSummarizer(stub)
    summarizer.generate(successful_dummy + failed_results)
    return True


# ---------------------------------------------------------------------------
# Directory classification and scanning
# ---------------------------------------------------------------------------

def _is_artist_mode(entry: Path) -> bool:
    """Return True if entry contains set subdirectories (artist-mode).

    A subdirectory qualifies if it contains at least one *.json file that
    isn't one of the artist-level summary files.
    """
    for sub in entry.iterdir():
        if sub.is_dir():
            json_files = [f for f in sub.glob("*.json") if f.name not in _SUMMARY_FILES]
            if json_files:
                return True
    return False


def _process_url_mode_dir(entry: Path, dry_run: bool) -> None:
    """Regenerate HTML for a URL-mode directory (JSON files directly inside)."""
    json_files = [f for f in entry.glob("*.json") if f.name not in _SUMMARY_FILES]
    for json_path in json_files:
        if dry_run:
            print(f"  [dry-run] {json_path.parent.name}/{json_path.name}")
        else:
            print(f"  Regenerating: {json_path.stem}")
            regenerate_set_html(json_path)


def _process_artist_dir(entry: Path, dry_run: bool) -> None:
    """Regenerate set HTML for each set subdir, then regenerate artist summary."""
    print(f"\n[Artist] {entry.name}")

    # 1. Set-level HTML first so set_html_rel links exist when artist summary runs
    for set_dir in sorted(entry.iterdir()):
        if not set_dir.is_dir():
            continue
        json_files = [f for f in set_dir.glob("*.json") if f.name not in _SUMMARY_FILES]
        for json_path in json_files:
            if dry_run:
                print(f"  [dry-run] {set_dir.name}/{json_path.name}")
            else:
                print(f"  Regenerating set: {json_path.stem}")
                regenerate_set_html(json_path)

    # 2. Artist summary
    if dry_run:
        print(f"  [dry-run] {entry.name}/artist_summary.html")
    else:
        print(f"  Regenerating artist summary: {entry.name}")
        regenerate_artist_html(entry)


def scan_and_regenerate(output_dir: Path, target: str | None, dry_run: bool) -> None:
    """Walk output_dir and regenerate HTML for all (or one targeted) directory.

    Args:
        output_dir: Root output directory to scan.
        target:     If set, only process the directory whose name matches.
        dry_run:    If True, print actions but write nothing.
    """
    if not output_dir.exists():
        print(f"Output directory not found: {output_dir}")
        return

    entries = sorted(output_dir.iterdir())
    if target:
        entries = [e for e in entries if e.is_dir() and e.name == target]
        if not entries:
            print(f"No directory named '{target}' found in {output_dir}")
            return

    for entry in entries:
        if not entry.is_dir():
            continue

        if _is_artist_mode(entry):
            _process_artist_dir(entry, dry_run)
        else:
            _process_url_mode_dir(entry, dry_run)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Regenerate HTML files from existing JSON outputs."
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Name of a specific output directory to regenerate (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be regenerated without writing files",
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

    scan_and_regenerate(output_dir, target=args.target, dry_run=args.dry_run)
    print("\nDone.")


if __name__ == "__main__":
    main()
