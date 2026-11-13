"""Single-job, capture-only study adapter around the unmodified recognizer.

No live execution CLI yet. run_prepared is CHILD-ONLY and its store is an RPC
proxy, not live durable authority. sampling_study_process.run_supervised owns
the real store and verifies native process exit before releasing admission.
"""
import asyncio
import hashlib
import math
import time
from importlib.metadata import version
from worker.jobs.sampling_study_manifest import validate_audio,digest
from worker.jobs.sampling_study_store import StudyPause,StudyFence,require_idle_autocommit
from worker.jobs.sampling_study_input import SealedStudyInput


def receipt_for(result):
    status=result.http_status
    valid=result.is_valid and status==200
    if valid:
        if result.recognized:
            candidate={'id':result.shazam_track_id,'artist':result.artist,'title':result.track_title}
            if any(not isinstance(v,str) or not 0<len(v)<=512 for v in candidate.values()):raise StudyFence('study_provider_identity_incomplete')
            outcome='matched'
        else:candidate=None;outcome='no_match'
    else:
        candidate=None
        # A timeout/transport exception cannot prove whether the provider saw it.
        # Unlike ordinary retries, this bounded experiment never replays unknowns.
        outcome='throttled' if status==429 else 'unknown' if status is None else 'failed'
    return {'outcome':outcome,'http_status':status,'candidate':candidate,
            'response_sha256':digest(result.raw_data) if valid else None,
            'error_type':result.error_type,'retry_after_seconds':result.retry_after_seconds,
            'retry_after_format':result.retry_after_format,'raw_response':result.raw_data if valid else None}


async def run_prepared(store,audio_loader,*,recognizer_factory=None,seconds=3300,check_versions=True):
    if not 1<=seconds<=3300:raise StudyFence('study_runtime_cap')
    if store.manifest is None:raise StudyFence('study_not_claimed')
    if check_versions and (version('shazamio')!='0.9.0' or version('shazamio-core')!='2.0.0'):raise StudyFence('study_sdk_changed')
    if recognizer_factory is None:
        from track_recognizer import TrackRecognizer
        recognizer_factory=TrackRecognizer
    deadline=time.monotonic()+seconds
    active={};reason='error';drained=False;prepared=None
    windows=list(store.windows.values())
    by_index={i:w for i,w in enumerate(windows)}
    def before(segment):
        i=segment['index'];w=by_index.get(i)
        if not w or segment['timestamp']!=store.manifest['sources'][w['source']]['start_seconds']+w['start_seconds']:raise StudyFence('study_segment_binding')
        if (prepared is None or segment.get('file') != prepared.path or
                prepared.expected_hash != w['input_sha256'] or
                segment.get('audio_sha256') != w['input_sha256']):
            raise StudyFence('study_segment_digest')
        prepared.verify()
        if active:raise StudyFence('study_local_inflight')
        # Mark uncertain before reserve, so a lost COMMIT acknowledgment cannot
        # permit a second provider call in this process.
        active['ticket']=None
        ticket=store.reserve(w['id'],w['input_sha256']);active.update(ticket=ticket,index=i,timestamp=segment['timestamp'])
        return ticket
    def finish(result,ticket,delay):
        if (not ticket or active.get('ticket')!=ticket or result.segment_index!=active.get('index') or result.timestamp!=active.get('timestamp')):raise StudyFence('study_local_ticket')
        receipt=receipt_for(result)
        directive=store.finish(ticket,receipt,delay)
        if receipt['outcome']=='unknown':raise StudyPause('study_unknown_outcome')
        active.clear()
        return directive
    recognizer=recognizer_factory(before_attempt=before,on_attempt=finish,quiet=True,
        max_retry_seconds=3300,continuation_deadline=deadline)
    attempt=getattr(recognizer,'recognize_segment',None)
    if attempt is not None:
        async def stop_uncertain_decode(segment):
            result=await attempt(segment)
            # A cancelled native awaiter may leave decoding in a background
            # thread. Do not let the generic retry engine start another decode
            # and later mistake its success for drain of the first one. Once
            # reservation exists, normal finish records the unknown HTTP result.
            if not result.is_valid and result.http_status is None and not active:
                raise StudyPause('study_native_result_uncertain')
            return result
        recognizer.recognize_segment=stop_uncertain_decode
    try:
        completed=store.completed_ids()
        for i,w in enumerate(windows):
            if w['id'] in completed:continue
            if time.monotonic()+65>=deadline:reason='paused';break
            data=audio_loader(w)
            validate_audio(data,w['input_sha256'])
            prepared=SealedStudyInput(data,w['input_sha256'])
            segment={'index':i,'timestamp':store.manifest['sources'][w['source']]['start_seconds']+w['start_seconds'],
                     'file':prepared.verify(),'audio_sha256':w['input_sha256']}
            result=await recognizer.recognize_segment_with_backoff(segment)
            # Invalid/no-request results may leave native decode running. Stop
            # the child and retain its fd until real process exit, never reuse it.
            if not result.is_valid:reason='paused';break
            prepared.close_after_success();prepared=None
        else:
            reason='complete' if len(store.completed_ids())==len(windows) else 'paused'
    except StudyPause:
        reason='paused'
    except asyncio.CancelledError:
        reason='cancelled';raise
    finally:
        # Child HTTP close is NOT native drain. The RPC release is only a
        # proposal; the parent verifies process exit before durable release.
        if prepared is not None:
            prepared.retain_until_exit()
        await recognizer.close();drained=True
        store.release(reason,transport_drained=drained)
    return reason


class ExclusiveSession:
    """Supported legacy-compatible option during a prearranged idle window.

    Holding the existing advisory mutex blocks NEW private admissions, not
    already-running jobs. The grant and demand checks are therefore mandatory.
    A verified terminal controller/empty queue plus external scheduling hold is
    required. This is not a replacement for cross-provider capacity telemetry.
    """
    def __init__(self,connection):self.conn=connection;self.held=False
    def __enter__(self):
        require_idle_autocommit(self.conn)
        with self.conn.cursor() as cur:
            cur.execute('SELECT pg_try_advisory_lock(183601,2) AS acquired')
            if cur.fetchone()['acquired'] is not True:raise StudyPause('study_admission_busy')
            self.held=True
        return self.conn
    def __exit__(self,*args):
        if self.held:
            with self.conn.cursor() as cur:
                cur.execute('SELECT pg_advisory_unlock(183601,2) AS released')
                if cur.fetchone()['released'] is not True:raise StudyFence('study_lock_release_unknown')
            self.held=False


def main():
    raise SystemExit('Execution disabled: review source preparation, exclusive grant, and commit/deployment scope first.')

if __name__=='__main__':main()
