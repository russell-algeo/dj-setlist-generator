"""Durable ordinary-run recognition using the existing run, lease and hit queue.

A committed reservation counts even if the process dies. Unknown outcomes are
never retried automatically. All participating ordinary runs share a database
pacing gate; private/legacy runners are deliberately outside this protocol.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import os
import uuid

from config import Config

VERSION = 1
WORKFLOW_REQUESTS = 24
WORKFLOW_SECONDS = 3600
CONTINUATIONS = 256
WINDOW_ATTEMPTS = 8
MAX_REQUESTS = 8192
MAX_AGE = 7 * 86400
REQUEST_SECONDS = 65
UNCERTAIN_COOLDOWN = 3600
GATE_LOCK = 934725101  # One protocol-wide lock, always before run/lease locks.


class RecognitionPause(RuntimeError):
    """Safe constant reason, never a provider/SQL message."""


class RecognitionFence(RuntimeError):
    pass


def valid_result(result):
    return result.is_valid and result.http_status == 200


def valid_coverage(hits, total, *, versioned, step=None):
    if total <= 0 or len(hits) != total:
        return False
    if {int(h.get('segment_index', -1)) for h in hits} != set(range(total)):
        return False
    for hit in hits:
        data = hit.get('raw_data')
        if not isinstance(data, dict):
            return False
        if versioned:
            evidence = data.get('shared_recognition') or {}
            if (evidence.get('version') != VERSION or evidence.get('valid') is not True
                    or evidence.get('in_flight') is not False):
                return False
            from worker.pipeline.models import Recognition
            try:
                response = Recognition.from_checkpoint(evidence['response'])
            except (KeyError, TypeError, ValueError, AttributeError):
                return False
            if (not valid_result(response) or response.segment_index != hit['segment_index']
                    or response.timestamp != hit.get('timestamp_seconds')
                    or (step is not None and response.timestamp != response.segment_index*step)):
                return False
        elif (not isinstance(data.get('matches'),list)
              or ('track' in data and not isinstance(data['track'],dict))
              or (data['matches'] and 'track' not in data)):
            return False
    return True


def audio_fingerprint(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def budget_reason(state, now, *, request=True):
    if now + REQUEST_SECONDS >= state['created_at'] + MAX_AGE:
        return 'lifetime_time_budget'
    if state['continuations'] > CONTINUATIONS:
        return 'continuation_budget'
    if request and state['requests'] >= state['request_limit']:
        return 'lifetime_request_budget'
    if now + 65 >= state['session_started'] + WORKFLOW_SECONDS:
        return 'workflow_time_budget'
    if request and state['session_requests'] >= WORKFLOW_REQUESTS:
        return 'workflow_request_budget'
    return None


class RecognitionStore:
    def __init__(self, run_id, *, connect=None, workflow_id=None, attempt=None, generation=None):
        from worker.db import connect as default_connect
        self.run_id = str(uuid.UUID(run_id))
        self.connect = connect or default_connect
        self.workflow = workflow_id or os.getenv('GITHUB_RUN_ID')
        self.attempt = attempt or os.getenv('GITHUB_RUN_ATTEMPT', '1')
        self.generation = generation if generation is not None else os.getenv('SET_LIST_DISPATCH_GENERATION', '')
        if not self.workflow or not self.workflow.isdecimal() or not self.attempt.isdecimal():
            raise RecognitionFence('shared_workflow_identity_required')
        self.identity = f'{self.workflow}:{self.attempt}'

    @contextmanager
    def locked(self):
        from psycopg import Error
        try:
            with self.connect() as conn, conn.transaction(), conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout='5s'")
                cur.execute("SET LOCAL statement_timeout='15s'")
                cur.execute('SELECT pg_advisory_xact_lock(%s)', (GATE_LOCK,))
                # The following statement runs AFTER the lock, with a fresh READ
                # COMMITTED snapshot. A lock CTE in this statement is not enough.
                cur.execute('''SELECT r.*,extract(epoch FROM clock_timestamp())::float8 AS db_now
                  FROM ops.set_runs r JOIN ops.submissions u ON u.id=r.submission_id
                  WHERE r.id=%s AND r.publication_visibility='public' AND u.visibility='public'
                    AND r.cancel_requested_at IS NULL AND u.cancel_requested_at IS NULL
                    AND r.status NOT IN ('cancelled','cancelling','completed')
                    AND r.published_set_id IS NULL AND r.stage IS DISTINCT FROM 'publishing_committed'
                    AND r.source_metadata->>'active_workflow_run_id'=%s
                    AND coalesce(r.source_metadata->>'dispatch_generation','')=%s
                  FOR UPDATE OF r,u''', (self.run_id, self.workflow, self.generation))
                row = cur.fetchone()
                if not row:
                    raise RecognitionFence('shared_owner_or_scope_changed')
                state = dict(row['source_metadata'].get('shared_recognition') or {})
                yield cur, row, state
        except Error:
            raise RecognitionFence('shared_storage_error') from None

    def save(self, cur, state):
        cur.execute('''UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,
          '{shared_recognition}',%s::jsonb),heartbeat_at=now(),updated_at=now() WHERE id=%s''',
                    (json.dumps(state), self.run_id))

    def require_state(self, state):
        if state.get('version') != VERSION or state.get('owner') != self.identity:
            raise RecognitionFence('shared_continuation_owner_changed')

    def begin(self):
        """Count continuation before download; return None for legacy evidence."""
        reason = None
        with self.locked() as (cur, row, state):
            if not state:
                cur.execute("SELECT obj_description('ops.claim_next_dispatchable_set_run(integer)'::regprocedure,'pg_proc') AS marker")
                if cur.fetchone()['marker'] != 'shared-recognition-continuation-v1':
                    raise RecognitionFence('shared_recognition_migration_required')
                cur.execute('''SELECT (SELECT count(*) FROM ops.segment_hits WHERE set_run_id=%s)
                  +(SELECT count(*) FROM ops.set_run_leases WHERE set_run_id=%s) AS n''',
                            (self.run_id, self.run_id))
                if cur.fetchone()['n']:
                    return None
                state = dict(version=VERSION, created_at=row['db_now'], continuations=0,
                    requests=0, session_requests=0, deadline=row['db_now']+MAX_AGE, spacing_seconds=30, next_allowed_at=0,
                    provider_next_allowed_at=0, consecutive_limits=0, in_flight=False, in_flight_until=0,
                    paused=False, review_required=False, used_owners=[], request_limit=MAX_REQUESTS)
            if state.get('version') != VERSION:
                raise RecognitionFence('shared_policy_version_unknown')
            if self.identity in state.get('used_owners', []):
                raise RecognitionFence('shared_continuation_replayed')
            if state.get('in_flight') or state.get('review_required'):
                raise RecognitionPause('recognition_requires_reconciliation')
            now = row['db_now']
            if self.complete(cur,state):
                state.update(owner=self.identity, paused=False, reason=None)
                self.save(cur,state)
                return state
            if state['continuations'] >= CONTINUATIONS:
                reason = 'continuation_budget'
            elif now >= state['created_at'] + MAX_AGE:
                reason = 'lifetime_time_budget'
            elif state['requests'] >= state['request_limit']:
                reason = 'lifetime_request_budget'
            elif now < state['next_allowed_at']:
                reason = 'cooldown_pending'
            if reason:
                state.update(paused=True, reason=reason)
                self.save(cur, state)
            else:
                state.update(owner=self.identity, continuations=state['continuations']+1,
                    session_started=now, session_requests=0, paused=False, reason=None,
                    used_owners=state.get('used_owners', []) + [self.identity])
                self.save(cur, state)
        if reason:
            raise RecognitionPause(reason)
        return state

    def prepared(self, context):
        fingerprint = audio_fingerprint(context.audio_file)
        geometry = dict(segment_duration=Config.SEGMENT_DURATION,
                        segment_overlap=Config.SEGMENT_OVERLAP, segment_count=context.total_segments)
        reason = None
        with self.locked() as (cur, row, state):
            self.require_state(state)
            expected = state.get('audio_sha256')
            if expected and (expected != fingerprint or state.get('geometry') != geometry
                             or state.get('source_url') != context.source_url):
                reason = 'prepared_audio_changed'
                state.update(paused=True, review_required=True, reason=reason)
            elif context.total_segments <= 0 or context.total_segments > MAX_REQUESTS:
                reason = 'source_window_budget'
                state.update(paused=True, review_required=True, reason=reason)
            else:
                state.update(audio_sha256=fingerprint, geometry=geometry, source_url=context.source_url,
                             request_limit=min(MAX_REQUESTS, context.total_segments * WINDOW_ATTEMPTS))
                cur.execute('''INSERT INTO ops.set_run_leases
                  (set_run_id,slot_index,segment_start_index,segment_end_index,status)
                  SELECT %s,0,i,i,'pending' FROM generate_series(0,%s) i
                  WHERE NOT EXISTS (SELECT 1 FROM ops.set_run_leases l
                    WHERE l.set_run_id=%s AND l.segment_start_index=i)''',
                            (self.run_id, context.total_segments-1, self.run_id))
            self.save(cur, state)
        if reason:
            raise RecognitionPause(reason)
        return context.total_segments

    def state(self):
        with self.locked() as (_, row, state):
            self.require_state(state)
            return row['db_now'], state

    def complete(self, cur, state):
        total = state.get('geometry', {}).get('segment_count', 0)
        step = state.get('geometry',{}).get('segment_duration',0)-state.get('geometry',{}).get('segment_overlap',0)
        cur.execute('''SELECT count(*) AS total,count(*) FILTER (WHERE
          segment_index>=0 AND segment_index<%s AND timestamp_seconds=segment_index*%s
          AND raw_data->'shared_recognition'->>'version'='1'
          AND raw_data->'shared_recognition'->>'valid'='true'
          AND raw_data->'shared_recognition'->>'in_flight'='false'
          AND raw_data->'shared_recognition'->'response'->'http_status'='200'::jsonb
          AND coalesce(raw_data->'shared_recognition'->'response'->>'error_type','')=''
          AND raw_data->'shared_recognition'->'response'->'was_rate_limited'='false'::jsonb
          AND raw_data->'shared_recognition'->'response'->'segment_index'=to_jsonb(segment_index)
          AND raw_data->'shared_recognition'->'response'->'timestamp'=to_jsonb(timestamp_seconds)
          AND jsonb_typeof(raw_data->'shared_recognition'->'response'->'raw_data'->'matches')='array'
          AND (NOT (raw_data->'shared_recognition'->'response'->'raw_data' ? 'track')
            OR jsonb_typeof(raw_data->'shared_recognition'->'response'->'raw_data'->'track')='object')
          AND (raw_data->'shared_recognition'->'response'->'raw_data'->'matches'='[]'::jsonb
            OR jsonb_typeof(raw_data->'shared_recognition'->'response'->'raw_data'->'track')='object')
          ) AS valid FROM ops.segment_hits WHERE set_run_id=%s''', (total,step,self.run_id))
        coverage=cur.fetchone()
        return total>0 and coverage['total']==total and coverage['valid']==total

    def reserve(self):
        """Commit exactly one window reservation, or return (None,wait,reason)."""
        with self.locked() as (cur, row, state):
            self.require_state(state)
            if self.complete(cur, state):
                state.update(paused=False, reason=None)
                self.save(cur, state)
                return None, 0, 'complete'
            if state.get('in_flight') or state.get('review_required'):
                return None, 0, 'recognition_requires_reconciliation'
            if state.get('paused'):
                return None, 0, state.get('reason') or 'paused'
            reason = budget_reason(state, row['db_now'])
            if reason:
                return None, 0, reason
            # Pacing survives clean continuations, concurrent slots, other runs,
            # completed runs, and request failures. No new table/access required.
            cur.execute('''SELECT
              coalesce(max((source_metadata->'shared_recognition'->>'provider_next_allowed_at')::float8),0) AS due,
              coalesce(max((source_metadata->'shared_recognition'->>'spacing_seconds')::float8),30) AS spacing,
              (coalesce(bool_or(source_metadata->'shared_recognition'->>'in_flight'='true' AND
                CASE WHEN jsonb_typeof(source_metadata->'shared_recognition'->'in_flight_until')='number'
                  THEN (source_metadata->'shared_recognition'->>'in_flight_until')::numeric > %s
                  ELSE true END),false)
                OR EXISTS (SELECT 1 FROM ops.segment_hits h JOIN ops.set_runs r ON r.id=h.set_run_id
                  WHERE r.publication_visibility='public'
                    AND r.source_metadata->'shared_recognition'->>'version'='1'
                    AND h.raw_data->'shared_recognition'->>'in_flight'='true'
                    AND CASE WHEN jsonb_typeof(h.raw_data->'shared_recognition'->'attempts'->-1->'expires_at')='number'
                      THEN (h.raw_data->'shared_recognition'->'attempts'->-1->>'expires_at')::numeric > %s
                      ELSE true END)) AS busy
              FROM ops.set_runs WHERE publication_visibility='public'
                AND source_metadata->'shared_recognition'->>'version'='1' ''', (row['db_now'],row['db_now']))
            gate = cur.fetchone()
            if gate['busy']:
                return None, 30, 'provider_busy'
            wait = max(0, state['next_allowed_at']-row['db_now'], gate['due']-row['db_now'])
            if wait:
                return None, wait, 'cooldown_pending'
            cur.execute('''SELECT l.id,l.segment_start_index AS segment_index,h.raw_data
              FROM ops.set_run_leases l LEFT JOIN ops.segment_hits h
                ON h.set_run_id=l.set_run_id AND h.segment_index=l.segment_start_index
              WHERE l.set_run_id=%s AND l.status='pending'
                AND coalesce(h.raw_data->'shared_recognition'->>'valid','false')<>'true'
              ORDER BY l.segment_start_index LIMIT 1 FOR UPDATE OF l''', (self.run_id,))
            candidate = cur.fetchone()
            if not candidate:
                return None, 0, 'recognition_requires_reconciliation'
            data = dict((candidate.get('raw_data') or {}).get('shared_recognition') or {})
            attempts = list(data.get('attempts') or [])
            if data.get('in_flight') or len(attempts) >= WINDOW_ATTEMPTS:
                return None, 0, 'window_attempt_budget'
            index, token = candidate['segment_index'], str(uuid.uuid4())
            attempts.append(dict(token=token, owner=self.identity, number=state['requests']+1,
                                 started_at=row['db_now'], expires_at=row['db_now']+REQUEST_SECONDS+UNCERTAIN_COOLDOWN, outcome='in_flight'))
            data.update(version=VERSION, valid=False, in_flight=True, attempts=attempts)
            step = state['geometry']['segment_duration'] - state['geometry']['segment_overlap']
            cur.execute('''INSERT INTO ops.segment_hits
              (set_run_id,lease_id,segment_index,timestamp_seconds,recognized,raw_data)
              VALUES(%s,%s,%s,%s,false,%s::jsonb) ON CONFLICT(set_run_id,segment_index)
              DO UPDATE SET raw_data=excluded.raw_data''',
                        (self.run_id,candidate['id'],index,index*step,json.dumps({'shared_recognition':data})))
            cur.execute('''UPDATE ops.set_run_leases SET status='claimed',claimed_by=%s,
              claimed_at=now(),updated_at=now() WHERE id=%s''', (token,candidate['id']))
            state.update(requests=state['requests']+1,session_requests=state['session_requests']+1,
                         spacing_seconds=max(state['spacing_seconds'],gate['spacing']),
                         provider_next_allowed_at=row['db_now']+max(state['spacing_seconds'],gate['spacing']),
                         in_flight=True, in_flight_until=row['db_now']+REQUEST_SECONDS+UNCERTAIN_COOLDOWN,
                         request_deadline=row['db_now']+REQUEST_SECONDS, active_index=index, token=token)
            self.save(cur,state)
            return dict(index=index,token=token), 0, None

    def authorize(self, reservation):
        """Last gate at the actual POST, after extraction/signature preparation.

        A late/stalled worker cannot transmit after its bounded reservation.
        Already-sent work cannot be synchronously recalled by cancellation.
        """
        with self.locked() as (_,row,state):
            self.require_state(state)
            if (not reservation or not state.get('in_flight') or state.get('review_required')
                    or state.get('token') != reservation['token']
                    or state.get('active_index') != reservation['index']
                    or row['db_now'] + max(1,min(Config.RECOGNITION_TIMEOUT,30)) >= state.get('request_deadline',0)
                    or row['db_now'] + max(1,min(Config.RECOGNITION_TIMEOUT,30)) >= state['session_started']+WORKFLOW_SECONDS
                    or row['db_now'] + max(1,min(Config.RECOGNITION_TIMEOUT,30)) >= state['created_at']+MAX_AGE):
                raise RecognitionFence('shared_transmission_not_authorized')

    def finish(self, reservation, result):
        with self.locked() as (cur,row,state):
            self.require_state(state)
            index = reservation['index']
            if (not state.get('in_flight') or state.get('token')!=reservation['token']
                    or state.get('active_index')!=index or result.segment_index!=index
                    or result.timestamp!=index*(state['geometry']['segment_duration']-state['geometry']['segment_overlap'])):
                raise RecognitionFence('shared_response_owner_changed')
            cur.execute('SELECT lease_id,raw_data FROM ops.segment_hits WHERE set_run_id=%s AND segment_index=%s FOR UPDATE',
                        (self.run_id,index))
            hit = cur.fetchone()
            data = dict(hit['raw_data']['shared_recognition'])
            attempts = list(data['attempts'])
            if not data['in_flight'] or data.get('valid') or attempts[-1]['token']!=reservation['token']:
                raise RecognitionFence('shared_response_reservation_changed')
            valid = valid_result(result)
            diagnostic = dict(http_status=result.http_status,error_type=result.error_type,
                was_rate_limited=result.was_rate_limited,retry_after_seconds=result.retry_after_seconds,
                retry_after_format=result.retry_after_format)
            attempts[-1].update(finished_at=row['db_now'],outcome='valid' if valid else 'failed',diagnostic=diagnostic)
            data.update(valid=valid,in_flight=False,attempts=attempts)
            if valid:
                data['response'] = asdict(result)
            cur.execute('''UPDATE ops.segment_hits SET recognized=%s,track_title=%s,artist=%s,
              shazam_track_id=%s,raw_data=%s::jsonb WHERE set_run_id=%s AND segment_index=%s''',
                        (bool(valid and result.recognized),result.track_title if valid else None,
                         result.artist if valid else None,result.shazam_track_id if valid else None,
                         json.dumps({'shared_recognition':data}),self.run_id,index))
            cur.execute('''UPDATE ops.set_run_leases SET status=%s,claimed_by=null,claimed_at=null,
              completed_at=CASE WHEN %s THEN now() ELSE null END,updated_at=now() WHERE id=%s''',
                        ('completed' if valid else 'pending',valid,hit['lease_id']))
            reason = None
            if result.was_rate_limited:
                state['consecutive_limits'] += 1
                state['spacing_seconds'] = min(180, state['spacing_seconds']*2)
                delay = min(3600, 300 * 2**min(state['consecutive_limits']-1,4))
                reason = 'sustained_rate_limit_pause' if state['consecutive_limits']>=4 else None
            elif valid:
                state['consecutive_limits'] = 0
                delay = state['spacing_seconds']
            else:
                delay = max(300,state['spacing_seconds'])
                reason = 'provider_error_pause'
            if result.retry_after_seconds is not None:
                delay = max(delay,result.retry_after_seconds)
            if result.retry_after_format == 'invalid':
                reason = 'retry_after_needs_review'
                state['review_required'] = True
            state.update(in_flight=False,in_flight_until=0,active_index=None,token=None,
                next_allowed_at=row['db_now']+delay,
                provider_next_allowed_at=max(state['provider_next_allowed_at'],row['db_now']+delay))
            if len(attempts)>=WINDOW_ATTEMPTS and not valid:
                reason = 'window_attempt_budget'
            if reason:
                state.update(paused=True,reason=reason)
            self.save(cur,state)
            return reason

    def pause(self, reason, *, wait=0):
        with self.locked() as (cur,row,state):
            self.require_state(state)
            if self.complete(cur,state):
                state.update(paused=False,reason=None)
            else:
                state.update(paused=True,reason=reason,
                             next_allowed_at=max(state['next_allowed_at'],row['db_now']+wait))
                if state.get('in_flight') or reason in ('recognition_requires_reconciliation','prepared_audio_changed',
                                                       'retry_after_needs_review','worker_or_storage_error'):
                    state['review_required'] = True
            self.save(cur,state)


async def recognize_continuation(store, context, *, check_active):
    """One SDK/client per continuation; cancellation wrapper remains in caller."""
    from track_recognizer import TrackRecognizer
    from worker.pipeline.recognize import recognize_segment_range
    _,state = store.state()
    if (audio_fingerprint(context.audio_file)!=state.get('audio_sha256')
            or state.get('geometry') != dict(segment_duration=Config.SEGMENT_DURATION,
                segment_overlap=Config.SEGMENT_OVERLAP,segment_count=context.total_segments)):
        store.pause('prepared_audio_changed')
        raise RecognitionPause('prepared_audio_changed')
    reservation = None
    recognizer = TrackRecognizer(single_attempt=True, before_request=lambda: store.authorize(reservation))
    completed = recognized = 0
    reason, wait = 'workflow_time_budget', 0
    try:
        while True:
            check_active()
            now,state=store.state()
            # Completion is allowed after the final permitted request and before
            # the next call to reserve checks the time/request budgets.
            reservation,wait,reason=store.reserve()
            if reason=='complete':
                return dict(lease_count=completed,recognized_count=recognized)
            if reservation is None:
                if reason!='provider_busy' and wait and wait<=60 and now+wait+70<state['session_started']+WORKFLOW_SECONDS:
                    await asyncio.sleep(min(wait,15))
                    continue
                break
            received=[]
            def persist(result):
                store.finish(reservation,result)
                received.append(result)
            await asyncio.wait_for(recognize_segment_range(context,start_index=reservation['index'],
                end_index=reservation['index'],on_result=persist,recognizer=recognizer),65)
            if len(received)!=1:
                raise RecognitionFence('shared_response_missing')
            if valid_result(received[0]):
                completed+=1
                recognized+=int(received[0].recognized)
    except asyncio.CancelledError:
        reason='cancelled_or_interrupted'
        raise
    except Exception:
        reason='worker_or_storage_error'
        raise
    finally:
        try:
            await recognizer.close()
        finally:
            # Fences deliberately reject writes after cancellation/owner changes;
            # the existing cancellation path owns terminal state in that case.
            try:
                store.pause(reason or 'workflow_paused',wait=wait)
            except RecognitionFence:
                pass
    return dict(lease_count=completed,recognized_count=recognized)
