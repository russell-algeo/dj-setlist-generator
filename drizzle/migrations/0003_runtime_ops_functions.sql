-- Recovers claimed leases that have been held longer than stale_before without
-- completing. Returns the count of leases reset to pending.
CREATE OR REPLACE FUNCTION "ops"."recover_stale_leases"("stale_before" interval)
RETURNS integer
LANGUAGE sql
AS $$
  WITH updated AS (
    UPDATE ops.set_run_leases
    SET status    = 'pending',
        claimed_by = NULL,
        claimed_at = NULL,
        updated_at = now()
    WHERE status     = 'claimed'
      AND claimed_at < now() - stale_before
    RETURNING id
  )
  SELECT count(*)::integer FROM updated;
$$;
--> statement-breakpoint

-- Marks a lease as completed or failed and records the optional error text.
CREATE OR REPLACE FUNCTION "ops"."complete_lease"(
  "p_lease_id"   uuid,
  "p_success"    boolean,
  "p_error_text" text DEFAULT NULL
)
RETURNS void
LANGUAGE sql
AS $$
  UPDATE ops.set_run_leases
  SET status       = CASE WHEN p_success THEN 'completed' ELSE 'failed' END,
      completed_at = CASE WHEN p_success THEN now() ELSE NULL END,
      error_text   = p_error_text,
      updated_at   = now()
  WHERE id = p_lease_id;
$$;
--> statement-breakpoint

-- Updates a set run's status and stage atomically, bumping heartbeat_at and
-- conditionally setting completed_at for terminal states.
-- Returns the updated row so callers can verify the transition.
CREATE OR REPLACE FUNCTION "ops"."mark_run_stage"(
  "p_set_run_id"      uuid,
  "p_status"          text,
  "p_stage"           text,
  "p_error_summary"   text DEFAULT NULL,
  "p_published_set_id" uuid DEFAULT NULL
)
RETURNS SETOF "ops"."set_runs"
LANGUAGE sql
AS $$
  UPDATE ops.set_runs
  SET status           = p_status,
      stage            = p_stage,
      error_summary    = COALESCE(p_error_summary, error_summary),
      published_set_id = COALESCE(p_published_set_id, published_set_id),
      heartbeat_at     = now(),
      completed_at     = CASE
                           WHEN p_status IN ('completed', 'failed', 'cancelled')
                           THEN now()
                           ELSE completed_at
                         END,
      updated_at       = now()
  WHERE id = p_set_run_id
  RETURNING *;
$$;
--> statement-breakpoint

-- Deletes expired operational rows according to the retention policy:
--   ops.segment_hits        → 7 days
--   ops.worker_events       → 14 days
--   ops.discovery_candidates → 7 days
-- Returns a JSONB summary of deletion counts for observability.
CREATE OR REPLACE FUNCTION "ops"."cleanup_expired_ops_data"()
RETURNS jsonb
LANGUAGE sql
AS $$
  WITH
    deleted_hits AS (
      DELETE FROM ops.segment_hits
      WHERE created_at < now() - interval '7 days'
      RETURNING id
    ),
    deleted_events AS (
      DELETE FROM ops.worker_events
      WHERE created_at < now() - interval '14 days'
      RETURNING id
    ),
    deleted_candidates AS (
      DELETE FROM ops.discovery_candidates
      WHERE created_at < now() - interval '7 days'
      RETURNING id
    )
  SELECT jsonb_build_object(
    'deleted_segment_hits',        (SELECT count(*) FROM deleted_hits),
    'deleted_worker_events',       (SELECT count(*) FROM deleted_events),
    'deleted_discovery_candidates',(SELECT count(*) FROM deleted_candidates)
  );
$$;
