"""Track recognition using Shazam with concurrent processing and checkpoint support."""

import asyncio
import random
import time
from datetime import datetime
from shazamio import Shazam, HTTPClient
from aiohttp_retry import JitterRetry
from dataclasses import dataclass
from typing import Optional
from config import Config

@dataclass
class Recognition:
    """Recognition result from Shazam."""
    timestamp: float
    track_title: Optional[str]
    artist: Optional[str]
    shazam_confidence: Optional[float]
    shazam_track_id: Optional[str]
    raw_data: Optional[dict]
    recognized: bool
    segment_index: int
    was_rate_limited: bool = False  # True if request failed due to 429 after exhausting retries


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
                    shazam_confidence=None,
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
                    shazam_confidence=None,
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
                shazam_confidence=None,
                shazam_track_id=None,
                raw_data=None,
                recognized=False,
                segment_index=segment['index'],
                was_rate_limited=was_rate_limited
            )

    async def recognize_all_segments(self, segments: list[dict], resume_from_checkpoint: bool = False) -> list[Recognition]:
        """
        Recognize all segments with concurrent processing and checkpoint support.

        Uses asyncio.Semaphore to limit concurrent requests and asyncio.gather
        for parallel execution within batches.
        """
        recognitions = []
        start_index = 0

        # Try to load checkpoint
        if resume_from_checkpoint and self.checkpoint_manager:
            checkpoint = self.checkpoint_manager.load_checkpoint()
            if checkpoint and checkpoint.get('stage') == 'recognizing':
                saved_recognitions = checkpoint['data'].get('recognitions', [])
                if saved_recognitions:
                    recognitions = [
                        Recognition(**rec) for rec in saved_recognitions
                    ]
                    start_index = len(recognitions)
                    print(f"📂 Resuming from segment {start_index}/{len(segments)}")

        total = len(segments)
        remaining_segments = segments[start_index:]

        if not remaining_segments:
            print("All segments already processed")
            return recognitions

        if start_index == 0:
            print(f"\n🚀 Recognizing tracks from {total} segments (concurrency: {Config.CONCURRENT_RECOGNITIONS})...")
        else:
            print(f"\n🚀 Continuing recognition from segment {start_index} (concurrency: {Config.CONCURRENT_RECOGNITIONS})...")

        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(Config.CONCURRENT_RECOGNITIONS)

        async def recognize_with_semaphore(segment: dict) -> Recognition:

            async with semaphore:
                while True:
                     # Wait for any active cooldown before calling
                    await self._wait_for_cooldown()

                    # Add random delay to spread out requests
                    await asyncio.sleep(random.uniform(0, Config.BASE_DELAY))
                    result = await self.recognize_segment(segment)

                    # Exit loop on success or non-throttle error
                    if not result.was_rate_limited:
                        return result

                    # Rate limited - trigger cooldown
                    await self._trigger_quota_cooldown()

        # Process in batches for checkpointing
        for batch_start in range(0, len(remaining_segments), Config.BATCH_SIZE):
            batch_end = min(batch_start + Config.BATCH_SIZE, len(remaining_segments))
            batch = remaining_segments[batch_start:batch_end]

            # Process batch concurrently
            tasks = [recognize_with_semaphore(seg) for seg in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            for i, result in enumerate(batch_results):
                seg = batch[i]
                global_idx = start_index + batch_start + i + 1

                if isinstance(result, Exception):
                    # Handle exceptions from gather
                    print(f"  ⚠️  [{global_idx}/{total}] Exception: {type(result).__name__}")
                    result = Recognition(
                        timestamp=seg['timestamp'],
                        track_title=None,
                        artist=None,
                        shazam_confidence=None,
                        shazam_track_id=None,
                        raw_data=None,
                        recognized=False,
                        segment_index=seg['index']
                    )

                recognitions.append(result)

                # Print progress
                status = "✓" if result.recognized else "✗"
                track_info = f"{result.artist} - {result.track_title}" if result.recognized else "Not recognized"
                print(f"  [{global_idx}/{total}] {seg['timestamp']/60:.1f}min {status} {track_info}")

            # Save checkpoint after each batch
            if self.checkpoint_manager:
                self.checkpoint_manager.save_recognition_checkpoint(recognitions, stage='recognizing')

            # Summary for batch
            batch_recognized = sum(1 for r in batch_results if isinstance(r, Recognition) and r.recognized)
            print(f"💾 Batch complete: {batch_recognized}/{len(batch)} recognized")

        recognized_count = sum(1 for r in recognitions if r.recognized)
        print(f"\n✅ Recognition complete: {recognized_count}/{total} segments recognized")

        # Save final checkpoint with 'recognized' stage to enable skipping on re-runs
        if self.checkpoint_manager:
            self.checkpoint_manager.save_recognition_checkpoint(recognitions, stage='recognized')

        return recognitions

