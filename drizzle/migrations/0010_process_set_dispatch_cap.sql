-- Restore bounded dispatch so artist discovery can keep a fixed number of
-- process-set workflows in flight while queued runs wait for capacity.
DROP FUNCTION IF EXISTS "ops"."claim_next_dispatchable_set_run"();--> statement-breakpoint
DROP FUNCTION IF EXISTS "ops"."claim_next_dispatchable_set_run"(integer);--> statement-breakpoint

CREATE OR REPLACE FUNCTION "ops"."claim_next_dispatchable_set_run"("max_active" integer DEFAULT 10)
RETURNS SETOF "ops"."set_runs"
LANGUAGE plpgsql
AS $$
DECLARE
  available_slots integer;
BEGIN
  -- Serialize the active-count + claim decision so concurrent finalize/dispatch
  -- requests cannot overfill the global process-set window.
  PERFORM pg_advisory_xact_lock(
    hashtext('ops.set_runs'),
    hashtext('claim_next_dispatchable_set_run')
  );

  SELECT GREATEST(COALESCE(max_active, 10), 0) - count(*)::integer
  INTO available_slots
  FROM ops.set_runs
  WHERE status IN (
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
    WHERE status = 'queued'
      AND cancel_requested_at IS NULL
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
