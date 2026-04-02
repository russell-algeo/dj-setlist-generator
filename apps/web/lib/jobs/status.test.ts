import { describe, expect, it } from "vitest";

import {
  isActiveSetRunStatus,
  isTerminalSetRunStatus,
  summarizeSetRunCounts,
} from "./status";

describe("set run status helpers", () => {
  it("recognizes in-flight and terminal statuses", () => {
    expect(isActiveSetRunStatus("recognizing")).toBe(true);
    expect(isActiveSetRunStatus("queued")).toBe(false);
    expect(isTerminalSetRunStatus("completed")).toBe(true);
    expect(isTerminalSetRunStatus("publishing")).toBe(false);
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
});
