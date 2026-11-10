"""Private source/storage adapter around the ordinary shared recognition engine."""
import asyncio
import concurrent.futures
import hashlib
import time
from pathlib import Path

from worker.jobs.yoon_resume_policy import WORKFLOW_SECONDS
from worker.jobs.yoon_resume_store import QueuePause
from worker.jobs.yoon_sources import CATALOG, JACKSON


async def recognize_resumable(store, audio: Path, *, slot_index=0):
    from audio_segmenter import AudioSegmenter
    from checkpoint_manager import CheckpointManager
    from track_recognizer import TrackRecognizer
    from config import Config

    saved = store.require_owner()
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
    cp = CheckpointManager('local:fixed-analysis','fixed-analysis')
    segmenter = AudioSegmenter(checkpoint_manager=cp)
    now,state = store.clock_state()
    remaining = WORKFLOW_SECONDS-(now-state['session_started'])
    if remaining < 65:
        return 'paused'

    def before_attempt(segment):
        store.require_owner()
        return store.reserve(segment['index'],slot_index)

    def on_attempt(result,ticket,delay_seconds):
        store.finish(result,ticket,delay_seconds)

    # Same provider, classification, retry pacing, backoff and concurrency as an
    # ordinary DJ worker. Only private source and durable storage are different.
    recognizer = TrackRecognizer(before_attempt=before_attempt,on_attempt=on_attempt,
                                 max_retry_seconds=remaining,continuation_deadline=time.monotonic()+remaining,quiet=True)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(Config.BATCH_SIZE,4)) as executor:
            while True:
                candidates,wait = store.next_windows(slot_index,Config.BATCH_SIZE)
                if not candidates:
                    return 'slot_complete'
                now,state = store.clock_state()
                remaining = WORKFLOW_SECONDS-(now-state['session_started'])
                if remaining < 65 or wait+65>=remaining:
                    return 'paused'
                if wait:
                    # Check cancellation/owner throughout an inherited cooldown.
                    await asyncio.sleep(min(wait,15))
                    store.require_owner()
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
                        extracted.extend(await segmenter.create_segments_batch(audio,first,end,executor))
                    task = asyncio.create_task(recognizer.recognize_batch(extracted,total_segments=source.windows))
                    try:
                        while True:
                            done,_ = await asyncio.wait({task},timeout=2)
                            store.require_owner()
                            if done:
                                await task
                                break
                    finally:
                        if not task.done():
                            task.cancel()
                        await asyncio.gather(task,return_exceptions=True)
                    _, after_state = store.clock_state()
                    if after_state['requests'] == requests_before:
                        return 'paused'
                finally:
                    for segment in extracted:
                        segment['file'].unlink(missing_ok=True)
    except QueuePause:
        return 'paused'
    finally:
        await recognizer.close()
        # The workflow's single private-release job owns release/finalization
        # after every matrix slot ends. A finishing slot must not cancel peers.
