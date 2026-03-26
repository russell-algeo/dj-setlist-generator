"""Enrichment and output helpers for published set runs."""

from __future__ import annotations

from pathlib import Path

from checkpoint_manager import sanitize_filename
from metadata_enricher import MetadataEnricher
from output_formatter import OutputFormatter
from set_explorer_formatter import save_set_explorer_html


def enrich_tracks(
    tracks: list,
    *,
    mix_info: dict[str, object],
    artist_name: str | None,
) -> tuple[list[dict], dict[str, object]]:
    enricher = MetadataEnricher()
    enriched_tracks = enricher.enrich_all_tracks(tracks)
    resolved_mix_info = dict(mix_info)

    if artist_name:
        try:
            expected_genres = MetadataEnricher.infer_genre_profile(
                [item.get("metadata", {}) for item in enriched_tracks]
            )
            artist_profile = enricher.enrich_set_artist_profile(
                artist_name,
                expected_genres=expected_genres,
            )
            resolved_mix_info.update(artist_profile)
        except Exception as error:
            print(f"  [Artist Profile] Set-level profile enrichment skipped: {error}")

    return enriched_tracks, resolved_mix_info


def write_set_outputs(
    *,
    output_dir: Path,
    enriched_tracks: list[dict],
    mix_info: dict[str, object],
) -> dict[str, Path | None]:
    formatter = OutputFormatter()
    formatter.output_dir = output_dir

    filename = sanitize_filename(str(mix_info.get("title") or "untitled_mix"))

    return {
        "json": formatter.save_setlist_json(enriched_tracks, mix_info, filename),
        "markdown": formatter.save_setlist_markdown(enriched_tracks, mix_info, filename),
        "html": save_set_explorer_html(output_dir, enriched_tracks, mix_info, filename),
    }


__all__ = [
    "MetadataEnricher",
    "enrich_tracks",
    "write_set_outputs",
]
