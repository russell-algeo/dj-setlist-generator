// Frozen reader semantics from 291eab5; test-only, never an application reader.
import "server-only";
import { and, desc, eq, inArray } from "drizzle-orm";
import { getDb } from "@/lib/db/client";
import { setRuns, workerEvents, submissions } from "@/lib/db/schema";
import { getTimelineSummary, getTimelineTone, type TimelineItemDto, type SubmissionRunEventsPageDto } from "@/lib/jobs/public";
import type { SessionActor } from "@/lib/auth/session";
import { readableSubmissionPredicate } from "@/lib/archive/access-policy";
const db = getDb();

const publicRunTimelineEventTypes = new Set([
  "set_run.dispatch",
  "set_run.dispatch_failed",
  "set_run.bootstrap.started",
  "set_run.bootstrap.completed",
  "set_run.recognition.started",
  "set_run.recognition.completed",
  "set_run.aggregate.started",
  "set_run.enrich.started",
  "set_run.publish.started",
  "set_run.publish.deferred",
  "set_run.retried",
  "set_run.cancel_requested",
  "set_run.requeued",
  "set_run.failed",
  "set_run.cancelled",
  "set_run.completed",
  "set_run.publish_retry_dispatched",
]);

const currentAttemptBoundaryEventTypes = new Set([
  "set_run.retried",
  "set_run.requeued",
  "set_run.dispatch",
  "set_run.publish_retry_dispatched",
  "set_run.bootstrap.started",
]);

const buildTimelineItems = (
  events: Array<{
    id: string;
    eventType: string;
    message: string;
    createdAt: Date;
    setRunId: string | null;
    details?: unknown;
  }>,
): TimelineItemDto[] =>
  events
    .filter((event) => publicRunTimelineEventTypes.has(event.eventType))
    .map((event) => ({
      id: event.id,
      eventType: event.eventType,
      summary: getTimelineSummary(event.eventType, event.message),
      message: event.message,
      createdAt: event.createdAt.toISOString(),
      setRunId: event.setRunId,
      tone: getTimelineTone(event.eventType),
    }));

const selectCurrentAttemptEvents = <
  T extends {
    eventType: string;
    createdAt: Date;
  },
>(
  events: readonly T[],
) => {
  const boundary = events.find((event) => currentAttemptBoundaryEventTypes.has(event.eventType));
  if (!boundary) {
    return [...events];
  }

  const boundaryTimestamp = boundary.createdAt.getTime();
  return events.filter((event) => event.createdAt.getTime() >= boundaryTimestamp);
};

export const getPublicSubmissionRunEventsPage = async ({
  actor,
  page,
  pageSize,
  setRunId,
  submissionId,
}: {
  actor: SessionActor;
  page: number;
  pageSize: number;
  setRunId: string;
  submissionId: string;
}): Promise<SubmissionRunEventsPageDto | null> => {
  const [run] = await db
    .select({ id: setRuns.id })
    .from(setRuns)
    .innerJoin(submissions, eq(submissions.id, setRuns.submissionId))
    .where(and(eq(setRuns.id, setRunId), eq(setRuns.submissionId, submissionId), readableSubmissionPredicate(actor.userId, actor.isAdmin)))
    .limit(1);

  if (!run) {
    return null;
  }

  const allEvents = await db
    .select({
      id: workerEvents.id,
      eventType: workerEvents.eventType,
      message: workerEvents.message,
      createdAt: workerEvents.createdAt,
      setRunId: workerEvents.setRunId,
      details: workerEvents.details,
    })
    .from(workerEvents)
    .where(
      and(
        eq(workerEvents.submissionId, submissionId),
        eq(workerEvents.setRunId, setRunId),
        inArray(workerEvents.eventType, [...publicRunTimelineEventTypes]),
      ),
    )
    .orderBy(desc(workerEvents.createdAt));

  const timelineItems = buildTimelineItems(selectCurrentAttemptEvents(allEvents));
  const safePageSize = Math.max(1, Math.min(pageSize, 20));
  const totalCount = timelineItems.length;
  const totalPages = Math.max(1, Math.ceil(totalCount / safePageSize));
  const currentPage = Math.max(1, Math.min(page, totalPages));

  return {
    events: timelineItems.slice((currentPage - 1) * safePageSize, currentPage * safePageSize),
    page: currentPage,
    pageSize: safePageSize,
    totalCount,
    totalPages,
  };
};
