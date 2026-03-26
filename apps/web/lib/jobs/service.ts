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

  return {
    submission,
    runs,
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
