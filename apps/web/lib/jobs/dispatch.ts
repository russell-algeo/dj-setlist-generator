import "server-only";

import { eq, inArray, sql } from "drizzle-orm";

import { dispatchDiscoverArtistWorkflow, dispatchProcessSetWorkflow } from "@/lib/github/workflows";
import { getDb } from "@/lib/db/client";
import { segmentHits, setRunLeases, setRuns, submissions } from "@/lib/db/schema";
import { env } from "@/lib/env";
import {
  automaticRecoveryAttemptLimit,
  createWorkerEvent,
} from "@/lib/jobs/internal";
import { isTerminalSetRunStatus } from "@/lib/jobs/status";
import { syncSubmissionStatusFromRuns } from "@/lib/jobs/submissions";

const db = getDb();

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

const getSetRunRecoveryState = async (setRunId: string) => {
  const [run] = await db.select().from(setRuns).where(eq(setRuns.id, setRunId)).limit(1);

  if (!run) {
    return null;
  }

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
        hitCount: sql<number>`count(*)`,
        recognizedCount: sql<number>`count(*) filter (where ${segmentHits.recognized} = true)`,
      })
      .from(segmentHits)
      .where(eq(segmentHits.setRunId, setRunId)),
  ]);

  const sourceMetadata = (run.sourceMetadata ?? {}) as Record<string, unknown>;
  const segmentCount = Number(sourceMetadata.segment_count ?? 0);
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
    (segmentCount <= 0 || hitCount >= segmentCount);

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
  };
};

const requeueSetRunForFullRecovery = async (
  run: typeof setRuns.$inferSelect,
  reason: string,
  details?: Record<string, unknown>,
) => {
  const now = new Date();

  await db.delete(segmentHits).where(eq(segmentHits.setRunId, run.id));
  await db.delete(setRunLeases).where(eq(setRunLeases.setRunId, run.id));

  await db
    .update(setRuns)
    .set({
      status: "queued",
      stage: "queued",
      errorSummary: null,
      heartbeatAt: null,
      completedAt: null,
      updatedAt: now,
      attemptCount: sql`${setRuns.attemptCount} + 1`,
    })
    .where(eq(setRuns.id, run.id));

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
};

const markSetRunFailed = async (
  run: typeof setRuns.$inferSelect,
  reason: string,
  details?: Record<string, unknown>,
) => {
  const now = new Date();

  await db
    .update(setRuns)
    .set({
      status: "failed",
      stage: "workflow_failed",
      errorSummary: reason,
      heartbeatAt: now,
      completedAt: now,
      updatedAt: now,
    })
    .where(eq(setRuns.id, run.id));

  await createWorkerEvent({
    submissionId: run.submissionId,
    setRunId: run.id,
    eventType: "set_run.failed",
    message: reason,
    details,
  });
};

const dispatchPublishOnlyRecovery = async (
  run: typeof setRuns.$inferSelect,
  reason: string,
  details?: Record<string, unknown>,
) => {
  const now = new Date();

  await db
    .update(setRuns)
    .set({
      status: "dispatched",
      stage: "publish_retry_dispatching",
      errorSummary: null,
      heartbeatAt: now,
      completedAt: null,
      updatedAt: now,
      attemptCount: sql`${setRuns.attemptCount} + 1`,
    })
    .where(eq(setRuns.id, run.id));

  await db
    .update(submissions)
    .set({
      status: "running",
      errorSummary: null,
      completedAt: null,
      updatedAt: now,
    })
    .where(eq(submissions.id, run.submissionId));

  try {
    const result = await dispatchProcessSetWorkflow(run.id, { resume_mode: "publish_only" });
    await createWorkerEvent({
      submissionId: run.submissionId,
      setRunId: run.id,
      eventType: "set_run.publish_retry_dispatched",
      message: reason,
      details: { ...(details ?? {}), result },
    });
    return { action: "publish_retry_dispatched" as const, result };
  } catch (error) {
    await createWorkerEvent({
      submissionId: run.submissionId,
      setRunId: run.id,
      eventType: "set_run.publish_retry_dispatch_failed",
      message: error instanceof Error ? error.message : "Publish retry dispatch failed",
    });

    await requeueSetRunForFullRecovery(
      run,
      "Publish-only recovery dispatch failed; falling back to a full retry",
      details,
    );

    return {
      action: "publish_retry_fell_back_to_full_retry" as const,
      dispatch: await dispatchPendingWork(),
    };
  }
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
  await db
    .update(submissions)
    .set({ status: "running", updatedAt: new Date() })
    .where(eq(submissions.id, queuedRun.submissionId));

  try {
    const result = await dispatchProcessSetWorkflow(queuedRun.id);
    await createWorkerEvent({
      submissionId: queuedRun.submissionId,
      setRunId: queuedRun.id,
      eventType: "set_run.dispatch",
      message: result.dispatched ? "Process set workflow dispatched" : "Set run dispatch skipped",
      details: result,
    });
    return { setRun: queuedRun, result };
  } catch (error) {
    await db
      .update(setRuns)
      .set({ status: "queued", stage: null, heartbeatAt: null, updatedAt: new Date() })
      .where(eq(setRuns.id, queuedRun.id));

    await db
      .update(submissions)
      .set({ status: "queued", updatedAt: new Date() })
      .where(eq(submissions.id, queuedRun.submissionId));

    await createWorkerEvent({
      submissionId: queuedRun.submissionId,
      setRunId: queuedRun.id,
      eventType: "set_run.dispatch_failed",
      message: error instanceof Error ? error.message : "Set run dispatch failed",
    });

    throw error;
  }
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
    dispatched: results.filter((r) => r.status === "fulfilled").length,
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

  if (isTerminalSetRunStatus(run.status)) {
    await syncSubmissionStatusFromRuns(run.submissionId);
    return {
      action: "already_terminal" as const,
      status: run.status,
      dispatch: await dispatchPendingWork(),
    };
  }

  if (run.cancelRequestedAt) {
    const now = new Date();
    await db
      .update(setRuns)
      .set({ status: "cancelled", stage: "cancelled", completedAt: now, updatedAt: now })
      .where(eq(setRuns.id, run.id));
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

  if (recognitionComplete) {
    if (run.attemptCount >= automaticRecoveryAttemptLimit) {
      await markSetRunFailed(
        run,
        `Automatic recovery exhausted after ${run.attemptCount} retries while waiting for publish`,
        details,
      );
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

  if (run.attemptCount >= automaticRecoveryAttemptLimit) {
    await markSetRunFailed(
      run,
      `Automatic recovery exhausted after ${run.attemptCount} retries with incomplete recognition state`,
      details,
    );
    await syncSubmissionStatusFromRuns(run.submissionId);
    return {
      action: "failed_after_recovery_limit" as const,
      dispatch: await dispatchPendingWork(),
    };
  }

  await requeueSetRunForFullRecovery(
    run,
    "Recognition workflow did not reach a terminal publishable state; requeuing automatically",
    details,
  );

  return {
    action: "requeued_for_full_retry" as const,
    dispatch: await dispatchPendingWork(),
  };
};
