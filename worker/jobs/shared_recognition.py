"""Durable ordinary-run recognition using the existing run, lease and hit queue.

A committed reservation counts even if the process dies. Unknown outcomes are
never retried automatically. Production-sized leases and concurrent per-window
reservations preserve the production request pace. The common TrackRecognizer owns retry timing.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import os
import time
import uuid

from config import Config
from recognition_transport import RequestDeferred

VERSION = 1
POLICY_VERSION = 2
WORKFLOW_SECONDS = 3600
CONTINUATIONS = 256
WINDOW_ATTEMPTS = 8
MAX_REQUESTS = 8192
MAX_AGE = 7 * 86400
REQUEST_SECONDS = 65


class RecognitionPause(RequestDeferred):
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
                # Row locks serialize evidence changes for this run only; no
                # database-wide provider mutex or delay is introduced.
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
        if (state.get('version') != VERSION or state.get('policy_version') != POLICY_VERSION
                or state.get('owner') != self.identity):
            raise RecognitionFence('shared_continuation_owner_changed')

    def begin(self):
        """Count continuation before download; return None for legacy evidence."""
        reason = None
        with self.locked() as (cur, row, state):
            cur.execute("SELECT obj_description('ops.claim_next_dispatchable_set_run(integer)'::regprocedure,'pg_proc') AS marker")
            if cur.fetchone()['marker'] != 'shared-recognition-parallel-v2':
                raise RecognitionFence('shared_recognition_migration_required')
            if not state:
                cur.execute('''SELECT (SELECT count(*) FROM ops.segment_hits WHERE set_run_id=%s)
                  +(SELECT count(*) FROM ops.set_run_leases WHERE set_run_id=%s) AS n''',
                            (self.run_id, self.run_id))
                if cur.fetchone()['n']:
                    return None
                state = dict(version=VERSION, policy_version=POLICY_VERSION, created_at=row['db_now'], continuations=0,
                    requests=0, session_requests=0, deadline=row['db_now']+MAX_AGE, next_allowed_at=0,
                    provider_next_allowed_at=0, consecutive_limits=0, in_flight=False, in_flight_until=0,
                    paused=False, review_required=False, used_owners=[], request_limit=MAX_REQUESTS)
            if state.get('version') != VERSION:
                raise RecognitionFence('shared_policy_version_unknown')
            if self.identity in state.get('used_owners', []):
                raise RecognitionFence('shared_continuation_replayed')
            cur.execute("SELECT count(*) AS n FROM ops.segment_hits WHERE set_run_id=%s AND raw_data->'shared_recognition'->>'in_flight'='true'", (self.run_id,))
            if state.get('in_flight') or state.get('review_required') or cur.fetchone()['n']:
                raise RecognitionPause('recognition_requires_reconciliation')
            if state.get('policy_version', 1) not in (1, POLICY_VERSION):
                raise RecognitionFence('shared_policy_version_unknown')
            # Clean legacy evidence remains immutable. Only the scheduling policy
            # upgrades, never an unknown request or a completed response.
            state['policy_version'] = POLICY_VERSION
            state.pop('spacing_seconds', None)
            state.pop('active_index', None)
            state.pop('token', None)
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

    def prepared(self, context, *, slot_count=1, lease_size=1):
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
                cur.execute('SELECT count(*) AS n FROM ops.set_run_leases WHERE set_run_id=%s', (self.run_id,))
                count = cur.fetchone()['n']
                if not count:
                    cur.execute("""INSERT INTO ops.set_run_leases
                      (set_run_id,slot_index,segment_start_index,segment_end_index,status)
                      SELECT %s,mod(ordinality-1, %s)::integer,i,least(i+%s-1,%s),'pending'
                      FROM generate_series(0,%s,%s) WITH ORDINALITY AS series(i,ordinality)""",
                      (self.run_id,max(1,slot_count),max(1,lease_size),context.total_segments-1,
                       context.total_segments-1,max(1,lease_size)))
                cur.execute('SELECT count(*) AS n FROM ops.set_run_leases WHERE set_run_id=%s', (self.run_id,))
                count = cur.fetchone()['n']
            self.save(cur, state)
        if reason:
            raise RecognitionPause(reason)
        return count

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

    def claim_lease(self, worker_name):
        with self.locked() as (cur,row,state):
            self.require_state(state)
            if state.get('review_required'):
                raise RecognitionPause('recognition_requires_reconciliation')
            reason = budget_reason(state,row['db_now'])
            if reason:
                raise RecognitionPause(reason)
            cur.execute("""SELECT * FROM ops.set_run_leases WHERE set_run_id=%s AND status='pending'
                ORDER BY segment_start_index,id LIMIT 1 FOR UPDATE SKIP LOCKED""",(self.run_id,))
            lease=cur.fetchone()
            if lease:
                cur.execute("""UPDATE ops.set_run_leases SET status='claimed',claimed_by=%s,
                  claimed_at=now(),updated_at=now() WHERE id=%s""",(worker_name,lease['id']))
            return lease

    def missing_indices(self, lease):
        with self.locked() as (cur,_,state):
            self.require_state(state)
            cur.execute("""SELECT segment_index FROM ops.segment_hits WHERE set_run_id=%s
              AND raw_data->'shared_recognition'->>'valid'='true'
              AND segment_index BETWEEN %s AND %s""",
              (self.run_id,lease['segment_start_index'],lease['segment_end_index']))
            valid={r['segment_index'] for r in cur.fetchall()}
            return [i for i in range(lease['segment_start_index'],lease['segment_end_index']+1) if i not in valid]

    def reserve(self, index, lease_id, worker_name):
        """Reserve one actual HTTP attempt; other windows/leases remain concurrent."""
        from recognition_transport import RequestAuthorizationError
        with self.locked() as (cur,row,state):
            self.require_state(state)
            reason=budget_reason(state,row['db_now'])
            if reason or state.get('review_required'):
                raise RecognitionPause(reason or 'recognition_requires_reconciliation')
            cur.execute("""SELECT id FROM ops.set_run_leases WHERE id=%s AND set_run_id=%s
              AND status='claimed' AND claimed_by=%s AND %s BETWEEN segment_start_index AND segment_end_index
              FOR UPDATE""",(lease_id,self.run_id,worker_name,index))
            if not cur.fetchone():
                raise RequestAuthorizationError('shared_lease_owner_changed')
            cur.execute('SELECT raw_data FROM ops.segment_hits WHERE set_run_id=%s AND segment_index=%s FOR UPDATE',
                        (self.run_id,index))
            hit=cur.fetchone()
            data=dict((hit['raw_data'] if hit else {}).get('shared_recognition') or {})
            attempts=list(data.get('attempts') or [])
            if data.get('valid') or data.get('in_flight'):
                raise RequestAuthorizationError('shared_window_not_admissible')
            if len(attempts)>=WINDOW_ATTEMPTS:
                raise RecognitionPause('window_attempt_budget')
            if row['db_now'] < data.get('next_allowed_at',0):
                raise RecognitionPause('cooldown_pending')
            token=str(uuid.uuid4())
            attempts.append(dict(token=token,owner=self.identity,number=state['requests']+1,
                                 started_at=row['db_now'],expires_at=row['db_now']+REQUEST_SECONDS,
                                 outcome='in_flight'))
            data.update(version=VERSION,policy_version=POLICY_VERSION,valid=False,in_flight=True,attempts=attempts)
            step=state['geometry']['segment_duration']-state['geometry']['segment_overlap']
            cur.execute("""INSERT INTO ops.segment_hits
              (set_run_id,lease_id,segment_index,timestamp_seconds,recognized,raw_data)
              VALUES(%s,%s,%s,%s,false,%s::jsonb) ON CONFLICT(set_run_id,segment_index)
              DO UPDATE SET lease_id=excluded.lease_id,raw_data=excluded.raw_data""",
              (self.run_id,lease_id,index,index*step,json.dumps({'shared_recognition':data})))
            state.update(requests=state['requests']+1,session_requests=state['session_requests']+1,
                         in_flight=True,in_flight_until=max(state.get('in_flight_until',0),row['db_now']+REQUEST_SECONDS))
            self.save(cur,state)
            return dict(index=index,token=token,lease_id=str(lease_id),worker_name=worker_name)

    def finish(self, reservation, result, delay_seconds=0):
        with self.locked() as (cur,row,state):
            self.require_state(state)
            index=reservation['index']
            if (result.segment_index!=index or result.timestamp!=index*(state['geometry']['segment_duration']-state['geometry']['segment_overlap'])):
                raise RecognitionFence('shared_response_owner_changed')
            cur.execute('SELECT lease_id,raw_data FROM ops.segment_hits WHERE set_run_id=%s AND segment_index=%s FOR UPDATE',
                        (self.run_id,index))
            hit=cur.fetchone()
            if not hit or str(hit['lease_id'])!=reservation['lease_id']:
                raise RecognitionFence('shared_response_reservation_changed')
            data=dict(hit['raw_data']['shared_recognition']); attempts=list(data['attempts'])
            if (not data.get('in_flight') or data.get('valid') or attempts[-1]['token']!=reservation['token']
                    or attempts[-1]['owner']!=self.identity):
                raise RecognitionFence('shared_response_reservation_changed')
            valid=valid_result(result)
            diagnostic=dict(http_status=result.http_status,error_type=result.error_type,
                was_rate_limited=result.was_rate_limited,retry_after_seconds=result.retry_after_seconds,
                retry_after_format=result.retry_after_format)
            attempts[-1].update(finished_at=row['db_now'],outcome='valid' if valid else 'failed',diagnostic=diagnostic)
            delay=max(0,delay_seconds,result.retry_after_seconds or 0) if not valid else 0
            data.update(valid=valid,in_flight=False,attempts=attempts,next_allowed_at=row['db_now']+delay)
            if valid: data['response']=asdict(result)
            cur.execute("""UPDATE ops.segment_hits SET recognized=%s,track_title=%s,artist=%s,
              shazam_track_id=%s,raw_data=%s::jsonb WHERE set_run_id=%s AND segment_index=%s""",
              (bool(valid and result.recognized),result.track_title if valid else None,
               result.artist if valid else None,result.shazam_track_id if valid else None,
               json.dumps({'shared_recognition':data}),self.run_id,index))
            cur.execute("""SELECT count(*) AS n,coalesce(max((raw_data->'shared_recognition'->'attempts'->-1->>'expires_at')::float8),0) AS expires
              FROM ops.segment_hits WHERE set_run_id=%s AND raw_data->'shared_recognition'->>'in_flight'='true'""",(self.run_id,))
            active=cur.fetchone()
            state.update(in_flight=active['n']>0,in_flight_until=active['expires'],
                         next_allowed_at=max(state.get('next_allowed_at',0),row['db_now']+delay))
            reason=None
            if result.retry_after_format=='invalid':
                reason='retry_after_needs_review';state['review_required']=True
            if len(attempts)>=WINDOW_ATTEMPTS and not valid: reason='window_attempt_budget'
            if reason: state.update(paused=True,reason=reason)
            self.save(cur,state)
            return reason

    def settle_lease(self, lease, worker_name):
        with self.locked() as (cur,_,state):
            self.require_state(state)
            cur.execute("""SELECT count(*) AS n FROM ops.segment_hits WHERE set_run_id=%s
              AND segment_index BETWEEN %s AND %s AND raw_data->'shared_recognition'->>'valid'='true'
              AND raw_data->'shared_recognition'->>'in_flight'='false'""",
              (self.run_id,lease['segment_start_index'],lease['segment_end_index']))
            complete=cur.fetchone()['n']==lease['segment_end_index']-lease['segment_start_index']+1
            cur.execute("""UPDATE ops.set_run_leases SET status=%s,claimed_by=null,claimed_at=null,
              completed_at=CASE WHEN %s THEN now() ELSE null END,updated_at=now()
              WHERE id=%s AND set_run_id=%s AND claimed_by=%s AND status='claimed'""",
              ('completed' if complete else 'failed',complete,lease['id'],self.run_id,worker_name))
            return complete

    def pause(self, reason, *, wait=0):
        with self.locked() as (cur,row,state):
            self.require_state(state)
            if self.complete(cur,state):
                state.update(paused=False,reason=None)
            else:
                # Other slots may still be making legitimate concurrent requests.
                # Their in-flight evidence is not an error; finalization waits for
                # the workflow and separately fences any genuinely unknown result.
                state.update(paused=True,reason=state.get('reason') or reason,
                             next_allowed_at=max(state['next_allowed_at'],row['db_now']+wait))
                if reason in ('prepared_audio_changed','retry_after_needs_review'):
                    state['review_required']=True
            self.save(cur,state)


async def recognize_continuation(store, context, *, check_active, slot_index=0):
    """Production lease fanout and shared recognition engine; durable evidence only."""
    from track_recognizer import TrackRecognizer
    from worker.pipeline.recognize import recognize_segment_range
    _,state=store.state()
    if (audio_fingerprint(context.audio_file)!=state.get('audio_sha256')
            or state.get('geometry')!=dict(segment_duration=Config.SEGMENT_DURATION,
                segment_overlap=Config.SEGMENT_OVERLAP,segment_count=context.total_segments)):
        store.pause('prepared_audio_changed');raise RecognitionPause('prepared_audio_changed')
    worker_name=f'{store.identity}:slot-{slot_index}:{uuid.uuid4()}'
    completed=recognized=0
    reason='workflow_time_budget'
    lease=None
    recognizer=None
    try:
        while True:
            check_active()
            lease=store.claim_lease(worker_name)
            if not lease: break
            now,state=store.state()
            remaining=state['session_started']+WORKFLOW_SECONDS-now
            recognizer=TrackRecognizer(
                before_attempt=lambda segment:store.reserve(segment['index'],lease['id'],worker_name),
                on_attempt=lambda result,ticket,delay:store.finish(ticket,result,delay),
                max_retry_seconds=max(0,remaining-REQUEST_SECONDS),
                continuation_deadline=time.monotonic()+max(0,remaining-REQUEST_SECONDS))
            missing=store.missing_indices(lease)
            # Retain every completed window, including holes within an old lease.
            ranges=[]
            for index in missing:
                if ranges and index==ranges[-1][1]+1: ranges[-1]=(ranges[-1][0],index)
                else: ranges.append((index,index))
            for start,end in ranges:
                def received(result):
                    nonlocal recognized
                    if valid_result(result): recognized+=int(result.recognized)
                await recognize_segment_range(context,start_index=start,end_index=end,
                                               on_result=received,recognizer=recognizer)
            check_active()
            if not store.settle_lease(lease,worker_name):
                reason='recognition_retry_pending';break
            completed+=1
            await recognizer.close();recognizer=None
    except RequestDeferred as exc:
        reason=str(exc)
    except asyncio.CancelledError:
        reason='cancelled_or_interrupted';raise
    except Exception:
        reason='worker_or_storage_error';raise
    finally:
        try:
            if recognizer is not None: await recognizer.close()
        finally:
            try:
                if lease: store.settle_lease(lease,worker_name)
                store.pause(reason)
            except RecognitionFence: pass
    return dict(lease_count=completed,recognized_count=recognized)
