import { PgDialect } from "drizzle-orm/pg-core";
import { beforeEach, describe, expect, it, vi } from "vitest";
const db = { execute: vi.fn() };
const dispatch = vi.fn();
const environment = {
  deploymentTarget: "development", githubOwner: "russell-algeo", githubRepo: "dj-setlist-generator",
  githubWorkflowRef: "preview", githubWorkflowProcessSet: "process-set.yml", githubDispatchToken: "synthetic",
};
vi.mock("server-only", () => ({}));
vi.mock("@/lib/db/client", () => ({ getWorkerDb: () => db }));
vi.mock("@/lib/env", () => ({ env: environment }));
vi.mock("@/lib/github/workflows", () => ({ dispatchPrivateYoonWorkflow: dispatch }));
const setRunId = "a0000000-0000-4000-8000-000000000010";
const generation = "a0000000-0000-4000-8000-000000000020";
const sql = (index = 0) => new PgDialect().sqlToQuery(db.execute.mock.calls[index][0]);
describe("private Yoon dispatch", () => {
  beforeEach(() => { vi.resetModules(); vi.clearAllMocks(); environment.deploymentTarget = "development";
    db.execute.mockResolvedValue({ rows: [{ id: setRunId }] }); dispatch.mockResolvedValue({ dispatched: true }); });
  it("checks configured Preview isolation before accessing private data", async () => {
    environment.deploymentTarget = "production";
    const { dispatchPrivateYoon } = await import("./private-yoon-dispatch");
    expect((await dispatchPrivateYoon({ setRunId, generation })).dispatched).toBe(false);
    expect(db.execute).not.toHaveBeenCalled(); expect(dispatch).not.toHaveBeenCalled();
  });
  it("claims one exact private identity before external dispatch", async () => {
    const { dispatchPrivateYoon } = await import("./private-yoon-dispatch");
    expect(await dispatchPrivateYoon({ setRunId, generation })).toEqual({ dispatched: true });
    const claim = sql();
    for (const gate of ["publication_visibility='private'", "s.visibility='private'", "u.visibility='private'", "r.cancel_requested_at IS NULL", "u.cancel_requested_at IS NULL", "r.published_set_id IS NULL", "'descriptor'=r.source_metadata->'yoon_fixed_input'", "archive_collection_members", "'status'='reserved'", "'generation'"]) expect(claim.sql).toContain(gate);
    expect(claim.params).toContain(generation);
    expect(dispatch).toHaveBeenCalledExactlyOnceWith(setRunId, { dispatch_generation: generation });
    expect(db.execute.mock.invocationCallOrder[0]).toBeLessThan(dispatch.mock.invocationCallOrder[0]);
    expect(sql(1).sql).toContain("'status'='sending'"); // Cannot overwrite consumed owner.
  });
  it("never dispatches a lost reservation", async () => {
    db.execute.mockResolvedValue({ rows: [] });
    const { dispatchPrivateYoon } = await import("./private-yoon-dispatch");
    expect((await dispatchPrivateYoon({ setRunId, generation })).reason).toBe("fence_changed");
    expect(dispatch).not.toHaveBeenCalled();
  });
  it("keeps an uncertain send reserved and never exposes provider errors", async () => {
    dispatch.mockRejectedValue(new Error("synthetic private secret"));
    const { dispatchPrivateYoon } = await import("./private-yoon-dispatch");
    expect(await dispatchPrivateYoon({ setRunId, generation })).toEqual({ dispatched: false, reason: "dispatch_requires_reconciliation" });
    expect(db.execute).toHaveBeenCalledTimes(1); expect(dispatch).toHaveBeenCalledTimes(1);
  });
  it("fences controller rollover once per monotonic workflow attempt", async () => {
    const { dispatchPrivateYoon } = await import("./private-yoon-dispatch");
    expect(await dispatchPrivateYoon({ setRunId, controller: true, workflowRunId: "9001", runAttempt: "1" })).toEqual({ dispatched: true });
    expect(sql().sql).toContain("last_wake"); expect(sql().sql).toContain("::numeric <");
    expect(dispatch).toHaveBeenCalledExactlyOnceWith(setRunId, { resume_mode: "private_queue" });
  });
});
