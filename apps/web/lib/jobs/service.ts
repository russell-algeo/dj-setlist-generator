import { and, asc, desc, eq, inArray, isNull, sql } from "drizzle-orm";
import { z } from "zod";

import { dispatchDiscoverArtistWorkflow, dispatchProcessSetWorkflow } from "@/lib/github/workflows";
import { getDb } from "@/lib/db/client";
import {
  apiTokens,
  discoveryCandidates,
  segmentHits,
  setRunLeases,
  setRuns,
  submissions,
  workerEvents,
} from "@/lib/db/schema";
import type { SessionActor } from "@/lib/auth/session";

const db = getDb();
const activeSetRunStatuses = [
  "dispatched",
  "resolving",
  "recognizing",
  "aggregating",
  "enriching",
  "publishing",
  "running",
  "cancelling",
] as const;
const terminalSetRunStatuses = ["completed", "failed", "cancelled"] as const;
const automaticRecoveryAttemptLimit = 3;

const submissionSchema = z
  .object({
    mode: z.enum(["url", "artist", "curated_artist"]),
    sourceUrl: z.string().url().optional(),
    sourceUrls: z.array(z.string().url()).default([]),
    artistName: z.string().trim().min(1).optional(),
    createPlaylist: z.boolean().default(false),
    maxSetsOverride: z.number().int().positive().optional(),
  })
  .superRefine((value, ctx) => {
    if (value.mode === "url" && !value.sourceUrl) {
      ctx.addIssue({
        code: "custom",
        message: "A sourceUrl is required for url submissions",
        path: ["sourceUrl"],
      });
    }

    if (value.mode === "artist" && !value.artistName) {
      ctx.addIssue({
        code: "custom",
        message: "An artistName is required for artist submissions",
        path: ["artistName"],
      });
    }

    if (value.mode === "curated_artist") {
      if (!value.artistName) {
        ctx.addIssue({
          code: "custom",
          message: "An artistName is required for curated submissions",
          path: ["artistName"],
        });
      }

      if (value.sourceUrls.length === 0) {
        ctx.addIssue({
          code: "custom",
          message: "At least one source URL is required for curated submissions",
          path: ["sourceUrls"],
        });
      }
    }
  });

const createWorkerEvent = async (values: {
  submissionId?: string;
  setRunId?: string;
  eventType: string;
  message: string;
  details?: Record<string, unknown>;
}) => {
  await db.insert(workerEvents).values({
    submissionId: values.submissionId ?? null,
    setRunId: values.setRunId ?? null,
    eventType: values.eventType,
    message: values.message,
    details: values.details ?? {},
  });
};

const syncSubmissionStatusFromRuns = async (submissionId: string) => {
  const rows = await db
    .select({ status: setRuns.status })
    .from(setRuns)
    .where(eq(setRuns.submissionId, submissionId));

  if (rows.length === 0) {
    return null;
  }

  const totalCount = rows.length;
  const activeCount = rows.filter(
    ({ status }) =>
      status === "queued" ||
      activeSetRunStatuses.includes(status as (typeof activeSetRunStatuses)[number]),
  ).length;
  const failedCount = rows.filter(({ status }) => status === "failed").length;
  const cancelledCount = rows.filter(({ status }) => status === "cancelled").length;

  const nextStatus =
    activeCount > 0
      ? "running"
      : failedCount > 0
        ? "failed"
        : cancelledCount === totalCount
          ? "cancelled"
          : "completed";

  await db
    .update(submissions)
    .set({
      status: nextStatus,
      completedAt:
        nextStatus === "completed" || nextStatus === "failed" || nextStatus === "cancelled"
          ? new Date()
          : null,
      updatedAt: new Date(),
    })
    .where(eq(submissions.id, submissionId));

  return nextStatus;
};

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
        recognizedCount:
          sql<number>`count(*) filter (where ${segmentHits.recognized} = true)`,
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
      details: {
        ...(details ?? {}),
        result,
      },
    });
    return {
      action: "publish_retry_dispatched" as const,
      result,
    };
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

export type CreateSubmissionInput = z.infer<typeof submissionSchema>;

export const parseSubmissionInput = (value: unknown) => submissionSchema.parse(value);

export const createSubmission = async (actor: SessionActor, input: CreateSubmissionInput) => {
  const normalizedUrls =
    input.mode === "url"
      ? [input.sourceUrl!]
      : input.mode === "curated_artist"
        ? input.sourceUrls
        : [];

  const [submission] = await db
    .insert(submissions)
    .values({
      requestedBy: actor.userId,
      mode: input.mode,
      status: "queued",
      artistName: input.artistName ?? null,
      sourceUrl: input.sourceUrl ?? null,
      sourceUrls: normalizedUrls,
      createPlaylist: input.createPlaylist,
      maxSetsOverride: input.maxSetsOverride ?? null,
    })
    .returning();

  await createWorkerEvent({
    submissionId: submission.id,
    eventType: "submission.created",
    message: `Submission queued in ${input.mode} mode`,
    details: {
      mode: input.mode,
      sourceUrl: input.sourceUrl ?? null,
      sourceUrls: normalizedUrls,
      artistName: input.artistName ?? null,
    },
  });

  if (input.mode === "url" || input.mode === "curated_artist") {
    const runs = normalizedUrls.map((sourceUrl) => ({
      submissionId: submission.id,
      requestedBy: actor.userId,
      status: "queued",
      sourceUrl,
      sourcePlatform:
        sourceUrl.includes("soundcloud.com")
          ? "soundcloud"
          : sourceUrl.includes("youtu")
            ? "youtube"
            : "unknown",
      setTitle: null,
      createPlaylist: input.createPlaylist,
      sourceMetadata: {},
    }));

    if (runs.length > 0) {
      await db.insert(setRuns).values(runs);
    }
  }

  return submission;
};

export const getSubmissionDetail = async (submissionId: string) => {
  const [submission] = await db
    .select()
    .from(submissions)
    .where(eq(submissions.id, submissionId))
    .limit(1);

  if (!submission) {
    return null;
  }

  const [runs, events, candidates] = await Promise.all([
    db
      .select()
      .from(setRuns)
      .where(eq(setRuns.submissionId, submissionId))
      .orderBy(asc(setRuns.createdAt)),
    db
      .select()
      .from(workerEvents)
      .where(eq(workerEvents.submissionId, submissionId))
      .orderBy(desc(workerEvents.createdAt))
      .limit(50),
    db
      .select()
      .from(discoveryCandidates)
      .where(eq(discoveryCandidates.submissionId, submissionId))
      .orderBy(desc(discoveryCandidates.createdAt))
      .limit(50),
  ]);

  const runIds = runs.map((run) => run.id);
  const [leaseRollups, segmentHitCounts] = runIds.length
    ? await Promise.all([
        db
          .select({
            setRunId: setRunLeases.setRunId,
            totalCount: sql<number>`count(*)`,
            pendingCount: sql<number>`count(*) filter (where ${setRunLeases.status} = 'pending')`,
            claimedCount: sql<number>`count(*) filter (where ${setRunLeases.status} = 'claimed')`,
            completedCount: sql<number>`count(*) filter (where ${setRunLeases.status} = 'completed')`,
            failedCount: sql<number>`count(*) filter (where ${setRunLeases.status} = 'failed')`,
          })
          .from(setRunLeases)
          .where(inArray(setRunLeases.setRunId, runIds))
          .groupBy(setRunLeases.setRunId),
        db
          .select({
            setRunId: segmentHits.setRunId,
            hitCount: sql<number>`count(*)`,
            recognizedCount:
              sql<number>`count(*) filter (where ${segmentHits.recognized} = true)`,
          })
          .from(segmentHits)
          .where(inArray(segmentHits.setRunId, runIds))
          .groupBy(segmentHits.setRunId),
      ])
    : [[], []];

  const leaseRollupsByRun = new Map(
    leaseRollups.map((rollup) => [rollup.setRunId, rollup] as const),
  );
  const segmentHitsByRun = new Map(
    segmentHitCounts.map((rollup) => [rollup.setRunId, rollup] as const),
  );

  return {
    submission,
    runs: runs.map((run) => ({
      ...run,
      leaseRollup: leaseRollupsByRun.get(run.id) ?? null,
      segmentHitRollup: segmentHitsByRun.get(run.id) ?? null,
    })),
    events,
    discoveryCandidates: candidates,
  };
};

export const listSubmissionsForActor = async (actor: SessionActor) => {
  return db
    .select()
    .from(submissions)
    .where(actor.isAdmin ? undefined : eq(submissions.requestedBy, actor.userId))
    .orderBy(desc(submissions.createdAt))
    .limit(100);
};

export const getDashboardSummary = async (actor: SessionActor) => {
  const whereClause = actor.isAdmin ? undefined : eq(submissions.requestedBy, actor.userId);
  const [submissionCounts] = await db
    .select({
      total: sql<number>`count(${submissions.id})`,
      active: sql<number>`count(*) filter (where ${submissions.status} in ('queued', 'running', 'cancelling'))`,
      failed: sql<number>`count(*) filter (where ${submissions.status} = 'failed')`,
    })
    .from(submissions)
    .where(whereClause);

  const recentRuns = await db
    .select()
    .from(setRuns)
    .where(actor.isAdmin ? undefined : eq(setRuns.requestedBy, actor.userId))
    .orderBy(desc(setRuns.createdAt))
    .limit(10);

  return {
    totalSubmissions: Number(submissionCounts?.total ?? 0),
    activeSubmissions: Number(submissionCounts?.active ?? 0),
    failedSubmissions: Number(submissionCounts?.failed ?? 0),
    recentRuns,
  };
};

export const createApiTokenForUser = async (values: {
  userId: string;
  name: string;
  tokenPrefix: string;
  tokenHash: string;
}) => {
  const [token] = await db
    .insert(apiTokens)
    .values({
      userId: values.userId,
      name: values.name,
      tokenPrefix: values.tokenPrefix,
      tokenHash: values.tokenHash,
    })
    .returning();

  return token;
};

export const listApiTokensForUser = async (userId: string) =>
  db
    .select()
    .from(apiTokens)
    .where(and(eq(apiTokens.userId, userId), isNull(apiTokens.revokedAt)))
    .orderBy(desc(apiTokens.createdAt));

export const revokeApiTokenForUser = async (tokenId: string, actor: SessionActor) => {
  const [existing] = await db
    .select()
    .from(apiTokens)
    .where(
      and(
        eq(apiTokens.id, tokenId),
        actor.isAdmin ? undefined : eq(apiTokens.userId, actor.userId),
      ),
    )
    .limit(1);

  if (!existing) {
    return null;
  }

  await db
    .update(apiTokens)
    .set({
      revokedAt: new Date(),
      updatedAt: new Date(),
    })
    .where(eq(apiTokens.id, tokenId));

  return existing;
};

export const markSubmissionCancelled = async (submissionId: string) => {
  const now = new Date();

  await db
    .update(submissions)
    .set({
      status: "cancelling",
      cancelRequestedAt: now,
      updatedAt: now,
    })
    .where(eq(submissions.id, submissionId));

  await db
    .update(setRuns)
    .set({
      cancelRequestedAt: now,
      status: sql`case when ${setRuns.status} = 'queued' then 'cancelled' else 'cancelling' end`,
      updatedAt: now,
      completedAt: sql`case when ${setRuns.status} = 'queued' then now() else ${setRuns.completedAt} end`,
    })
    .where(
      and(
        eq(setRuns.submissionId, submissionId),
        inArray(setRuns.status, ["queued", ...activeSetRunStatuses]),
      ),
    );

  await createWorkerEvent({
    submissionId,
    eventType: "submission.cancel_requested",
    message: "Cancellation requested",
  });
};

export const retrySubmission = async (submissionId: string) => {
  const now = new Date();

  const runIds = await db
    .select({ id: setRuns.id })
    .from(setRuns)
    .where(eq(setRuns.submissionId, submissionId));

  if (runIds.length > 0) {
    const ids = runIds.map((row) => row.id);
    await db.delete(discoveryCandidates).where(eq(discoveryCandidates.submissionId, submissionId));
    await db.delete(segmentHits).where(inArray(segmentHits.setRunId, ids));
    await db.delete(setRunLeases).where(inArray(setRunLeases.setRunId, ids));
  }

  await db
    .update(submissions)
    .set({
      status: "queued",
      warningSummary: null,
      errorSummary: null,
      cancelRequestedAt: null,
      completedAt: null,
      updatedAt: now,
    })
    .where(eq(submissions.id, submissionId));

  await db
    .update(setRuns)
    .set({
      status: "queued",
      stage: null,
      errorSummary: null,
      cancelRequestedAt: null,
      completedAt: null,
      heartbeatAt: null,
      updatedAt: now,
    })
    .where(eq(setRuns.submissionId, submissionId));

  await createWorkerEvent({
    submissionId,
    eventType: "submission.retried",
    message: "Submission returned to queue",
  });
};

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
      .set({
        status: "queued",
        updatedAt: new Date(),
      })
      .where(eq(submissions.id, submission.id));

    await createWorkerEvent({
      submissionId: submission.id,
      eventType: "submission.dispatch_failed",
      message: error instanceof Error ? error.message : "Discover artist dispatch failed",
    });

    throw error;
  }
};

export const dispatchNextQueuedSetRun = async () => {
  const claimed = await db.execute(sql`select * from ops.claim_next_dispatchable_set_run(1) limit 1`);
  const claimedSetRunId = claimed.rows[0]?.id ? String(claimed.rows[0].id) : null;

  const [queuedRun] = claimedSetRunId
    ? await db.select().from(setRuns).where(eq(setRuns.id, claimedSetRunId)).limit(1)
    : [];

  if (!queuedRun) {
    const [activeRun] = await db
      .select({ id: setRuns.id })
      .from(setRuns)
      .where(inArray(setRuns.status, [...activeSetRunStatuses]))
      .limit(1);

    return {
      setRun: null,
      result: {
        dispatched: false,
        reason: activeRun ? "active_run_present" : "queue_empty",
      } as const,
    };
  }

  await db
    .update(submissions)
    .set({
      status: "running",
      updatedAt: new Date(),
    })
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
    return {
      setRun: queuedRun,
      result,
    };
  } catch (error) {
    await db
      .update(setRuns)
      .set({
        status: "queued",
        stage: null,
        heartbeatAt: null,
        updatedAt: new Date(),
      })
      .where(eq(setRuns.id, queuedRun.id));

    await db
      .update(submissions)
      .set({
        status: "queued",
        updatedAt: new Date(),
      })
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

export const dispatchPendingWork = async () => {
  const [artistDispatch, setDispatch] = await Promise.all([
    dispatchQueuedArtistSubmission(),
    dispatchNextQueuedSetRun(),
  ]);

  return {
    artistDispatch,
    setDispatch,
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
    return {
      action: "missing_set_run" as const,
    };
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
    return {
      action: "superseded_workflow_finalize_ignored" as const,
    };
  }

  if (terminalSetRunStatuses.includes(run.status as (typeof terminalSetRunStatuses)[number])) {
    await syncSubmissionStatusFromRuns(run.submissionId);
    return {
      action: "already_terminal" as const,
      status: run.status,
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

export const runSchedulerRecovery = async () => {
  const leaseRecovery = await db.execute(
    sql`select ops.recover_stale_leases(interval '15 minutes') as recovered`,
  );
  const runRecovery = await db.execute(
    sql`select ops.recover_stale_set_runs(interval '30 minutes') as recovered`,
  );

  const { artistDispatch, setDispatch } = await dispatchPendingWork();

  return {
    recoveredLeases: Number(leaseRecovery.rows[0]?.recovered ?? 0),
    recoveredRuns: Number(runRecovery.rows[0]?.recovered ?? 0),
    artistDispatch,
    setDispatch,
  };
};
