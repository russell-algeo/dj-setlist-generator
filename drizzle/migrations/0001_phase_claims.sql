CREATE OR REPLACE FUNCTION "ops"."recover_stale_set_runs"("stale_before" interval)
RETURNS integer
LANGUAGE sql
AS $$
  WITH updated AS (
    UPDATE ops.set_runs
    SET status = 'queued',
        stage = 'queued',
        updated_at = now(),
        heartbeat_at = NULL
    WHERE status IN ('dispatched', 'resolving', 'recognizing', 'aggregating', 'enriching', 'publishing')
      AND COALESCE(heartbeat_at, updated_at, created_at) < now() - stale_before
    RETURNING id
  )
  SELECT count(*)::integer FROM updated;
$$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION "ops"."dispatchable_set_runs"("max_active" integer)
RETURNS SETOF "ops"."set_runs"
LANGUAGE sql
AS $$
  WITH active_count AS (
    SELECT count(*)::integer AS count
    FROM ops.set_runs
    WHERE status IN ('dispatched', 'resolving', 'recognizing', 'aggregating', 'enriching', 'publishing', 'cancelling')
  )
  SELECT *
  FROM ops.set_runs
  WHERE status = 'queued'
    AND (SELECT count FROM active_count) < max_active
  ORDER BY created_at ASC, id ASC;
$$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION "ops"."claim_next_artist_submission"()
RETURNS SETOF "ops"."submissions"
LANGUAGE sql
AS $$
  WITH candidate AS (
    SELECT id
    FROM ops.submissions
    WHERE mode = 'artist'
      AND status = 'queued'
      AND cancel_requested_at IS NULL
    ORDER BY created_at ASC, id ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
  ),
  updated AS (
    UPDATE ops.submissions submission
    SET status = 'running',
        updated_at = now()
    WHERE submission.id IN (SELECT id FROM candidate)
    RETURNING submission.*
  )
  SELECT * FROM updated;
$$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION "ops"."claim_next_dispatchable_set_run"("max_active" integer DEFAULT 1)
RETURNS SETOF "ops"."set_runs"
LANGUAGE sql
AS $$
  WITH active_count AS (
    SELECT count(*)::integer AS count
    FROM ops.set_runs
    WHERE status IN ('dispatched', 'resolving', 'recognizing', 'aggregating', 'enriching', 'publishing', 'cancelling')
  ),
  candidate AS (
    SELECT id
    FROM ops.set_runs
    WHERE status = 'queued'
      AND cancel_requested_at IS NULL
      AND (SELECT count FROM active_count) < max_active
    ORDER BY created_at ASC, id ASC
    LIMIT 1
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
  SELECT * FROM updated;
$$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION "ops"."initialize_set_run_leases"(
  "p_set_run_id" uuid,
  "p_total_segments" integer,
  "p_slot_count" integer,
  "p_lease_size" integer
)
RETURNS integer
LANGUAGE sql
AS $$
  WITH deleted_hits AS (
    DELETE FROM ops.segment_hits
    WHERE set_run_id = p_set_run_id
    RETURNING id
  ),
  deleted_leases AS (
    DELETE FROM ops.set_run_leases
    WHERE set_run_id = p_set_run_id
    RETURNING id
  ),
  inserted AS (
    INSERT INTO ops.set_run_leases (
      set_run_id,
      slot_index,
      segment_start_index,
      segment_end_index,
      status
    )
    SELECT
      p_set_run_id,
      ((ordinality - 1) % GREATEST(p_slot_count, 1))::integer,
      start_idx,
      LEAST(start_idx + GREATEST(p_lease_size, 1) - 1, p_total_segments - 1),
      'pending'
    FROM generate_series(
      0,
      GREATEST(p_total_segments - 1, 0),
      GREATEST(p_lease_size, 1)
    ) WITH ORDINALITY AS series(start_idx, ordinality)
    WHERE p_total_segments > 0
    RETURNING id
  )
  SELECT count(*)::integer FROM inserted;
$$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION "ops"."claim_next_lease"(
  "p_set_run_id" uuid,
  "p_slot_index" integer,
  "p_worker_name" text
)
RETURNS SETOF "ops"."set_run_leases"
LANGUAGE sql
AS $$
  WITH candidate AS (
    SELECT id
    FROM ops.set_run_leases
    WHERE set_run_id = p_set_run_id
      AND slot_index = p_slot_index
      AND status = 'pending'
    ORDER BY segment_start_index ASC, id ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
  ),
  updated AS (
    UPDATE ops.set_run_leases lease
    SET status = 'claimed',
        claimed_by = p_worker_name,
        claimed_at = now(),
        updated_at = now()
    WHERE lease.id IN (SELECT id FROM candidate)
    RETURNING lease.*
  )
  SELECT * FROM updated;
$$;
