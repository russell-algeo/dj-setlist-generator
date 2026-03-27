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
import { activeSetRunStatuses, createWorkerEvent } from "@/lib/jobs/internal";

const db = getDb();

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

  const totalCount = rows.length;
  const activeCount = rows.filter(
    ({ status }) =>
      status === "queued" ||
      activeSetRunStatuses.includes(status as (typeof activeSetRunStatuses)[number]),
  ).length;
  const completedCount = rows.filter(({ status }) => status === "completed").length;
  const failedCount = rows.filter(({ status }) => status === "failed").length;
  const cancelledCount = rows.filter(({ status }) => status === "cancelled").length;

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
    input.mode === "url"
      ? [input.sourceUrl!]
      : input.mode === "curated_artist"
        ? input.sourceUrls
        : [];

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
      createPlaylist: effectiveCreatePlaylist,
      warnings: warnings.length > 0 ? warnings : undefined,
    },
  });

  if (input.mode === "url" || input.mode === "curated_artist") {
    const runs = normalizedUrls.map((sourceUrl) => ({
      submissionId: submission.id,
      requestedBy: actor.userId,
      status: "queued",
      sourceUrl,
      sourcePlatform: sourceUrl.includes("soundcloud.com")
        ? "soundcloud"
        : sourceUrl.includes("youtu")
          ? "youtube"
          : "unknown",
      setTitle: null,
      createPlaylist: effectiveCreatePlaylist,
      sourceMetadata: {},
    }));

    if (runs.length > 0) {
      await db.insert(setRuns).values(runs);
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

// Retries only the failed or cancelled set-runs within a submission.
// Returns "nothing_to_retry" when all child runs have already completed successfully.
export const retryFailedSetRuns = async (
  submissionId: string,
): Promise<"retried" | "nothing_to_retry"> => {
  const now = new Date();

  const retryableRuns = await db
    .select({ id: setRuns.id })
    .from(setRuns)
    .where(
      and(
        eq(setRuns.submissionId, submissionId),
        inArray(setRuns.status, ["failed", "cancelled"]),
      ),
    );

  if (retryableRuns.length === 0) {
    return "nothing_to_retry";
  }

  const ids = retryableRuns.map((row) => row.id);
  await db.delete(segmentHits).where(inArray(segmentHits.setRunId, ids));
  await db.delete(setRunLeases).where(inArray(setRunLeases.setRunId, ids));

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
    .where(inArray(setRuns.id, ids));

  // Recalculate submission status now that some runs are back to queued.
  await syncSubmissionStatusFromRuns(submissionId);

  await createWorkerEvent({
    submissionId,
    eventType: "submission.retried",
    message: `${retryableRuns.length} failed/cancelled run(s) returned to queue`,
    details: { retryedRunIds: ids },
  });

  return "retried";
};
