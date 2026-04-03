import { describe, expect, it } from "vitest";

import {
  isCancellableSetRunStatus,
  isActiveSetRunStatus,
  isActiveSubmissionStatus,
  isRetryableSetRun,
  isTerminalSetRunStatus,
  summarizeSubmissionActions,
  summarizeSetRunCounts,
} from "./status";

describe("set run status helpers", () => {
  it("recognizes in-flight and terminal statuses", () => {
    expect(isActiveSetRunStatus("recognizing")).toBe(true);
    expect(isActiveSetRunStatus("queued")).toBe(false);
    expect(isActiveSubmissionStatus("cancelling")).toBe(true);
    expect(isActiveSubmissionStatus("failed")).toBe(false);
    expect(isTerminalSetRunStatus("completed")).toBe(true);
    expect(isTerminalSetRunStatus("publishing")).toBe(false);
    expect(isCancellableSetRunStatus("queued")).toBe(true);
    expect(isCancellableSetRunStatus("completed")).toBe(false);
  });

  it("summarizes queued, in-flight, and terminal run counts", () => {
    const counts = summarizeSetRunCounts([
      { status: "queued" },
      { status: "dispatched" },
      { status: "recognizing" },
      { status: "completed" },
      { status: "failed" },
      { status: "cancelled" },
    ]);

    expect(counts).toEqual({
      totalCount: 6,
      queuedCount: 1,
      inFlightCount: 2,
      activeCount: 3,
      completedCount: 1,
      failedCount: 1,
      cancelledCount: 1,
      terminalCount: 3,
    });
  });

  it("applies retry and cancel eligibility using the shared attempt limit", () => {
    expect(isRetryableSetRun("failed", 2)).toBe(true);
    expect(isRetryableSetRun("cancelled", 2)).toBe(true);
    expect(isRetryableSetRun("failed", 3)).toBe(false);
    expect(isRetryableSetRun("completed", 0)).toBe(false);

    const actions = summarizeSubmissionActions([
      { status: "failed", attemptCount: 2 },
      { status: "cancelled", attemptCount: 3 },
      { status: "queued", attemptCount: 0 },
      { status: "recognizing", attemptCount: 1 },
      { status: "completed", attemptCount: 1 },
    ]);

    expect(actions).toEqual({
      retryableCount: 1,
      exhaustedRetryCount: 1,
      cancellableCount: 2,
      canRetry: true,
      canCancel: true,
    });
  });
});
