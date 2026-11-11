"""Private source/storage adapter around the ordinary shared recognition engine."""
import asyncio
import concurrent.futures
import hashlib
import time
from pathlib import Path

from worker.jobs.yoon_recognition_diagnostics import phase
from worker.jobs.yoon_resume_policy import WORKFLOW_SECONDS
from worker.jobs.yoon_resume_store import QueuePause
from worker.jobs.yoon_sources import CATALOG, JACKSON


async def _recognize_batch_preserving_stops(recognizer, segments, total_segments):
    """Permit cooldown reselection only after every gathered task settled safely."""
    original = recognizer.recognize_segment_with_backoff
    stops = []

    async def observed(segment):
        try:
            return await original(segment)
        except (Exception, asyncio.CancelledError) as exc:
            if not (isinstance(exc, QueuePause) and str(exc) == 'cooldown'):
                stops.append(exc)
            raise

    recognizer.recognize_segment_with_backoff = observed
    try:
        return await recognizer.recognize_batch(segments,total_segments=total_segments)
    except QueuePause as exc:
        if str(exc) == 'cooldown' and stops:
            # The common batch raises in segment order. An earlier cooldown must
            # not hide a later cancellation, owner failure or uncertain error.
            raise next((stop for stop in stops if isinstance(stop, asyncio.CancelledError)), stops[0])
        raise
    finally:
        recognizer.recognize_segment_with_backoff = original


async def recognize_resumable(store, audio: Path, *, slot_index=0):
    with phase('imports'):
        from audio_segmenter import AudioSegmenter
        from checkpoint_manager import CheckpointManager
        from track_recognizer import TrackRecognizer
        from config import Config

    with phase('owner'):
        saved = store.require_owner()
    with phase('audio_validation'):
        source = CATALOG.get(saved.get('source_id', JACKSON.id))
        if source is None:
            raise RuntimeError('fixed_input_mismatch')
        with audio.open('rb') as source_file:
            if hashlib.file_digest(source_file,'sha256').hexdigest()!=saved.get('audio_sha256'):
                raise RuntimeError('private_audio_digest_mismatch')
        if abs(AudioSegmenter.get_audio_duration_ffprobe(audio)-source.duration)>.2:
            raise RuntimeError('private_audio_duration_mismatch')
        if (Config.SEGMENT_DURATION!=30 or Config.SEGMENT_OVERLAP!=15
                or AudioSegmenter().calculate_total_segments(source.duration)!=source.windows):
            raise RuntimeError('private_audio_geometry_mismatch')
    with phase('initialization'):
        cp = CheckpointManager('local:fixed-analysis','fixed-analysis')
        segmenter = AudioSegmenter(checkpoint_manager=cp)
    with phase('clock'):
        now,state = store.clock_state()
    remaining = WORKFLOW_SECONDS-(now-state['session_started'])
    if remaining < 65:
        return 'paused'

    def before_attempt(segment):
        with phase('reserve'):
            store.check_owner()
            return store.reserve(segment['index'],slot_index)

    def on_attempt(result,ticket,delay_seconds):
        with phase('finish'):
            return store.finish(result,ticket,delay_seconds)

    # Same provider, classification, retry pacing, backoff and concurrency as an
    # ordinary DJ worker. Only private source and durable storage are different.
    with phase('initialization'):
        recognizer = TrackRecognizer(before_attempt=before_attempt,on_attempt=on_attempt,
                                     max_retry_seconds=remaining,continuation_deadline=time.monotonic()+remaining,quiet=True)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(Config.BATCH_SIZE,4)) as executor:
            while True:
                with phase('select_windows'):
                    candidates,wait = store.next_windows(slot_index,Config.BATCH_SIZE)
                if not candidates:
                    return 'slot_complete'
                with phase('clock'):
                    now,state = store.clock_state()
                remaining = WORKFLOW_SECONDS-(now-state['session_started'])
                if remaining < 65 or wait+65>=remaining:
                    return 'paused'
                if wait:
                    # Check cancellation/owner throughout an inherited cooldown.
                    await asyncio.sleep(min(wait,15))
                    with phase('owner'):
                        store.check_owner()
                    continue
                # Extract only missing windows. A seeded successful window is
                # never sent again, including gaps inside a scheduler partition.
                requests_before = state['requests']
                extracted = []
                try:
                    ranges = []
                    for candidate in candidates:
                        index = candidate['segment_index']
                        if ranges and ranges[-1][1] == index:
                            ranges[-1] = (ranges[-1][0],index+1)
                        else:
                            ranges.append((index,index+1))
                    # The ordinary segmenter's batch method fans FFmpeg out over
                    # this same bounded executor. Keep contiguous missing windows
                    # together instead of serializing every extraction.
                    for first,end in ranges:
                        with phase('extract'):
                            extracted.extend(await segmenter.create_segments_batch(audio,first,end,executor))
                    task = asyncio.create_task(_recognize_batch_preserving_stops(recognizer,extracted,source.windows))
                    try:
                        while True:
                            # Passive guard only: request admission/receipts still
                            # check immediately, and completion wakes this wait.
                            # Ten seconds cuts timer reads by 80% versus two;
                            # an in-flight stop can be noticed up to 8s later.
                            done,_ = await asyncio.wait({task},timeout=10)
                            with phase('owner'):
                                store.check_owner()
                            if done:
                                with phase('batch'):
                                    await task
                                break
                    finally:
                        if not task.done():
                            task.cancel()
                        await asyncio.gather(task,return_exceptions=True)
                    with phase('clock'):
                        _, after_state = store.clock_state()
                    if after_state['requests'] == requests_before:
                        return 'paused'
                except QueuePause as exc:
                    if str(exc) != 'cooldown':
                        raise
                    # A peer can extend the durable cooldown after selection.
                    # The gathered batch has settled; reselect only missing
                    # windows and honor the existing wait/deadline/owner checks.
                    continue
                finally:
                    with phase('cleanup'):
                        for segment in extracted:
                            segment['file'].unlink(missing_ok=True)
    except QueuePause:
        return 'paused'
    finally:
        with phase('close'):
            await recognizer.close()
        # The workflow's single private-release job owns release/finalization
        # after every matrix slot ends. A finishing slot must not cancel peers.
