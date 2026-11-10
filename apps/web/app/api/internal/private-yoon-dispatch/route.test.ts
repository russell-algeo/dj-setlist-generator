import { beforeEach, expect, it, vi } from "vitest";
const auth = vi.fn(); const dispatch = vi.fn();
vi.mock("@/lib/auth/session", () => ({ assertInternalRequest: auth }));
vi.mock("@/lib/jobs/private-yoon-dispatch", () => ({ dispatchPrivateYoon: dispatch }));
const body = { setRunId: "a0000000-0000-4000-8000-000000000010", generation: "a0000000-0000-4000-8000-000000000020" };
const request = (data: unknown) => new Request("https://example.invalid/api/internal/private-yoon-dispatch", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(data) });
beforeEach(() => { vi.resetModules(); vi.clearAllMocks(); auth.mockReturnValue(null); dispatch.mockResolvedValue({ dispatched: true }); });
it("requires internal authentication before parsing private input", async () => {
  auth.mockReturnValue(new Response(null, { status: 401 }));
  const { POST } = await import("./route"); expect((await POST(request(body))).status).toBe(401); expect(dispatch).not.toHaveBeenCalled();
});
it.each([{ ...body, source_url: "private" }, { ...body, generation: "bad" }, { setRunId: body.setRunId, controller: true, workflowRunId: "9", runAttempt: "bad" }])("rejects unexpected data or malformed fences", async (data) => {
  const { POST } = await import("./route"); expect((await POST(request(data))).status).toBe(400); expect(dispatch).not.toHaveBeenCalled();
});
it("returns accepted dispatch only after the dispatcher confirms it", async () => {
  const { POST } = await import("./route"); expect((await POST(request(body))).status).toBe(200);
  dispatch.mockResolvedValue({ dispatched: false, reason: "dispatch_requires_reconciliation" }); expect((await POST(request(body))).status).toBe(409);
});
