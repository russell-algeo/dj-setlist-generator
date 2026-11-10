-- Policy 3: actual HTTP 429 responses do not consume the non-throttle budget.
-- Total requests remain audit evidence; bounded workflows may continue indefinitely.
-- A different run's active HTTP attempt is not a global provider mutex.
CREATE OR REPLACE FUNCTION ops.shared_recognition_dispatchable(run_id uuid, metadata jsonb)
RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE s jsonb := metadata->'shared_recognition'; n numeric := extract(epoch from now()); segments numeric;
BEGIN
  -- The uncertain run never retries itself. Other runs resume only after the
  -- durable request timeout plus maximum cooldown quarantine has elapsed.
  IF s IS NOT NULL AND coalesce(s->>'policy_version', '1') NOT IN ('2','3') AND EXISTS (SELECT 1 FROM ops.set_runs other
      WHERE other.publication_visibility='public'
        AND other.source_metadata->'shared_recognition'->>'version'='1'
        AND coalesce(other.source_metadata->'shared_recognition'->>'policy_version', '1') NOT IN ('2','3')
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
    OR (s ? 'policy_version' AND s->'policy_version' NOT IN ('1'::jsonb,'2'::jsonb,'3'::jsonb))
    OR s->>'review_required' IS DISTINCT FROM 'false'
    OR s->>'in_flight' IS DISTINCT FROM 'false'
    OR s->>'reason' IN ('window_attempt_budget','lifetime_request_budget')
    OR (s->'policy_version' IS DISTINCT FROM '3'::jsonb AND s->>'reason' IN ('lifetime_time_budget','continuation_budget'))
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
  IF s->'policy_version' IS NOT DISTINCT FROM '3'::jsonb THEN
    IF jsonb_typeof(s->'throttle_requests') IS DISTINCT FROM 'number' THEN RETURN false; END IF;
    IF (s->>'throttle_requests')::numeric < 0
      OR (s->>'throttle_requests')::numeric > (s->>'requests')::numeric
      OR (s->>'throttle_requests')::numeric <> trunc((s->>'throttle_requests')::numeric)
      OR (s->>'next_allowed_at')::numeric < 0
      OR (s->>'deadline')::numeric <= 0
      OR (s->>'created_at')::numeric > 1.7976931348623157e308
      OR (s->>'deadline')::numeric > 1.7976931348623157e308
      OR (s->>'next_allowed_at')::numeric > 1.7976931348623157e308
      OR (s->>'requests')::numeric > 9007199254740991
      OR (s->>'continuations')::numeric > 9007199254740991
    THEN RETURN false; END IF;
  END IF;
  RETURN (s->>'created_at')::numeric > 0
    AND (s->'policy_version' IS NOT DISTINCT FROM '3'::jsonb OR ((s->>'deadline')::numeric > n
      AND (s->>'deadline')::numeric <= (s->>'created_at')::numeric + 604800))
    AND (s->>'next_allowed_at')::numeric <= n
    AND (s->>'continuations')::numeric >= 0 AND (s->'policy_version' IS NOT DISTINCT FROM '3'::jsonb OR (s->>'continuations')::numeric < 256)
    AND (s->>'continuations')::numeric = trunc((s->>'continuations')::numeric)
    AND (s->>'requests')::numeric >= 0
    AND (s->>'request_limit')::numeric BETWEEN 1 AND 8192
    AND (s->>'request_limit')::numeric = trunc((s->>'request_limit')::numeric)
    AND (s->>'requests')::numeric - CASE WHEN s->'policy_version' IS NOT DISTINCT FROM '3'::jsonb
      THEN (s->>'throttle_requests')::numeric ELSE 0 END < CASE
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
COMMENT ON FUNCTION ops.claim_next_dispatchable_set_run(integer) IS 'shared-recognition-throttle-v3';
