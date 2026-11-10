import { sql } from "drizzle-orm";

export type PrivateYoonDispatch = { setRunId: string; generation?: string; controller?: boolean; workflowRunId?: string; runAttempt?: string };

export function buildPrivateYoonDispatchClaim(input: PrivateYoonDispatch) {
  const scope = sql`
    r.id=${input.setRunId}::uuid AND r.publication_visibility='private'
    AND r.target_set_id=s.id AND s.visibility='private' AND s.collection_id=r.collection_id
    AND u.id=r.submission_id AND u.visibility='private' AND u.collection_id=r.collection_id
    AND r.requested_by=u.requested_by AND r.create_playlist=false AND u.create_playlist=false
    AND r.cancel_requested_at IS NULL AND u.cancel_requested_at IS NULL AND r.published_set_id IS NULL
    AND r.source_metadata->'yoon_queue_v1'->'version'='1'::jsonb
    AND r.source_metadata->'yoon_queue_v1'->'identity'->>'id'=r.id::text
    AND r.source_metadata->'yoon_queue_v1'->'identity'->>'target_set_id'=r.target_set_id::text
    AND r.source_metadata->'yoon_queue_v1'->'identity'->>'submission_id'=r.submission_id::text
    AND r.source_metadata->'yoon_queue_v1'->'identity'->>'collection_id'=r.collection_id::text
    AND r.source_metadata->'yoon_queue_v1'->'identity'->>'requested_by'=r.requested_by
    AND r.source_metadata->'yoon_queue_v1'->'identity'->'descriptor'=r.source_metadata->'yoon_fixed_input'
    AND r.source_metadata->'yoon_queue_v1'->'identity'->'members'=(SELECT jsonb_agg(jsonb_build_object('user_id',m.user_id,'role',m.role) ORDER BY m.user_id) FROM app.archive_collection_members m WHERE m.collection_id=r.collection_id)`;
  return input.controller
    ? sql`UPDATE ops.set_runs r SET source_metadata=jsonb_set(r.source_metadata,'{yoon_queue_v1,last_wake}',${JSON.stringify({ workflow: input.workflowRunId, attempt: input.runAttempt, fence: `${input.workflowRunId}:${input.runAttempt}` })}::jsonb),updated_at=now()
        FROM app.sets s,ops.submissions u WHERE ${scope}
        AND r.source_metadata->'yoon_queue_v1'->>'status' IN ('queued','running')
        AND (r.source_metadata->'yoon_queue_v1'->'last_wake' IS NULL OR
          (r.source_metadata->'yoon_queue_v1'->'last_wake'->>'workflow')::numeric < ${input.workflowRunId}::numeric OR
          ((r.source_metadata->'yoon_queue_v1'->'last_wake'->>'workflow')::numeric = ${input.workflowRunId}::numeric AND
           (r.source_metadata->'yoon_queue_v1'->'last_wake'->>'attempt')::numeric < ${input.runAttempt}::numeric)) RETURNING r.id`
    : sql`UPDATE ops.set_runs r SET source_metadata=jsonb_set(r.source_metadata,'{yoon_queue_v1,status}','"sending"'::jsonb),updated_at=now()
        FROM app.sets s,ops.submissions u WHERE ${scope}
        AND r.status IN ('private_resume_pending','private_resume_paused')
        AND r.source_metadata->'yoon_queue_v1'->>'status'='reserved'
        AND r.source_metadata->'yoon_queue_v1'->>'generation'=${input.generation}
        AND (r.source_metadata->'yoon_resume'->>'review_required') IS DISTINCT FROM 'true'
        RETURNING r.id`;
}
