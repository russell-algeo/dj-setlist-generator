import { sql } from "drizzle-orm";
import { setRuns } from "@/lib/db/schema";
import { recoveryEligibility } from "./recovery-eligibility";
import { retireWorkflowOwner } from "./publication";

export const samplingCapacityReasons = [
  "sampling_capacity_unsettled", "sampling_capacity_retry_after_review", "sampling_capacity_cooldown",
] as const;
export const isSamplingCapacityReason = (value: unknown) =>
  typeof value === "string" && samplingCapacityReasons.some((reason) => reason === value);
const key = "sampling_capacity_deferral_v1";
const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);

// This is durable worker-authored evidence, not a reason supplied by a callback.
// Unknown/partial markers are never interpreted as a free retry.
export const validSamplingCapacityDeferral = (
  metadata: Record<string, unknown>, stage: string | null, workflowRunId?: string,
) => {
  const value = metadata[key];
  const keys = ["version", "workflow_run_id", "run_attempt", "dispatch_generation", "reason", "observed_at"];
  return object(value) && Object.keys(value).length === keys.length && keys.every((name) => name in value)
    && stage === "sampling_capacity_deferred" && value.version === 1
    && typeof value.workflow_run_id === "string" && /^[0-9]+$/.test(value.workflow_run_id)
    && typeof value.run_attempt === "string" && /^[0-9]+$/.test(value.run_attempt)
    && typeof value.dispatch_generation === "string"
    && value.dispatch_generation === (metadata.dispatch_generation ?? "")
    && value.workflow_run_id === metadata.active_workflow_run_id
    && workflowRunId === value.workflow_run_id
    && isSamplingCapacityReason(value.reason)
    && typeof value.observed_at === "number" && Number.isFinite(value.observed_at) && value.observed_at > 0;
};

// Dedicated requeue: no cleanup, lease reset, provider result, or attempt charge.
// A late/cancelled/stale callback changes nothing. The authoritative admission
// function keeps queued work parked until the persistent sampling ledger opens.
export const buildSamplingCapacityRequeue = (run: typeof setRuns.$inferSelect) => sql`
  update ${setRuns}
  set status = 'queued', stage = 'queued', heartbeat_at = null,
      completed_at = null, error_summary = null, updated_at = now(),
      source_metadata = (${retireWorkflowOwner()}) - 'sampling_capacity_deferral_v1'
  where ${recoveryEligibility(run)}
    and ${setRuns.sourceMetadata}->'sampling_capacity_deferral_v1' = ${JSON.stringify((run.sourceMetadata as Record<string, unknown>)[key])}::jsonb
    and exists (select 1 from ops.submissions u where u.id = ${setRuns.submissionId}
      and u.visibility = 'public' and u.cancel_requested_at is null)
    and not exists (select 1 from ops.set_run_leases l where l.set_run_id = ${setRuns.id}
      and (l.status is null or l.status not in ('pending','completed','failed')))
    and not exists (select 1 from ops.segment_hits h where h.set_run_id = ${setRuns.id}
      and (jsonb_typeof(h.raw_data) is distinct from 'object'
        or (h.raw_data ? 'shared_recognition' and (
          jsonb_typeof(h.raw_data->'shared_recognition') is distinct from 'object'
          or h.raw_data->'shared_recognition'->'in_flight' is distinct from 'false'::jsonb))))
    and (not (${setRuns.sourceMetadata} ? 'shared_recognition') or (
      ${setRuns.sourceMetadata}->'shared_recognition'->'version' = '1'::jsonb
      and ${setRuns.sourceMetadata}->'shared_recognition'->'in_flight' = 'false'::jsonb
      and ${setRuns.sourceMetadata}->'shared_recognition'->'review_required' = 'false'::jsonb))
  returning ${setRuns.id}
`;
