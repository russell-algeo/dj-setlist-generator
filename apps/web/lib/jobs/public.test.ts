import { describe, expect, it } from "vitest";

import {
  buildArtistSubmissionWorkflowSteps,
  buildRunWorkflowSteps,
  getRunDisplayStatus,
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

  it("advances the visible workflow to publish when recognition is fully complete", () => {
    const waitingForPublish = buildRunWorkflowSteps({
      status: "recognizing",
      stage: "slot_1_recognizing",
      progress: {
        totalLeases: 9,
        completedLeases: 9,
        hitCount: 86,
        recognizedCount: 9,
      },
      recognitionSlotCount: 9,
      completedRecognitionSlots: 9,
    });

    expect(waitingForPublish.map((step) => step.state)).toEqual([
      "complete",
      "complete",
      "active",
      "pending",
    ]);
    expect(waitingForPublish[2]?.detail).toBe("Waiting for publish workers");
    expect(getRunDisplayStatus("recognizing", waitingForPublish)).toBe("publishing");
  });

  it("builds a top-level artist submission timeline from discovery through completion", () => {
    const steps = buildArtistSubmissionWorkflowSteps({
      submissionStatus: "running",
      runCounts: {
        totalCount: 12,
        queuedCount: 4,
        inFlightCount: 5,
        activeCount: 9,
        completedCount: 3,
        failedCount: 0,
        cancelledCount: 0,
        terminalCount: 3,
      },
      runCount: 12,
      discoveryCandidateCount: 12,
      hasDiscoveryStarted: true,
      hasDiscoveryCompleted: true,
      hasDiscoveryEmpty: false,
      hasDiscoveryFailed: false,
    });

    expect(steps.map((step) => step.state)).toEqual([
      "complete",
      "complete",
      "active",
      "pending",
    ]);
    expect(steps[2]?.progress).toEqual({
      current: 3,
      total: 12,
      label: "sets",
    });
  });
});
