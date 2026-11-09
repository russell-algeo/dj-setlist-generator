"""Track recognition using Shazam with concurrent processing and checkpoint support."""

import asyncio
import concurrent.futures
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, TYPE_CHECKING

from shazamio import Shazam
from recognition_transport import (SingleAttemptHTTP, RequestAuthorizationError, classify_error,
                                   validate_response)

from config import Config
from worker.pipeline.models import Recognition

if TYPE_CHECKING:
    from audio_segmenter import AudioSegmenter


class RecognitionIncomplete(RuntimeError):
    """Recognition is resumable but cannot be published as a completed set."""


class TrackRecognizer:
    """Recognize tracks using Shazam with concurrent processing and checkpoint support."""

    def __init__(self, checkpoint_manager=None, *, single_attempt=False,
                 max_attempts=None, max_retry_seconds=300, before_request=None):
        self.checkpoint_manager = checkpoint_manager
        self.single_attempt = single_attempt
        self.before_request = before_request
        self.attempt_timeout = max(1, min(Config.RECOGNITION_TIMEOUT, 30)) if single_attempt else Config.RECOGNITION_TIMEOUT
        self.max_attempts = max(1, Config.MAX_RETRIES if max_attempts is None else max_attempts)
        self.max_retry_seconds = max(0, max_retry_seconds)
        self._quota_cooldown_until = 0
        self._throttle_lock = asyncio.Lock()
        self.transport = None
        self.shazam = self._create_shazam_client()

    def _create_shazam_client(self) -> Shazam:
        self.transport = SingleAttemptHTTP(timeout=self.attempt_timeout, before_request=self.before_request)
        return Shazam(http_client=self.transport, endpoint_country='US')

    async def close(self):
        if self.transport is not None:
            await self.transport.close()

    def _is_rate_limit_error(self, error: Exception) -> bool:
        return classify_error(error).was_rate_limited

    async def _trigger_quota_cooldown(self, seconds=None):
        self._quota_cooldown_until = max(self._quota_cooldown_until,
            time.monotonic() + max(Config.QUOTA_COOLDOWN_DURATION, seconds or 0))

    async def _wait_for_cooldown(self, deadline=None):
        async with self._throttle_lock:
            while True:
                remaining = self._quota_cooldown_until - time.monotonic()
                if remaining <= 0:
                    return True
                if deadline is not None and remaining >= deadline - time.monotonic():
                    return False
                await asyncio.sleep(remaining)

    async def recognize_segment(self, segment: dict) -> Recognition:
        """One bounded provider attempt, returning only sanitized failure diagnostics."""
        start_time = time.time()
        token = self.transport.begin() if self.transport is not None else None
        try:
            if self.transport is not None:
                result = await asyncio.wait_for(self.shazam.recognize(str(segment['file'])),
                                                self.attempt_timeout)
            else:
                result = await self.shazam.recognize(str(segment['file']))
            validate_response(result)
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
                    was_rate_limited=False,
                    http_status=200,
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
                    was_rate_limited=False,
                    http_status=200,
                )

        except RequestAuthorizationError:
            raise
        except Exception as e:
            elapsed = time.time() - start_time

            # Check if this was a rate limit error
            was_rate_limited = self._is_rate_limit_error(e)

            failure = classify_error(e)
            error_name = failure.error_type
            print(f"  Recognition attempt failed: {error_name}")

            return Recognition(
                timestamp=segment['timestamp'],
                track_title=None,
                artist=None,
                shazam_track_id=None,
                raw_data=None,
                recognized=False,
                segment_index=segment['index'],
                was_rate_limited=was_rate_limited,
                error_type=error_name,
                error_details=None,
                http_status=failure.http_status,
                retry_after_seconds=failure.retry_after_seconds,
                retry_after_format=failure.retry_after_format,
            )

        finally:
            if token is not None:
                self.transport.end(token)

    async def recognize_segment_with_backoff(self, segment: dict) -> Recognition:
        """Bounded CLI retries; durable workers opt out and account each attempt."""
        if self.single_attempt:
            return await self.recognize_segment(segment)
        deadline = time.monotonic() + self.max_retry_seconds
        result = None
        for attempt in range(self.max_attempts):
            remaining = self._quota_cooldown_until - time.monotonic()
            if remaining > max(0, deadline - time.monotonic()):
                break
            if not await self._wait_for_cooldown(deadline):
                break
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(min(random.uniform(0, Config.BASE_DELAY), max(0, deadline - time.monotonic())))
            if not await self._wait_for_cooldown(deadline) or time.monotonic() >= deadline:
                break
            try:
                result = await asyncio.wait_for(self.recognize_segment(segment), deadline - time.monotonic())
            except asyncio.TimeoutError:
                return Recognition(segment['timestamp'], None, None, None, None,
                                   False, segment['index'], error_type='RequestTimeout')
            if result.is_valid:
                return result
            if result.error_type not in {'RateLimited', 'ProviderServerError',
                                         'RequestTimeout', 'TransportError'}:
                return result
            if result.retry_after_format == 'invalid':
                return result
            delay = max(Config.QUOTA_COOLDOWN_DURATION if result.was_rate_limited
                        else min(Config.MAX_BACKOFF_DELAY, Config.BASE_DELAY * 2 ** attempt),
                        result.retry_after_seconds or 0)
            self._quota_cooldown_until = max(self._quota_cooldown_until, time.monotonic() + delay)
        return result or Recognition(segment['timestamp'], None, None, None, None,
                                     False, segment['index'], error_type='RetryBudgetExceeded')

    async def recognize_batch(
        self,
        batch_segments: list[dict],
        *,
        total_segments: int | None = None,
        batch_start: int = 0,
        on_result: Callable[[Recognition], None] | None = None,
        cleanup_files: bool = True,
    ) -> list[Recognition]:
        """Recognize a prepared batch of extracted segment files."""
        semaphore = asyncio.Semaphore(Config.CONCURRENT_RECOGNITIONS)

        async def _recognize_with_semaphore(segment: dict) -> Recognition:
            async with semaphore:
                return await self.recognize_segment_with_backoff(segment)

        batch_results = await asyncio.gather(
            *[_recognize_with_semaphore(segment) for segment in batch_segments],
            return_exceptions=True,
        )

        recognitions: list[Recognition] = []
        total = total_segments or len(batch_segments)

        for index, (segment, result) in enumerate(zip(batch_segments, batch_results)):
            global_idx = batch_start + index + 1

            if isinstance(result, (asyncio.CancelledError, RequestAuthorizationError)):
                raise result
            if isinstance(result, Exception):
                print(
                    f"  ⚠️  [{global_idx}/{total}] "
                    f"Recognition attempt failed: {classify_error(result).error_type}"
                )
                result = Recognition(
                    timestamp=segment["timestamp"],
                    track_title=None,
                    artist=None,
                    shazam_track_id=None,
                    raw_data=None,
                    recognized=False,
                    segment_index=segment["index"],
                    error_type=classify_error(result).error_type,
                    error_details=None,
                )

            recognitions.append(result)
            if on_result:
                on_result(result)

            status = "✓" if result.recognized else "✗"
            track_info = (
                f"{result.artist} - {result.track_title}"
                if result.recognized
                else "Not recognized"
            )
            print(f"  [{global_idx}/{total}] {segment['timestamp'] / 60:.1f}min {status} {track_info}")

            if cleanup_files:
                try:
                    segment["file"].unlink(missing_ok=True)
                except Exception:
                    pass

        return recognitions

    async def recognize_segments_streaming(
        self,
        audio_file: Path,
        mix_duration: float,
        segmenter: 'AudioSegmenter',
        resume_from_checkpoint: bool = False,
    ) -> list[Recognition]:
        """Recognize missing windows with valid-only checkpoints; fail closed if incomplete.

        Extract one bounded batch at a time and discard its files after recognition.
        Saved no-match responses count as complete; transport/extraction errors never do.
        """
        actual_duration = mix_duration if mix_duration and mix_duration > 0 else 0
        if actual_duration <= 0:
            actual_duration = segmenter.get_audio_duration_ffprobe(audio_file)
        total = segmenter.calculate_total_segments(actual_duration)
        completed = {}
        geometry = {'segment_duration': getattr(segmenter, 'segment_duration', Config.SEGMENT_DURATION),
                    'segment_overlap': getattr(segmenter, 'overlap', Config.SEGMENT_OVERLAP)}
        if self.checkpoint_manager:
            self.checkpoint_manager.recognition_geometry = geometry
        if resume_from_checkpoint and self.checkpoint_manager:
            checkpoint = self.checkpoint_manager.load_checkpoint()
            if (checkpoint and checkpoint.get('stage') in {'recognizing', 'recognized'}
                    and checkpoint.get('data', {}).get('geometry', geometry) == geometry):
                for saved in checkpoint.get('data', {}).get('recognitions', []):
                    try:
                        result = Recognition.from_checkpoint(saved)
                        if (result.is_valid and type(result.segment_index) is int and 0 <= result.segment_index < total
                                and result.timestamp == result.segment_index * (geometry['segment_duration'] - geometry['segment_overlap'])):
                            completed[result.segment_index] = result
                    except (TypeError, ValueError, KeyError):
                        continue

        def save(stage='recognizing'):
            if self.checkpoint_manager:
                self.checkpoint_manager.save_recognition_checkpoint(
                    [completed[i] for i in sorted(completed)], stage=stage)

        # Extract only missing contiguous ranges. Never infer completion from list length.
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(Config.BATCH_SIZE, 4)) as executor:
                index = 0
                while index < total:
                    if index in completed:
                        index += 1
                        continue
                    end = index + 1
                    while end < total and end - index < Config.BATCH_SIZE and end not in completed:
                        end += 1
                    try:
                        segments = await segmenter.create_segments_batch(audio_file, index, end, executor)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        save()
                        raise RecognitionIncomplete('segment_extraction_failed') from None
                    results = await self.recognize_batch(segments, total_segments=total, batch_start=index)
                    for result in results:
                        if result.is_valid and index <= result.segment_index < end:
                            completed[result.segment_index] = result
                    save()
                    if any(i not in completed for i in range(index, end)):
                        raise RecognitionIncomplete('recognition_incomplete_resume_required')
                    index = end
            if len(completed) != total:
                raise RecognitionIncomplete('recognition_incomplete_resume_required')
            save('recognized')
            return [completed[i] for i in range(total)]
        finally:
            await self.close()
