import "server-only";

import { randomUUID } from "node:crypto";

import { and, eq, inArray, isNotNull, sql } from "drizzle-orm";

import { dispatchDiscoverArtistWorkflow, dispatchProcessSetWorkflow } from "@/lib/github/workflows";
import { getDb } from "@/lib/db/client";
import { segmentHits, setRunLeases, setRuns, submissions } from "@/lib/db/schema";
import { env } from "@/lib/env";
import {
  automaticRecoveryAttemptLimit,
  createWorkerEvent,
} from "@/lib/jobs/internal";
import { isActiveSubmissionStatus, isTerminalSetRunStatus } from "@/lib/jobs/status";
import { syncSubmissionStatusFromRuns } from "@/lib/jobs/submissions";
import { hasUncommittedPublication, matchesWorkflowOwner, prepareDispatchMetadata, publicationCommittedStage, retireWorkflowOwner } from "@/lib/jobs/publication";
import { recoveryEligibility } from "./recovery-eligibility";
import { buildRequeueWithCleanupQuery } from "@/lib/jobs/requeue";

import { sharedRecognition, sharedRecognitionConsumesRecoveryAttempt, sharedRecognitionExhausted, sharedRecognitionNeedsReview, validRecognitionHit } from "./shared-recognition";

const db = getDb();

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

const getSetRunRecoveryState = async (setRunId: string) => {
  const [run] = await db.select().from(setRuns).where(eq(setRuns.id, setRunId)).limit(1);

  if (!run) {
    return null;
  }

  const sourceMetadata = (run.sourceMetadata ?? {}) as Record<string, unknown>;
  const shared = sharedRecognition(sourceMetadata);
  const segmentCount = Number(sourceMetadata.segment_count ?? 0);
  const geometry = shared?.geometry as Record<string, unknown> | undefined;
  const segmentStep = typeof geometry?.segment_duration === "number" && typeof geometry?.segment_overlap === "number"
    ? geometry.segment_duration - geometry.segment_overlap : undefined;
  const [[leaseRollup], [segmentHitRollup]] = await Promise.all([
    db
      .select({
        totalCount: sql<number>`count(*)`,
        pendingCount: sql<number>`count(*) filter (where ${setRunLeases.status} = 'pending')`,
        claimedCount: sql<number>`count(*) filter (where ${setRunLeases.status} = 'claimed')`,
        completedCount: sql<number>`count(*) filter (where ${setRunLeases.status} = 'completed')`,
        failedCount: sql<number>`count(*) filter (where ${setRunLeases.status} = 'failed')`,
      })
      .from(setRunLeases)
      .where(eq(setRunLeases.setRunId, setRunId)),
    db
      .select({
        rowCount: sql<number>`count(*)`,
        hitCount: sql<number>`count(*) filter (where ${validRecognitionHit(Boolean(shared), segmentCount, segmentStep)})`,
        inFlightCount: sql<number>`count(*) filter (where ${segmentHits.rawData}->'shared_recognition'->>'in_flight' = 'true')`,
        recognizedCount: sql<number>`count(*) filter (where ${segmentHits.recognized} = true)`,
      })
      .from(segmentHits)
      .where(eq(segmentHits.setRunId, setRunId)),
  ]);

  const totalLeases = Number(leaseRollup?.totalCount ?? 0);
  const pendingLeases = Number(leaseRollup?.pendingCount ?? 0);
  const claimedLeases = Number(leaseRollup?.claimedCount ?? 0);
  const failedLeases = Number(leaseRollup?.failedCount ?? 0);
  const hitCount = Number(segmentHitRollup?.hitCount ?? 0);
  const recognitionComplete =
    totalLeases > 0 &&
    pendingLeases === 0 &&
    claimedLeases === 0 &&
    failedLeases === 0 &&
    segmentCount > 0 && Number(segmentHitRollup?.rowCount ?? 0) === segmentCount &&
    hitCount === segmentCount && Number(segmentHitRollup?.inFlightCount ?? 0) === 0;

  return {
    run,
    segmentCount,
    hitCount,
    leaseRollup: {
      totalCount: totalLeases,
      pendingCount: pendingLeases,
      claimedCount: claimedLeases,
      completedCount: Number(leaseRollup?.completedCount ?? 0),
      failedCount: failedLeases,
    },
    recognitionComplete,
    inFlightCount: Number(segmentHitRollup?.inFlightCount ?? 0),
  };
};

const requeueSetRunForFullRecovery = async (
  run: typeof setRuns.$inferSelect,
  reason: string,
  details?: Record<string, unknown>,
) => {
  const now = new Date();

  const requeued = await db.execute(buildRequeueWithCleanupQuery({
    predicate: recoveryEligibility(run),
    stage: "queued",
    incrementAttempt: sharedRecognitionConsumesRecoveryAttempt(sharedRecognition((run.sourceMetadata ?? {}) as Record<string, unknown>)),
  }));
  if (requeued.rows.length === 0) return false;

  await db
    .update(submissions)
    .set({
      status: "queued",
      errorSummary: null,
      completedAt: null,
      updatedAt: now,
    })
    .where(eq(submissions.id, run.submissionId));

  await createWorkerEvent({
    submissionId: run.submissionId,
    setRunId: run.id,
    eventType: "set_run.requeued",
    message: reason,
    details,
  });
  return true;
};

const markSetRunFailed = async (
  run: typeof setRuns.$inferSelect,
  reason: string,
  details?: Record<string, unknown>,
) => {
  const now = new Date();

  const [failed] = await db
    .update(setRuns)
    .set({
      status: "failed",
      stage: "workflow_failed",
      errorSummary: reason,
      heartbeatAt: now,
      completedAt: now,
      updatedAt: now,
    })
    .where(recoveryEligibility(run))
    .returning({ id: setRuns.id });

  if (!failed) return false;

  await createWorkerEvent({
    submissionId: run.submissionId,
    setRunId: run.id,
    eventType: "set_run.failed",
    message: reason,
    details,
  });
  return true;
};

const dispatchPublishOnlyRecovery = async (
  run: typeof setRuns.$inferSelect,
  reason: string,
  details?: Record<string, unknown>,
) => {
  const now = new Date();
  const generation = randomUUID();

  const [claimed] = await db
    .update(setRuns)
    .set({
      status: "dispatched",
      stage: "publish_retry_dispatching",
      sourceMetadata: prepareDispatchMetadata(generation),
      errorSummary: null,
      heartbeatAt: now,
      completedAt: null,
      updatedAt: now,
      attemptCount: sql`${setRuns.attemptCount} + 1`,
    })
    .where(recoveryEligibility(run))
    .returning();

  if (!claimed) return { action: "recovery_skipped" as const };

  await db
    .update(submissions)
    .set({
      status: "running",
      errorSummary: null,
      completedAt: null,
      updatedAt: now,
    })
    .where(eq(submissions.id, run.submissionId));

  let result: Awaited<ReturnType<typeof dispatchProcessSetWorkflow>>;
  try {
    result = await dispatchProcessSetWorkflow(run.id, { resume_mode: "publish_only", dispatch_generation: generation });
  } catch (error) {
    await createWorkerEvent({
      submissionId: run.submissionId,
      setRunId: run.id,
      eventType: "set_run.publish_retry_dispatch_failed",
      message: error instanceof Error ? error.message : "Publish retry dispatch failed",
    });

    const requeued = await requeueSetRunForFullRecovery(
      claimed,
      "Publish-only recovery dispatch failed; falling back to a full retry",
      details,
    );

    if (!requeued) return { action: "recovery_skipped" as const };

    return {
      action: "publish_retry_fell_back_to_full_retry" as const,
      dispatch: await dispatchPendingWork(),
    };
  }

  await createWorkerEvent({
    submissionId: run.submissionId,
    setRunId: run.id,
    eventType: "set_run.publish_retry_dispatched",
    message: reason,
    details: { ...(details ?? {}), result },
  });
  return { action: "publish_retry_dispatched" as const, result };
};

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export const dispatchQueuedArtistSubmission = async () => {
  const claimed = await db.execute(sql`select * from ops.claim_next_artist_submission() limit 1`);
  const claimedSubmissionId = claimed.rows[0]?.id ? String(claimed.rows[0].id) : null;

  const [submission] = claimedSubmissionId
    ? await db.select().from(submissions).where(eq(submissions.id, claimedSubmissionId)).limit(1)
    : [];

  if (!submission) {
    return null;
  }

  try {
    const result = await dispatchDiscoverArtistWorkflow(submission.id);
    await createWorkerEvent({
      submissionId: submission.id,
      eventType: "submission.dispatch",
      message: result.dispatched
        ? "Discover artist workflow dispatched"
        : "Discover artist workflow not dispatched",
      details: result,
    });
    return { submission, result };
  } catch (error) {
    await db
      .update(submissions)
      .set({ status: "queued", updatedAt: new Date() })
      .where(eq(submissions.id, submission.id));

    await createWorkerEvent({
      submissionId: submission.id,
      eventType: "submission.dispatch_failed",
      message: error instanceof Error ? error.message : "Discover artist dispatch failed",
    });

    throw error;
  }
};

const dispatchOneSetRun = async (queuedRun: typeof setRuns.$inferSelect) => {
  const generation = randomUUID();
  // Admission already claimed this row. Global provider state may change after
  // that transaction commits; rechecking it here would strand a dispatched run.
  // Per-run snapshot/owner/cancellation CAS remains, and reservation gates HTTP.
  const [claimed] = await db.update(setRuns).set({
    sourceMetadata: prepareDispatchMetadata(generation),
    updatedAt: new Date(),
  }).where(recoveryEligibility(queuedRun)).returning({ id: setRuns.id });
  if (!claimed) return { setRun: queuedRun, result: { dispatched: false, reason: "run_changed" } };
  const dispatchSnapshot = {
    ...queuedRun,
    sourceMetadata: {
      ...(queuedRun.sourceMetadata as Record<string, unknown> | null ?? {}),
      active_workflow_run_id: "awaiting_dispatch",
      dispatch_generation: generation,
    },
  };

  await db
    .update(submissions)
    .set({ status: "running", updatedAt: new Date() })
    .where(eq(submissions.id, queuedRun.submissionId));

  let result: Awaited<ReturnType<typeof dispatchProcessSetWorkflow>>;
  try {
    result = await dispatchProcessSetWorkflow(queuedRun.id, { dispatch_generation: generation });
  } catch (error) {
    const [reset] = await db
      .update(setRuns)
      .set({ status: "queued", stage: null, heartbeatAt: null, updatedAt: new Date(), sourceMetadata: retireWorkflowOwner() })
      .where(recoveryEligibility(dispatchSnapshot))
      .returning({ id: setRuns.id });

    if (reset) await syncSubmissionStatusFromRuns(queuedRun.submissionId);
    await createWorkerEvent({
      submissionId: queuedRun.submissionId,
      setRunId: queuedRun.id,
      eventType: "set_run.dispatch_failed",
      message: error instanceof Error ? error.message : "Set run dispatch failed",
    });
    throw error;
  }

  await createWorkerEvent({
    submissionId: queuedRun.submissionId,
    setRunId: queuedRun.id,
    eventType: "set_run.dispatch",
    message: result.dispatched ? "Process set workflow dispatched" : "Set run dispatch skipped",
    details: result,
  });
  return { setRun: queuedRun, result };
};

export const dispatchAllQueuedSetRuns = async () => {
  const maxActive = env.processSetMaxActiveRuns;
  const claimed = await db.execute(
    sql`select * from ops.claim_next_dispatchable_set_run(${maxActive})`,
  );
  const claimedCount = claimed.rows.length;

  if (claimedCount === 0) {
    return { maxActive, claimedCount, dispatched: 0, results: [] };
  }

  const claimedIds = claimed.rows.map((r) => String(r.id));
  const queuedRuns = await db.select().from(setRuns).where(inArray(setRuns.id, claimedIds));

  const results = await Promise.allSettled(queuedRuns.map(dispatchOneSetRun));

  return {
    maxActive,
    claimedCount,
    dispatched: results.filter((r) => r.status === "fulfilled" && r.value.result.dispatched).length,
    results: results.map((r) => (r.status === "fulfilled" ? r.value : { error: String(r.reason) })),
  };
};

export const dispatchPendingWork = async () => {
  const [artistDispatch, setDispatch] = await Promise.all([
    dispatchQueuedArtistSubmission(),
    dispatchAllQueuedSetRuns(),
  ]);

  return { artistDispatch, setDispatch };
};

export const finalizeArtistDiscoveryWorkflow = async (values: {
  submissionId: string;
  workflowRunId?: string;
  workflowResult: string;
}) => {
  const [submission] = await db
    .select()
    .from(submissions)
    .where(eq(submissions.id, values.submissionId))
    .limit(1);

  if (!submission) {
    return { action: "missing_submission" as const };
  }

  const runRows = await db
    .select({ id: setRuns.id, status: setRuns.status })
    .from(setRuns)
    .where(eq(setRuns.submissionId, values.submissionId));

  if (runRows.length > 0) {
    const status = await syncSubmissionStatusFromRuns(values.submissionId);
    return {
      action: "synced_from_runs" as const,
      status,
      dispatch: await dispatchPendingWork(),
    };
  }

  if (values.workflowResult === "success") {
    return {
      action: "success_noop" as const,
      dispatch: await dispatchPendingWork(),
    };
  }

  if (!isActiveSubmissionStatus(submission.status)) {
    return {
      action: "already_terminal" as const,
      status: submission.status,
      dispatch: await dispatchPendingWork(),
    };
  }

  const now = new Date();
  const reason = values.workflowRunId
    ? `Discover artist workflow ${values.workflowRunId} failed before discovery completed`
    : "Discover artist workflow failed before discovery completed";

  await db
    .update(submissions)
    .set({
      status: "failed",
      errorSummary: reason,
      completedAt: now,
      updatedAt: now,
    })
    .where(eq(submissions.id, values.submissionId));

  await createWorkerEvent({
    submissionId: values.submissionId,
    eventType: "submission.discovery.failed",
    message: reason,
    details: {
      workflowRunId: values.workflowRunId ?? null,
      workflowResult: values.workflowResult,
    },
  });

  return {
    action: "marked_failed" as const,
    dispatch: await dispatchPendingWork(),
  };
};

export const finalizeSetRunWorkflow = async (values: {
  setRunId: string;
  workflowRunId?: string;
  bootstrapResult: string;
  recognizeResult: string;
  publishResult: string;
}) => {
  const state = await getSetRunRecoveryState(values.setRunId);

  if (!state) {
    return { action: "missing_set_run" as const };
  }

  const { run, recognitionComplete, leaseRollup, hitCount, segmentCount } = state;
  const sourceMetadata = (run.sourceMetadata ?? {}) as Record<string, unknown>;
  const activeWorkflowRunId =
    typeof sourceMetadata.active_workflow_run_id === "string"
      ? sourceMetadata.active_workflow_run_id
      : null;
  const details = {
    workflowRunId: values.workflowRunId ?? null,
    activeWorkflowRunId,
    bootstrapResult: values.bootstrapResult,
    recognizeResult: values.recognizeResult,
    publishResult: values.publishResult,
    leaseRollup,
    hitCount,
    segmentCount,
    attemptCount: run.attemptCount,
  };

  if (values.workflowRunId && activeWorkflowRunId && values.workflowRunId !== activeWorkflowRunId) {
    await createWorkerEvent({
      submissionId: run.submissionId,
      setRunId: run.id,
      eventType: "set_run.finalize_superseded",
      message: `Ignoring finalize from superseded workflow ${values.workflowRunId}`,
      details,
    });
    return { action: "superseded_workflow_finalize_ignored" as const };
  }

  // A committed writer can still be running after a caller timeout. Do not
  // cancel it, clear its gate, or dispatch an overlapping recovery attempt.
  if (run.stage === publicationCommittedStage && !run.publishedSetId) {
    await createWorkerEvent({
      submissionId: run.submissionId,
      setRunId: run.id,
      eventType: "set_run.publication_requires_reconciliation",
      message: "Publication may still be running or have an uncertain outcome. Reconcile archive writes before retrying.",
      details,
    });
    return { action: "publication_requires_reconciliation" as const };
  }

  if (run.cancelRequestedAt && !run.publishedSetId && run.status !== "cancelled") {
    const now = new Date();
    const [cancelled] = await db
      .update(setRuns)
      .set({ status: "cancelled", stage: "cancelled", completedAt: now, updatedAt: now })
      .where(and(
        eq(setRuns.id, run.id),
        isNotNull(setRuns.cancelRequestedAt),
        hasUncommittedPublication(),
        matchesWorkflowOwner(values.workflowRunId),
      ))
      .returning({ id: setRuns.id });
    if (!cancelled) return { action: "recovery_skipped" as const };
    await createWorkerEvent({
      submissionId: run.submissionId,
      setRunId: run.id,
      eventType: "set_run.cancelled",
      message: "Run marked cancelled after workflow completed with a pending cancel request",
      details,
    });
    await syncSubmissionStatusFromRuns(run.submissionId);
    return {
      action: "cancelled" as const,
      dispatch: await dispatchPendingWork(),
    };
  }

  if (isTerminalSetRunStatus(run.status) || run.publishedSetId) {
    await syncSubmissionStatusFromRuns(run.submissionId);
    return {
      action: "already_terminal" as const,
      status: run.status,
      dispatch: await dispatchPendingWork(),
    };
  }

  const shared = sharedRecognition(sourceMetadata);
  if (Object.prototype.hasOwnProperty.call(sourceMetadata, "shared_recognition") && !shared) {
    return { action: "recognition_requires_reconciliation" as const };
  }
  if (shared && sharedRecognitionNeedsReview(shared, state.inFlightCount)) {
    return { action: "recognition_requires_reconciliation" as const };
  }

  if (recognitionComplete) {
    if (run.attemptCount >= automaticRecoveryAttemptLimit) {
      const failed = await markSetRunFailed(
        run,
        `Automatic recovery exhausted after ${run.attemptCount} retries while waiting for publish`,
        details,
      );
      if (!failed) return { action: "recovery_skipped" as const };
      await syncSubmissionStatusFromRuns(run.submissionId);
      return {
        action: "failed_after_recovery_limit" as const,
        dispatch: await dispatchPendingWork(),
      };
    }

    return dispatchPublishOnlyRecovery(
      run,
      "Recognition data is complete; dispatching publish-only recovery",
      details,
    );
  }

  if (shared) {
    if (sharedRecognitionExhausted(shared, segmentCount)) {
      const failed = await markSetRunFailed(run, "Durable recognition budget or deadline exhausted", details);
      if (failed) await syncSubmissionStatusFromRuns(run.submissionId);
      return { action: failed ? "recognition_budget_exhausted" as const : "recovery_skipped" as const };
    }
    // Only a clean, explicit pause is an automatic continuation. Crashed or
    // malformed state remains available for reconciliation without data loss.
    if (shared.paused !== true || typeof shared.next_allowed_at !== "number" || !Number.isFinite(shared.next_allowed_at)) {
      return { action: "recognition_requires_reconciliation" as const };
    }
    if (sharedRecognitionConsumesRecoveryAttempt(shared) && run.attemptCount >= automaticRecoveryAttemptLimit) {
      const failed = await markSetRunFailed(run, "Non-throttle workflow recovery exhausted", details);
      if (failed) await syncSubmissionStatusFromRuns(run.submissionId);
      return { action: failed ? "failed_after_recovery_limit" as const : "recovery_skipped" as const };
    }
    const requeued = await requeueSetRunForFullRecovery(run, "Durable recognition paused; preserving completed windows for continuation", details);
    if (!requeued) return { action: "recovery_skipped" as const };
    return { action: "recognition_continuation_queued" as const, dispatch: await dispatchPendingWork() };
  }

  if (run.attemptCount >= automaticRecoveryAttemptLimit) {
    const failed = await markSetRunFailed(
      run,
      `Automatic recovery exhausted after ${run.attemptCount} retries with incomplete recognition state`,
      details,
    );
    if (!failed) return { action: "recovery_skipped" as const };
    await syncSubmissionStatusFromRuns(run.submissionId);
    return {
      action: "failed_after_recovery_limit" as const,
      dispatch: await dispatchPendingWork(),
    };
  }

  const requeued = await requeueSetRunForFullRecovery(
    run,
    "Recognition workflow did not reach a terminal publishable state; requeuing automatically",
    details,
  );

  if (!requeued) return { action: "recovery_skipped" as const };

  return {
    action: "requeued_for_full_retry" as const,
    dispatch: await dispatchPendingWork(),
  };
};
