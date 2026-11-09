import { PgDialect } from "drizzle-orm/pg-core";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockedDb = { select: vi.fn(), update: vi.fn() };
const claim = vi.fn();
const updateSet = vi.fn();
const updateWhere = vi.fn();
const upsertArchiveSet = vi.fn();
const refreshArchiveHomeMaterializedViews = vi.fn();
const assertInternalRequest = vi.fn();

vi.mock("@/lib/db/client", () => ({ getDb: () => mockedDb }));
vi.mock("@/lib/archive/publish-set", () => ({ upsertArchiveSet }));
vi.mock("@/lib/archive/home-materialized-views", () => ({ refreshArchiveHomeMaterializedViews }));
vi.mock("@/lib/auth/session", () => ({ assertInternalRequest }));

const setRunId = "00000000-0000-4000-8000-000000000001";
const published = { setId: "00000000-0000-4000-8000-000000000002", slug: "test-set", affectedArtistSlugs: ["test-artist"] };
const run = {
  id: setRunId, status: "publishing", stage: "publishing", cancelRequestedAt: null,
  publishedSetId: null, sourceMetadata: { active_workflow_run_id: "workflow-1" },
};
const request = (workflowRunId: string | undefined = "workflow-1") => new Request("http://localhost/api/internal/publish-set-run", {
  method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ setRunId, workflowRunId, payload: { mix_info: {}, metadata: {}, tracks: [] } }),
});
const selectRows = (rows: unknown[]) => ({ from: () => ({ where: () => ({ limit: async () => rows }) }) });

describe("publication cancellation boundary", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    mockedDb.select.mockReset();
    claim.mockReset().mockResolvedValue([{ id: setRunId }]);
    updateWhere.mockReturnValue({ returning: claim });
    updateSet.mockReturnValue({ where: updateWhere });
    mockedDb.update.mockReturnValue({ set: updateSet });
    upsertArchiveSet.mockReset().mockResolvedValue(published);
    refreshArchiveHomeMaterializedViews.mockReset().mockResolvedValue(undefined);
    assertInternalRequest.mockReset().mockReturnValue(null);
  });

  it("atomically checks cancellation, terminal status, committed stage and owner before any writes", async () => {
    const { POST } = await import("./route");
    const response = await POST(request());
    expect(response.status).toBe(200);
    const predicate = new PgDialect().sqlToQuery(updateWhere.mock.calls[0][0]);
    expect(predicate.sql).toContain('"cancel_requested_at" is null');
    expect(predicate.sql).toContain('"published_set_id" is null');
    expect(predicate.sql).toContain('"stage" is distinct from');
    expect(predicate.sql).toContain("active_workflow_run_id");
    expect(predicate.params).toContain("publishing_committed");
    expect(predicate.params).toContain("workflow-1");
    expect(predicate.params).not.toContain("cancelled");
    expect(predicate.params).not.toContain("completed");
    expect(predicate.params).not.toContain("failed");
    expect(predicate.params).not.toContain("cancelling");
    expect(upsertArchiveSet).toHaveBeenCalledTimes(1);
    expect(claim.mock.invocationCallOrder[0]).toBeLessThan(upsertArchiveSet.mock.invocationCallOrder[0]);
    expect(updateSet).toHaveBeenLastCalledWith(expect.objectContaining({ publishedSetId: published.setId, status: "completed" }));
    expect(updateSet.mock.invocationCallOrder[1]).toBeLessThan(refreshArchiveHomeMaterializedViews.mock.invocationCallOrder[0]);
  });

  it.each([
    { status: "cancelling", cancelRequestedAt: new Date() },
    { status: "cancelled", cancelRequestedAt: null },
    { status: "failed", cancelRequestedAt: new Date() },
  ])("does not publish an accepted cancellation (%s)", async (overrides) => {
    claim.mockResolvedValue([]);
    mockedDb.select.mockReturnValue(selectRows([{ ...run, ...overrides }]));
    const { POST } = await import("./route");
    const response = await POST(request());
    expect(response.status).toBe(409);
    expect(await response.json()).toMatchObject({ errorCode: "run_cancelled" });
    expect(upsertArchiveSet).not.toHaveBeenCalled();
    expect(refreshArchiveHomeMaterializedViews).not.toHaveBeenCalled();
  });

  it("rejects a superseded workflow", async () => {
    claim.mockResolvedValue([]);
    mockedDb.select.mockReturnValue(selectRows([run]));
    const { POST } = await import("./route");
    const response = await POST(request("old-workflow"));
    expect(response.status).toBe(409);
    expect(await response.json()).toMatchObject({ errorCode: "workflow_superseded" });
    expect(upsertArchiveSet).not.toHaveBeenCalled();
  });

  it.each(["failed", "completed"])("rejects unpublished terminal %s runs", async (status) => {
    claim.mockResolvedValue([]);
    mockedDb.select.mockReturnValue(selectRows([{ ...run, status }]));
    const { POST } = await import("./route");
    const response = await POST(request());
    expect(response.status).toBe(409);
    expect(await response.json()).toMatchObject({ errorCode: "run_not_publishable" });
    expect(upsertArchiveSet).not.toHaveBeenCalled();
  });

  it("allows exactly one archive writer when two publication requests overlap", async () => {
    let finish!: (result: typeof published) => void;
    let started!: () => void;
    const startedPromise = new Promise<void>((resolve) => { started = resolve; });
    upsertArchiveSet.mockImplementationOnce(() => {
      started();
      return new Promise((resolve) => { finish = resolve; });
    });
    claim.mockResolvedValueOnce([{ id: setRunId }]).mockResolvedValueOnce([]);
    mockedDb.select.mockReturnValue(selectRows([{ ...run, stage: "publishing_committed" }]));
    const { POST } = await import("./route");
    const first = POST(request());
    await startedPromise;
    const duplicate = await POST(request());
    expect(duplicate.status).toBe(409);
    expect(await duplicate.json()).toMatchObject({ errorCode: "publication_in_progress" });
    finish(published);
    expect((await first).status).toBe(200);
    expect(upsertArchiveSet).toHaveBeenCalledTimes(1);
  });

  it("replays persisted success after a lost response without rewriting published data", async () => {
    claim.mockResolvedValue([]);
    mockedDb.select.mockReturnValue(selectRows([{
      ...run, status: "completed", publishedSetId: published.setId,
      cancelRequestedAt: new Date(), // legacy inconsistent state must not erase real data
      sourceMetadata: { ...run.sourceMetadata, publication_result: published },
    }]));
    const { POST } = await import("./route");
    const response = await POST(request());
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(published);
    expect(upsertArchiveSet).not.toHaveBeenCalled();
    expect(updateSet).toHaveBeenCalledTimes(1); // rejected claim only
  });

  it("does not record success for a superseded generation after writing", async () => {
    claim.mockResolvedValueOnce([{ id: setRunId }]).mockResolvedValueOnce([]);
    const { POST } = await import("./route");
    const response = await POST(request());
    expect(response.status).toBe(409);
    expect(await response.json()).toMatchObject({ errorCode: "workflow_superseded" });
    const predicate = new PgDialect().sqlToQuery(updateWhere.mock.calls[1][0]);
    expect(predicate.sql).toContain("active_workflow_run_id");
    expect(predicate.params).toContain("workflow-1");
    expect(refreshArchiveHomeMaterializedViews).not.toHaveBeenCalled();
  });

  it("retains the commit marker after an uncertain archive write failure", async () => {
    upsertArchiveSet.mockRejectedValue(new Error("database response lost"));
    const { POST } = await import("./route");
    await expect(POST(request())).rejects.toThrow("database response lost");
    expect(updateSet).toHaveBeenCalledTimes(2);
    expect(updateSet).toHaveBeenNthCalledWith(1, expect.objectContaining({ stage: "publishing_committed" }));
    expect(updateSet).toHaveBeenLastCalledWith(expect.objectContaining({ errorSummary: expect.stringContaining("uncertain") }));
    expect(updateSet.mock.calls[1][0]).not.toHaveProperty("stage");
    expect(updateSet.mock.calls[1][0]).not.toHaveProperty("status");
    expect(refreshArchiveHomeMaterializedViews).not.toHaveBeenCalled();
  });

  it("persists published data even if view refresh fails", async () => {
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    refreshArchiveHomeMaterializedViews.mockRejectedValue(new Error("refresh failed"));
    const { POST } = await import("./route");
    const response = await POST(request());
    expect(response.status).toBe(500);
    expect(await response.json()).toMatchObject({ ...published, errorCode: "archive_home_materialized_view_refresh_failed" });
    expect(updateSet).toHaveBeenLastCalledWith(expect.objectContaining({ publishedSetId: published.setId, status: "completed" }));
    log.mockRestore();
  });

  it("rejects unauthenticated calls without claiming a run", async () => {
    assertInternalRequest.mockReturnValue(new Response("denied", { status: 401 }));
    const { POST } = await import("./route");
    expect((await POST(request())).status).toBe(401);
    expect(mockedDb.update).not.toHaveBeenCalled();
    expect(upsertArchiveSet).not.toHaveBeenCalled();
  });
});
