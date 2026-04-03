import { setRunRetryAttemptLimit } from "./policy";

export const queuedSetRunStatuses = ["queued"] as const;

export type QueuedSetRunStatus = (typeof queuedSetRunStatuses)[number];

export const activeSetRunStatuses = [
  "dispatched",
  "resolving",
  "recognizing",
  "aggregating",
  "enriching",
  "publishing",
  "cancelling",
] as const;

export type ActiveSetRunStatus = (typeof activeSetRunStatuses)[number];

export const terminalSetRunStatuses = ["completed", "failed", "cancelled"] as const;

export type TerminalSetRunStatus = (typeof terminalSetRunStatuses)[number];

export const activeSubmissionStatuses = ["queued", "running", "cancelling"] as const;

export type ActiveSubmissionStatus = (typeof activeSubmissionStatuses)[number];

export const isQueuedSetRunStatus = (status: string): status is QueuedSetRunStatus =>
  queuedSetRunStatuses.includes(status as QueuedSetRunStatus);

export const isActiveSetRunStatus = (status: string): status is ActiveSetRunStatus =>
  activeSetRunStatuses.includes(status as ActiveSetRunStatus);

export const isTerminalSetRunStatus = (status: string): status is TerminalSetRunStatus =>
  terminalSetRunStatuses.includes(status as TerminalSetRunStatus);

export const isActiveSubmissionStatus = (status: string): status is ActiveSubmissionStatus =>
  activeSubmissionStatuses.includes(status as ActiveSubmissionStatus);

export const isCancellableSetRunStatus = (status: string) =>
  isQueuedSetRunStatus(status) || isActiveSetRunStatus(status);

export const isRetryableSetRun = (
  status: string,
  attemptCount: number,
  retryAttemptLimit = setRunRetryAttemptLimit,
) => (status === "failed" || status === "cancelled") && attemptCount < retryAttemptLimit;

export const summarizeSubmissionActions = <T extends { status: string; attemptCount: number }>(
  runs: readonly T[],
  retryAttemptLimit = setRunRetryAttemptLimit,
) => {
  let retryableCount = 0;
  let exhaustedRetryCount = 0;
  let cancellableCount = 0;

  for (const run of runs) {
    if (isRetryableSetRun(run.status, run.attemptCount, retryAttemptLimit)) {
      retryableCount += 1;
      continue;
    }

    if ((run.status === "failed" || run.status === "cancelled") && run.attemptCount >= retryAttemptLimit) {
      exhaustedRetryCount += 1;
      continue;
    }

    if (isCancellableSetRunStatus(run.status)) {
      cancellableCount += 1;
    }
  }

  return {
    retryableCount,
    exhaustedRetryCount,
    cancellableCount,
    canRetry: retryableCount > 0,
    canCancel: cancellableCount > 0,
  };
};

export const summarizeSetRunCounts = <T extends { status: string }>(runs: readonly T[]) => {
  let queuedCount = 0;
  let inFlightCount = 0;
  let completedCount = 0;
  let failedCount = 0;
  let cancelledCount = 0;

  for (const run of runs) {
    if (isQueuedSetRunStatus(run.status)) {
      queuedCount += 1;
      continue;
    }

    if (isActiveSetRunStatus(run.status)) {
      inFlightCount += 1;
      continue;
    }

    if (run.status === "completed") {
      completedCount += 1;
      continue;
    }

    if (run.status === "failed") {
      failedCount += 1;
      continue;
    }

    if (run.status === "cancelled") {
      cancelledCount += 1;
    }
  }

  return {
    totalCount: runs.length,
    queuedCount,
    inFlightCount,
    activeCount: queuedCount + inFlightCount,
    completedCount,
    failedCount,
    cancelledCount,
    terminalCount: completedCount + failedCount + cancelledCount,
  };
};
