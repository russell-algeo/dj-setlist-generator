import { beforeEach, describe, expect, it, vi } from "vitest";
import { PgDialect } from "drizzle-orm/pg-core";

const mockedDb = {
  execute: vi.fn(),
  select: vi.fn(),
  update: vi.fn(),
  delete: vi.fn(),
};

const dispatchProcessSetWorkflow = vi.fn();
const createWorkerEvent = vi.fn();
vi.mock("server-only", () => ({}));

vi.mock("@/lib/db/client", () => ({
  getDb: () => mockedDb,
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
      { id: "run-1", submissionId: "sub-1", status: "dispatched", stage: "dispatching", attemptCount: 1 },
      { id: "run-2", submissionId: "sub-2", status: "dispatched", stage: "dispatching", attemptCount: 1 },
    ];

    mockedDb.execute.mockResolvedValueOnce({ rows: claimedRows });
    mockedDb.select.mockReturnValueOnce({
      from: vi.fn().mockReturnValue({
        where: vi.fn().mockResolvedValue(queuedRuns),
      }),
    });

    mockedDb.update.mockReturnValue({
      set: vi.fn().mockReturnValue({
        where: vi.fn().mockReturnValue({ returning: vi.fn().mockResolvedValue([{ id: "run-2" }]) }),
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
    expect(dispatchProcessSetWorkflow).toHaveBeenNthCalledWith(1, "run-1", { dispatch_generation: expect.any(String) });
    expect(dispatchProcessSetWorkflow).toHaveBeenNthCalledWith(2, "run-2", { dispatch_generation: expect.any(String) });
    expect(mockedDb.update).toHaveBeenCalledTimes(5);
    expect(createWorkerEvent).toHaveBeenCalledTimes(2);
    expect(result.results).toHaveLength(2);
    expect(result.results[1]).toEqual({ error: "Error: dispatch exploded" });
  }, 15_000);

  it("does not reset a dispatched workflow when only event recording fails", async () => {
    mockedDb.execute.mockResolvedValueOnce({ rows: [{ id: "run-1" }] });
    mockedDb.select.mockReturnValueOnce(selectWhere([{ id: "run-1", submissionId: "sub-1", status: "dispatched", stage: "dispatching", attemptCount: 1 }]));
    mockedDb.update.mockReturnValue({ set: vi.fn().mockReturnValue({ where: vi.fn().mockReturnValue({ returning: vi.fn().mockResolvedValue([{ id: "run-1" }]) }) }) });
    dispatchProcessSetWorkflow.mockResolvedValue({ dispatched: true });
    createWorkerEvent.mockRejectedValue(new Error("event unavailable"));
    const { dispatchAllQueuedSetRuns } = await import("./dispatch");
    const result = await dispatchAllQueuedSetRuns();
    expect(result.results).toEqual([{ error: "Error: event unavailable" }]);
    expect(mockedDb.update).toHaveBeenCalledTimes(2); // generation claim and submission update only
  });

  it("does not dispatch when cancellation or a newer generation wins the dispatch claim", async () => {
    mockedDb.execute.mockResolvedValueOnce({ rows: [{ id: "run-1" }] });
    mockedDb.select.mockReturnValueOnce(selectWhere([{ id: "run-1", submissionId: "sub-1", status: "dispatched", stage: "dispatching", attemptCount: 1 }]));
    const where = vi.fn().mockReturnValue({ returning: vi.fn().mockResolvedValue([]) });
    mockedDb.update.mockReturnValue({ set: vi.fn().mockReturnValue({ where }) });
    const { dispatchAllQueuedSetRuns } = await import("./dispatch");
    const result = await dispatchAllQueuedSetRuns();
    expect(result.dispatched).toBe(0);
    expect(dispatchProcessSetWorkflow).not.toHaveBeenCalled();
    const predicate = new PgDialect().sqlToQuery(where.mock.calls[0][0]);
    expect(predicate.sql).toContain("dispatch_generation");
    expect(predicate.sql).toContain('"cancel_requested_at" is null');
    expect(predicate.params).toContain("publishing_committed");
  });

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
  const returning = vi.fn();
  const where = vi.fn();
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    dispatchProcessSetWorkflow.mockReset();
    createWorkerEvent.mockReset();
    mockedDb.execute.mockReset().mockResolvedValue({ rows: [] });
    mockedDb.select.mockReset();
    returning.mockReset().mockResolvedValue([{ id: "run-1" }]);
    where.mockReturnValue({ returning });
    updateSet.mockReturnValue({ where });
    mockedDb.update.mockReturnValue({ set: updateSet });
    mockedDb.delete.mockReturnValue({ where: vi.fn().mockResolvedValue(undefined) });
  });
  const prepare = (overrides: Record<string, unknown> = {}, recognitionComplete = false) => {
    mockedDb.select
      .mockReturnValueOnce(selectLimit([{ id: "run-1", submissionId: "sub-1", status: "recognizing",
        attemptCount: 0, cancelRequestedAt: null, sourceMetadata: { active_workflow_run_id: "new-workflow" }, ...overrides }]))
      .mockReturnValueOnce(selectWhere([{ totalCount: 1, claimedCount: recognitionComplete ? 0 : 1, completedCount: recognitionComplete ? 1 : 0 }]))
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
  it("treats private or missing runs as unavailable before finalizer side effects", async () => {
    prepare();
    const where = vi.fn().mockReturnValue({ limit: vi.fn().mockResolvedValue([]) });
    mockedDb.select.mockReset().mockReturnValue({ from: () => ({ where }) });
    const { finalizeSetRunWorkflow } = await import("./dispatch");
    expect(await finalizeSetRunWorkflow(payload)).toEqual({ action: "missing_set_run" });
    const query = new PgDialect().sqlToQuery(where.mock.calls[0]![0]);
    expect(query.sql).toContain('"publication_visibility"'); expect(query.params).toContain("public");
    expect(mockedDb.update).not.toHaveBeenCalled(); expect(mockedDb.execute).not.toHaveBeenCalled();
    expect(mockedDb.delete).not.toHaveBeenCalled(); expect(createWorkerEvent).not.toHaveBeenCalled(); expect(dispatchProcessSetWorkflow).not.toHaveBeenCalled();
  });
  it("honors pending cancellation before a failed terminal callback", async () => {
    prepare({ status: "failed", cancelRequestedAt: new Date() });
    const { finalizeSetRunWorkflow } = await import("./dispatch");
    expect((await finalizeSetRunWorkflow(payload)).action).toBe("cancelled");
    expect(updateSet).toHaveBeenCalledWith(expect.objectContaining({ status: "cancelled" }));
    expect(mockedDb.delete).not.toHaveBeenCalled();
    expect(dispatchProcessSetWorkflow).not.toHaveBeenCalled();
  });
  it("does not relabel or erase legitimately published data with legacy pending cancellation", async () => {
    prepare({ status: "completed", publishedSetId: "set-1", cancelRequestedAt: new Date() });
    const { finalizeSetRunWorkflow } = await import("./dispatch");
    expect((await finalizeSetRunWorkflow(payload)).action).toBe("already_terminal");
    expect(mockedDb.update).not.toHaveBeenCalled();
    expect(mockedDb.delete).not.toHaveBeenCalled();
  });
  it("does not recover or cancel while an archive writer may still be in flight", async () => {
    prepare({ status: "publishing", stage: "publishing_committed" });
    const { finalizeSetRunWorkflow } = await import("./dispatch");
    expect((await finalizeSetRunWorkflow(payload)).action).toBe("publication_requires_reconciliation");
    expect(mockedDb.update).not.toHaveBeenCalled();
    expect(mockedDb.delete).not.toHaveBeenCalled();
    expect(dispatchProcessSetWorkflow).not.toHaveBeenCalled();
  });
  it("does not requeue, erase recognition data or dispatch when a cancellation wins after the read", async () => {
    prepare();
    returning.mockResolvedValue([]);
    const { finalizeSetRunWorkflow } = await import("./dispatch");
    expect((await finalizeSetRunWorkflow(payload)).action).toBe("recovery_skipped");
    expect(mockedDb.delete).not.toHaveBeenCalled();
    expect(dispatchProcessSetWorkflow).not.toHaveBeenCalled();
    expect(createWorkerEvent).not.toHaveBeenCalled();
  });
  it("does not overwrite cancellation when the recovery-limit failure update loses the race", async () => {
    prepare({ attemptCount: 3 });
    returning.mockResolvedValue([]);
    const { finalizeSetRunWorkflow } = await import("./dispatch");
    expect((await finalizeSetRunWorkflow(payload)).action).toBe("recovery_skipped");
    expect(mockedDb.delete).not.toHaveBeenCalled();
    expect(dispatchProcessSetWorkflow).not.toHaveBeenCalled();
    expect(createWorkerEvent).not.toHaveBeenCalled();
  });
  it("is idempotent on already-cancelled callbacks", async () => {
    prepare({ status: "cancelled", cancelRequestedAt: new Date() });
    const { finalizeSetRunWorkflow } = await import("./dispatch");
    expect((await finalizeSetRunWorkflow(payload)).action).toBe("already_terminal");
    expect(mockedDb.update).not.toHaveBeenCalled();
    expect(mockedDb.delete).not.toHaveBeenCalled();
  });
  it("atomically requeues and clears recognition data before exposing work to dispatch", async () => {
    prepare();
    mockedDb.execute.mockResolvedValueOnce({ rows: [{ id: "run-1" }] });
    const { finalizeSetRunWorkflow } = await import("./dispatch");
    expect((await finalizeSetRunWorkflow(payload)).action).toBe("requeued_for_full_retry");
    const query = new PgDialect().sqlToQuery(mockedDb.execute.mock.calls[0][0]);
    expect(query.sql).toContain("with requeued as");
    expect(query.sql).toContain('delete from "ops"."segment_hits" using requeued');
    expect(query.sql).toContain('delete from "ops"."set_run_leases" using requeued');
    expect(query.sql).toContain('"cancel_requested_at" is null');
    expect(query.sql).toContain("retired_workflow_run_ids");
    expect(query.sql).toContain("awaiting_dispatch");
    expect(query.params).toContain("publishing_committed");
    expect(mockedDb.delete).not.toHaveBeenCalled();
  });
  it("does not dispatch publish recovery if cancellation wins its claim", async () => {
    prepare({}, true);
    returning.mockResolvedValue([]);
    const { finalizeSetRunWorkflow } = await import("./dispatch");
    expect((await finalizeSetRunWorkflow(payload)).action).toBe("recovery_skipped");
    expect(dispatchProcessSetWorkflow).not.toHaveBeenCalled();
    expect(mockedDb.execute).not.toHaveBeenCalled();
  });
  it("retires the old owner before dispatching publish-only recovery", async () => {
    prepare({}, true);
    dispatchProcessSetWorkflow.mockResolvedValue({ dispatched: true });
    const { finalizeSetRunWorkflow } = await import("./dispatch");
    expect((await finalizeSetRunWorkflow(payload)).action).toBe("publish_retry_dispatched");
    const metadata = new PgDialect().sqlToQuery(updateSet.mock.calls[0][0].sourceMetadata);
    expect(metadata.sql).toContain("retired_workflow_run_ids");
    expect(metadata.sql).toContain("awaiting_dispatch");
    expect(dispatchProcessSetWorkflow).toHaveBeenCalledWith("run-1", { resume_mode: "publish_only", dispatch_generation: expect.any(String) });
  });
  it("does not fall back to a full retry if only publish-recovery event recording fails", async () => {
    prepare({}, true);
    dispatchProcessSetWorkflow.mockResolvedValue({ dispatched: true });
    createWorkerEvent.mockRejectedValue(new Error("event unavailable"));
    const { finalizeSetRunWorkflow } = await import("./dispatch");
    await expect(finalizeSetRunWorkflow(payload)).rejects.toThrow("event unavailable");
    expect(mockedDb.execute).not.toHaveBeenCalled();
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
