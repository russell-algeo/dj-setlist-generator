-- Replace the serial dispatch gate with an unrestricted version that claims
-- all queued set_runs at once. The old function accepted a `max_active`
-- parameter that prevented more than one run from being dispatched at a time;
-- removing that gate allows every queued run to be dispatched concurrently.
--> statement-breakpoint
DROP FUNCTION IF EXISTS "ops"."claim_next_dispatchable_set_run"(integer);
--> statement-breakpoint
CREATE OR REPLACE FUNCTION "ops"."claim_next_dispatchable_set_run"()
RETURNS SETOF "ops"."set_runs"
LANGUAGE sql
AS $$
  WITH candidate AS (
    SELECT id
    FROM ops.set_runs
    WHERE status = 'queued'
      AND cancel_requested_at IS NULL
    ORDER BY created_at ASC, id ASC
    FOR UPDATE SKIP LOCKED
  ),
  updated AS (
    UPDATE ops.set_runs set_run
    SET status    = 'dispatched',
        stage     = 'dispatching',
        heartbeat_at = now(),
        updated_at   = now()
    WHERE set_run.id IN (SELECT id FROM candidate)
    RETURNING set_run.*
  )
  SELECT * FROM updated;
$$;
