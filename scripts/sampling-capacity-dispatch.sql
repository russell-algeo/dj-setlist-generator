-- EXPLICIT OPT-IN ONLY: install after sampling-study-schema.sql and reviewed
-- caller ledger SELECT grants, before enabling coordinated v4 workers/studies.
-- Not an automatic application migration. No grant or study activation here.
BEGIN;
CREATE OR REPLACE FUNCTION "ops"."claim_next_dispatchable_set_run"("max_active" integer DEFAULT 10)
RETURNS SETOF "ops"."set_runs"
LANGUAGE plpgsql
AS $$
DECLARE
  available_slots integer;
  capacity record;
BEGIN
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION 'sampling_capacity_requires_read_committed';
  END IF;
  -- Same key/order as cooperating Python request reservations and study activation.
  -- A study holds this key for its entire session. Do not pin a web request
  -- behind that session: lack of the mutex leaves queued work untouched.
  -- Once acquired, the VOLATILE function reads fresh committed ledger state.
  IF NOT pg_try_advisory_xact_lock(183601, 2) THEN RETURN; END IF;
  SELECT
  EXISTS(SELECT 1 FROM ops.sampling_studies_v1
         WHERE status IN ('running','uncertain')) AS active,
  EXISTS(SELECT 1 FROM ops.sampling_attempts_v1
         WHERE outcome IN ('reserved','unknown')) AS unsettled,
  EXISTS(SELECT 1 FROM ops.sampling_attempts_v1
         WHERE outcome NOT IN ('reserved','unknown') AND (
           (CASE
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
  ELSE false END) IS NOT TRUE OR
           receipt->>'retry_after_format'='invalid')) AS invalid_retry_after,
  coalesce((SELECT max(next_allowed_at) FROM ops.sampling_studies_v1),0)::float8
    AS next_allowed_at,
  extract(epoch FROM clock_timestamp())::float8 AS db_now INTO capacity;
  IF capacity.next_allowed_at IS NULL OR capacity.db_now IS NULL
    OR capacity.next_allowed_at < 0 OR capacity.next_allowed_at >= 'Infinity'::float8
    OR capacity.db_now < 0 OR capacity.db_now >= 'Infinity'::float8 THEN
    RAISE EXCEPTION 'sampling_capacity_clock_invalid';
  END IF;
  IF capacity.active IS DISTINCT FROM false OR capacity.unsettled IS DISTINCT FROM false
    OR capacity.invalid_retry_after IS DISTINCT FROM false
    OR capacity.db_now < capacity.next_allowed_at THEN RETURN; END IF;
  -- Serialize the active-count + claim decision so concurrent finalize/dispatch
  -- requests cannot overfill the global process-set window.
  PERFORM pg_advisory_xact_lock(
    hashtext('ops.set_runs'),
    hashtext('claim_next_dispatchable_set_run')
  );

  SELECT GREATEST(COALESCE(max_active, 10), 0) - count(*)::integer
  INTO available_slots
  FROM ops.set_runs
  WHERE publication_visibility = 'public' AND status IN (
    'dispatched',
    'resolving',
    'recognizing',
    'aggregating',
    'enriching',
    'publishing',
    'cancelling'
  );

  available_slots := GREATEST(COALESCE(available_slots, 0), 0);

  IF available_slots <= 0 THEN
    RETURN;
  END IF;

  RETURN QUERY
  WITH candidate AS (
    SELECT id
    FROM ops.set_runs
    WHERE publication_visibility = 'public' AND status = 'queued'
      AND cancel_requested_at IS NULL
      AND published_set_id IS NULL AND stage IS DISTINCT FROM 'publishing_committed'
      AND NOT (source_metadata ? 'sampling_capacity_deferral_v1')
      AND ops.shared_recognition_dispatchable(id, source_metadata)
    ORDER BY created_at ASC, id ASC
    LIMIT available_slots
    FOR UPDATE SKIP LOCKED
  ),
  updated AS (
    UPDATE ops.set_runs set_run
    SET status = 'dispatched',
        stage = 'dispatching',
        heartbeat_at = now(),
        updated_at = now()
    WHERE set_run.id IN (SELECT id FROM candidate)
    RETURNING set_run.*
  )
  SELECT *
  FROM updated
  ORDER BY created_at ASC, id ASC;
END;
$$;

COMMENT ON FUNCTION ops.claim_next_dispatchable_set_run(integer) IS 'shared-recognition-throttle-v3-sampling-capacity-v4';
COMMIT;
