import "server-only";

import { and, desc, eq, inArray, sql } from "drizzle-orm";

import type { SessionActor } from "@/lib/auth/session";
import { getDb } from "@/lib/db/client";
import { setRuns, submissions, workerEvents } from "@/lib/db/schema";
import { setRunRetryAttemptLimit } from "./policy";
import {
  getTimelineSummary,
  getTimelineTone,
  normalizePublicSubmissionFilter,
  type PublicSubmissionFilter,
  type SubmissionActionSummary,
  type SubmissionCountsDto,
  type SubmissionDetailDto,
  type SubmissionListItemDto,
  type SubmissionRunActionSummary,
  type TimelineItemDto,
} from "@/lib/jobs/public";
import { getSubmissionDetail } from "@/lib/jobs/submissions";
import {
  activeSetRunStatuses,
  isActiveSubmissionStatus,
  isCancellableSetRunStatus,
  isRetryableSetRun,
  summarizeSetRunCounts,
  summarizeSubmissionActions,
} from "@/lib/jobs/status";

const db = getDb();

const emptyCounts: SubmissionCountsDto = {
  totalCount: 0,
  queuedCount: 0,
  inFlightCount: 0,
  activeCount: 0,
  completedCount: 0,
  failedCount: 0,
  cancelledCount: 0,
  terminalCount: 0,
};

const emptyActions: SubmissionActionSummary = {
  retryableCount: 0,
  exhaustedRetryCount: 0,
  cancellableCount: 0,
  canRetry: false,
  canCancel: false,
};

const publicTimelineEventTypes = new Set([
  "submission.created",
  "submission.dispatch",
  "submission.dispatch_failed",
  "submission.discovery.started",
  "submission.discovery.completed",
  "submission.discovery.empty",
  "submission.discovery.failed",
  "submission.retried",
  "submission.cancel_requested",
  "set_run.dispatch",
  "set_run.retried",
  "set_run.cancel_requested",
  "set_run.dispatch_failed",
  "set_run.bootstrap.started",
  "set_run.recognition.started",
  "set_run.publish.started",
  "set_run.requeued",
  "set_run.failed",
  "set_run.cancelled",
  "set_run.completed",
  "set_run.publish_retry_dispatched",
]);

const getFilterClause = (filter: PublicSubmissionFilter) => {
  if (filter === "all") {
    return undefined;
  }

  if (filter === "active") {
    return inArray(submissions.status, ["queued", "running", "cancelling"]);
  }

  return eq(submissions.status, filter);
};

const buildRunActionSummary = (status: string, attemptCount: number): SubmissionRunActionSummary => {
  const canRetry = isRetryableSetRun(status, attemptCount);
  const retryExhausted =
    (status === "failed" || status === "cancelled") && attemptCount >= setRunRetryAttemptLimit;

  return {
    retryableCount: canRetry ? 1 : 0,
    exhaustedRetryCount: retryExhausted ? 1 : 0,
    cancellableCount: isCancellableSetRunStatus(status) ? 1 : 0,
    canRetry,
    canCancel: isCancellableSetRunStatus(status),
    retryBudgetRemaining: Math.max(setRunRetryAttemptLimit - attemptCount, 0),
    retryExhausted,
  };
};

const buildTimelineItems = (
  events: Array<{
    id: string;
    eventType: string;
    message: string;
    createdAt: Date;
    setRunId: string | null;
  }>,
): TimelineItemDto[] =>
  events
    .filter((event) => publicTimelineEventTypes.has(event.eventType))
    .slice(0, 15)
    .map((event) => ({
      id: event.id,
      eventType: event.eventType,
      summary: getTimelineSummary(event.eventType, event.message),
      message: event.message,
      createdAt: event.createdAt.toISOString(),
      setRunId: event.setRunId,
      tone: getTimelineTone(event.eventType),
    }));

export const listPublicSubmissionsForActor = async (
  actor: SessionActor,
  requestedFilter?: string,
): Promise<SubmissionListItemDto[]> => {
  const filter = normalizePublicSubmissionFilter(requestedFilter);
  const whereClause = and(
    actor.isAdmin ? undefined : eq(submissions.requestedBy, actor.userId),
    getFilterClause(filter),
  );

  const rows = await db
    .select()
    .from(submissions)
    .where(whereClause)
    .orderBy(desc(submissions.createdAt))
    .limit(100);

  if (rows.length === 0) {
    return [];
  }

  const submissionIds = rows.map((row) => row.id);

  const [runCounts, recentEvents] = await Promise.all([
    db
      .select({
        submissionId: setRuns.submissionId,
        totalCount: sql<number>`count(*)`,
        queuedCount: sql<number>`count(*) filter (where ${setRuns.status} = 'queued')`,
        inFlightCount: sql<number>`count(*) filter (where ${inArray(setRuns.status, [...activeSetRunStatuses])})`,
        completedCount: sql<number>`count(*) filter (where ${setRuns.status} = 'completed')`,
        failedCount: sql<number>`count(*) filter (where ${setRuns.status} = 'failed')`,
        cancelledCount: sql<number>`count(*) filter (where ${setRuns.status} = 'cancelled')`,
        retryableCount: sql<number>`count(*) filter (where ${setRuns.status} in ('failed', 'cancelled') and ${setRuns.attemptCount} < ${setRunRetryAttemptLimit})`,
        exhaustedRetryCount: sql<number>`count(*) filter (where ${setRuns.status} in ('failed', 'cancelled') and ${setRuns.attemptCount} >= ${setRunRetryAttemptLimit})`,
        cancellableCount: sql<number>`count(*) filter (where ${setRuns.status} = 'queued' or ${inArray(setRuns.status, [...activeSetRunStatuses])})`,
      })
      .from(setRuns)
      .where(inArray(setRuns.submissionId, submissionIds))
      .groupBy(setRuns.submissionId),
    db
      .select({
        submissionId: workerEvents.submissionId,
        message: workerEvents.message,
        createdAt: workerEvents.createdAt,
      })
      .from(workerEvents)
      .where(inArray(workerEvents.submissionId, submissionIds))
      .orderBy(desc(workerEvents.createdAt)),
  ]);

  const countsBySubmission = new Map(
    runCounts.map((row) => {
      const counts: SubmissionCountsDto = {
        totalCount: Number(row.totalCount ?? 0),
        queuedCount: Number(row.queuedCount ?? 0),
        inFlightCount: Number(row.inFlightCount ?? 0),
        activeCount: Number(row.queuedCount ?? 0) + Number(row.inFlightCount ?? 0),
        completedCount: Number(row.completedCount ?? 0),
        failedCount: Number(row.failedCount ?? 0),
        cancelledCount: Number(row.cancelledCount ?? 0),
        terminalCount:
          Number(row.completedCount ?? 0) +
          Number(row.failedCount ?? 0) +
          Number(row.cancelledCount ?? 0),
      };

      const actions: SubmissionActionSummary = {
        retryableCount: Number(row.retryableCount ?? 0),
        exhaustedRetryCount: Number(row.exhaustedRetryCount ?? 0),
        cancellableCount: Number(row.cancellableCount ?? 0),
        canRetry: Number(row.retryableCount ?? 0) > 0,
        canCancel: Number(row.cancellableCount ?? 0) > 0,
      };

      return [row.submissionId, { counts, actions }] as const;
    }),
  );

  const latestEventBySubmission = new Map<
    string,
    { message: string; createdAt: Date | null }
  >();

  for (const event of recentEvents) {
    if (!event.submissionId || latestEventBySubmission.has(event.submissionId)) {
      continue;
    }

    latestEventBySubmission.set(event.submissionId, {
      message: event.message,
      createdAt: event.createdAt,
    });
  }

  return rows.map((row) => {
    const aggregated = countsBySubmission.get(row.id);
    const counts = aggregated?.counts ?? emptyCounts;
    const actions = aggregated?.actions ?? emptyActions;
    const latestEvent = latestEventBySubmission.get(row.id);
    const lastActivityAt = latestEvent?.createdAt ?? row.updatedAt ?? row.createdAt;

    return {
      id: row.id,
      mode: row.mode,
      status: row.status,
      displayTitle: row.artistName ?? row.sourceUrl ?? row.id,
      artistName: row.artistName ?? null,
      sourceUrl: row.sourceUrl ?? null,
      createdAt: row.createdAt.toISOString(),
      lastActivityAt: lastActivityAt.toISOString(),
      lastActivityMessage: latestEvent?.message ?? null,
      counts,
      actions,
      hasActiveWork: counts.activeCount > 0 || isActiveSubmissionStatus(row.status),
    };
  });
};

export const serializeSubmissionDetail = (
  detail: NonNullable<Awaited<ReturnType<typeof getSubmissionDetail>>>,
): SubmissionDetailDto => {
  const counts = summarizeSetRunCounts(detail.runs);
  const actions = summarizeSubmissionActions(detail.runs);
  const totalHits = detail.runs.reduce((sum, run) => sum + Number(run.segmentHitRollup?.hitCount ?? 0), 0);
  const totalRecognized = detail.runs.reduce(
    (sum, run) => sum + Number(run.segmentHitRollup?.recognizedCount ?? 0),
    0,
  );
  const latestEvent = detail.events[0] ?? null;

  return {
    submission: {
      id: detail.submission.id,
      mode: detail.submission.mode,
      status: detail.submission.status,
      artistName: detail.submission.artistName ?? null,
      sourceUrl: detail.submission.sourceUrl ?? null,
      createdAt: detail.submission.createdAt.toISOString(),
      updatedAt: detail.submission.updatedAt.toISOString(),
    },
    counts,
    actions,
    totalHits,
    totalRecognized,
    recognitionRate: totalHits > 0 ? Math.round((totalRecognized / totalHits) * 100) : null,
    hasActiveWork: counts.activeCount > 0 || isActiveSubmissionStatus(detail.submission.status),
    lastActivityAt: (latestEvent?.createdAt ?? detail.submission.updatedAt).toISOString(),
    lastActivityMessage: latestEvent?.message ?? null,
    discoveryCandidateCount: detail.discoveryCandidates.length,
    runs: detail.runs.map((run) => ({
      id: run.id,
      sourceUrl: run.sourceUrl,
      sourcePlatform: run.sourcePlatform,
      title: run.setTitle,
      stage: run.stage,
      status: run.status,
      errorSummary: run.errorSummary,
      publishedSetId: run.publishedSetId,
      attemptCount: run.attemptCount,
      createdAt: run.createdAt.toISOString(),
      updatedAt: (run.heartbeatAt ?? run.updatedAt)?.toISOString() ?? null,
      progress:
        run.leaseRollup || run.segmentHitRollup
          ? {
              totalLeases: Number(run.leaseRollup?.totalCount ?? 0),
              completedLeases: Number(run.leaseRollup?.completedCount ?? 0),
              hitCount: Number(run.segmentHitRollup?.hitCount ?? 0),
              recognizedCount: Number(run.segmentHitRollup?.recognizedCount ?? 0),
            }
          : null,
      actions: buildRunActionSummary(run.status, run.attemptCount),
    })),
    timeline: buildTimelineItems(
      detail.events.map((event) => ({
        id: event.id,
        eventType: event.eventType,
        message: event.message,
        createdAt: event.createdAt,
        setRunId: event.setRunId,
      })),
    ),
  };
};

export const getPublicSubmissionDetail = async (submissionId: string) => {
  const detail = await getSubmissionDetail(submissionId);
  return detail ? serializeSubmissionDetail(detail) : null;
};
