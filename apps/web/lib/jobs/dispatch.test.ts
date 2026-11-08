import { beforeEach, describe, expect, it, vi } from "vitest";

const mockedDb = {
  execute: vi.fn(),
  select: vi.fn(),
  update: vi.fn(),
  delete: vi.fn(),
};

const dispatchProcessSetWorkflow = vi.fn();
const createWorkerEvent = vi.fn();
const schemaField = new Proxy(
  {},
  {
    get: (_target, property) => String(property),
  },
);

vi.mock("server-only", () => ({}));

vi.mock("@/lib/db/client", () => ({
  getDb: () => mockedDb,
}));

vi.mock("@/lib/db/schema", () => ({
  segmentHits: schemaField,
  setRunLeases: schemaField,
  setRuns: schemaField,
  submissions: schemaField,
}));

vi.mock("@/lib/env", () => ({
  env: {
    processSetMaxActiveRuns: 10,
  },
}));

vi.mock("@/lib/github/workflows", () => ({
  dispatchDiscoverArtistWorkflow: vi.fn(),
  dispatchProcessSetWorkflow,
}));

vi.mock("@/lib/jobs/internal", () => ({
  automaticRecoveryAttemptLimit: 3,
  createWorkerEvent,
}));

vi.mock("@/lib/jobs/submissions", () => ({
  syncSubmissionStatusFromRuns: vi.fn(),
}));

vi.mock("@/lib/jobs/status", () => ({
  isActiveSubmissionStatus: (status: string) => ["queued", "running", "cancelling"].includes(status),
  isTerminalSetRunStatus: (status: string) =>
    ["completed", "failed", "cancelled"].includes(status),
}));

const selectLimit = <T>(rows: T[]) => ({
  from: vi.fn().mockReturnValue({
    where: vi.fn().mockReturnValue({
      limit: vi.fn().mockResolvedValue(rows),
    }),
  }),
});

const selectWhere = <T>(rows: T[]) => ({
  from: vi.fn().mockReturnValue({
    where: vi.fn().mockResolvedValue(rows),
  }),
});

describe("dispatchAllQueuedSetRuns", () => {
  beforeEach(() => {
    vi.resetModules();
    mockedDb.execute.mockReset();
    mockedDb.select.mockReset();
    mockedDb.update.mockReset();
    mockedDb.delete.mockReset();
    dispatchProcessSetWorkflow.mockReset();
    createWorkerEvent.mockReset();
  });

  it("dispatches only claimed runs and requeues failed dispatches", async () => {
    const claimedRows = [{ id: "run-1" }, { id: "run-2" }];
    const queuedRuns = [
      { id: "run-1", submissionId: "sub-1" },
      { id: "run-2", submissionId: "sub-2" },
    ];

    mockedDb.execute.mockResolvedValueOnce({ rows: claimedRows });
    mockedDb.select.mockReturnValueOnce({
      from: vi.fn().mockReturnValue({
        where: vi.fn().mockResolvedValue(queuedRuns),
      }),
    });

    mockedDb.update.mockReturnValue({
      set: vi.fn().mockReturnValue({
        where: vi.fn().mockResolvedValue(undefined),
      }),
    });

    dispatchProcessSetWorkflow
      .mockResolvedValueOnce({ dispatched: true })
      .mockRejectedValueOnce(new Error("dispatch exploded"));

    const { dispatchAllQueuedSetRuns } = await import("./dispatch");
    const result = await dispatchAllQueuedSetRuns();

    expect(result.maxActive).toBe(10);
    expect(result.claimedCount).toBe(2);
    expect(result.dispatched).toBe(1);
    expect(dispatchProcessSetWorkflow).toHaveBeenCalledTimes(2);
    expect(dispatchProcessSetWorkflow).toHaveBeenNthCalledWith(1, "run-1");
    expect(dispatchProcessSetWorkflow).toHaveBeenNthCalledWith(2, "run-2");
    expect(mockedDb.update).toHaveBeenCalledTimes(4);
    expect(createWorkerEvent).toHaveBeenCalledTimes(2);
    expect(result.results).toHaveLength(2);
    expect(result.results[1]).toEqual({ error: "Error: dispatch exploded" });
  }, 15_000);

  it("returns an empty dispatch result when no slots are available", async () => {
    mockedDb.execute.mockResolvedValueOnce({ rows: [] });

    const { dispatchAllQueuedSetRuns } = await import("./dispatch");
    const result = await dispatchAllQueuedSetRuns();

    expect(result).toEqual({
      maxActive: 10,
      claimedCount: 0,
      dispatched: 0,
      results: [],
    });
    expect(mockedDb.select).not.toHaveBeenCalled();
    expect(dispatchProcessSetWorkflow).not.toHaveBeenCalled();
  }, 15_000);
});

describe("finalizeArtistDiscoveryWorkflow", () => {
  beforeEach(() => {
    vi.resetModules();
    mockedDb.execute.mockReset();
    mockedDb.select.mockReset();
    mockedDb.update.mockReset();
    mockedDb.delete.mockReset();
    dispatchProcessSetWorkflow.mockReset();
    createWorkerEvent.mockReset();
  });

  it("marks an active submission failed when discovery workflow fails before creating runs", async () => {
    mockedDb.select
      .mockReturnValueOnce(selectLimit([{ id: "sub-1", status: "running" }]))
      .mockReturnValueOnce(selectWhere([]));

    mockedDb.update.mockReturnValue({
      set: vi.fn().mockReturnValue({
        where: vi.fn().mockResolvedValue(undefined),
      }),
    });

    mockedDb.execute.mockResolvedValue({ rows: [] });

    const { finalizeArtistDiscoveryWorkflow } = await import("./dispatch");
    const result = await finalizeArtistDiscoveryWorkflow({
      submissionId: "sub-1",
      workflowRunId: "workflow-1",
      workflowResult: "failure",
    });

    expect(result.action).toBe("marked_failed");
    expect(mockedDb.update).toHaveBeenCalledTimes(1);
    expect(createWorkerEvent).toHaveBeenCalledWith({
      submissionId: "sub-1",
      eventType: "submission.discovery.failed",
      message: "Discover artist workflow workflow-1 failed before discovery completed",
      details: {
        workflowRunId: "workflow-1",
        workflowResult: "failure",
      },
    });
  }, 15_000);
});

describe("set workflow finalization during rollout", () => {
  const updateSet = vi.fn();
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    mockedDb.execute.mockReset().mockResolvedValue({ rows: [] });
    mockedDb.select.mockReset();
    updateSet.mockReturnValue({ where: vi.fn().mockResolvedValue(undefined) });
    mockedDb.update.mockReturnValue({ set: updateSet });
    mockedDb.delete.mockReturnValue({ where: vi.fn().mockResolvedValue(undefined) });
  });
  const prepare = (overrides: Record<string, unknown> = {}) => {
    mockedDb.select
      .mockReturnValueOnce(selectLimit([{ id: "run-1", submissionId: "sub-1", status: "recognizing",
        attemptCount: 0, cancelRequestedAt: null, sourceMetadata: { active_workflow_run_id: "new-workflow" }, ...overrides }]))
      .mockReturnValueOnce(selectWhere([{ totalCount: 1, claimedCount: 1 }]))
      .mockReturnValueOnce(selectWhere([{ hitCount: 0 }]));
  };
  const payload = { setRunId: "run-1", workflowRunId: "new-workflow", bootstrapResult: "success", recognizeResult: "cancelled", publishResult: "skipped" };
  it("ignores an older workflow callback without requeue or mutation", async () => {
    prepare();
    const { finalizeSetRunWorkflow } = await import("./dispatch");
    expect(await finalizeSetRunWorkflow({ ...payload, workflowRunId: "old-workflow" })).toEqual({ action: "superseded_workflow_finalize_ignored" });
    expect(mockedDb.update).not.toHaveBeenCalled();
    expect(mockedDb.execute).not.toHaveBeenCalled();
    expect(dispatchProcessSetWorkflow).not.toHaveBeenCalled();
  });
  it("honors cancellation without retrying the cancelled run", async () => {
    prepare({ cancelRequestedAt: new Date() });
    const { finalizeSetRunWorkflow } = await import("./dispatch");
    expect((await finalizeSetRunWorkflow(payload)).action).toBe("cancelled");
    expect(updateSet).toHaveBeenCalledWith(expect.objectContaining({ status: "cancelled" }));
    expect(mockedDb.delete).not.toHaveBeenCalled();
    expect(dispatchProcessSetWorkflow).not.toHaveBeenCalled();
  });
  it("preserves completed runs on repeated failure callbacks", async () => {
    prepare({ status: "completed" });
    const { finalizeSetRunWorkflow } = await import("./dispatch");
    expect((await finalizeSetRunWorkflow(payload)).action).toBe("already_terminal");
    expect(mockedDb.update).not.toHaveBeenCalled();
    expect(mockedDb.delete).not.toHaveBeenCalled();
  });
  it("stops retrying after the recovery limit", async () => {
    prepare({ attemptCount: 3 });
    const { finalizeSetRunWorkflow } = await import("./dispatch");
    expect((await finalizeSetRunWorkflow(payload)).action).toBe("failed_after_recovery_limit");
    expect(updateSet).toHaveBeenCalledWith(expect.objectContaining({ status: "failed" }));
    expect(mockedDb.delete).not.toHaveBeenCalled();
    expect(dispatchProcessSetWorkflow).not.toHaveBeenCalled();
  });
});
