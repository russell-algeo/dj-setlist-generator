import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  env: { deploymentTarget: "production" },
  getRequestActor: vi.fn(),
  createSubmission: vi.fn(),
  parseSubmissionInput: vi.fn((value) => value),
  dispatchPendingWork: vi.fn(),
}));
vi.mock("@/lib/env", () => ({ env: mocks.env }));
vi.mock("@/lib/auth/session", () => ({ getRequestActor: mocks.getRequestActor }));
vi.mock("@/lib/jobs/submissions", () => ({ createSubmission: mocks.createSubmission, parseSubmissionInput: mocks.parseSubmissionInput }));
vi.mock("@/lib/jobs/dispatch", () => ({ dispatchPendingWork: mocks.dispatchPendingWork }));
vi.mock("@/lib/jobs/public.server", () => ({ listPublicSubmissionsForActor: vi.fn() }));

import { POST } from "./route";

const request = (overrides: Record<string, unknown> = {}) => new Request(
  "https://production.example/api/jobs?deploymentTarget=development&allowDiscoveryMaxSets=true",
  {
    method: "POST",
    headers: { "content-type": "application/json", "x-deployment-target": "development" },
    body: JSON.stringify({ mode: "artist", artistName: "Phil Weeks", artistAliases: ["Alias"], ...overrides }),
  },
);

describe("Preview-only discovery cap at the application boundary", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubEnv("VERCEL_ENV", "");
    mocks.env.deploymentTarget = "production";
    mocks.getRequestActor.mockResolvedValue({ authType: "session", userId: "test-user" });
    mocks.createSubmission.mockResolvedValue({ submission: { id: "submission-id" }, warnings: [] });
    mocks.dispatchPendingWork.mockResolvedValue({});
  });
  afterEach(() => vi.unstubAllEnvs());

  it("accepts cap1 and aliases when the trusted server environment is development", async () => {
    mocks.env.deploymentTarget = "development";
    const response = await POST(request({ maxSetsOverride: "1" }));
    expect(response.status).toBe(201);
    expect(mocks.createSubmission).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({
      maxSetsOverride: 1, artistAliases: ["Alias"], createPlaylist: false,
    }));
    expect(mocks.dispatchPendingWork).toHaveBeenCalledOnce();
  });

  it.each(["session", "api_token"])("rejects Production caps for %s even with forged client flags", async (authType) => {
    mocks.getRequestActor.mockResolvedValue({ authType, userId: "test-user" });
    const response = await POST(request({ maxSetsOverride: "1", allowDiscoveryMaxSets: true, deploymentTarget: "development" }));
    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({ error: "Maximum sets is available only in Preview." });
    expect(mocks.parseSubmissionInput).not.toHaveBeenCalled();
    expect(mocks.createSubmission).not.toHaveBeenCalled();
    expect(mocks.dispatchPendingWork).not.toHaveBeenCalled();
  });

  it("preserves ordinary Production submissions without an override", async () => {
    const response = await POST(request());
    expect(response.status).toBe(201);
    expect(mocks.createSubmission).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ maxSetsOverride: undefined, createPlaylist: false }));
  });

  it("rejects a platform Production override even when the app is misconfigured as development", async () => {
    mocks.env.deploymentTarget = "development";
    vi.stubEnv("VERCEL_ENV", "production");
    expect((await POST(request({ maxSetsOverride: "1" }))).status).toBe(400);
    expect(mocks.parseSubmissionInput).not.toHaveBeenCalled();
    expect(mocks.createSubmission).not.toHaveBeenCalled();
    expect(mocks.dispatchPendingWork).not.toHaveBeenCalled();
  });

  it("rejects empty or invalid supplied Production overrides instead of silently running uncapped", async () => {
    for (const maxSetsOverride of ["", 0, -1, 1.5, null]) {
      expect((await POST(request({ maxSetsOverride }))).status).toBe(400);
    }
    expect(mocks.createSubmission).not.toHaveBeenCalled();
    expect(mocks.dispatchPendingWork).not.toHaveBeenCalled();
  });

  it("still requires authentication before evaluating the submission", async () => {
    mocks.getRequestActor.mockResolvedValue(null);
    expect((await POST(request({ maxSetsOverride: "1" }))).status).toBe(401);
    expect(mocks.createSubmission).not.toHaveBeenCalled();
  });
});
