import { and, eq, isNull, sql } from "drizzle-orm";
import { setRuns } from "@/lib/db/schema";
import { hasUncommittedPublication, matchesWorkflowOwner, matchesDispatchGeneration } from "./publication";

// Finalizer reads are snapshots. Recheck cancellation, publication and workflow
// ownership in every recovery mutation so a late callback cannot revive a run.
export const recoveryEligibility = (run: typeof setRuns.$inferSelect) => and(
  eq(setRuns.id, run.id),
  eq(setRuns.status, run.status),
  eq(setRuns.attemptCount, run.attemptCount),
  sql`${setRuns.sourceMetadata}->'shared_recognition' is not distinct from ${(run.sourceMetadata as Record<string, unknown> | null)?.shared_recognition ? JSON.stringify((run.sourceMetadata as Record<string, unknown>).shared_recognition) : null}::jsonb`,
  run.stage ? eq(setRuns.stage, run.stage) : isNull(setRuns.stage),
  isNull(setRuns.cancelRequestedAt),
  hasUncommittedPublication(),
  matchesWorkflowOwner((run.sourceMetadata as Record<string, unknown> | null)?.active_workflow_run_id as string | undefined),
  matchesDispatchGeneration((run.sourceMetadata as Record<string, unknown> | null)?.dispatch_generation as string | undefined),
);
