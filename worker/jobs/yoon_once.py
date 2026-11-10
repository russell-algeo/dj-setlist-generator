"""Fixed one-off analysis. Requires deployed private ACL + precreated private run."""
from __future__ import annotations
import asyncio
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid

from worker.jobs.yoon_recognition import PrivateRecognitionSession, policy_for

SOURCE_SHA = 'aa01c4b637efe4e59bac051ef67ce4014e270a1f41fad8b6cbba95310fa58aae'
SOURCE_BYTES = 4290463660
START, END, WINDOWS = 3120, 10320, 479
BUDGET = 80 * 60
# This query intentionally fails when the private-schema migration is absent.
PRIVATE_GUARD = '''
    r.id = %s AND r.publication_visibility = 'private'
    AND r.target_set_id = s.id AND s.visibility = 'private'
    AND r.collection_id = s.collection_id
    AND u.id = r.submission_id AND u.visibility = 'private'
    AND u.collection_id = r.collection_id AND r.cancel_requested_at IS NULL
    AND r.published_set_id IS NULL AND r.create_playlist = false
'''


def validate_descriptor(value):
    expected = dict(source_sha256=SOURCE_SHA, source_bytes=SOURCE_BYTES,
                    source_start_seconds=START, source_end_seconds=END)
    if not isinstance(value, dict) or any(value.get(k) != v for k, v in expected.items()):
        raise RuntimeError('fixed_input_mismatch')
    url = value.get('source_url')
    if not isinstance(url, str) or not allowed_source(url):
        raise RuntimeError('invalid_source')
    return url


def allowed_source(url):
    try:
        p = urllib.parse.urlsplit(url)
        host = (p.hostname or '').lower()
        return (p.scheme == 'https' and not p.username and not p.password
                and p.port in (None, 443)
                and any(host == d or host.endswith('.' + d)
                        for d in ('dropbox.com', 'dropboxusercontent.com')))
    except ValueError:
        return False


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_source(newurl):
            raise RuntimeError('invalid_redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, destination):
    if not allowed_source(url):
        raise RuntimeError('invalid_source')
    digest, size, started = hashlib.sha256(), 0, time.monotonic()
    try:
        with urllib.request.build_opener(Redirects()).open(url, timeout=60) as response, destination.open('wb') as out:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > SOURCE_BYTES or time.monotonic() - started > 1200:
                    raise RuntimeError('download_budget')
                digest.update(chunk)
                out.write(chunk)
    except Exception:
        raise RuntimeError('source_download_failed') from None
    if size != SOURCE_BYTES or digest.hexdigest() != SOURCE_SHA:
        raise RuntimeError('source_digest_mismatch')


class Store:
    """Only fixed-run ops JSON writes; existing dev worker credentials, no new grant."""
    def __init__(self, run_id, workflow_id, attempt):
        self.run_id = str(uuid.UUID(run_id))
        if not workflow_id.isdecimal() or not attempt.isdecimal():
            raise RuntimeError('invalid_workflow_owner')
        self.owner = {'workflow_run_id': workflow_id, 'run_attempt': attempt}
        self.target = None
        from worker.db import connect
        self.connect = connect

    def read(self):
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute('''SELECT r.status, r.source_metadata, r.target_set_id, r.collection_id
                FROM ops.set_runs r, app.sets s, ops.submissions u WHERE ''' + PRIVATE_GUARD,
                (self.run_id,))
            row = cur.fetchone()
        if not row:
            raise RuntimeError('private_run_required')
        target = (str(row['target_set_id']), str(row['collection_id']))
        if self.target is not None and self.target != target:
            raise RuntimeError('private_target_changed')
        self.target = target
        return row

    def claim(self):
        row = self.read()
        descriptor = row['source_metadata'].get('yoon_fixed_input')
        source = validate_descriptor(descriptor)
        if row['status'] != 'private_analysis_pending' or row['source_metadata'].get('yoon_analysis'):
            raise RuntimeError('run_not_fresh')
        policy = policy_for(descriptor.get('recognition_mode', 'probe'))
        self.write({'status': 'preparing', 'recognition_mode': policy.mode}, claim=True)
        return source

    def write(self, data, *, claim=False):
        from psycopg.types.json import Json
        if self.target is None:
            self.read()
        payload = {**data, **self.owner, 'target_set_id': self.target[0],
                   'collection_id': self.target[1], 'source_sha256': SOURCE_SHA,
                   'source_start_seconds': START, 'source_end_seconds': END,
                   'bounds': 'approximate; end schedule-derived', 'app_sha': os.getenv('GITHUB_SHA')}
        if claim:
            fence = "r.status = 'private_analysis_pending' AND NOT (r.source_metadata ? 'yoon_analysis')"
            owner_params = ()
        else:
            fence = "r.status = 'private_analysis_running' AND r.source_metadata->'yoon_analysis'->>'workflow_run_id' = %s AND r.source_metadata->'yoon_analysis'->>'run_attempt' = %s"
            owner_params = (self.owner['workflow_run_id'], self.owner['run_attempt'])
        state = {'complete': 'private_analysis_complete', 'partial': 'private_analysis_partial',
                 'failed': 'private_analysis_failed'}.get(data['status'], 'private_analysis_running')
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute('''UPDATE ops.set_runs r SET
                source_metadata = jsonb_set(r.source_metadata, '{yoon_analysis}', %s::jsonb),
                status = %s, stage = 'private_analysis', heartbeat_at = now(), updated_at = now()
                FROM app.sets s, ops.submissions u WHERE ''' + PRIVATE_GUARD + '''
                AND r.target_set_id = %s::uuid AND r.collection_id = %s::uuid AND ''' + fence + ' RETURNING r.id',
                (Json(payload), state, self.run_id, *self.target, *owner_params))
            if cur.fetchone() is None:
                raise RuntimeError('private_write_fence_failed')

    def require_owner(self):
        row = self.read()
        saved = row['source_metadata'].get('yoon_analysis', {})
        if row['status'] != 'private_analysis_running' or any(saved.get(k) != v for k, v in self.owner.items()):
            raise RuntimeError('private_owner_mismatch')
        return saved


def prepare(store, root):
    source = store.claim()
    mode = store.require_owner()['recognition_mode']
    master = root / 'source.wav'
    audio = root / 'audio' / 'input.mp3'
    audio.parent.mkdir(parents=True, exist_ok=True)
    try:
        if shutil.disk_usage(root).free < 8_000_000_000:
            raise RuntimeError('disk_budget')
        fetch(source, master)
        subprocess.run(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-ss', str(START),
            '-i', str(master), '-t', str(END - START), '-vn', '-acodec', 'libmp3lame',
            '-ab', '128k', '-ar', '44100', str(audio)], check=True, timeout=600,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        from audio_segmenter import AudioSegmenter
        if abs(AudioSegmenter.get_audio_duration_ffprobe(audio) - (END - START)) > .2:
            raise RuntimeError('duration_mismatch')
        with audio.open('rb') as f:
            digest = hashlib.file_digest(f, 'sha256').hexdigest()
        store.write({'status': 'prepared', 'audio_sha256': digest, 'recognition_mode': mode})
    except Exception:
        audio.unlink(missing_ok=True)
        store.write({'status': 'failed', 'reason': 'preparation_failed'})
        raise
    finally:
        master.unlink(missing_ok=True)


async def recognize_private_range(context, *, start_index, end_index, session, on_result):
    from worker.pipeline.recognize import recognize_segment_range
    return await recognize_segment_range(context, start_index=start_index,
            end_index=end_index, on_result=on_result, recognizer=session)


async def recognize(store, audio):
    from config import Config
    from checkpoint_manager import CheckpointManager
    from worker.pipeline.recognize import PreparedSetContext
    from worker.pipeline.aggregate import build_tracks_from_recognitions
    from audio_segmenter import AudioSegmenter
    previous = store.require_owner()
    with audio.open('rb') as f:
        if hashlib.file_digest(f, 'sha256').hexdigest() != previous.get('audio_sha256'):
            raise RuntimeError('audio_digest_mismatch')
    if abs(AudioSegmenter.get_audio_duration_ffprobe(audio) - (END - START)) > .2:
        raise RuntimeError('duration_mismatch')
    cp = CheckpointManager('local:fixed-analysis', 'fixed-analysis')
    context = PreparedSetContext('local:fixed-analysis', None, {'duration': END - START}, cp, audio, WINDOWS)
    if AudioSegmenter(checkpoint_manager=cp).calculate_total_segments(END - START) != WINDOWS:
        raise RuntimeError('geometry_mismatch')
    rows, status, reason = [], 'partial', None
    policy = policy_for(previous.get('recognition_mode', 'probe'))
    session = PrivateRecognitionSession(policy, before_request=store.require_owner)
    def snapshot(state):
        return {'status': state, 'audio_sha256': previous['audio_sha256'],
                'recognition_mode': policy.mode, 'recognition_diagnostics': session.diagnostics(),
                'expected_windows': WINDOWS, 'raw_recognitions': [asdict(r) for r in rows],
                'valid_responses': sum(not r.error_type and not r.was_rate_limited for r in rows)}
    def persist(result):
        # One latest result per window; all attempts remain in sanitized diagnostics.
        rows[:] = [row for row in rows if row.segment_index != result.segment_index]
        rows.append(result)
        rows.sort(key=lambda r: r.segment_index)
        store.write(snapshot('recognizing'))
    async def batches():
        for first in range(0, min(WINDOWS, policy.window_limit), 10):
            store.require_owner()
            await recognize_private_range(context, start_index=first,
                    end_index=min(first + 9, WINDOWS - 1, policy.window_limit - 1),
                    session=session, on_result=persist)
            if session.stopped or any(r.error_type or r.was_rate_limited for r in rows):
                return 'partial', session.reason or 'provider_error'
        if policy.mode == 'probe':
            return 'partial', 'probe_complete'
        complete = (len(rows) == WINDOWS
                    and {r.segment_index for r in rows} == set(range(WINDOWS))
                    and all(not r.error_type and not r.was_rate_limited for r in rows))
        return ('complete', None) if complete else ('partial', 'missing_responses')
    try:
        status, reason = await asyncio.wait_for(batches(), min(BUDGET, policy.seconds_limit))
    except asyncio.TimeoutError:
        reason = 'time_budget'
    except asyncio.CancelledError:
        reason = 'cancelled'
        status = 'partial'
        raise
    except Exception:
        reason = 'worker_or_storage_error'
        status = 'partial'
        raise
    finally:
        # Closing the client or clustering must not bypass the final partial flush.
        try:
            await session.close()
        except Exception:
            status, reason = 'partial', 'transport_close_error'
        payload = snapshot(status)
        if reason:
            payload['reason'] = reason
        if status == 'complete':
            try:
                tracks, _ = build_tracks_from_recognitions(rows)
                payload['clustered_setlist'] = [asdict(t) for t in tracks]
            except Exception:
                status = 'partial'
                payload.update(status='partial', reason='aggregation_error')
        store.write(payload)
    return status


def main():
    # Workflow shell also redirects entire process. Cover direct module execution.
    sys.stdout.flush(); sys.stderr.flush()
    fd = os.open(os.devnull, os.O_WRONLY)
    os.dup2(fd, 1); os.dup2(fd, 2); os.close(fd)
    os.umask(0o077)
    if (os.getenv('GITHUB_ACTIONS') != 'true' or os.getenv('RUNNER_OS') != 'Linux'
            or os.getenv('GITHUB_REPOSITORY') != 'russell-algeo/dj-setlist-generator'
            or os.getenv('WORKER_DEPLOYMENT_TARGET') != 'development'):
        return 2
    root = Path(os.environ['RUNNER_TEMP']) / 'fixed-analysis'
    root.mkdir(exist_ok=True)
    os.chdir(root)
    store = Store(os.environ['PRIVATE_RUN_ID'], os.environ['GITHUB_RUN_ID'], os.environ['GITHUB_RUN_ATTEMPT'])
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in ('prepare', 'recognize', 'release'):
            return 2
        descriptor = store.read()['source_metadata'].get('yoon_fixed_input') or {}
        if descriptor.get('recognition_mode') == 'resumable':
            from worker.jobs.yoon_resume_store import ResumeStore
            from worker.jobs.yoon_resume import recognize_resumable
            store = ResumeStore(store.run_id,store.owner['workflow_run_id'],store.owner['run_attempt'])
            if sys.argv[1] == 'release':
                try:
                    store.release('workflow_interrupted')
                except RuntimeError:
                    pass
                return 0
            if sys.argv[1] == 'prepare':
                if store.finalize_ready():
                    with open(os.environ['GITHUB_OUTPUT'],'a') as output:
                        output.write('complete=true\n')
                    return 0
                prepare(store,root)
                plan = store.prepare_scheduler()
                with open(os.environ['GITHUB_OUTPUT'],'a') as output:
                    output.write('slot_matrix='+json.dumps(list(range(plan.slot_count)))+'\n')
                    output.write('effective_slot_count='+str(plan.slot_count)+'\n')
                return 0
            result = asyncio.run(recognize_resumable(store,root/'audio'/'input.mp3',
                slot_index=int(os.getenv('PRIVATE_SLOT_INDEX','0'))))
            return 0 if result in ('complete','slot_complete','paused') else 1
        if sys.argv[1] == 'release':
            return 0
        if sys.argv[1] == 'prepare':
            prepare(store, root)
            # Historical bounded probe/full modes remain one private job.
            with open(os.environ['GITHUB_OUTPUT'],'a') as output:
                output.write('slot_matrix=[0]\n')
                output.write('effective_slot_count=1\n')
            return 0
        return 0 if asyncio.run(recognize(store, root / 'audio' / 'input.mp3')) == 'complete' else 1
    except Exception:
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
