"""Private reviewed-source durable queue using existing lease/hit tables, never events.

All mutations serialize on the scoped private run. Public initialization,
destructive requeue, callback publication and ordinary worker statuses are not
used. A request reservation is committed before transmission; a hard-killed
reservation is explicitly uncertain, not silently a valid no-match.
"""
from contextlib import contextmanager
from worker.recognition_transactions import (
    recognition_transaction, retry_lock_timeouts,
)
from dataclasses import asdict
import json
import math
import os
import re
import uuid
from recognition_transport import RequestDeferred
from recognition_retry_policy import (POLICY_VERSION, RetryDirective, actual_throttle,
    non_throttle_attempts, throttle_streak, throttle_delay, effective_requests)
from worker.jobs.yoon_sources import JACKSON, reviewed_source

from worker.jobs.yoon_resume_policy import (
    CONTINUATION_LIMIT, may_reserve,
)


class QueuePause(RequestDeferred):
    pass


def verified_window_exhaustion(data, index):
    """Classify only a settled, well-formed refusal; never authorize a retry."""
    if data.get('valid') is not False or data.get('in_flight') is not False:
        return False
    attempts = data.get('attempts')
    if not isinstance(attempts, list) or not attempts:
        return False
    seen_tickets, previous_number = set(), 0
    for attempt in attempts:
        if not isinstance(attempt, dict) or attempt.get('state') != 'finished':
            return False
        diagnostic = attempt.get('diagnostic')
        if not isinstance(diagnostic, dict):
            return False
        status = diagnostic.get('http_status')
        if status is not None and (type(status) is not int or not 100 <= status <= 599):
            return False
        if (not isinstance(diagnostic.get('outcome'), str) or not diagnostic['outcome']
                or diagnostic.get('retry_after_format') == 'invalid'):
            return False
        for field in ('started_at', 'finished_at'):
            value = attempt.get(field)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                return False
        if attempt['finished_at'] < attempt['started_at']:
            return False
        if type(attempt.get('number')) is not int or attempt['number'] <= previous_number:
            return False
        previous_number = attempt['number']
        if not all(isinstance(attempt.get(k), str) and attempt[k].isdecimal()
                   for k in ('workflow_run_id', 'run_attempt')):
            return False
        try:
            uuid.UUID(attempt['ticket'])
            if attempt['ticket'] in seen_tickets: return False
            seen_tickets.add(attempt['ticket'])
        except (KeyError, ValueError, TypeError, AttributeError):
            return False
    response = data.get('response')
    if (not isinstance(response, dict) or response.get('segment_index') != index
            or response.get('timestamp') != index * 15
            or not isinstance(response.get('error_type'), str) or not response['error_type']):
        return False
    if (response.get('http_status') != attempts[-1]['diagnostic'].get('http_status')
            or response['error_type'] != attempts[-1]['diagnostic'].get('outcome')):
        return False
    return non_throttle_attempts(attempts) >= 8


class ResumeStore:
    source = JACKSON
    def __init__(self, run_id, workflow_id, attempt, connect=None):
        from worker.db import connect as default_connect
        self.run_id = str(uuid.UUID(run_id))
        if not workflow_id.isdecimal() or not attempt.isdecimal():
            raise RuntimeError('invalid_private_owner')
        self.owner = {'workflow_run_id': workflow_id, 'run_attempt': attempt}
        self.connect = connect or default_connect
        self.source = JACKSON

    @contextmanager
    def locked(self, *, owner=True, admission=False):
        from worker.jobs.yoon_once import PRIVATE_GUARD, validate_descriptor
        with recognition_transaction(self.connect) as conn, conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute("SET LOCAL statement_timeout = '15s'")
            if admission:
                from worker.jobs.yoon_admission import lock
                lock(cur)
            cur.execute('''SELECT r.*, extract(epoch from clock_timestamp())::float8 AS db_now
                FROM ops.set_runs r, app.sets s, ops.submissions u, app.archive_collections c WHERE ''' + PRIVATE_GUARD + '''
                AND u.cancel_requested_at IS NULL AND u.create_playlist=false
                AND r.requested_by=u.requested_by AND c.id=r.collection_id
                FOR UPDATE OF r,u''', (self.run_id,))
            row = cur.fetchone()
            if not row:
                raise RuntimeError('private_resume_scope_required')
            descriptor = row['source_metadata'].get('yoon_fixed_input')
            validate_descriptor(descriptor)
            source = reviewed_source(descriptor)
            self.source = source
            state = dict(row['source_metadata'].get('yoon_resume') or {})
            if descriptor.get('recognition_mode') != 'resumable' or state.get('version') != 1:
                raise RuntimeError('private_resume_required')
            if source != JACKSON and (state.get('initialization_mode') != 'fresh'
                    or state.get('origin') or state.get('provenance_seeded')):
                raise RuntimeError('private_fresh_source_required')
            if source != JACKSON or 'source_id' in state:
                if (state.get('source_id') != source.id
                        or state.get('source_pins') != source.pins()):
                    raise RuntimeError('private_resume_source_changed')
            cur.execute('''SELECT user_id,role FROM app.archive_collection_members
                WHERE collection_id=%s ORDER BY user_id''', (row['collection_id'],))
            members = [{'user_id': str(r['user_id']), 'role': r['role']} for r in cur.fetchall()]
            if len(members) != 2 or members != state.get('members'):
                raise RuntimeError('private_resume_audience_changed')
            if owner and (row['status'] != 'private_resume_running' or
                          any(state.get(k) != v for k,v in self.owner.items())):
                raise RuntimeError('private_resume_owner_changed')
            yield cur, row, state

    def save_state(self, cur, state, status='private_resume_running'):
        cur.execute('''UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,
            '{yoon_resume}',%s::jsonb),status=%s,stage='private_resume',heartbeat_at=now(),
            updated_at=now() WHERE id=%s''', (json.dumps(state), status, self.run_id))

    @retry_lock_timeouts
    def claim(self):
        from worker.jobs.yoon_once import validate_descriptor
        with self.locked(owner=False, admission=True) as (cur,row,state):
            from worker.jobs.yoon_admission import check
            generation = os.getenv('SET_LIST_DISPATCH_GENERATION') or None
            from worker.jobs.yoon_queue import consume
            check(cur, self.run_id, row["target_set_id"], generation=generation)
            consume(cur, row, state, self.owner, generation)
            cur.execute("SELECT obj_description('ops.cleanup_expired_ops_data()'::regprocedure,'pg_proc') AS marker")
            if cur.fetchone()['marker']!='private-recognition-retention-v1':
                raise RuntimeError('private_retention_migration_required')
            if row['status'] not in ('private_resume_pending','private_resume_paused'):
                raise RuntimeError('private_resume_not_released')
            identity = f"{self.owner['workflow_run_id']}:{self.owner['run_attempt']}"
            used = list(state.get('used_owners') or [])
            if identity in used:
                raise RuntimeError('private_continuation_identity_replayed')
            if state.get('review_required'):
                raise QueuePause('private_resume_review_required')
            # Upgrade only a released, certain owner. Completed responses and
            # one-off allowance receipts are immutable historical evidence.
            cur.execute("SELECT raw_data FROM ops.segment_hits WHERE set_run_id=%s", (self.run_id,))
            evidence = [(h['raw_data'].get('private_jackson_v2') or {}) for h in cur.fetchall()]
            if any(d.get('in_flight') for d in evidence):
                raise RuntimeError('uncertain_request_requires_reconciliation')
            if state.get('throttle_policy_version') not in (None, POLICY_VERSION):
                raise RuntimeError('private_throttle_policy_unknown')
            if state.get('throttle_policy_version') != POLICY_VERSION:
                state['throttle_requests'] = sum(actual_throttle(a) for d in evidence for a in d.get('attempts', []))
                effective_requests(state)
                state['throttle_policy_version'] = POLICY_VERSION
                # A known 429 exhaustion becomes retryable, never a no-match.
                cur.execute("""UPDATE ops.set_run_leases l SET status='pending',updated_at=now()
                    FROM ops.segment_hits h WHERE h.lease_id=l.id AND l.set_run_id=%s
                    AND l.status='exhausted' AND h.raw_data->'private_jackson_v2'->>'valid'='false'
                    AND h.raw_data->'private_jackson_v2'->>'in_flight'='false'
                    AND (SELECT count(*) FROM jsonb_array_elements(h.raw_data->'private_jackson_v2'->'attempts') a
                      WHERE (a->>'state'='finished' AND a->'diagnostic'->'http_status'='429'::jsonb) IS NOT TRUE) < 8""", (self.run_id,))
            reason = may_reserve(state,now=row['db_now'],session_started=row['db_now'],
                                 session_requests=0,window_attempts=0, windows=self.source.windows)
            if reason:
                raise QueuePause(reason)
            # No automatic takeover of an uncertain live workflow. Only a clean
            # previous private finalization can release this run for continuation.
            cur.execute('''SELECT count(*) AS n FROM ops.segment_hits
                WHERE set_run_id=%s AND raw_data->'private_jackson_v2'->>'in_flight'='true' ''', (self.run_id,))
            if cur.fetchone()['n']:
                raise RuntimeError('uncertain_request_requires_reconciliation')
            state.update(self.owner, continuations=state['continuations']+1,
                         session_requests=0,session_started=row['db_now'], reason=None,
                         recognition_mode='resumable', status='preparing', pacing_policy='shared-production-v2')
            state['used_owners'] = used + [identity]
            if self.source != JACKSON:
                state.update(expected_windows=self.source.windows,
                             source_duration_seconds=self.source.duration, bounds=self.source.bounds)
            fresh = self.source != JACKSON and not state.get('fresh_source_initialized')
            if fresh:
                self.require_empty_fresh_source(cur, state)
            # Reuse ordinary lease geometry/storage without destructive initializer.
            cur.execute('''INSERT INTO ops.set_run_leases
                (set_run_id,slot_index,segment_start_index,segment_end_index,status)
                SELECT %s,0,i,i,'pending' FROM generate_series(0,%s) i
                WHERE NOT EXISTS(SELECT 1 FROM ops.set_run_leases l
                  WHERE l.set_run_id=%s AND l.segment_start_index=i)''', (self.run_id,self.source.windows-1,self.run_id))
            if fresh:
                state['fresh_source_initialized'] = True
            elif self.source == JACKSON and not state.get('provenance_seeded'):
                self.seed_valid_evidence(cur,row,state)
            self.save_state(cur,state)
            return validate_descriptor(row['source_metadata']['yoon_fixed_input'])

    def require_empty_fresh_source(self, cur, state):
        # Only explicit new catalog runs may start without a legacy origin.
        if (state.get('initialization_mode') != 'fresh' or state.get('origin')
                or state.get('provenance_seeded') or state.get('expected_audio_sha256')
                or state.get('audio_sha256') or state['requests'] != 0
                or state['continuations'] != 1):
            raise RuntimeError('private_fresh_source_required')
        cur.execute('SELECT count(*) AS n FROM ops.segment_hits WHERE set_run_id=%s', (self.run_id,))
        if cur.fetchone()['n']:
            raise RuntimeError('private_fresh_requires_empty_hits')
        cur.execute('SELECT count(*) AS n FROM ops.set_run_leases WHERE set_run_id=%s', (self.run_id,))
        if cur.fetchone()['n']:
            raise RuntimeError('private_fresh_requires_empty_leases')

    def seed_valid_evidence(self, cur, row, state):
        from worker.jobs.yoon_once import validate_descriptor
        origin = state['origin']
        cur.execute('''SELECT p.source_metadata,encode(digest(p.source_metadata::text,'sha256'),'hex') AS digest
            FROM ops.set_runs p WHERE p.id=%s AND p.id<>%s
            AND p.status='private_analysis_partial' AND p.publication_visibility='private'
            AND p.target_set_id=%s AND p.collection_id=%s AND p.submission_id=%s
            AND p.requested_by=%s AND p.create_playlist=false AND p.cancel_requested_at IS NULL
            AND p.published_set_id IS NULL FOR SHARE''',
            (origin['run_id'],self.run_id,row['target_set_id'],row['collection_id'],row['submission_id'],row['requested_by']))
        parent = cur.fetchone()
        if not parent or parent['digest']!=origin['metadata_sha256']:
            raise RuntimeError('private_origin_changed')
        metadata = parent['source_metadata']
        if (validate_descriptor(metadata['yoon_fixed_input']) != validate_descriptor(row['source_metadata']['yoon_fixed_input'])
                or reviewed_source(metadata['yoon_fixed_input']) != self.source):
            raise RuntimeError('private_origin_source_changed')
        analysis = metadata.get('yoon_analysis') or {}
        if analysis.get('workflow_run_id')!=origin['workflow_run_id'] or analysis.get('status')!='partial':
            raise RuntimeError('private_origin_provenance_mismatch')
        audio_digest = analysis.get('audio_sha256','')
        if not re.fullmatch('[0-9a-f]{64}',audio_digest):
            raise RuntimeError('private_origin_audio_digest_required')
        state['expected_audio_sha256'] = audio_digest
        cur.execute('SELECT count(*) AS n FROM ops.segment_hits WHERE set_run_id=%s',(self.run_id,))
        if cur.fetchone()['n']:
            raise RuntimeError('private_seed_requires_empty_hits')
        attempts = analysis.get('recognition_diagnostics',{}).get('attempts',[])
        latest = {a['segment_index']:a for a in attempts}
        seen = set()
        for response in analysis.get('raw_recognitions',[]):
            index = response.get('segment_index')
            if type(index) is not int or not 0<=index<self.source.windows or index in seen:
                raise RuntimeError('private_origin_geometry_invalid')
            seen.add(index)
            if response.get('error_type') or response.get('was_rate_limited'):
                continue
            if response.get('timestamp')!=index*15 or latest.get(index,{}).get('http_status')!=200:
                raise RuntimeError('private_origin_response_unverified')
            data = dict(valid=True,in_flight=False,attempts=[],response=response,
                        origin=dict(origin,segment_index=index))
            cur.execute('''INSERT INTO ops.segment_hits(set_run_id,lease_id,segment_index,timestamp_seconds,
                recognized,track_title,artist,shazam_track_id,raw_data)
                SELECT %s,id,%s,%s,%s,%s,%s,%s,%s::jsonb FROM ops.set_run_leases
                WHERE set_run_id=%s AND segment_start_index=%s RETURNING lease_id''',
                (self.run_id,index,index*15,bool(response['recognized']),response.get('track_title'),
                 response.get('artist'),response.get('shazam_track_id'),
                 json.dumps({'private_jackson_v2':data}),self.run_id,index))
            hit = cur.fetchone()
            if not hit:
                raise RuntimeError('private_origin_lease_missing')
            cur.execute("UPDATE ops.set_run_leases SET status='completed',completed_at=now() WHERE id=%s",(hit['lease_id'],))
        cur.execute('SELECT count(*) AS n FROM ops.segment_hits WHERE set_run_id=%s',(self.run_id,))
        if cur.fetchone()['n']!=origin['valid_windows']:
            raise RuntimeError('private_origin_coverage_changed')
        state['provenance_seeded'] = True

    @retry_lock_timeouts
    def require_owner(self):
        with self.locked() as (_,_,state):
            if state.get('review_required'):
                raise QueuePause('private_resume_review_required')
            return state

    @retry_lock_timeouts
    def write(self, payload):
        # Adapter for the unchanged fixed-source prepare/transcode implementation.
        mismatch = False
        with self.locked() as (cur,_,state):
            digest = payload.get('audio_sha256')
            if digest and not re.fullmatch('[0-9a-f]{64}', digest):
                raise RuntimeError('private_audio_digest_required')
            if digest and not state.get('expected_audio_sha256'):
                if (self.source == JACKSON or not state.get('fresh_source_initialized')
                        or state.get('initialization_mode') != 'fresh' or state.get('origin')
                        or state.get('provenance_seeded') or state.get('audio_sha256')
                        or state['requests'] != 0 or state.get('status') != 'preparing'
                        or payload.get('status') != 'prepared'):
                    raise RuntimeError('private_audio_pin_required')
                state['expected_audio_sha256'] = digest
            if digest and digest != state['expected_audio_sha256']:
                state.update(status='paused',reason='prepared_audio_changed',review_required=True)
                self.save_state(cur,state,'private_resume_paused')
                mismatch = True
            elif payload['status'] == 'failed':
                state.update(status='paused',reason='preparation_failed')
                self.save_state(cur,state,'private_resume_paused')
            else:
                state.update(payload)
                self.save_state(cur,state)
        if mismatch:
            raise RuntimeError('prepared_audio_changed')

    @retry_lock_timeouts
    def prepare_scheduler(self):
        """Persist the same scheduler geometry ordinary DJ runs use."""
        from worker.scheduler import build_scheduler_plan
        with self.locked() as (cur, _, state):
            plan = build_scheduler_plan(self.source.windows)
            state['scheduler_plan'] = plan.as_metadata()
            self.save_state(cur, state)
        return plan

    def _slot(self, state, slot_index):
        plan = state.get('scheduler_plan') or {}
        slots, size = int(plan.get('slot_count', 1)), int(plan.get('lease_size', 10))
        if type(slot_index) is not int or not 0 <= slot_index < slots or size < 1:
            raise RuntimeError('private_slot_invalid')
        return slots, size

    @retry_lock_timeouts
    def next_windows(self, slot_index=0, limit=10):
        with self.locked() as (cur,row,state):
            slots, size = self._slot(state, slot_index)
            # Selection only needs the inherited due time, not provider history.
            # Preserve nonobjects and absent keys so malformed/falsey values keep
            # their existing Python behavior; JSON null is not a missing key.
            cur.execute('''SELECT l.id,l.segment_start_index AS segment_index,
                CASE WHEN jsonb_typeof(h.raw_data)='object' THEN
                  CASE WHEN h.raw_data ? 'private_jackson_v2' THEN
                    jsonb_build_object('private_jackson_v2',
                      CASE WHEN jsonb_typeof(h.raw_data->'private_jackson_v2')='object' THEN
                        CASE WHEN (h.raw_data->'private_jackson_v2') ? 'next_allowed_at' THEN
                          jsonb_build_object('next_allowed_at',h.raw_data#>'{private_jackson_v2,next_allowed_at}')
                        ELSE '{}'::jsonb END
                      ELSE h.raw_data->'private_jackson_v2' END)
                  ELSE '{}'::jsonb END
                ELSE h.raw_data END AS raw_data
                FROM ops.set_run_leases l LEFT JOIN ops.segment_hits h
                ON h.set_run_id=l.set_run_id AND h.segment_index=l.segment_start_index
                WHERE l.set_run_id=%s AND l.status='pending'
                AND mod(l.segment_start_index / %s, %s)=%s
                AND coalesce(h.raw_data->'private_jackson_v2'->>'valid','false')<>'true'
                ORDER BY l.segment_start_index LIMIT %s FOR UPDATE OF l SKIP LOCKED''',
                (self.run_id,size,slots,slot_index,max(1,min(int(limit),self.source.windows))))
            candidates = [dict(r) for r in cur.fetchall()]
            due = max([state.get('next_allowed_at',0)] + [
                ((r.get('raw_data') or {}).get('private_jackson_v2') or {}).get('next_allowed_at',0)
                for r in candidates])
            return candidates, max(0, due-row['db_now'])

    def next_window(self):
        rows,wait = self.next_windows(limit=1)
        return (rows[0] if rows else None),wait

    @retry_lock_timeouts
    def reserve(self, index, slot_index=0):
        with self.locked() as (cur,row,state):
            slots, size = self._slot(state, slot_index)
            if state.get('review_required'):
                raise QueuePause('private_resume_review_required')
            if type(index) is not int or not 0 <= index < self.source.windows or (index // size) % slots != slot_index:
                raise RuntimeError('private_window_slot_mismatch')
            cur.execute('''SELECT l.id,l.status,h.raw_data FROM ops.set_run_leases l
                LEFT JOIN ops.segment_hits h ON h.set_run_id=l.set_run_id
                  AND h.segment_index=l.segment_start_index
                WHERE l.set_run_id=%s AND l.segment_start_index=%s FOR UPDATE OF l''', (self.run_id,index))
            lease = cur.fetchone()
            data = dict((lease.get('raw_data') or {}).get('private_jackson_v2') or {}) if lease else {}
            attempts = list(data.get('attempts') or [])
            if lease and lease['status'] == 'exhausted' and verified_window_exhaustion(data, index):
                # finish() already closed this window at its effective cap.
                # Propagate intentional deferral through the common transport;
                # do not reopen the lease, append evidence or grant a request.
                raise QueuePause('window_attempt_budget')
            if not lease or lease['status'] != 'pending' or data.get('valid') or data.get('in_flight'):
                raise RuntimeError('private_window_not_available')
            reason = may_reserve(state,now=row['db_now'],session_started=state['session_started'],
                                 session_requests=state['session_requests'],window_attempts=non_throttle_attempts(attempts),
                                 next_allowed_at=data.get('next_allowed_at',0),windows=self.source.windows,
                                 window_attempt_limit=8)
            if reason:
                raise QueuePause(reason)
            state['requests'] += 1
            state['session_requests'] += 1
            ticket = str(uuid.uuid4())
            record = dict(self.owner,number=state['requests'],started_at=row['db_now'],state='in_flight',
                          slot_index=slot_index,ticket=ticket)
            attempts.append(record)
            data.update(valid=False,in_flight=True,attempts=attempts)
            cur.execute('''INSERT INTO ops.segment_hits(set_run_id,lease_id,segment_index,timestamp_seconds,recognized,raw_data)
                VALUES(%s,%s,%s,%s,false,%s::jsonb) ON CONFLICT(set_run_id,segment_index)
                DO UPDATE SET raw_data=excluded.raw_data''',
                (self.run_id,lease['id'],index,index*15,json.dumps({'private_jackson_v2':data})))
            cur.execute("UPDATE ops.set_run_leases SET status='claimed',claimed_by=%s,claimed_at=now(),updated_at=now() WHERE id=%s",
                        (self.owner['workflow_run_id'],lease['id']))
            self.save_state(cur,state)
            return ticket

    @retry_lock_timeouts
    def finish(self, result, ticket, delay_seconds=0):
        """Persist the common engine's attempt and due time; never choose pacing."""
        with self.locked() as (cur,row,state):
            cur.execute('''SELECT h.*,l.status AS lease_status,l.claimed_by FROM ops.segment_hits h
                JOIN ops.set_run_leases l ON l.id=h.lease_id
                WHERE h.set_run_id=%s AND h.segment_index=%s FOR UPDATE OF h,l''', (self.run_id,result.segment_index))
            hit = cur.fetchone()
            data = dict((hit or {}).get('raw_data',{}).get('private_jackson_v2') or {})
            attempts = list(data.get('attempts') or [])
            if (not hit or hit['lease_status'] != 'claimed' or not data.get('in_flight')
                or not attempts or any(attempts[-1].get(k)!=v for k,v in self.owner.items())
                or attempts[-1].get('ticket') != ticket):
                raise RuntimeError('private_attempt_owner_changed')
            valid = result.is_valid and result.http_status == 200
            diagnostic = dict(http_status=result.http_status,retry_after_seconds=result.retry_after_seconds,
                retry_after_format=result.retry_after_format,
                outcome=('recognized' if result.recognized else 'no_match') if valid else result.error_type,
                delay_seconds=delay_seconds)
            attempts[-1].update(state='finished',finished_at=row['db_now'],diagnostic=diagnostic)
            if result.http_status == 429:
                state['throttle_requests'] = state.get('throttle_requests', 0) + 1
                delay_seconds = max(delay_seconds, throttle_delay(throttle_streak(attempts), result.retry_after_seconds))
                state['next_allowed_at'] = max(state.get('next_allowed_at', 0), row['db_now']+delay_seconds)
            delay_seconds = max(0, delay_seconds, result.retry_after_seconds or 0)
            data.update(valid=valid,in_flight=False,attempts=attempts,
                        next_allowed_at=row['db_now']+delay_seconds)
            response = asdict(result)
            response['error_details'] = None
            data['response'] = response
            reason = 'retry_after_needs_review' if result.retry_after_format == 'invalid' else None
            exhausted = not valid and non_throttle_attempts(attempts)>=8
            cur.execute('''UPDATE ops.segment_hits SET recognized=%s,track_title=%s,artist=%s,
                shazam_track_id=%s,raw_data=%s::jsonb WHERE id=%s''',
                (bool(valid and result.recognized),result.track_title if valid else None,
                 result.artist if valid else None,result.shazam_track_id if valid else None,
                 json.dumps({'private_jackson_v2':data}),hit['id']))
            cur.execute('''UPDATE ops.set_run_leases SET status=%s,claimed_by=null,
                claimed_at=null,completed_at=CASE WHEN %s THEN now() ELSE null END,updated_at=now()
                WHERE id=%s''', ('completed' if valid else 'exhausted' if exhausted else 'pending',valid,hit['lease_id']))
            state.update(status='recognizing',reason=reason)
            if reason:
                state['review_required'] = True
            self.save_state(cur,state)
            return RetryDirective(delay_seconds)

    @retry_lock_timeouts
    def release(self, reason):
        with self.locked() as (cur,row,state):
            if self.coverage_ready(cur):
                self.complete_locked(cur,state)
                return
            # A killed/uncertain request is preserved for explicit reconciliation.
            cur.execute('''SELECT count(*) AS n FROM ops.segment_hits WHERE set_run_id=%s
                AND raw_data->'private_jackson_v2'->>'in_flight'='true' ''', (self.run_id,))
            uncertain = bool(cur.fetchone()['n'])
            if uncertain:
                reason = 'uncertain_request_requires_reconciliation'
            else:
                cur.execute('''SELECT count(*) FILTER (WHERE status='exhausted') AS exhausted,
                    coalesce(max((h.raw_data->'private_jackson_v2'->>'next_allowed_at')::float8),0) AS due
                    FROM ops.set_run_leases l LEFT JOIN ops.segment_hits h ON h.lease_id=l.id
                    WHERE l.set_run_id=%s AND l.status<>'completed' ''',(self.run_id,))
                pending = cur.fetchone()
                if pending['exhausted']:
                    reason = 'window_attempt_budget'
                else:
                    # Describe the actual retained budget/cooldown instead of
                    # labelling every clean bounded pause as an interrupted job.
                    now = row['db_now']
                    reason = may_reserve(state,now=now,session_started=state['session_started'],
                        session_requests=state['session_requests'],window_attempts=0,
                        next_allowed_at=pending['due'],windows=self.source.windows) or reason
                    if reason == 'cooldown':
                        reason = 'cooldown_pending'
            state.update(status='paused',reason=reason,review_required=bool(state.get('review_required') or uncertain))
            self.save_state(cur,state,'private_resume_paused')

    def coverage_ready(self,cur):
        cur.execute('''SELECT count(*) AS n FROM ops.segment_hits WHERE set_run_id=%s
            AND raw_data->'private_jackson_v2'->>'valid'='true'
            AND raw_data->'private_jackson_v2'->>'in_flight'='false' ''',(self.run_id,))
        return cur.fetchone()['n']==self.source.windows

    @retry_lock_timeouts
    def finalize_ready(self):
        # A clean paused run with every durable response can finish even when all
        # provider budgets are exhausted. No ownership takeover or provider call.
        # Quiescent finalization can change queue/version state; use the common
        # global-before-row order. Active per-window transactions stay unchanged.
        with self.locked(owner=False, admission=True) as (cur,row,state):
            # A queue-owned worker must recheck explicit review/pause fences
            # after dispatch, including its complete-coverage fast path. Legacy
            # nonqueued finalization retains its existing behavior.
            from worker.jobs.yoon_queue import completion_block_reason, assert_completion_certain, validate_identity, KEY, SAFE_PAUSES
            if KEY in row['source_metadata']:
                queue = row['source_metadata'][KEY]
                validate_identity(row, state, queue)
                reason = completion_block_reason(row, state)
                if reason or queue.get('status') == 'blocked':
                    raise RuntimeError(reason or 'private_queue_requires_review')
                if row['status'] == 'private_resume_complete' and queue.get('status') != 'complete':
                    raise RuntimeError('private_queue_completion_changed')
                assert_completion_certain(cur, self.run_id, state)
            if row['status']=='private_resume_complete':
                return True
            if row['status'] not in ('private_resume_paused','private_resume_pending'):
                return False
            if not self.coverage_ready(cur):
                if (KEY in row['source_metadata'] and row['status'] == 'private_resume_paused'
                        and state.get('reason') not in SAFE_PAUSES):
                    raise RuntimeError('pause_requires_review')
                return False
            from worker.jobs.yoon_queue import consume, KEY, save
            queue = row['source_metadata'].get(KEY)
            if queue is not None:
                consume(cur, row, state, self.owner, os.getenv('SET_LIST_DISPATCH_GENERATION'))
                save(cur, self.run_id, {**queue, 'status': 'complete', 'owner': self.owner})
            self.complete_locked(cur,state)
            return True

    @retry_lock_timeouts
    def summary(self):
        with self.locked() as (cur,_,state):
            cur.execute('''SELECT count(*) FILTER(WHERE status='completed') AS valid,
                count(*) FILTER(WHERE status='exhausted') AS exhausted,
                count(*) FILTER(WHERE status='claimed') AS claimed,
                count(*) AS total FROM ops.set_run_leases WHERE set_run_id=%s''', (self.run_id,))
            return dict(cur.fetchone()),state

    @retry_lock_timeouts
    def complete(self):
        with self.locked() as (cur,_,state):
            self.complete_locked(cur,state)

    def complete_locked(self,cur,state):
        from worker.pipeline.models import Recognition
        from worker.pipeline.aggregate import build_tracks_from_recognitions
        cur.execute('''SELECT segment_index,raw_data FROM ops.segment_hits
            WHERE set_run_id=%s ORDER BY segment_index''', (self.run_id,))
        hits = cur.fetchall()
        if len(hits)!=self.source.windows or [r['segment_index'] for r in hits]!=list(range(self.source.windows)):
            raise RuntimeError('private_resume_incomplete')
        data = [r['raw_data']['private_jackson_v2'] for r in hits]
        if any(not d.get('valid') or d.get('in_flight') for d in data):
            raise RuntimeError('private_resume_incomplete')
        responses = [Recognition.from_checkpoint(d['response']) for d in data]
        tracks,_ = build_tracks_from_recognitions(responses)
        state.update(status='complete',reason=None,valid_responses=self.source.windows,
                     clustered_setlist=[asdict(t) for t in tracks])
        self.save_state(cur,state,'private_resume_complete')

    @retry_lock_timeouts
    def clock_state(self):
        with self.locked() as (_,row,state):
            return row['db_now'],state
