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
