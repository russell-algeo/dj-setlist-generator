"""Track recognition using Shazam with concurrent processing and checkpoint support."""

import asyncio
import concurrent.futures
import random
import time
from datetime import datetime
from pathlib import Path
from shazamio import Shazam, HTTPClient
from aiohttp_retry import JitterRetry
from dataclasses import dataclass, fields
from typing import Optional, TYPE_CHECKING
from config import Config

if TYPE_CHECKING:
    from audio_segmenter import AudioSegmenter

@dataclass
class Recognition:
    """Recognition result from Shazam."""
    timestamp: float
    track_title: Optional[str]
    artist: Optional[str]
    shazam_track_id: Optional[str]
    raw_data: Optional[dict]
    recognized: bool
    segment_index: int
    was_rate_limited: bool = False  # True if request failed due to 429 after exhausting retries

    @classmethod
    def from_checkpoint(cls, data: dict) -> 'Recognition':
        """Create a Recognition from checkpoint data, ignoring unknown fields."""
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


class TrackRecognizer:
    """Recognize tracks using Shazam with concurrent processing and checkpoint support."""

    def __init__(self, checkpoint_manager=None):
        self.checkpoint_manager = checkpoint_manager
        self._quota_cooldown_until = 0  # Unix timestamp when cooldown ends
        self._throttle_lock = asyncio.Lock()
        self.shazam = self._create_shazam_client()

    def _create_shazam_client(self) -> Shazam:
        """Create a Shazam client with throttle-aware retry settings.

        Uses JitterRetry for exponential backoff with randomness to prevent
        thundering herd when multiple requests retry simultaneously.
        """
        retry_options = JitterRetry(
            attempts=Config.MAX_RETRIES,
            start_timeout=Config.BASE_DELAY,
            max_timeout=Config.MAX_BACKOFF_DELAY,
            random_interval_size=Config.JITTER_INTERVAL_SIZE,
            statuses={429, 500, 502, 503, 504},
        )

        http_client = HTTPClient(
            retry_options=retry_options,
        )

        return Shazam(
            http_client=http_client,
            endpoint_country='US'
            )

    def _is_rate_limit_error(self, error: Exception) -> bool:
        """Check if an error indicates rate limiting (429)."""
        error_str = str(error).lower()
        cause_str = str(error.__cause__).lower() if error.__cause__ else ""
        return "429" in error_str or "429" in cause_str

    async def _trigger_quota_cooldown(self):
        """Trigger a quota cooldown period."""
        # Only trigger if not already in cooldown
        if time.time() >= self._quota_cooldown_until:
            self._quota_cooldown_until = time.time() + Config.QUOTA_COOLDOWN_DURATION
            print(f"\n  🛑 QUOTA EXHAUSTED! Entering cooldown for {Config.QUOTA_COOLDOWN_DURATION}s")

    async def _wait_for_cooldown(self):
        """Wait if we're in a quota cooldown period."""
        async with self._throttle_lock:
            while True:
                remaining = self._quota_cooldown_until - time.time()
                if remaining <= 0:
                    return

                # Show countdown every 30 seconds
                if remaining > 30:
                    print(f"  ⏸️  Quota cooldown: {remaining:.0f}s remaining...")
                    await asyncio.sleep(30)
                else:
                    print(f"  ⏸️  Quota cooldown: {remaining:.0f}s remaining...")
                    await asyncio.sleep(remaining)

    async def recognize_segment(self, segment: dict) -> Recognition:
        """
        Recognize a single audio segment.

        Uses aiohttp's built-in timeout handling instead of asyncio.wait_for
        to ensure proper connection cleanup.

        Returns:
            Recognition with was_rate_limited=True if request failed due to 429
            after exhausting retries.
        """
        start_time = time.time()
        try:
            result = await self.shazam.recognize(str(segment['file']))
            elapsed = time.time() - start_time

            print(f"  🔄 [{datetime.now().strftime('%H:%M:%S')}] Segment {segment['index']} took {elapsed:.1f}s")

            if 'track' in result:
                track = result['track']
                return Recognition(
                    timestamp=segment['timestamp'],
                    track_title=track.get('title'),
                    artist=track.get('subtitle'),
                    shazam_track_id=track.get('key'),
                    raw_data=result,
                    recognized=True,
                    segment_index=segment['index'],
                    was_rate_limited=False
                )
            else:
                return Recognition(
                    timestamp=segment['timestamp'],
                    track_title=None,
                    artist=None,
                    shazam_track_id=None,
                    raw_data=result,
                    recognized=False,
                    segment_index=segment['index'],
                    was_rate_limited=False
                )

        except Exception as e:
            elapsed = time.time() - start_time

            # Check if this was a rate limit error
            was_rate_limited = self._is_rate_limit_error(e)

            # Enhanced error logging for debugging
            error_name = type(e).__name__
            cause = e.__cause__
            error_details = f"{e} | Cause: {type(cause).__name__}: {cause}" if cause else str(e)

            # Log elapsed time to see if retries happened before failure
            print(f"  ⚠️  [{datetime.now().strftime('%H:%M:%S')}] Error on segment {segment['index']} after {elapsed:.1f}s: {error_name}: {error_details}")

            return Recognition(
                timestamp=segment['timestamp'],
                track_title=None,
                artist=None,
                shazam_track_id=None,
                raw_data=None,
                recognized=False,
                segment_index=segment['index'],
                was_rate_limited=was_rate_limited
            )

    async def recognize_segments_streaming(
        self,
        audio_file: Path,
        mix_duration: float,
        segmenter: 'AudioSegmenter',
        resume_from_checkpoint: bool = False,
    ) -> list[Recognition]:
        """Streaming recognition: create, recognize, then discard each batch of segments.

        Instead of buffering all segment files to disk before recognition begins,
        this method processes one batch at a time:
          1. Extract BATCH_SIZE segments via FFmpeg (parallel subprocesses, no RAM load).
          2. Recognize the batch concurrently with the Shazam semaphore.
          3. Delete the segment files immediately after recognition.
          4. Save a 'recognizing' checkpoint and move to the next batch.

        Peak disk usage is limited to roughly BATCH_SIZE × ~0.5 MB of segment files
        rather than the full 500 MB+ that writing all segments up-front requires.

        Checkpoint resumption works by inspecting how many recognitions are already
        stored; segment creation restarts from that index using the still-present
        audio file.

        Args:
            audio_file: Path to the downloaded MP3 (must already exist on disk).
            mix_duration: Audio duration in seconds (from video metadata).  Falls
                          back to ffprobe if 0 or unavailable.
            segmenter: AudioSegmenter instance (carries segment_duration, overlap,
                       assets_dir, mix_id settings).
            resume_from_checkpoint: If True, look for a 'recognizing' checkpoint and
                                    skip already-processed segments.

        Returns:
            Ordered list of Recognition results, one per segment.
        """
        recognitions: list[Recognition] = []
        start_index = 0

        # --- Checkpoint resume -----------------------------------------------
        if resume_from_checkpoint and self.checkpoint_manager:
            checkpoint = self.checkpoint_manager.load_checkpoint()
            if checkpoint and checkpoint.get('stage') == 'recognizing':
                saved = checkpoint['data'].get('recognitions', [])
                if saved:
                    recognitions = [Recognition.from_checkpoint(r) for r in saved]
                    start_index = len(recognitions)
                    print(f"📂 Resuming streaming recognition from segment {start_index}")

        # --- Determine total segment count ------------------------------------
        # Use yt-dlp reported duration; fall back to ffprobe if unavailable.
        actual_duration = mix_duration if mix_duration and mix_duration > 0 else 0
        if actual_duration <= 0:
            print("  Duration not available from metadata; probing audio file...")
            actual_duration = segmenter.get_audio_duration_ffprobe(audio_file)

        total = segmenter.calculate_total_segments(actual_duration)

        if start_index >= total:
            print("All segments already processed")
            return recognitions

        if start_index == 0:
            print(
                f"\n🚀 Streaming recognition: {total} segments "
                f"({segmenter.segment_duration}s each, {segmenter.overlap}s overlap, "
                f"concurrency: {Config.CONCURRENT_RECOGNITIONS})..."
            )
        else:
            print(
                f"\n🚀 Continuing streaming recognition from segment "
                f"{start_index}/{total} (concurrency: {Config.CONCURRENT_RECOGNITIONS})..."
            )

        # --- Semaphore + per-segment recognize helper ------------------------
        semaphore = asyncio.Semaphore(Config.CONCURRENT_RECOGNITIONS)

        async def _recognize_with_semaphore(segment: dict) -> Recognition:
            async with semaphore:
                while True:
                    await self._wait_for_cooldown()
                    await asyncio.sleep(random.uniform(0, Config.BASE_DELAY))
                    result = await self.recognize_segment(segment)
                    if not result.was_rate_limited:
                        return result
                    await self._trigger_quota_cooldown()

        # --- Batch loop (producer-consumer pipeline) --------------------------
        # The producer extracts FFmpeg segments for batch N+1 while the
        # consumer is recognising batch N with Shazam, hiding the FFmpeg
        # overhead inside the (much longer) network-bound recognition phase.
        # maxsize=1 caps pre-extraction at one batch ahead, so at most
        # 2×BATCH_SIZE segment files exist on disk at any moment.
        max_ffmpeg_workers = min(Config.BATCH_SIZE, 4)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_ffmpeg_workers) as executor:
            queue: asyncio.Queue = asyncio.Queue(maxsize=1)

            async def _producer() -> None:
                for batch_start in range(start_index, total, Config.BATCH_SIZE):
                    batch_end = min(batch_start + Config.BATCH_SIZE, total)
                    print(
                        f"\n  Extracting segments {batch_start}–{batch_end - 1} "
                        f"of {total - 1} via FFmpeg..."
                    )
                    try:
                        segments = await segmenter.create_segments_batch(
                            audio_file, batch_start, batch_end, executor
                        )
                        await queue.put(('ok', batch_start, batch_end, segments))
                    except Exception as e:
                        print(
                            f"  ⚠️  Segment extraction failed for batch "
                            f"{batch_start}–{batch_end - 1}: {e}"
                        )
                        await queue.put(('error', batch_start, batch_end, e))
                await queue.put(None)  # sentinel: no more batches

            producer_task = asyncio.create_task(_producer())

            while True:
                item = await queue.get()
                if item is None:
                    break

                kind, batch_start, batch_end, payload = item
                batch_size = batch_end - batch_start

                if kind == 'error':
                    # Record failed recognitions so indices stay aligned.
                    for i in range(batch_start, batch_end):
                        info = segmenter._segment_info(i)
                        recognitions.append(Recognition(
                            timestamp=info['timestamp'],
                            track_title=None,
                            artist=None,
                            shazam_track_id=None,
                            raw_data=None,
                            recognized=False,
                            segment_index=i,
                            was_rate_limited=False,
                        ))
                    if self.checkpoint_manager:
                        self.checkpoint_manager.save_recognition_checkpoint(
                            recognitions, stage='recognizing'
                        )
                    continue

                batch_segments = payload

                # Recognize all segments in the batch concurrently.
                tasks = [_recognize_with_semaphore(seg) for seg in batch_segments]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)

                # Record results, print progress, delete segment files.
                batch_recognized = 0
                for i, (seg, result) in enumerate(zip(batch_segments, batch_results)):
                    global_idx = batch_start + i + 1

                    if isinstance(result, Exception):
                        print(
                            f"  ⚠️  [{global_idx}/{total}] "
                            f"Unexpected exception: {type(result).__name__}: {result}"
                        )
                        result = Recognition(
                            timestamp=seg['timestamp'],
                            track_title=None,
                            artist=None,
                            shazam_track_id=None,
                            raw_data=None,
                            recognized=False,
                            segment_index=seg['index'],
                        )

                    if result.recognized:
                        batch_recognized += 1
                    recognitions.append(result)

                    status = "✓" if result.recognized else "✗"
                    track_info = (
                        f"{result.artist} - {result.track_title}"
                        if result.recognized
                        else "Not recognized"
                    )
                    print(f"  [{global_idx}/{total}] {seg['timestamp'] / 60:.1f}min {status} {track_info}")

                    # Delete segment file immediately — no longer needed.
                    try:
                        seg['file'].unlink(missing_ok=True)
                    except Exception:
                        pass

                # Save incremental checkpoint.
                if self.checkpoint_manager:
                    self.checkpoint_manager.save_recognition_checkpoint(
                        recognitions, stage='recognizing'
                    )

                print(f"💾 Batch complete: {batch_recognized}/{batch_size} recognized")

            await producer_task

        # --- Finalise ---------------------------------------------------------
        recognized_count = sum(1 for r in recognitions if r.recognized)
        print(f"\n✅ Streaming recognition complete: {recognized_count}/{total} segments recognized")

        if self.checkpoint_manager:
            self.checkpoint_manager.save_recognition_checkpoint(recognitions, stage='recognized')

        return recognitions

