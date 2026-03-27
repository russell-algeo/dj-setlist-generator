-- Extend recover_stale_set_runs to include 'cancelling' runs.
-- Stuck 'cancelling' runs are marked 'cancelled' (not 'queued') since
-- cancel_requested_at is set and re-dispatching them would have no effect.
--> statement-breakpoint
CREATE OR REPLACE FUNCTION "ops"."recover_stale_set_runs"("stale_before" interval)
RETURNS integer
LANGUAGE sql
AS $$
  WITH updated AS (
    UPDATE ops.set_runs
    SET status       = CASE WHEN status = 'cancelling' THEN 'cancelled' ELSE 'queued' END,
        stage        = CASE WHEN status = 'cancelling' THEN 'cancelled' ELSE 'queued' END,
        completed_at = CASE WHEN status = 'cancelling' THEN now() ELSE NULL END,
        heartbeat_at = NULL,
        updated_at   = now()
    WHERE status IN (
      'dispatched', 'resolving', 'recognizing',
      'aggregating', 'enriching', 'publishing', 'cancelling'
    )
      AND COALESCE(heartbeat_at, updated_at, created_at) < now() - stale_before
    RETURNING id
  )
  SELECT count(*)::integer FROM updated;
$$;
