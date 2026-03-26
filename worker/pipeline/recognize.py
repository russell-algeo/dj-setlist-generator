"""Recognition pipeline helpers for bootstrap and lease workers."""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from audio_downloader import AudioDownloader
from audio_segmenter import AudioSegmenter
from checkpoint_manager import CheckpointManager
from worker.pipeline.models import Recognition


@dataclass(slots=True)
class PreparedSetContext:
    source_url: str
    artist_name: str | None
    mix_info: dict[str, object]
    checkpoint_manager: CheckpointManager
    audio_file: Path
    total_segments: int


def build_checkpoint_manager(source_url: str, mix_info: dict[str, object], artist_name: str | None) -> CheckpointManager:
    mix_title = str(mix_info.get("title") or "Unknown Set")
    return CheckpointManager(source_url, mix_title, artist_name=artist_name)


def prepare_set_context(
    source_url: str,
    *,
    artist_name: str | None,
    mix_info: dict[str, object] | None = None,
) -> PreparedSetContext:
    downloader = AudioDownloader()
    resolved_mix_info = dict(mix_info or downloader.get_video_info(source_url))
    resolved_mix_info["url"] = source_url
    if artist_name:
        resolved_mix_info["artist_name"] = artist_name

    checkpoint_manager = build_checkpoint_manager(source_url, resolved_mix_info, artist_name)
    audio_file = downloader.download(source_url, output_path=checkpoint_manager.audio_file)

    segmenter = AudioSegmenter(checkpoint_manager=checkpoint_manager)
    duration = float(resolved_mix_info.get("duration") or 0)
    if duration <= 0:
        duration = segmenter.get_audio_duration_ffprobe(audio_file)
        resolved_mix_info["duration"] = duration

    total_segments = segmenter.calculate_total_segments(duration)

    return PreparedSetContext(
        source_url=source_url,
        artist_name=artist_name,
        mix_info=resolved_mix_info,
        checkpoint_manager=checkpoint_manager,
        audio_file=audio_file,
        total_segments=total_segments,
    )


def restore_set_context(
    source_url: str,
    *,
    artist_name: str | None,
    source_metadata: dict[str, object],
    require_audio: bool = True,
) -> PreparedSetContext:
    mix_info = dict(source_metadata.get("mix_info") or {})
    if not mix_info:
        raise RuntimeError("source_metadata.mix_info is required before recognition")

    checkpoint_manager = build_checkpoint_manager(source_url, mix_info, artist_name)
    audio_file = checkpoint_manager.audio_file
    if require_audio and not audio_file.exists():
        raise RuntimeError(f"Prepared audio file is missing: {audio_file}")

    total_segments = int(source_metadata.get("segment_count") or 0)
    if total_segments <= 0:
        segmenter = AudioSegmenter(checkpoint_manager=checkpoint_manager)
        duration = float(mix_info.get("duration") or 0)
        if duration <= 0:
            duration = segmenter.get_audio_duration_ffprobe(audio_file)
        total_segments = segmenter.calculate_total_segments(duration)

    return PreparedSetContext(
        source_url=source_url,
        artist_name=artist_name,
        mix_info=mix_info,
        checkpoint_manager=checkpoint_manager,
        audio_file=audio_file,
        total_segments=total_segments,
    )


def serialize_prepared_context(
    context: PreparedSetContext,
    *,
    slot_count: int,
    lease_size: int,
) -> dict[str, object]:
    return {
        "mix_info": context.mix_info,
        "segment_count": context.total_segments,
        "recognition_slot_count": slot_count,
        "lease_size": lease_size,
        "mix_id": context.checkpoint_manager.mix_id,
    }


async def recognize_segment_range(
    context: PreparedSetContext,
    *,
    start_index: int,
    end_index: int,
    on_result: Callable[[Recognition], None] | None = None,
) -> list[Recognition]:
    from track_recognizer import TrackRecognizer

    segmenter = AudioSegmenter(checkpoint_manager=context.checkpoint_manager)
    recognizer = TrackRecognizer()
    max_workers = max(1, min(end_index - start_index + 1, 4))

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        segments = await segmenter.create_segments_batch(
            context.audio_file,
            start_index,
            end_index + 1,
            executor,
        )

    return await recognizer.recognize_batch(
        segments,
        total_segments=context.total_segments,
        batch_start=start_index,
        on_result=on_result,
    )


__all__ = [
    "PreparedSetContext",
    "Recognition",
    "build_checkpoint_manager",
    "prepare_set_context",
    "recognize_segment_range",
    "restore_set_context",
    "serialize_prepared_context",
]
