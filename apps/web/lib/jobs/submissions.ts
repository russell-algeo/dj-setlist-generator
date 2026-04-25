import "server-only";

import { and, asc, desc, eq, inArray, isNotNull, isNull, sql } from "drizzle-orm";
import { z } from "zod";

import { getDb } from "@/lib/db/client";
import {
  discoveryCandidates,
  segmentHits,
  setRunLeases,
  setRuns,
  spotifyConnections,
  submissions,
  workerEvents,
} from "@/lib/db/schema";
import type { SessionActor } from "@/lib/auth/session";
import { createWorkerEvent } from "@/lib/jobs/internal";
import { setRunRetryAttemptLimit } from "./policy";
import {
  activeSetRunStatuses,
  isRetryableSetRun,
  summarizeSetRunCounts,
} from "@/lib/jobs/status";
import { prepareArtistAliases } from "@/lib/jobs/artist-aliases";

const db = getDb();

const submissionSchema = z
  .object({
    mode: z.enum(["artist", "curated_artist"]),
    sourceUrl: z.string().url().optional(),
    sourceUrls: z.array(z.string().url()).default([]),
    artistName: z.string().trim().min(1).optional(),
    artistAliases: z.array(z.string()).default([]),
    createPlaylist: z.boolean().default(false),
    maxSetsOverride: z.number().int().positive().optional(),
  })
  .superRefine((value, ctx) => {
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

    if (
      prepareArtistAliases({
        mode: value.mode,
        artistName: value.artistName,
        artistAliases: value.artistAliases,
      }).exceedsLimit
    ) {
      ctx.addIssue({
        code: "custom",
        message: "You can add up to 5 aliases",
        path: ["artistAliases"],
      });
    }
  })
  .transform((value) => ({
    ...value,
    artistAliases: prepareArtistAliases({
      mode: value.mode,
      artistName: value.artistName,
      artistAliases: value.artistAliases,
    }).aliases,
  }));

export type CreateSubmissionInput = z.infer<typeof submissionSchema>;

export const parseSubmissionInput = (value: unknown) => submissionSchema.parse(value);

// Exported so dispatch.ts can call it after changing run states.
export const syncSubmissionStatusFromRuns = async (submissionId: string) => {
  const rows = await db
    .select({ status: setRuns.status })
    .from(setRuns)
    .where(eq(setRuns.submissionId, submissionId));

  if (rows.length === 0) {
    return null;
  }

  const {
    totalCount,
    activeCount,
    completedCount,
    failedCount,
    cancelledCount,
  } = summarizeSetRunCounts(rows);

  const nextStatus =
    activeCount > 0
      ? "running"
      : failedCount > 0 && completedCount > 0
        ? "partial"
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
        nextStatus === "completed" ||
        nextStatus === "partial" ||
        nextStatus === "failed" ||
        nextStatus === "cancelled"
          ? new Date()
          : null,
      updatedAt: new Date(),
    })
    .where(eq(submissions.id, submissionId));

  return nextStatus;
};

export const createSubmission = async (actor: SessionActor, input: CreateSubmissionInput) => {
  const normalizedUrls =
    input.mode === "curated_artist"
      ? input.sourceUrls
      : [];
  const normalizedArtistAliases = input.mode === "artist" ? input.artistAliases : [];

  // If the user asked for playlist creation, verify they have an active Spotify connection.
  // If not, accept the submission but downgrade createPlaylist and surface a warning.
  let effectiveCreatePlaylist = input.createPlaylist;
  const warnings: string[] = [];

  if (input.createPlaylist) {
    const [connection] = await db
      .select({ userId: spotifyConnections.userId })
      .from(spotifyConnections)
      .where(
        and(
          eq(spotifyConnections.userId, actor.userId),
          isNotNull(spotifyConnections.refreshTokenCiphertext),
          isNull(spotifyConnections.revokedAt),
        ),
      )
      .limit(1);

    if (!connection) {
      effectiveCreatePlaylist = false;
      warnings.push(
        "Spotify playlist creation was disabled: no Spotify account connected. Connect Spotify in Settings and resubmit to enable playlists.",
      );
    }
  }

  const [submission] = await db
    .insert(submissions)
    .values({
      requestedBy: actor.userId,
      mode: input.mode,
      status: "queued",
      artistName: input.artistName ?? null,
      artistAliases: normalizedArtistAliases,
      sourceUrl: input.sourceUrl ?? null,
      sourceUrls: normalizedUrls,
      createPlaylist: effectiveCreatePlaylist,
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
      artistAliases: normalizedArtistAliases.length > 0 ? normalizedArtistAliases : undefined,
      createPlaylist: effectiveCreatePlaylist,
      warnings: warnings.length > 0 ? warnings : undefined,
    },
  });

  if (input.mode === "curated_artist") {
    // Dedup: find URLs already published in a completed run so we don't re-process them.
    const dedupedByUrl = new Map<string, string>(); // sourceUrl → publishedSetId
    const existingCompleted = await db
      .select({ sourceUrl: setRuns.sourceUrl, publishedSetId: setRuns.publishedSetId })
      .from(setRuns)
      .where(
        and(
          inArray(setRuns.sourceUrl, normalizedUrls),
          eq(setRuns.status, "completed"),
          isNotNull(setRuns.publishedSetId),
          isNull(setRuns.archiveRemovedAt),
        ),
      );
    for (const row of existingCompleted) {
      if (row.sourceUrl && row.publishedSetId && !dedupedByUrl.has(row.sourceUrl)) {
        dedupedByUrl.set(row.sourceUrl, row.publishedSetId);
      }
    }

    const now = new Date();
    const runs = normalizedUrls.map((sourceUrl) => {
      const existingPublishedSetId = dedupedByUrl.get(sourceUrl) ?? null;
      return {
        submissionId: submission.id,
        requestedBy: actor.userId,
        status: existingPublishedSetId ? "completed" : "queued",
        stage: existingPublishedSetId ? "deduped" : null,
        sourceUrl,
        sourcePlatform: sourceUrl.includes("soundcloud.com")
          ? "soundcloud"
          : sourceUrl.includes("youtu")
            ? "youtube"
            : "unknown",
        setTitle: null,
        createPlaylist: effectiveCreatePlaylist,
        sourceMetadata: {},
        publishedSetId: existingPublishedSetId,
        completedAt: existingPublishedSetId ? now : null,
      };
    });

    if (runs.length > 0) {
      await db.insert(setRuns).values(runs);
    }

    // If any runs were deduped, sync submission status immediately so it doesn't
    // stay stuck as "queued" when all its runs are already completed.
    if (dedupedByUrl.size > 0) {
      await syncSubmissionStatusFromRuns(submission.id);
    }
  }

  return { submission, warnings };
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
            recognizedCount: sql<number>`count(*) filter (where ${segmentHits.recognized} = true)`,
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

export const listSubmissionsForActor = async (actor: SessionActor) =>
  db
    .select()
    .from(submissions)
    .where(actor.isAdmin ? undefined : eq(submissions.requestedBy, actor.userId))
    .orderBy(desc(submissions.createdAt))
    .limit(100);

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

export type RetrySetRunsResult = {
  targetRunIds: string[];
  retriedRunIds: string[];
  skippedExhaustedRunIds: string[];
  skippedIneligibleRunIds: string[];
  retriedCount: number;
  skippedExhaustedCount: number;
  skippedIneligibleCount: number;
  nothingToRetry: boolean;
};

export type CancelSetRunsResult = {
  targetRunIds: string[];
  cancelledRunIds: string[];
  cancellingRunIds: string[];
  skippedIneligibleRunIds: string[];
  cancelledCount: number;
  cancellingCount: number;
  skippedIneligibleCount: number;
  affectedCount: number;
  nothingToCancel: boolean;
};

export const getSubmissionSetRun = async (submissionId: string, setRunId: string) => {
  const [run] = await db
    .select()
    .from(setRuns)
    .where(and(eq(setRuns.submissionId, submissionId), eq(setRuns.id, setRunId)))
    .limit(1);

  return run ?? null;
};

const getSubmissionRuns = async (submissionId: string, setRunIds?: readonly string[]) => {
  if (setRunIds && setRunIds.length === 0) {
    return [];
  }

  return db
    .select({
      id: setRuns.id,
      status: setRuns.status,
      attemptCount: setRuns.attemptCount,
    })
    .from(setRuns)
    .where(
      and(
        eq(setRuns.submissionId, submissionId),
        setRunIds ? inArray(setRuns.id, [...setRunIds]) : undefined,
      ),
    );
};

const retrySetRunsInternal = async (
  submissionId: string,
  setRunIds?: readonly string[],
): Promise<RetrySetRunsResult> => {
  const now = new Date();
  const runs = await getSubmissionRuns(submissionId, setRunIds);

  const retriedRunIds = runs
    .filter((run) => isRetryableSetRun(run.status, run.attemptCount))
    .map((run) => run.id);
  const skippedExhaustedRunIds = runs
    .filter(
      (run) =>
        (run.status === "failed" || run.status === "cancelled") &&
        run.attemptCount >= setRunRetryAttemptLimit,
    )
    .map((run) => run.id);
  const skippedIneligibleRunIds = runs
    .filter((run) => !retriedRunIds.includes(run.id) && !skippedExhaustedRunIds.includes(run.id))
    .map((run) => run.id);

  if (retriedRunIds.length === 0) {
    return {
      targetRunIds: runs.map((run) => run.id),
      retriedRunIds,
      skippedExhaustedRunIds,
      skippedIneligibleRunIds,
      retriedCount: 0,
      skippedExhaustedCount: skippedExhaustedRunIds.length,
      skippedIneligibleCount: skippedIneligibleRunIds.length,
      nothingToRetry: true,
    };
  }

  await db.delete(segmentHits).where(inArray(segmentHits.setRunId, retriedRunIds));
  await db.delete(setRunLeases).where(inArray(setRunLeases.setRunId, retriedRunIds));

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
    .where(inArray(setRuns.id, retriedRunIds));

  await syncSubmissionStatusFromRuns(submissionId);

  await createWorkerEvent({
    submissionId,
    setRunId: retriedRunIds.length === 1 ? retriedRunIds[0] : undefined,
    eventType: retriedRunIds.length === 1 ? "set_run.retried" : "submission.retried",
    message:
      retriedRunIds.length === 1
        ? "Run returned to queue"
        : `${retriedRunIds.length} failed/cancelled run(s) returned to queue`,
    details: {
      retriedRunIds,
      skippedExhaustedRunIds,
      skippedIneligibleRunIds,
    },
  });

  return {
    targetRunIds: runs.map((run) => run.id),
    retriedRunIds,
    skippedExhaustedRunIds,
    skippedIneligibleRunIds,
    retriedCount: retriedRunIds.length,
    skippedExhaustedCount: skippedExhaustedRunIds.length,
    skippedIneligibleCount: skippedIneligibleRunIds.length,
    nothingToRetry: false,
  };
};

const cancelSetRunsInternal = async (
  submissionId: string,
  setRunIds?: readonly string[],
  options?: { submissionScope?: boolean },
): Promise<CancelSetRunsResult> => {
  const now = new Date();
  const runs = await getSubmissionRuns(submissionId, setRunIds);

  const cancelledRunIds = runs
    .filter((run) => run.status === "queued")
    .map((run) => run.id);
  const cancellingRunIds = runs
    .filter((run) => activeSetRunStatuses.includes(run.status as (typeof activeSetRunStatuses)[number]))
    .map((run) => run.id);
  const skippedIneligibleRunIds = runs
    .filter((run) => !cancelledRunIds.includes(run.id) && !cancellingRunIds.includes(run.id))
    .map((run) => run.id);

  if (cancelledRunIds.length === 0 && cancellingRunIds.length === 0) {
    return {
      targetRunIds: runs.map((run) => run.id),
      cancelledRunIds,
      cancellingRunIds,
      skippedIneligibleRunIds,
      cancelledCount: 0,
      cancellingCount: 0,
      skippedIneligibleCount: skippedIneligibleRunIds.length,
      affectedCount: 0,
      nothingToCancel: true,
    };
  }

  if (cancelledRunIds.length > 0) {
    await db
      .update(setRuns)
      .set({
        cancelRequestedAt: now,
        status: "cancelled",
        stage: "cancelled",
        updatedAt: now,
        completedAt: now,
      })
      .where(inArray(setRuns.id, cancelledRunIds));
  }

  if (cancellingRunIds.length > 0) {
    await db
      .update(setRuns)
      .set({
        cancelRequestedAt: now,
        status: "cancelling",
        updatedAt: now,
      })
      .where(inArray(setRuns.id, cancellingRunIds));
  }

  if (options?.submissionScope) {
    await db
      .update(submissions)
      .set({
        status: "cancelling",
        cancelRequestedAt: now,
        updatedAt: now,
      })
      .where(eq(submissions.id, submissionId));
  } else {
    await syncSubmissionStatusFromRuns(submissionId);
  }

  await createWorkerEvent({
    submissionId,
    setRunId:
      cancelledRunIds.length + cancellingRunIds.length === 1
        ? cancelledRunIds[0] ?? cancellingRunIds[0]
        : undefined,
    eventType:
      options?.submissionScope || cancelledRunIds.length + cancellingRunIds.length > 1
        ? "submission.cancel_requested"
        : "set_run.cancel_requested",
    message:
      options?.submissionScope || cancelledRunIds.length + cancellingRunIds.length > 1
        ? "Cancellation requested"
        : "Run cancellation requested",
    details: {
      cancelledRunIds,
      cancellingRunIds,
      skippedIneligibleRunIds,
    },
  });

  return {
    targetRunIds: runs.map((run) => run.id),
    cancelledRunIds,
    cancellingRunIds,
    skippedIneligibleRunIds,
    cancelledCount: cancelledRunIds.length,
    cancellingCount: cancellingRunIds.length,
    skippedIneligibleCount: skippedIneligibleRunIds.length,
    affectedCount: cancelledRunIds.length + cancellingRunIds.length,
    nothingToCancel: false,
  };
};

export const markSubmissionCancelled = async (submissionId: string) =>
  cancelSetRunsInternal(submissionId, undefined, { submissionScope: true });

export const cancelSubmissionSetRun = async (submissionId: string, setRunId: string) =>
  cancelSetRunsInternal(submissionId, [setRunId]);

export const retryFailedSetRuns = async (submissionId: string): Promise<RetrySetRunsResult> =>
  retrySetRunsInternal(submissionId);

export const retrySubmissionSetRun = async (submissionId: string, setRunId: string) =>
  retrySetRunsInternal(submissionId, [setRunId]);
