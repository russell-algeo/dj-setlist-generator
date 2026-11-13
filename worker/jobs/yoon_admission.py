"""Fail-closed aggregate private Yoon admission; no provider behavior changes.

Acquire the transaction lock BEFORE any run/submission lock. READ COMMITTED
is required so the occupancy query sees the last lock holder's commit. Existing
running legacy owners are counted, but new legacy admissions must be stopped
at rollout because they do not take this lock. No timeout-based takeover.
"""
import os
import re


def capacity():
    """Use the ordinary scheduler's configuration, never a private default.

    The runtime value must be copied from the verified effective ordinary
    scheduler setting at rollout. GitHub and Vercel do not share environments;
    absence is not evidence that Production uses its source default. Keep this
    lazy so release/cleanup can still run when configuration is unavailable.
    """
    value = os.environ.get('PROCESS_SET_MAX_ACTIVE_RUNS')
    if value is None or value == '':
        raise RuntimeError('private_admission_capacity_unconfigured')
    # Stricter than JavaScript parseInt: reject suffixes/fractions rather than
    # silently authorizing a different limit. Do not echo configuration values.
    if not re.fullmatch(r'[1-9][0-9]{0,15}', value) or int(value) > 9007199254740991:
        raise RuntimeError('private_admission_capacity_invalid')
    return int(value)

LOCK_SQL = "SELECT pg_advisory_xact_lock(183601, 2)"
def _object_fields_sql(expression, fields):
    # Retain malformed/scalar/null values exactly so existing validators still
    # fail closed. Missing versus explicit null keys are equivalent for these
    # get-only consumers; no owner identity or lifecycle rule is changed.
    pairs = ','.join("'%s',%s->'%s'" % (key, expression, key) for key in fields)
    return "CASE WHEN jsonb_typeof(%s)='object' THEN jsonb_build_object(%s) ELSE %s END" % (expression, pairs, expression)


def _admission_metadata_sql():
    groups = {
        'yoon_resume': ('review_required','in_flight','workflow_run_id','run_attempt'),
        'yoon_analysis': ('workflow_run_id','run_attempt'),
        'yoon_spotify_enrichment': ('status','owner'),
        'yoon_spotify_recheck_v1': ('status','owner'),
        'yoon_metadata_enrichment_v1': ('status','owner'),
        'yoon_queue_v1': ('version','status','generation','owner'),
    }
    pairs = ','.join("'%s',%s" % (key, _object_fields_sql("r.source_metadata->'%s'" % key, fields)) for key, fields in groups.items())
    return "CASE WHEN jsonb_typeof(r.source_metadata)='object' THEN jsonb_build_object(%s) ELSE r.source_metadata END" % pairs


ROWS_SQL = """SELECT r.id,r.target_set_id,r.status,""" + _admission_metadata_sql() + """ AS source_metadata,
 EXISTS(SELECT 1 FROM ops.segment_hits h WHERE h.set_run_id=r.id
   AND h.raw_data->'private_jackson_v2'->>'in_flight'='true') AS uncertain_hit,
 EXISTS(SELECT 1 FROM ops.set_run_leases l WHERE l.set_run_id=r.id
   AND l.status='claimed') AS claimed_lease
 FROM ops.set_runs r WHERE r.source_metadata ?| ARRAY[
 'yoon_fixed_input','yoon_resume','yoon_analysis','yoon_spotify_enrichment','yoon_spotify_recheck_v1','yoon_metadata_enrichment_v1','yoon_queue_v1']"""
IDLE = frozenset(('private_analysis_pending','private_analysis_partial',
 'private_analysis_complete','private_analysis_failed','private_resume_pending',
 'private_resume_paused','private_resume_complete','cancelled'))


def lock(cur):
    cur.execute('SHOW transaction_isolation')
    if cur.fetchone()['transaction_isolation'] != 'read committed':
        raise RuntimeError('private_admission_requires_read_committed')
    cur.execute(LOCK_SQL)


def valid_owner(value):
    return isinstance(value, dict) and all(
        isinstance(value.get(k), str) and value[k].isdecimal()
        for k in ('workflow_run_id','run_attempt'))


def occupied(row):
    metadata = row['source_metadata']
    resume = metadata.get('yoon_resume') or {}
    if resume.get('review_required') or resume.get('in_flight'):
        raise RuntimeError('private_admission_uncertain_owner')
    owners = []
    if row['status'] in ('private_resume_running','private_analysis_running'):
        owners.append(metadata.get('yoon_resume' if row['status']=='private_resume_running' else 'yoon_analysis'))
    elif row['status'] not in IDLE:
        raise RuntimeError('private_admission_unknown_state')
    elif row['uncertain_hit'] or row['claimed_lease']:
        raise RuntimeError('private_admission_uncertain_owner')
    for key in ('yoon_spotify_enrichment','yoon_spotify_recheck_v1','yoon_metadata_enrichment_v1'):
        receipt = metadata.get(key)
        if receipt is not None and receipt.get('status') != 'complete':
            if receipt.get('status') != 'reserved':
                raise RuntimeError('private_admission_uncertain_enrichment')
            owners.append(receipt.get('owner'))
    if any(not valid_owner(owner) for owner in owners) or len(owners)>1:
        raise RuntimeError('private_admission_uncertain_owner')
    queue = metadata.get('yoon_queue_v1')
    if queue is not None:
        if not isinstance(queue, dict) or queue.get('version') != 1:
            raise RuntimeError('private_admission_uncertain_queue')
        status = queue.get('status')
        if status in ('reserved', 'sending', 'dispatched'):
            if owners or queue.get('owner') is not None:
                raise RuntimeError('private_admission_uncertain_queue')
            return True
        if status == 'running':
            # A clean released owner may await queue reconciliation. Count the
            # actual work only, while preserving unknown/in-flight checks above.
            # Resume receipts contain progress and source fields as well as the
            # owner pair. Compare identity fields, not the entire receipt.
            queue_owner = queue.get('owner')
            if (not valid_owner(queue_owner) or (owners and any(
                    queue_owner[k] != owners[0][k] for k in ('workflow_run_id','run_attempt')))):
                raise RuntimeError('private_admission_uncertain_queue')
        elif status not in ('queued', 'complete', 'blocked'):
            raise RuntimeError('private_admission_uncertain_queue')
    return bool(owners)


def check(cur, run_id, target_set_id, *, generation=None):
    limit = capacity()
    # Caller owns the global admission transaction lock and the target row lock.
    # Release never creates occupancy and therefore needs no global lock.
    # The mutex helper also serves receipt/finalization paths. Only genuine
    # admission checks the study capacity; settling existing work stays possible.
    from worker.jobs.sampling_capacity import check_ledger
    check_ledger(cur)
    cur.execute('SELECT ops.assert_yoon_version_execution(%s, %s, %s)',
                (str(run_id), 'admit', generation))
    cur.execute(ROWS_SQL)
    active = []
    for row in cur.fetchall():
        busy = occupied(row)
        queue = row['source_metadata'].get('yoon_queue_v1') or {}
        if (generation and str(row['id']) == str(run_id)
                and queue.get('status') in ('reserved', 'sending', 'dispatched')
                and queue.get('generation') == generation and queue.get('owner') is None):
            continue
        if busy:
            active.append(row)
    if any(str(row['id'])==str(run_id) or str(row['target_set_id'])==str(target_set_id)
           for row in active):
        raise RuntimeError('private_admission_duplicate_target')
    if len(active) >= limit:
        raise RuntimeError('private_admission_capacity')
