import { beforeEach, describe, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({ actor: vi.fn(), access: vi.fn(), read: vi.fn() }));
vi.mock("@/lib/auth/session", () => ({ getRequestActor: mocks.actor, canAccessSubmission: mocks.access }));
vi.mock("@/lib/jobs/public.server", () => ({ getPublicSubmissionRunEventsPage: mocks.read }));
import { GET } from "./route";
const page = { events: [], page: 1, pageSize: 6, totalCount: 0, totalPages: 1 };
const request = (query = "") => new Request(`https://example.invalid/api/jobs/sub/runs/run/events${query}`);
const params = { params: Promise.resolve({ submissionId: "sub", setRunId: "run" }) };
describe("run events endpoint compatibility", () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.actor.mockResolvedValue({userId:"owner"}); mocks.access.mockResolvedValue(true); mocks.read.mockResolvedValue(page); });
  it("requires authentication before reading events", async () => { mocks.actor.mockResolvedValue(null); expect((await GET(request(), params)).status).toBe(401); expect(mocks.read).not.toHaveBeenCalled(); });
  it("requires submission access before reading events", async () => { mocks.access.mockResolvedValue(false); expect((await GET(request(), params)).status).toBe(404); expect(mocks.read).not.toHaveBeenCalled(); });
  it("returns missing run as404", async () => { mocks.read.mockResolvedValue(null); expect((await GET(request(), params)).status).toBe(404); });
  it.each(["", "?page=NaN&pageSize=Infinity", "?page=-1&pageSize=0"])("preserves default inputs for %s", async (query) => { const response=await GET(request(query),params); expect(response.status).toBe(200); expect(mocks.read).toHaveBeenCalledWith(expect.objectContaining({page:1,pageSize:6,setRunId:"run",submissionId:"sub"})); expect(await response.json()).toEqual(page); });
  it("floors positive fractional request inputs", async () => { await GET(request("?page=2.9&pageSize=7.5"),params); expect(mocks.read).toHaveBeenCalledWith(expect.objectContaining({page:2,pageSize:7})); });
  it("retains large page request for reader clamping", async () => { await GET(request("?page=999&pageSize=100"),params); expect(mocks.read).toHaveBeenCalledWith(expect.objectContaining({page:999,pageSize:100})); });
});
