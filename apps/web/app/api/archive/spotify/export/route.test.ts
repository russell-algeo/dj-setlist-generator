import { beforeEach, describe, expect, it, vi } from "vitest";

const getRequestActor = vi.fn();
const executeSpotifyExport = vi.fn();

vi.mock("@/lib/auth/session", () => ({
  getRequestActor,
}));

vi.mock("@/lib/archive/spotify-export.server", () => ({
  SpotifyExportNoTracksError: class SpotifyExportNoTracksError extends Error {},
  SpotifyExportNotFoundError: class SpotifyExportNotFoundError extends Error {},
  SpotifyExportRemoteError: class SpotifyExportRemoteError extends Error {},
  SpotifyExportScopeError: class SpotifyExportScopeError extends Error {},
  executeSpotifyExport,
}));

vi.mock("@/lib/spotify/server", () => ({
  SpotifyConfigurationError: class SpotifyConfigurationError extends Error {},
  SpotifyConnectionError: class SpotifyConnectionError extends Error {},
  SpotifyTokenRefreshError: class SpotifyTokenRefreshError extends Error {},
}));

describe("POST /api/archive/spotify/export", () => {
  beforeEach(() => {
    getRequestActor.mockReset();
    executeSpotifyExport.mockReset();
  });

  it("returns 401 when the request is unauthenticated", async () => {
    getRequestActor.mockResolvedValue(null);

    const { POST } = await import("./route");
    const response = await POST(
      new Request("http://localhost/api/archive/spotify/export", {
        body: JSON.stringify({
          confidenceFilter: "all",
          entityType: "set",
          slug: "demo",
        }),
        headers: {
          "content-type": "application/json",
        },
        method: "POST",
      }),
    );

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toEqual({ error: "Authentication required" });
    expect(executeSpotifyExport).not.toHaveBeenCalled();
  });
});
