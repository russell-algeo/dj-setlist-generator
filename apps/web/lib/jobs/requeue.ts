import { sql, type SQL } from "drizzle-orm";

import { segmentHits, setRunLeases, setRuns } from "@/lib/db/schema";
import { retireWorkflowOwner } from "./publication";

// Retire the eligible generation and expose queued status atomically. Legacy
// retries clear their work; v1 retries retain evidence and completed leases.
// A failed CAS resets/deletes nothing, and an uncertain v1 reservation is fenced.
export const buildRequeueWithCleanupQuery = ({
  predicate,
  stage,
  resetCancellation = false,
  incrementAttempt = false,
}: {
  predicate: SQL | undefined;
  stage: "queued" | null;
  resetCancellation?: boolean;
  incrementAttempt?: boolean;
}) => sql`
  with requeued as (
    update ${setRuns}
    set status = 'queued', stage = ${stage}, error_summary = null,
        heartbeat_at = null, completed_at = null, updated_at = now(),
        source_metadata = ${retireWorkflowOwner()},
        cancel_requested_at = ${resetCancellation ? sql`null` : sql`${setRuns.cancelRequestedAt}`},
        attempt_count = ${setRuns.attemptCount} + ${incrementAttempt ? 1 : 0}
    where ${predicate}
      and (not (coalesce(${setRuns.sourceMetadata}, '{}'::jsonb) ? 'shared_recognition')
        or (${setRuns.sourceMetadata}->'shared_recognition'->>'version' = '1'
          and ${setRuns.sourceMetadata}->'shared_recognition'->>'review_required' = 'false'
          and ${setRuns.sourceMetadata}->'shared_recognition'->>'in_flight' = 'false'
          and not exists (select 1 from ops.segment_hits h where h.set_run_id = ${setRuns.id}
            and h.raw_data->'shared_recognition'->>'in_flight' = 'true')))

    returning ${setRuns.id}, ${setRuns.sourceMetadata}->'shared_recognition'->>'version' as shared_version
  ), deleted_hits as (
    delete from ${segmentHits} using requeued
    where ${segmentHits.setRunId} = requeued.id and requeued.shared_version is null
    returning ${segmentHits.id}
  ), deleted_leases as (
    delete from ${setRunLeases} using requeued
    where ${setRunLeases.setRunId} = requeued.id and requeued.shared_version is null
      and (select count(*) from deleted_hits) >= 0
  ), reset_shared_leases as (
    update ${setRunLeases}
    set status = 'pending', claimed_by = null, claimed_at = null,
        completed_at = null, error_text = null, updated_at = now()
    from requeued
    where ${setRunLeases.setRunId} = requeued.id and requeued.shared_version = '1'
      and ${setRunLeases.status} in ('claimed', 'failed')
  )
  select id from requeued
`;
