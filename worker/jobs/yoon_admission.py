"""Fail-closed aggregate private Yoon admission; no provider behavior changes.

Acquire the transaction lock BEFORE any run/submission lock. READ COMMITTED
is required so the occupancy query sees the last lock holder's commit. Existing
running legacy owners are counted, but new legacy admissions must be stopped
at rollout because they do not take this lock. No timeout-based takeover.
"""
CAP = 2
LOCK_SQL = "SELECT pg_advisory_xact_lock(183601, 2)"
ROWS_SQL = """SELECT r.id,r.target_set_id,r.status,r.source_metadata,
 EXISTS(SELECT 1 FROM ops.segment_hits h WHERE h.set_run_id=r.id
   AND h.raw_data->'private_jackson_v2'->>'in_flight'='true') AS uncertain_hit,
 EXISTS(SELECT 1 FROM ops.set_run_leases l WHERE l.set_run_id=r.id
   AND l.status='claimed') AS claimed_lease
 FROM ops.set_runs r WHERE r.source_metadata ?| ARRAY[
 'yoon_fixed_input','yoon_resume','yoon_analysis','yoon_spotify_enrichment','yoon_spotify_recheck_v1']"""
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
    for key in ('yoon_spotify_enrichment','yoon_spotify_recheck_v1'):
        receipt = metadata.get(key)
        if receipt is not None and receipt.get('status') != 'complete':
            if receipt.get('status') != 'reserved':
                raise RuntimeError('private_admission_uncertain_enrichment')
            owners.append(receipt.get('owner'))
    if any(not valid_owner(owner) for owner in owners) or len(owners)>1:
        raise RuntimeError('private_admission_uncertain_owner')
    return bool(owners)


def check(cur, run_id, target_set_id):
    # Caller owns the global admission transaction lock and the target row lock.
    # Release never creates occupancy and therefore needs no global lock.
    cur.execute(ROWS_SQL)
    active = [row for row in cur.fetchall() if occupied(row)]
    if any(str(row['id'])==str(run_id) or str(row['target_set_id'])==str(target_set_id)
           for row in active):
        raise RuntimeError('private_admission_duplicate_target')
    if len(active) >= CAP:
        raise RuntimeError('private_admission_capacity')
