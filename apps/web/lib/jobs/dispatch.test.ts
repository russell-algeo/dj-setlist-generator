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
  isTerminalSetRunStatus: (status: string) =>
    ["completed", "failed", "cancelled"].includes(status),
}));

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
