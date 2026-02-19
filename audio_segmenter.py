"""Audio segmentation into overlapping chunks via FFmpeg subprocess (seek-based)."""

import asyncio
import concurrent.futures
import math
import subprocess
from pathlib import Path

from config import Config


class AudioSegmenter:
    """Create overlapping segments from audio file."""

    def __init__(self, checkpoint_manager=None, segment_duration: int = None, overlap: int = None):
        """
        Initialize segmenter.

        Args:
            checkpoint_manager: CheckpointManager instance. Provides mix_id and assets_dir.
                                 If None, falls back to Config defaults.
            segment_duration: Duration of each segment in seconds
            overlap: Overlap between segments in seconds
        """
        self.segment_duration = segment_duration or Config.SEGMENT_DURATION
        self.overlap = overlap or Config.SEGMENT_OVERLAP
        self.assets_dir = checkpoint_manager.assets_dir if checkpoint_manager else Config.ASSETS_DIR
        self.mix_id = checkpoint_manager.mix_id if checkpoint_manager else "default"
        self.assets_dir.mkdir(parents=True, exist_ok=True)

    def calculate_total_segments(self, duration_sec: float) -> int:
        """Return the number of overlapping segments for a given audio duration."""
        duration_ms = duration_sec * 1000
        segment_duration_ms = self.segment_duration * 1000
        step_ms = (self.segment_duration - self.overlap) * 1000
        if duration_ms <= segment_duration_ms:
            return 1
        return math.ceil((duration_ms - segment_duration_ms) / step_ms) + 1

    def _segment_info(self, index: int) -> dict:
        """Return metadata dict for a segment at the given index."""
        step = self.segment_duration - self.overlap
        start_sec = index * step
        return {
            'index': index,
            'timestamp': float(start_sec),
            'duration': self.segment_duration,
            'file': self.assets_dir / f"segment_{self.mix_id}_{index:04d}.mp3",
        }

    @staticmethod
    def get_audio_duration_ffprobe(audio_file: Path) -> float:
        """Return audio duration in seconds using ffprobe (no full file load)."""
        result = subprocess.run(
            [
                'ffprobe', '-v', 'quiet',
                '-show_entries', 'format=duration',
                '-of', 'csv=p=0',
                str(audio_file),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
        raise RuntimeError(f"ffprobe could not determine duration of {audio_file}: {result.stderr}")

    def _extract_segment_ffmpeg(
        self,
        audio_file: Path,
        start_sec: float,
        duration_sec: float,
        output_file: Path,
    ) -> None:
        """Extract a single audio segment using FFmpeg (synchronous, no RAM load).

        Uses seek (-ss) before the input so FFmpeg seeks efficiently without
        decoding the entire file from the beginning.
        """
        cmd = [
            'ffmpeg', '-y', '-loglevel', 'error',
            '-ss', str(start_sec),
            '-t', str(duration_sec),
            '-i', str(audio_file),
            '-vn',               # no video stream
            '-acodec', 'libmp3lame',
            '-ab', '128k',
            '-ar', '44100',
            str(output_file),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg failed to extract segment at {start_sec:.1f}s "
                f"from {audio_file.name}: {result.stderr.strip()}"
            )

    async def create_segments_batch(
        self,
        audio_file: Path,
        start_idx: int,
        end_idx: int,
        executor: concurrent.futures.ThreadPoolExecutor,
    ) -> list[dict]:
        """Create a batch of segments using FFmpeg in parallel (non-blocking).

        Segments are extracted via FFmpeg seek so the full audio file is never
        loaded into RAM.  The caller is responsible for deleting the files after
        they are no longer needed.

        Args:
            audio_file: Path to the source MP3.
            start_idx: Index of the first segment (inclusive).
            end_idx: Index of the last segment (exclusive).
            executor: ThreadPoolExecutor used to run FFmpeg subprocesses.

        Returns:
            List of segment info dicts with keys: index, timestamp, duration, file.
        """
        loop = asyncio.get_running_loop()
        segment_infos = [self._segment_info(i) for i in range(start_idx, end_idx)]

        tasks = [
            loop.run_in_executor(
                executor,
                self._extract_segment_ffmpeg,
                audio_file,
                info['timestamp'],
                info['duration'],
                info['file'],
            )
            for info in segment_infos
        ]

        await asyncio.gather(*tasks)
        return segment_infos

