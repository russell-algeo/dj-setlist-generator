-- Admission stays serialized by the existing transaction advisory lock.
CREATE OR REPLACE FUNCTION ops.shared_recognition_dispatchable(run_id uuid, metadata jsonb)
RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE s jsonb := metadata->'shared_recognition'; n numeric := extract(epoch from now()); segments numeric;
BEGIN
  -- The uncertain run never retries itself. Other runs resume only after the
  -- durable request timeout plus maximum cooldown quarantine has elapsed.
  IF EXISTS (SELECT 1 FROM ops.set_runs other
      WHERE other.publication_visibility='public'
        AND other.source_metadata->'shared_recognition'->>'version'='1'
        AND ((other.source_metadata->'shared_recognition'->>'in_flight'='true'
          AND CASE WHEN jsonb_typeof(other.source_metadata->'shared_recognition'->'in_flight_until')='number'
            THEN (other.source_metadata->'shared_recognition'->>'in_flight_until')::numeric > n
            ELSE true END)
          OR EXISTS (SELECT 1 FROM ops.segment_hits h WHERE h.set_run_id=other.id
            AND h.raw_data->'shared_recognition'->>'in_flight'='true'
            AND CASE
              WHEN jsonb_typeof(h.raw_data->'shared_recognition'->'attempts'->-1->'expires_at')='number'
                THEN (h.raw_data->'shared_recognition'->'attempts'->-1->>'expires_at')::numeric > n
              WHEN other.source_metadata->'shared_recognition'->>'in_flight'='true'
                AND other.source_metadata->'shared_recognition'->'active_index'=to_jsonb(h.segment_index)
                AND jsonb_typeof(other.source_metadata->'shared_recognition'->'in_flight_until')='number'
                THEN (other.source_metadata->'shared_recognition'->>'in_flight_until')::numeric > n
              ELSE true END))) THEN RETURN false; END IF;
  IF s IS NULL THEN RETURN true; END IF;
  IF jsonb_typeof(s) <> 'object' OR s->>'version' IS DISTINCT FROM '1'
    OR s->>'review_required' IS DISTINCT FROM 'false'
    OR s->>'in_flight' IS DISTINCT FROM 'false'
    OR s->>'reason' IN ('window_attempt_budget','lifetime_request_budget','lifetime_time_budget','continuation_budget')
    OR jsonb_typeof(s->'created_at') IS DISTINCT FROM 'number'
    OR jsonb_typeof(s->'deadline') IS DISTINCT FROM 'number'
    OR jsonb_typeof(s->'next_allowed_at') IS DISTINCT FROM 'number'
    OR jsonb_typeof(s->'continuations') IS DISTINCT FROM 'number'
    OR jsonb_typeof(s->'requests') IS DISTINCT FROM 'number'
    OR jsonb_typeof(s->'request_limit') IS DISTINCT FROM 'number'
  THEN RETURN false; END IF;
  IF jsonb_typeof(metadata->'segment_count')='number' THEN segments := (metadata->>'segment_count')::numeric; END IF;
  IF (s->>'requests')::numeric > 0 AND (
    segments IS NULL OR segments <= 0 OR segments <> trunc(segments)
    OR jsonb_typeof(s->'geometry') IS DISTINCT FROM 'object'
    OR s->'geometry'->'segment_count' IS DISTINCT FROM metadata->'segment_count'
  ) THEN RETURN false; END IF;
  RETURN (s->>'created_at')::numeric > 0
    AND (s->>'deadline')::numeric > n
    AND (s->>'deadline')::numeric <= (s->>'created_at')::numeric + 604800
    AND (s->>'next_allowed_at')::numeric <= n
    AND (s->>'continuations')::numeric >= 0 AND (s->>'continuations')::numeric < 256
    AND (s->>'continuations')::numeric = trunc((s->>'continuations')::numeric)
    AND (s->>'requests')::numeric >= 0
    AND (s->>'request_limit')::numeric BETWEEN 1 AND 8192
    AND (s->>'request_limit')::numeric = trunc((s->>'request_limit')::numeric)
    AND (s->>'requests')::numeric < CASE
      WHEN segments > 0 AND segments=trunc(segments)
      THEN least((s->>'request_limit')::numeric, 8192, segments * 8)
      WHEN (s->>'requests')::numeric = 0 THEN (s->>'request_limit')::numeric
      ELSE 0 END
    AND (s->>'requests')::numeric = trunc((s->>'requests')::numeric)
    AND NOT EXISTS (SELECT 1 FROM ops.segment_hits h WHERE h.set_run_id=run_id
      AND h.raw_data->'shared_recognition'->>'in_flight' = 'true');
END;
$$;
--> statement-breakpoint
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
--> statement-breakpoint
COMMENT ON FUNCTION ops.claim_next_dispatchable_set_run(integer) IS 'shared-recognition-continuation-v1';
--> statement-breakpoint
-- Preserve durable private recognition evidence; public retention is unchanged.
CREATE OR REPLACE FUNCTION "ops"."cleanup_expired_ops_data"()
RETURNS jsonb
LANGUAGE sql
AS $$
  WITH
    deleted_hits AS (
      DELETE FROM ops.segment_hits
      WHERE created_at < now() - interval '7 days'
        AND EXISTS (SELECT 1 FROM ops.set_runs r WHERE r.id=segment_hits.set_run_id AND r.publication_visibility='public'
          AND (NOT (coalesce(r.source_metadata,'{}'::jsonb) ? 'shared_recognition')
            OR (r.status IN ('completed','failed','cancelled')
              AND r.source_metadata->'shared_recognition'->>'review_required' = 'false'
              AND r.source_metadata->'shared_recognition'->>'in_flight' = 'false'
              AND jsonb_typeof(r.source_metadata->'shared_recognition'->'deadline') = 'number'
              AND (r.source_metadata->'shared_recognition'->>'deadline')::numeric <= extract(epoch from now())
              AND NOT EXISTS (SELECT 1 FROM ops.segment_hits h WHERE h.set_run_id=r.id
                AND h.raw_data->'shared_recognition'->>'in_flight' = 'true'))))
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
--> statement-breakpoint
-- Old application/worker releases cannot erase enrolled durable evidence.
CREATE OR REPLACE FUNCTION ops.guard_shared_recognition_evidence()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r ops.set_runs; protected boolean;
BEGIN
  SELECT * INTO r FROM ops.set_runs WHERE id=OLD.set_run_id;
  IF r.publication_visibility IS DISTINCT FROM 'public' OR
     r.source_metadata->'shared_recognition'->>'version' IS DISTINCT FROM '1'
  THEN IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF; END IF;
  protected := r.status NOT IN ('completed','failed','cancelled')
    OR r.source_metadata->'shared_recognition'->>'review_required' IS DISTINCT FROM 'false'
    OR r.source_metadata->'shared_recognition'->>'in_flight' IS DISTINCT FROM 'false'
    OR jsonb_typeof(r.source_metadata->'shared_recognition'->'deadline') IS DISTINCT FROM 'number';
  IF NOT protected THEN
    protected := (r.source_metadata->'shared_recognition'->>'deadline')::numeric > extract(epoch from now())
      OR EXISTS (SELECT 1 FROM ops.segment_hits h WHERE h.set_run_id=r.id
        AND h.raw_data->'shared_recognition'->>'in_flight' = 'true');
  END IF;
  IF TG_TABLE_NAME='segment_hits' THEN
    IF TG_OP='UPDATE' THEN
      -- Settling an in-flight reservation is permitted; overwriting completed
      -- valid evidence is not. The worker owns reservation-token CAS.
      IF OLD.raw_data->'shared_recognition'->>'valid' = 'true' THEN
        RAISE EXCEPTION 'Shared recognition valid evidence is immutable';
      END IF;
    ELSIF protected THEN
      RAISE EXCEPTION 'Shared recognition evidence requires retention/reconciliation';
    END IF;
  ELSIF TG_OP='DELETE' AND protected THEN
    RAISE EXCEPTION 'Shared recognition leases require retention/reconciliation';
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$;
--> statement-breakpoint
CREATE TRIGGER guard_shared_recognition_hits BEFORE UPDATE OR DELETE ON ops.segment_hits
FOR EACH ROW EXECUTE FUNCTION ops.guard_shared_recognition_evidence();
--> statement-breakpoint
CREATE TRIGGER guard_shared_recognition_leases BEFORE DELETE ON ops.set_run_leases
FOR EACH ROW EXECUTE FUNCTION ops.guard_shared_recognition_evidence();
