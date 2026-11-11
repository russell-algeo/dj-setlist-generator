"""Opt-in private recognition queue. No public dispatch, imports or provider calls.

Enqueue a reviewed manifest once; a singleton Preview controller claims bounded
reservations using the same admission lock as recognition and metadata workers.
A reservation never expires: uncertain sends/owners require reconciliation.
"""
from __future__ import annotations
from contextlib import redirect_stdout, redirect_stderr
import json
import math
import os
import time
import uuid

from worker.jobs import yoon_admission as admission
from worker.jobs.yoon_resume_store import ResumeStore
from worker.jobs.yoon_resume_policy import may_reserve
from worker.jobs.yoon_sources import reviewed_source

KEY = 'yoon_queue_v1'
RESERVED = frozenset(('reserved', 'sending', 'dispatched'))
SAFE_PAUSES = frozenset(('workflow_time_budget', 'cooldown_pending'))
COMPLETION_PAUSES = SAFE_PAUSES | {'lifetime_time_budget', 'lifetime_request_budget',
                                  'continuation_budget', 'window_attempt_budget'}


def identity(row, state):
    return {**{k: str(row[k]) for k in ('id', 'submission_id', 'target_set_id', 'collection_id', 'requested_by')},
            'descriptor': row['source_metadata']['yoon_fixed_input'], 'members': state['members']}


def validate_identity(row, state, queue):
    if (not isinstance(queue, dict) or type(queue.get('version')) is not int
            or queue.get('version') != 1 or not isinstance(state, dict)
            or queue.get('identity') != identity(row, state)):
        raise RuntimeError('private_queue_identity_changed')


def completion_block_reason(row, state):
    # Shared by the controller and the worker's queued fast-finalizer. Coverage
    # and provider budgets never override an explicit operator review boundary.
    if state.get('review_required') is not None and state.get('review_required') is not False:
        return 'recognition_requires_review'
    if state.get('in_flight') is not None and state.get('in_flight') is not False:
        return 'private_queue_completion_uncertain'
    if row['status'] == 'private_resume_paused' and state.get('reason') not in COMPLETION_PAUSES:
        return 'pause_requires_review'
    if row['status'] == 'private_resume_complete' and (state.get('status') != 'complete' or state.get('reason') is not None):
        return 'private_queue_completion_changed'
    return None


def assert_completion_certain(cur, run_id, state):
    # Only local uncertainty matters for completion: a safe finished run must
    # not be blocked by an unrelated run's provider reservation.
    if state.get('in_flight') is not None and state.get('in_flight') is not False:
        raise RuntimeError('private_queue_completion_uncertain')
    cur.execute("""SELECT
        (SELECT count(*) FROM ops.set_run_leases WHERE set_run_id=%s AND status='claimed') +
        (SELECT count(*) FROM ops.segment_hits WHERE set_run_id=%s
          AND raw_data->'private_jackson_v2'->>'in_flight'='true') AS n""", (run_id, run_id))
    if cur.fetchone()['n']:
        raise RuntimeError('private_queue_completion_uncertain')


def requires_review(row):
    """Read-only validation of every opt-in record, including excluded statuses.

    A malformed/unfinished record must never disappear from the controller's
    completion decision. Do not mutate evidence while diagnosing these records.
    """
    try:
        metadata = row['source_metadata']
        queue, state = metadata[KEY], metadata['yoon_resume']
        validate_identity(row, state, queue)
        reviewed_source(metadata['yoon_fixed_input'])
        if type(state.get('version')) is not int or state['version'] != 1:
            return True
        if completion_block_reason(row, state):
            return True
        if (row.get('claimed_lease') or row.get('uncertain_hit')) and row['status'] != 'private_resume_running':
            return True
        status = queue.get('status')
        if status == 'complete':
            return row['status'] != 'private_resume_complete' or state.get('status') != 'complete'
        if status in RESERVED or status == 'running':
            generation = queue.get('generation')
            if not isinstance(generation, str) or str(uuid.UUID(generation)) != generation:
                return True
        if status in RESERVED:
            return (row['status'] not in ('private_resume_pending', 'private_resume_paused')
                    or queue.get('owner') is not None
                    or (row['status'] == 'private_resume_paused' and state.get('reason') not in SAFE_PAUSES)
                    or queue.get('reason') == 'dispatch_requires_reconciliation')
        if status == 'running':
            owner = queue.get('owner')
            return (not admission.valid_owner(owner)
                    or any(state.get(k) != v for k, v in owner.items())
                    or row['status'] not in ('private_resume_running', 'private_resume_paused', 'private_resume_complete'))
        if status == 'queued':
            return row['status'] not in ('private_resume_pending', 'private_resume_paused')
        return True  # Includes explicit blocked, null, missing and unknown status.
    except (AttributeError, KeyError, TypeError, ValueError, RuntimeError):
        return True


def save(cur, run_id, queue):
    cur.execute("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_queue_v1}',%s::jsonb),updated_at=now() WHERE id=%s",
                (json.dumps(queue), run_id))


def consume(cur, row, state, owner, generation):
    """Called in the admission transaction. A manually dispatched workflow cannot
    steal a queued run; a replayed generation cannot create a second owner."""
    queue = row['source_metadata'].get(KEY)
    if queue is None:
        if generation:
            raise RuntimeError('private_queue_reservation_required')
        return
    validate_identity(row, state, queue)
    if (not generation or queue.get('generation') != generation or queue.get('status') not in RESERVED
            or queue.get('owner') is not None):
        raise RuntimeError('private_queue_reservation_changed')
    queue = {**queue, 'status': 'running', 'owner': owner}
    save(cur, str(row['id']), queue)


class PrivateQueue:
    def __init__(self, connect=None):
        from worker.db import connect as default_connect
        self.connect = connect or default_connect

    def store(self, run_id):
        # Synthetic owner is never admitted; only used for scoped locked reads.
        return ResumeStore(run_id, '0', '1', connect=self.connect)

    def enqueue(self, manifests):
        """Each manifest is the full reviewed identity() snapshot. Atomic per run,
        idempotent across repeats. Existing active legacy owners stay untouched."""
        result = {'queued': 0, 'existing': 0, 'complete': 0, 'active_legacy': 0}
        manifests = list(manifests)
        seen, targets = set(), set()
        for expected in manifests:
            run_id, target = str(uuid.UUID(expected['id'])), str(uuid.UUID(expected['target_set_id']))
            if run_id in seen or target in targets:
                raise RuntimeError('private_queue_duplicate_manifest')
            seen.add(run_id)
            targets.add(target)
        for expected in manifests:
            run_id = str(uuid.UUID(expected['id']))
            with self.store(run_id).locked(owner=False, admission=True) as (cur, row, state):
                if expected != identity(row, state):
                    raise RuntimeError('private_queue_manifest_changed')
                queue = row['source_metadata'].get(KEY)
                if queue is not None:
                    validate_identity(row, state, queue)
                    result['existing'] += 1
                    continue
                cur.execute('SELECT ops.assert_yoon_version_execution(%s, %s, %s)',
                            (run_id, 'enqueue', None))
                cur.execute('''SELECT id FROM ops.set_runs WHERE target_set_id=%s AND id<>%s
                    AND source_metadata ? 'yoon_queue_v1' LIMIT 1''', (row['target_set_id'], run_id))
                if cur.fetchone():
                    raise RuntimeError('private_queue_duplicate_target')
                if row['status'] == 'private_resume_running':
                    result['active_legacy'] += 1
                    continue
                if row['status'] not in ('private_resume_pending', 'private_resume_paused', 'private_resume_complete'):
                    raise RuntimeError('private_queue_status_not_eligible')
                complete = row['status'] == 'private_resume_complete'
                queue = dict(version=1, identity=expected, status='complete' if complete else 'queued',
                             enqueued_at=row['db_now'], dispatch_count=0)
                save(cur, run_id, queue)
                result['complete' if complete else 'queued'] += 1
        return result

    def ids(self, *, rollover=False):
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT id FROM ops.set_runs WHERE publication_visibility='private' AND cancel_requested_at IS NULL
                AND source_metadata ? 'yoon_queue_v1'
                AND source_metadata->'yoon_queue_v1'->>'status' IN ('queued','reserved','sending','dispatched','running')
                ORDER BY coalesce((source_metadata->'yoon_queue_v1'->>'last_dispatched_at')::float8,0),created_at,id""")
            ids = [str(row['id']) for row in cur.fetchall()]
            if rollover:
                cur.execute("SELECT id FROM ops.set_runs WHERE id=ANY(%s::uuid[]) AND source_metadata->'yoon_queue_v1'->>'status' IN ('queued','running') ORDER BY id", (ids,))
                return [str(row['id']) for row in cur.fetchall()]
            return ids

    def refresh_and_reserve(self, run_id):
        store = self.store(run_id)
        with store.locked(owner=False, admission=True) as (cur, row, state):
            queue = dict(row['source_metadata'].get(KEY) or {})
            validate_identity(row, state, queue)
            status = queue['status']
            block_reason = completion_block_reason(row, state)
            if block_reason:
                save(cur, run_id, {**queue, 'status': 'blocked', 'reason': block_reason})
                return None
            if status == 'running':
                if any(state.get(k) != v for k, v in queue['owner'].items()):
                    raise RuntimeError('private_queue_owner_changed')
                if row['status'] == 'private_resume_complete':
                    if state.get('status') != 'complete':
                        raise RuntimeError('private_queue_completion_changed')
                    save(cur, run_id, {**queue, 'status': 'complete'})
                    return None
                if row['status'] == 'private_resume_running':
                    return None
                if row['status'] != 'private_resume_paused':
                    save(cur, run_id, {**queue, 'status': 'blocked', 'reason': 'pause_requires_review'})
                    return None
                queue.update(status='queued', owner=None)
            elif status != 'queued':
                # No timeout-based dispatch retry or owner takeover.
                return None
            if row['status'] not in ('private_resume_pending', 'private_resume_paused'):
                raise RuntimeError('private_queue_status_changed')
            # Complete durable coverage needs no provider budget or new owner.
            # Validate every window through the existing private finalizer first.
            if store.coverage_ready(cur):
                assert_completion_certain(cur, run_id, state)
                with open(os.devnull, 'w') as quiet, redirect_stdout(quiet), redirect_stderr(quiet):
                    store.complete_locked(cur, state)
                save(cur, run_id, {**queue, 'status': 'complete'})
                return None
            if row['status'] == 'private_resume_paused' and state.get('reason') not in SAFE_PAUSES:
                save(cur, run_id, {**queue, 'status': 'blocked', 'reason': 'pause_requires_review'})
                return None
            cur.execute("""SELECT coalesce(max((raw_data->'private_jackson_v2'->>'next_allowed_at')::float8),0) AS due
                FROM ops.segment_hits WHERE set_run_id=%s
                AND raw_data->'private_jackson_v2'->>'valid' IS DISTINCT FROM 'true'""", (run_id,))
            due = max(state.get('next_allowed_at', 0), cur.fetchone()['due'])
            if type(due) not in (int, float) or not math.isfinite(due) or due < 0:
                raise RuntimeError('private_queue_due_invalid')
            source = reviewed_source(row['source_metadata']['yoon_fixed_input'])
            reason = may_reserve(state, now=row['db_now'], session_started=row['db_now'],
                                 session_requests=0, window_attempts=0, windows=source.windows, next_allowed_at=due)
            if reason:
                save(cur, run_id, {**queue, 'status': 'queued' if reason == 'cooldown' else 'blocked', 'reason': reason, 'due_at': due})
                return None
            # Do not release old reservation in a separate transaction. Occupancy
            # and capacity are checked before the new generation is committed.
            admission.check(cur, run_id, row['target_set_id'])
            generation = str(uuid.uuid4())
            queue.update(status='reserved', generation=generation, owner=None, reason=None,
                         last_dispatched_at=row['db_now'], dispatch_count=queue['dispatch_count'] + 1)
            save(cur, run_id, queue)
            return {'setRunId': run_id, 'generation': generation}

    def uncertain(self, reservation):
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_queue_v1,reason}','"dispatch_requires_reconciliation"'::jsonb)
                WHERE id=%s AND source_metadata->'yoon_queue_v1'->>'generation'=%s
                AND source_metadata->'yoon_queue_v1'->>'status' IN ('reserved','sending','dispatched')""",
                (reservation['setRunId'], reservation['generation']))

    def blocked_ids(self):
        # Do not filter by status: malformed, null or falsely complete entries
        # are blockers, not an empty queue. No mutations or external calls here.
        with self.connect() as conn, conn.cursor() as cur:
            # Project only fields used by requires_review. Preserve additional
            # queue owner keys in the state for the existing identity comparison.
            cur.execute("""SELECT r.id,r.submission_id,r.target_set_id,r.collection_id,r.requested_by,r.status,
                CASE WHEN jsonb_typeof(r.source_metadata)='object' THEN jsonb_build_object(
                    'yoon_fixed_input',r.source_metadata->'yoon_fixed_input',
                    'yoon_resume',CASE WHEN jsonb_typeof(r.source_metadata->'yoon_resume')='object' THEN
                      (SELECT coalesce(jsonb_object_agg(k,v),'{}'::jsonb)
                       FROM jsonb_each(CASE WHEN jsonb_typeof(r.source_metadata->'yoon_resume')='object'
                         THEN r.source_metadata->'yoon_resume' ELSE '{}'::jsonb END) AS e(k,v)
                       WHERE k IN ('version','members','review_required','in_flight','reason','status','workflow_run_id','run_attempt')
                         OR CASE WHEN jsonb_typeof(r.source_metadata#>'{yoon_queue_v1,owner}')='object'
                           THEN (r.source_metadata#>'{yoon_queue_v1,owner}') ? k ELSE false END)
                      ELSE r.source_metadata->'yoon_resume' END,
                    'yoon_queue_v1',CASE WHEN jsonb_typeof(r.source_metadata->'yoon_queue_v1')='object' THEN
                      (SELECT coalesce(jsonb_object_agg(k,v),'{}'::jsonb)
                       FROM jsonb_each(CASE WHEN jsonb_typeof(r.source_metadata->'yoon_queue_v1')='object'
                         THEN r.source_metadata->'yoon_queue_v1' ELSE '{}'::jsonb END) AS e(k,v)
                       WHERE k IN ('version','identity','status','generation','owner','reason'))
                      ELSE r.source_metadata->'yoon_queue_v1' END)
                  ELSE r.source_metadata END AS source_metadata,
                EXISTS(SELECT 1 FROM ops.set_run_leases l WHERE l.set_run_id=r.id
                    AND l.status='claimed') AS claimed_lease,
                EXISTS(SELECT 1 FROM ops.segment_hits h WHERE h.set_run_id=r.id
                    AND h.raw_data->'private_jackson_v2'->>'in_flight'='true') AS uncertain_hit
                FROM ops.set_runs r WHERE r.publication_visibility='private'
                AND r.source_metadata ? 'yoon_queue_v1'""")
            return {str(row['id']) for row in cur.fetchall() if requires_review(row)}

    def tick(self, send):
        counts = {'pending': 0, 'reserved': 0, 'blocked': 0}
        blocked_ids = self.blocked_ids()
        if blocked_ids:
            return {**counts, 'pending': len(self.ids()), 'blocked': len(blocked_ids)}
        ids = self.ids()
        counts['pending'] = len(ids)
        for run_id in ids:
            try:
                reservation = self.refresh_and_reserve(run_id)
            except RuntimeError as exc:
                if str(exc) == 'private_admission_capacity':
                    continue
                # Keep protected evidence unchanged. One uncertain run also makes
                # aggregate admission fail closed rather than creating capacity.
                blocked_ids.add(run_id)
                break
            if reservation:
                counts['reserved'] += 1
                try:
                    send(reservation)
                except Exception:
                    # Could have reached GitHub. Never unreserve or repeat send.
                    self.uncertain(reservation)
                    blocked_ids.add(run_id)
                    break
            # refresh may persist an intentional review/budget block and return
            # no reservation. Stop this tick before touching the next run.
            blocked_ids.update(self.blocked_ids())
            if blocked_ids:
                break
        blocked_ids.update(self.blocked_ids())
        counts['blocked'] = len(blocked_ids)
        return counts


def main():
    # No source descriptors, callback errors, response bodies or exception text.
    if (os.getenv('GITHUB_ACTIONS') != 'true' or os.getenv('RUNNER_OS') != 'Linux'
            or os.getenv('GITHUB_REPOSITORY') != 'russell-algeo/dj-setlist-generator'
            or os.getenv('GITHUB_REF') != 'refs/heads/preview'
            or os.getenv('WORKER_DEPLOYMENT_TARGET') != 'development'):
        return 2
    from worker.callbacks import callback_headers, _open, validate_callback_settings
    from worker.config import get_settings
    from urllib.request import Request
    settings = get_settings()
    validate_callback_settings(settings)
    def send(payload):
        request = Request(settings.api_base_url + '/api/internal/private-yoon-dispatch',
                          data=json.dumps(payload).encode(), method='POST',
                          headers={**callback_headers(settings), 'content-type': 'application/json'})
        with _open(request, timeout=90) as response:
            if response.status != 200:
                raise RuntimeError('private_queue_dispatch_not_confirmed')
    queue = PrivateQueue()
    started = time.monotonic()
    while time.monotonic() - started < 4 * 60 * 60:
        result = queue.tick(send)
        print(json.dumps(result), flush=True)
        if result['blocked']:
            print('Private queue blocked; operator review required.', flush=True)
            return 1
        if result['pending'] == 0:
            return 0
        time.sleep(60)
    # One fenced rollover only. An uncertain rollover requires operator review.
    ids = queue.ids(rollover=True)
    if ids:
        send({'setRunId': ids[0], 'controller': True, 'workflowRunId': os.environ['GITHUB_RUN_ID'],
              'runAttempt': os.environ['GITHUB_RUN_ATTEMPT']})
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        print('Private queue stopped; operator review required.', flush=True)
        raise SystemExit(1)
