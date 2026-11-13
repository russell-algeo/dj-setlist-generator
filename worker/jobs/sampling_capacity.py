"""Persistent sampling exclusion for cooperating ordinary/private workers.

The existing study ledger is the durable hold; the advisory lock only orders
admission against activation. A crashed connection never clears persisted
running/uncertain state, unknown attempts, or the provider cooldown. No TTL or
grant expiry authorizes takeover. This module cannot activate or clear a hold.

Call lock_and_check before any run/lease/hit row lock and retain that transaction
through the request reservation commit. Receipt and drain paths must not call it.
The opt-in study schema and worker read privileges must exist before deployment.
Missing tables/permissions and malformed evidence fail closed. Mixed/legacy
workers still require explicit drain and rollout proof; this is not a security
boundary against unmodified code or a live experiment activation mechanism.
"""
import math

from recognition_transport import RequestDeferred


PAUSE_REASONS = frozenset(('sampling_capacity_unsettled',
    'sampling_capacity_retry_after_review', 'sampling_capacity_cooldown'))
DEFERRAL_KEY = 'sampling_capacity_deferral_v1'
DEFERRAL_STAGE = 'sampling_capacity_deferred'
DISPATCH_MARKER = 'shared-recognition-throttle-v3-sampling-capacity-v4'


class CapacityPause(RequestDeferred):
    def __init__(self, reason, *, observed_at=None):
        super().__init__(reason)
        self.observed_at = observed_at


def valid_pause_observation(reason, observed_at):
    return (type(reason) is str and reason in PAUSE_REASONS
        and type(observed_at) in (int, float) and math.isfinite(observed_at)
        and observed_at > 0)


def valid_deferral(metadata, stage):
    if not isinstance(metadata, dict) or stage != DEFERRAL_STAGE:
        return False
    marker = metadata.get(DEFERRAL_KEY)
    if not isinstance(marker, dict) or set(marker) != {
            'version', 'workflow_run_id', 'run_attempt', 'dispatch_generation',
            'reason', 'observed_at'}:
        return False
    return (type(marker['version']) is int and marker['version'] == 1
        and all(type(marker[k]) is str and marker[k].isascii() and marker[k].isdigit()
                for k in ('workflow_run_id', 'run_attempt'))
        and type(marker['dispatch_generation']) is str
        and marker['workflow_run_id'] == metadata.get('active_workflow_run_id')
        and marker['dispatch_generation'] == metadata.get('dispatch_generation', '')
        and valid_pause_observation(marker['reason'], marker['observed_at']))


def valid_private_pause(marker, owner):
    return (isinstance(marker, dict) and set(marker) == {'version',
        'workflow_run_id', 'run_attempt', 'reason', 'observed_at'}
        and type(marker['version']) is int and marker['version'] == 1
        and all(type(marker.get(k)) is str and marker[k].isascii()
            and marker[k].isdigit() and marker[k] == owner.get(k)
            for k in ('workflow_run_id', 'run_attempt'))
        and valid_pause_observation(marker.get('reason'), marker.get('observed_at')))


def require_private_pause_integrity(state):
    if ('sampling_capacity_pause_v1' in state
            and not valid_private_pause(state['sampling_capacity_pause_v1'], state)):
        raise RuntimeError('private_capacity_pause_requires_reconciliation')


class CapacityFence(RuntimeError):
    pass


LOCK_SQL = 'SELECT pg_advisory_xact_lock(183601, 2)'

# Settled receipts must retain the same explicit format/seconds contract as the
# parent validator. SQL NULL, scalar receipts, unknown forms and falsey malformed
# values must not collapse to "no invalid header" after aggregate projection.
# Successful Recognition objects legitimately use None/None for these optional
# fields; failed responses must explicitly say absent/invalid/delta/http_date.
RETRY_CONTRACT_SQL = """CASE
  WHEN jsonb_typeof(receipt) IS DISTINCT FROM 'object' THEN false
  WHEN NOT (receipt ?& ARRAY['outcome','retry_after_format','retry_after_seconds']) THEN false
  WHEN receipt->>'outcome' IS DISTINCT FROM outcome THEN false
  WHEN receipt->'retry_after_format' = 'null'::jsonb THEN
    outcome IN ('matched','no_match') AND receipt->'retry_after_seconds' = 'null'::jsonb
  WHEN jsonb_typeof(receipt->'retry_after_format') IS DISTINCT FROM 'string' THEN false
  WHEN receipt->>'retry_after_format' IN ('absent','invalid') THEN
    receipt->'retry_after_seconds' = 'null'::jsonb
  WHEN receipt->>'retry_after_format' IN ('delta_seconds','http_date') THEN
    CASE WHEN jsonb_typeof(receipt->'retry_after_seconds') = 'number' THEN
      (receipt->>'retry_after_seconds')::float8 >= 0 AND
      (receipt->>'retry_after_seconds')::float8 < 'Infinity'::float8
    ELSE false END
  ELSE false END"""

LEDGER_SQL = """SELECT
  EXISTS(SELECT 1 FROM ops.sampling_studies_v1
         WHERE status IN ('running','uncertain')) AS active,
  EXISTS(SELECT 1 FROM ops.sampling_attempts_v1
         WHERE outcome IN ('reserved','unknown')) AS unsettled,
  EXISTS(SELECT 1 FROM ops.sampling_attempts_v1
         WHERE outcome NOT IN ('reserved','unknown') AND (
           (""" + RETRY_CONTRACT_SQL + """) IS NOT TRUE OR
           receipt->>'retry_after_format'='invalid')) AS invalid_retry_after,
  coalesce((SELECT max(next_allowed_at) FROM ops.sampling_studies_v1),0)::float8
    AS next_allowed_at,
  extract(epoch FROM clock_timestamp())::float8 AS db_now"""

# Finished/cancelled/paused status must not hide an unknown ordinary request.
# All three durable uncertainty locations are considered before study activation.
# Malformed non-object metadata and malformed hold flags are conservative holds.
# Only reviewed non-active ordinary lease states count as idle. Private-only or
# future lease states on a public run require reconciliation, not an idle guess.
ORDINARY_DEMAND_SQL = """SELECT EXISTS(
  SELECT 1 FROM ops.set_runs r WHERE publication_visibility='public' AND (
    status IS NULL OR status NOT IN ('queued','completed','failed','cancelled')
    OR jsonb_typeof(source_metadata) IS DISTINCT FROM 'object'
    OR (source_metadata ? 'shared_recognition' AND (
      jsonb_typeof(source_metadata->'shared_recognition') IS DISTINCT FROM 'object'
      OR (source_metadata->'shared_recognition' ? 'in_flight' AND
          source_metadata->'shared_recognition'->'in_flight' IS DISTINCT FROM 'false'::jsonb)
      OR (source_metadata->'shared_recognition' ? 'review_required' AND
          source_metadata->'shared_recognition'->'review_required' IS DISTINCT FROM 'false'::jsonb)))
    OR EXISTS(SELECT 1 FROM ops.segment_hits h WHERE h.set_run_id=r.id AND
      h.raw_data ? 'shared_recognition' AND (
        jsonb_typeof(h.raw_data->'shared_recognition') IS DISTINCT FROM 'object'
        OR h.raw_data->'shared_recognition'->'in_flight' IS DISTINCT FROM 'false'::jsonb))
    OR EXISTS(SELECT 1 FROM ops.set_run_leases l WHERE l.set_run_id=r.id AND (
      l.status IS NULL OR l.status NOT IN ('pending','completed','failed')))
  )) AS busy"""


def retry_after_wait(receipt):
    """Validate without coercing malformed evidence; return the known wait."""
    form = receipt['retry_after_format']
    seconds = receipt['retry_after_seconds']
    if form is None:
        if receipt['outcome'] not in ('matched', 'no_match') or seconds is not None:
            raise ValueError('sampling_retry_after_contract')
        return 0
    if type(form) is not str or form not in ('absent', 'invalid', 'delta_seconds', 'http_date'):
        raise ValueError('sampling_retry_after_contract')
    if form in ('absent', 'invalid'):
        if seconds is not None:
            raise ValueError('sampling_retry_after_contract')
        return 0
    try:
        finite = type(seconds) in (int, float) and math.isfinite(seconds)
    except OverflowError:
        finite = False
    if not finite or seconds < 0:
        raise ValueError('sampling_retry_after_contract')
    return seconds


def settled_retry_needs_review(receipt, outcome):
    if not isinstance(receipt, dict) or receipt.get('outcome') != outcome:
        return True
    try:
        retry_after_wait(receipt)
    except (KeyError, ValueError):
        return True
    return receipt['retry_after_format'] == 'invalid'


def check_ledger(cur):
    """Read-only hold observation. An open result only authorizes under a lock."""
    cur.execute(LEDGER_SQL)
    row = cur.fetchone()
    flags = ('active', 'unsettled', 'invalid_retry_after')
    if not isinstance(row, dict) or any(type(row.get(k)) is not bool for k in flags):
        raise CapacityFence('sampling_capacity_evidence_invalid')
    for key in ('next_allowed_at', 'db_now'):
        value = row.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise CapacityFence('sampling_capacity_clock_invalid')
    if row['active'] or row['unsettled']:
        raise CapacityPause('sampling_capacity_unsettled', observed_at=row['db_now'])
    if row['invalid_retry_after']:
        raise CapacityPause('sampling_capacity_retry_after_review', observed_at=row['db_now'])
    if row['db_now'] < row['next_allowed_at']:
        raise CapacityPause('sampling_capacity_cooldown', observed_at=row['db_now'])


def lock_capacity(cur):
    """Take the shared admission mutex before any run/submission row lock."""
    cur.execute('SHOW transaction_isolation')
    row = cur.fetchone()
    if not isinstance(row, dict) or row.get('transaction_isolation') != 'read committed':
        raise CapacityFence('sampling_capacity_requires_read_committed')
    cur.execute(LOCK_SQL)


def lock_and_check(cur):
    """Serialize admission and observe committed durable state after lock wait."""
    # A known durable hold must not wait behind the study's long session lock.
    # An unlocked open result NEVER authorizes work: recheck after acquisition.
    check_ledger(cur)
    lock_capacity(cur)
    check_ledger(cur)
