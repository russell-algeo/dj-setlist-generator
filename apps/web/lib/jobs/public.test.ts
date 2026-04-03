import { describe, expect, it } from "vitest";

import {
  getTimelineSummary,
  getTimelineTone,
  normalizePublicSubmissionFilter,
  sortSubmissionRuns,
} from "./public";

describe("public submission helpers", () => {
  it("normalizes unsupported filters to all", () => {
    expect(normalizePublicSubmissionFilter("failed")).toBe("failed");
    expect(normalizePublicSubmissionFilter("something-else")).toBe("all");
    expect(normalizePublicSubmissionFilter(undefined)).toBe("all");
  });

  it("maps known timeline events to compact summaries and tones", () => {
    expect(getTimelineSummary("submission.discovery.completed", "Queued 8 discovered sets")).toBe(
      "Discovery completed",
    );
    expect(getTimelineSummary("custom.event", "A custom message")).toBe("A custom message");
    expect(getTimelineTone("set_run.failed")).toBe("danger");
    expect(getTimelineTone("custom.event")).toBe("neutral");
  });

  it("sorts runs by status first by default and preserves original order when requested", () => {
    const runs = [
      { id: "done", status: "completed", createdAt: "2025-01-01T00:00:03.000Z" },
      { id: "queued", status: "queued", createdAt: "2025-01-01T00:00:01.000Z" },
      { id: "failed", status: "failed", createdAt: "2025-01-01T00:00:02.000Z" },
    ];

    expect(sortSubmissionRuns(runs as never, "status_first").map((run) => run.id)).toEqual([
      "failed",
      "queued",
      "done",
    ]);
    expect(sortSubmissionRuns(runs as never, "original_order").map((run) => run.id)).toEqual([
      "queued",
      "failed",
      "done",
    ]);
  });
});
