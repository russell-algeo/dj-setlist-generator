import { PgDialect } from "drizzle-orm/pg-core";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockedDb = { select: vi.fn(), update: vi.fn(), execute: vi.fn() };
const updateSet = vi.fn();
const updateWhere = vi.fn();
const returning = vi.fn();
const createWorkerEvent = vi.fn();
vi.mock("@/lib/db/client", () => ({ getDb: () => mockedDb }));
vi.mock("@/lib/jobs/internal", () => ({ createWorkerEvent }));
vi.mock("@/lib/jobs/source-url-normalizer", () => ({ resolveCanonicalSourceUrl: vi.fn(), resolveCanonicalSourceUrls: vi.fn() }));

const rows = (runs: unknown[]) => ({ from: () => ({ where: async () => runs }) });

describe("atomic run cancellation", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    mockedDb.execute.mockReset().mockResolvedValue({ rows: [] });
    mockedDb.select.mockReset().mockReturnValue(rows([{ id: "run-1", status: "publishing", attemptCount: 0 }]));
    returning.mockReset().mockResolvedValue([{ id: "run-1", status: "cancelling" }]);
    updateWhere.mockReturnValue({ returning });
    updateSet.mockReturnValue({ where: updateWhere });
    mockedDb.update.mockReturnValue({ set: updateSet });
  });

  it("records cancellation only if publication has not crossed its atomic commit boundary", async () => {
    const { cancelSubmissionSetRun } = await import("./submissions");
    const result = await cancelSubmissionSetRun("sub-1", "run-1");
    expect(result).toMatchObject({ affectedCount: 1, cancellingRunIds: ["run-1"], nothingToCancel: false });
    const predicate = new PgDialect().sqlToQuery(updateWhere.mock.calls[0][0]);
    expect(predicate.sql).toContain('"published_set_id" is null');
    expect(predicate.sql).toContain('"stage" is distinct from');
    expect(predicate.params).toContain("publishing_committed");
    expect(predicate.params).toContain("sub-1");
    expect(predicate.params).not.toContain("completed");
    expect(predicate.params).not.toContain("failed");
    expect(predicate.params).not.toContain("cancelled");
    expect(returning).toHaveBeenCalledTimes(1);
  });

  it("does not report stale selected IDs as cancelled if publication wins the race", async () => {
    returning.mockResolvedValue([]);
    const { cancelSubmissionSetRun } = await import("./submissions");
    expect(await cancelSubmissionSetRun("sub-1", "run-1")).toMatchObject({
      targetRunIds: ["run-1"], affectedCount: 0, cancelledRunIds: [], cancellingRunIds: [],
      skippedIneligibleRunIds: ["run-1"], nothingToCancel: true,
    });
    expect(mockedDb.update).toHaveBeenCalledTimes(1);
    expect(createWorkerEvent).not.toHaveBeenCalled();
  });

  it("uses returned state when a queued run was dispatched after selection", async () => {
    mockedDb.select.mockReturnValue(rows([{ id: "run-1", status: "queued", attemptCount: 0 }]));
    const { cancelSubmissionSetRun } = await import("./submissions");
    const result = await cancelSubmissionSetRun("sub-1", "run-1");
    expect(result.cancelledRunIds).toEqual([]);
    expect(result.cancellingRunIds).toEqual(["run-1"]);
    const status = new PgDialect().sqlToQuery(updateSet.mock.calls[0][0].status);
    expect(status.sql).toContain("case when");
    expect(status.sql).toContain("then 'cancelled' else 'cancelling'");
  });

  it("reports only the actually cancelled subset of a submission", async () => {
    mockedDb.select.mockReturnValue(rows([
      { id: "run-1", status: "queued", attemptCount: 0 },
      { id: "run-2", status: "publishing", attemptCount: 0 },
    ]));
    returning.mockResolvedValue([{ id: "run-1", status: "cancelled" }]);
    const { markSubmissionCancelled } = await import("./submissions");
    const result = await markSubmissionCancelled("sub-1");
    expect(result).toMatchObject({ cancelledRunIds: ["run-1"], cancellingRunIds: [], skippedIneligibleRunIds: ["run-2"], affectedCount: 1 });
    expect(createWorkerEvent).toHaveBeenCalledWith(expect.objectContaining({ details: expect.objectContaining({ skippedIneligibleRunIds: ["run-2"] }) }));
  });

  it("does not relabel the submission when every requested cancellation is too late", async () => {
    returning.mockResolvedValue([]);
    const { markSubmissionCancelled } = await import("./submissions");
    expect((await markSubmissionCancelled("sub-1")).nothingToCancel).toBe(true);
    expect(mockedDb.update).toHaveBeenCalledTimes(1);
    expect(createWorkerEvent).not.toHaveBeenCalled();
  });
  it("marks an all-queued submission cancelled instead of leaving it cancelling forever", async () => {
    mockedDb.select.mockReturnValueOnce(rows([{ id: "run-1", status: "queued", attemptCount: 0 }]))
      .mockReturnValueOnce(rows([{ status: "cancelled" }]));
    returning.mockResolvedValue([{ id: "run-1", status: "cancelled" }]);
    const { markSubmissionCancelled } = await import("./submissions");
    await markSubmissionCancelled("sub-1");
    expect(updateSet).toHaveBeenLastCalledWith(expect.objectContaining({ status: "cancelled" }));
  });

  it("resyncs even when an active cancellation finishes before the submission flag is written", async () => {
    mockedDb.select.mockReturnValueOnce(rows([{ id: "run-1", status: "recognizing", attemptCount: 0 }]))
      .mockReturnValueOnce(rows([{ status: "cancelled" }]));
    returning.mockResolvedValue([{ id: "run-1", status: "cancelling" }]);
    const { markSubmissionCancelled } = await import("./submissions");
    await markSubmissionCancelled("sub-1");
    expect(updateSet).toHaveBeenLastCalledWith(expect.objectContaining({ status: "cancelled" }));
  });

  it("blocks retry of committed or already published failures", async () => {
    mockedDb.select.mockReturnValue(rows([
      { id: "run-1", status: "failed", stage: "publishing_committed", attemptCount: 0 },
      { id: "run-2", status: "failed", publishedSetId: "set-1", attemptCount: 0 },
    ]));
    const { retryFailedSetRuns } = await import("./submissions");
    expect(await retryFailedSetRuns("sub-1")).toMatchObject({ nothingToRetry: true, retriedRunIds: [], skippedIneligibleRunIds: ["run-1", "run-2"] });
    expect(mockedDb.execute).not.toHaveBeenCalled();
  });

  it("uses one guarded statement for retry cleanup and returns only actually claimed IDs", async () => {
    mockedDb.select.mockReturnValue(rows([{ id: "run-1", status: "cancelled", attemptCount: 0, cancelRequestedAt: new Date(), sourceMetadata: { active_workflow_run_id: "old-workflow" } }]));
    const { retryFailedSetRuns } = await import("./submissions");
    expect(await retryFailedSetRuns("sub-1")).toMatchObject({ nothingToRetry: true, retriedRunIds: [], skippedIneligibleRunIds: ["run-1"] });
    const query = new PgDialect().sqlToQuery(mockedDb.execute.mock.calls[0][0]);
    expect(query.sql).toContain("with requeued as");
    expect(query.sql).toContain('delete from "ops"."segment_hits" using requeued');
    expect(query.sql).toContain('delete from "ops"."set_run_leases" using requeued');
    expect(query.sql).toContain("retired_workflow_run_ids");
    expect(query.sql).toContain("awaiting_dispatch");
    expect(query.params).toContain("old-workflow");
    expect(query.params).toContain("publishing_committed");
    expect(createWorkerEvent).not.toHaveBeenCalled();
  });

});
