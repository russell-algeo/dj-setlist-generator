import { sql, type SQL } from "drizzle-orm";

import { segmentHits, setRunLeases, setRuns } from "@/lib/db/schema";
import { retireWorkflowOwner } from "./publication";

// Claim the eligible generation, erase only that claim's recognition work, and
// expose queued status in one statement/transaction. A scheduler cannot start a
// new worker between the status change and cleanup; failed CAS cleans up nothing.
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
    returning ${setRuns.id}
  ), deleted_hits as (
    delete from ${segmentHits} using requeued
    where ${segmentHits.setRunId} = requeued.id
    returning ${segmentHits.id}
  ), deleted_leases as (
    delete from ${setRunLeases} using requeued
    where ${setRunLeases.setRunId} = requeued.id
      and (select count(*) from deleted_hits) >= 0
  )
  select id from requeued
`;
