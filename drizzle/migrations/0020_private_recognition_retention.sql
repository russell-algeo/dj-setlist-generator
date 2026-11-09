-- Preserve durable private recognition evidence; public retention is unchanged.
CREATE OR REPLACE FUNCTION "ops"."cleanup_expired_ops_data"()
RETURNS jsonb
LANGUAGE sql
AS $$
  WITH
    deleted_hits AS (
      DELETE FROM ops.segment_hits
      WHERE created_at < now() - interval '7 days'
        AND EXISTS (SELECT 1 FROM ops.set_runs r WHERE r.id=segment_hits.set_run_id AND r.publication_visibility='public')
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
COMMENT ON FUNCTION ops.cleanup_expired_ops_data() IS 'private-recognition-retention-v1';
