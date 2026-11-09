"""Fixed Jackson continuation runner. No public publisher or automatic dispatch."""
import asyncio
import hashlib
from pathlib import Path

from worker.jobs.yoon_resume_policy import WORKFLOW_SECONDS, WORKFLOW_REQUEST_LIMIT
from worker.jobs.yoon_resume_store import QueuePause


async def recognize_resumable(store, audio: Path):
    from audio_segmenter import AudioSegmenter
    from checkpoint_manager import CheckpointManager
    from worker.pipeline.recognize import PreparedSetContext, recognize_segment_range
    from worker.jobs.yoon_recognition import Policy, PrivateRecognitionSession
    from config import Config
    saved = store.require_owner()
    with audio.open('rb') as f:
        if hashlib.file_digest(f,'sha256').hexdigest()!=saved.get('audio_sha256'):
            raise RuntimeError('private_audio_digest_mismatch')
    if abs(AudioSegmenter.get_audio_duration_ffprobe(audio)-7200)>.2:
        raise RuntimeError('private_audio_duration_mismatch')
    if (Config.SEGMENT_DURATION!=30 or Config.SEGMENT_OVERLAP!=15
            or AudioSegmenter().calculate_total_segments(7200)!=479):
        raise RuntimeError('private_audio_geometry_mismatch')
    cp = CheckpointManager('local:fixed-analysis','fixed-analysis')
    context = PreparedSetContext('local:fixed-analysis',None,{'duration':7200},cp,audio,479)
    reason = 'workflow_time_budget'
    index = None
    # Keep one SDK/client identity and transport for the entire continuation.
    # Durable database pacing, not client recreation, governs retries.
    session = PrivateRecognitionSession(
        Policy('resumable',479,WORKFLOW_REQUEST_LIMIT,WORKFLOW_SECONDS,spacing_seconds=0,retry_limit=0),
        before_request=lambda: store.reserve(index))
    try:
        while True:
            candidate,wait = store.next_window()
            if candidate is None:
                rollup,_ = store.summary()
                if rollup['valid']==479 and rollup['total']==479:
                    store.complete()
                    return 'complete'
                reason='window_attempts_need_review'; break
            # Budget caps prohibit additional provider calls, not finalizing
            # already-complete durable evidence on the last allowed request.
            now,state = store.clock_state()
            remaining = WORKFLOW_SECONDS-(now-state['session_started'])
            if remaining < 65:
                break
            if state['session_requests']>=WORKFLOW_REQUEST_LIMIT:
                reason='workflow_request_budget'; break
            if wait:
                if wait+65>=remaining:
                    reason='cooldown_pending'; break
                # Poll ownership/cancellation during waits, as the ordinary worker
                # does during recognition; sleep does not reset durable cooldown.
                await asyncio.sleep(min(wait,15))
                continue
            index = candidate['segment_index']
            session.stopped = False
            session.reason = None
            response_reason = None
            def received(result):
                nonlocal response_reason
                response_reason = store.finish(result,session.attempts[-1])
            # Reuse the actual shared range extractor and recognition mapping.
            # One-window leases preserve only missing work across continuations.
            await asyncio.wait_for(recognize_segment_range(context,start_index=index,
                end_index=index,on_result=received,recognizer=session),65)
            if response_reason:
                reason=response_reason; break
    except QueuePause as exc:
        reason=str(exc)
    except asyncio.CancelledError:
        reason='cancelled_or_interrupted'
        raise
    except Exception:
        reason='worker_or_storage_pause'
        raise
    finally:
        # A successful complete state cannot be re-opened by release. Any uncertain
        # reservation remains explicit and prevents an automatic duplicate retry.
        try:
            await session.close()
        finally:
            try:
                store.release(reason)
            except RuntimeError:
                pass
    return 'paused'
