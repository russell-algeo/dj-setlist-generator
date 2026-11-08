import { beforeEach, describe, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({ execute: vi.fn(), dispatch: vi.fn(), event: vi.fn() }));
vi.mock("server-only", () => ({}));
vi.mock("@/lib/db/client", () => ({ getDb: () => ({ execute: mocks.execute }) }));
vi.mock("@/lib/jobs/dispatch", () => ({ dispatchPendingWork: mocks.dispatch }));
vi.mock("@/lib/jobs/internal", () => ({ createWorkerEvent: mocks.event }));
import { runSchedulerRecovery } from "./scheduler";

describe("scheduler recovery", () => {
  beforeEach(() => vi.resetAllMocks());
  it("finishes recovery and cleanup before dispatching once", async () => {
    const order: string[] = [];
    mocks.execute
      .mockImplementationOnce(async () => { order.push("leases"); return { rows: [{ recovered: 2 }] }; })
      .mockImplementationOnce(async () => { order.push("runs"); return { rows: [{ recovered: 1 }] }; })
      .mockImplementationOnce(async () => { order.push("cleanup"); return { rows: [{ counts: {} }] }; });
    mocks.dispatch.mockImplementation(async () => { order.push("dispatch"); return { artistDispatch: [], setDispatch: [] }; });
    const result = await runSchedulerRecovery();
    expect(order).toEqual(["leases", "runs", "cleanup", "dispatch"]);
    expect(result).toMatchObject({ recoveredLeases: 2, recoveredRuns: 1 });
    expect(mocks.dispatch).toHaveBeenCalledTimes(1);
    expect(mocks.event).toHaveBeenCalledOnce();
  });
  it("does not dispatch when recovery fails", async () => {
    mocks.execute.mockRejectedValueOnce(new Error("database unavailable"));
    await expect(runSchedulerRecovery()).rejects.toThrow("database unavailable");
    expect(mocks.dispatch).not.toHaveBeenCalled();
  });
  it("empty recovery dispatches once without a misleading recovery event", async () => {
    mocks.execute.mockResolvedValue({ rows: [] });
    mocks.dispatch.mockResolvedValue({ artistDispatch: [], setDispatch: [] });
    expect(await runSchedulerRecovery()).toMatchObject({ recoveredLeases: 0, recoveredRuns: 0 });
    expect(mocks.event).not.toHaveBeenCalled();
    expect(mocks.dispatch).toHaveBeenCalledTimes(1);
  });
});
