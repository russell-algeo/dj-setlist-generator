import { describe, expect, it } from "vitest";

import {
  buildRunWorkflowSteps,
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

  it("builds workflow steps that reflect active recognition progress and publish completion", () => {
    const activeRecognition = buildRunWorkflowSteps({
      status: "recognizing",
      stage: "slot_1_recognizing",
      progress: {
        totalLeases: 24,
        completedLeases: 12,
        hitCount: 24,
        recognizedCount: 9,
      },
      recognitionSlotCount: 6,
      completedRecognitionSlots: 2,
    });

    expect(activeRecognition.map((step) => step.state)).toEqual([
      "complete",
      "active",
      "pending",
      "pending",
    ]);
    expect(activeRecognition[1]?.progress).toEqual({
      current: 2,
      total: 6,
      label: "slots",
    });
    expect(activeRecognition[1]?.detail).toContain("12/24 leases complete");

    const completedRun = buildRunWorkflowSteps({
      status: "completed",
      stage: "published",
      progress: {
        totalLeases: 8,
        completedLeases: 8,
        hitCount: 8,
        recognizedCount: 8,
      },
      recognitionSlotCount: 2,
      completedRecognitionSlots: 2,
    });

    expect(completedRun.map((step) => step.state)).toEqual([
      "complete",
      "complete",
      "complete",
      "complete",
    ]);
  });
});
