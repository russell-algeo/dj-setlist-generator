import { beforeEach, describe, expect, it, vi } from "vitest";

const getSessionActor = vi.fn();
const refreshSpotifyAccessTokenForUser = vi.fn();
const fetchMock = vi.fn();

vi.mock("@/lib/auth/session", () => ({ getSessionActor }));
vi.mock("@/lib/spotify/server", async () => {
  class SpotifyConnectionError extends Error {}
  class SpotifyConfigurationError extends Error {}
  class SpotifyTokenRefreshError extends Error {}
  return {
    refreshSpotifyAccessTokenForUser,
    SpotifyConnectionError,
    SpotifyConfigurationError,
    SpotifyTokenRefreshError,
  };
});

const TRACK = "7crxOiKNyPIb2rkCkCWlH7";
const post = (body: unknown, contentType = "application/json") =>
  new Request("https://example.test/api/spotify/library", {
    method: "POST",
    headers: { "content-type": contentType },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });

describe("POST /api/spotify/library", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.stubGlobal("fetch", fetchMock);
    getSessionActor.mockResolvedValue({ userId: "u1" });
    fetchMock.mockResolvedValue(new Response(null, { status: 200 }));
  });

  it("rejects non-JSON bodies so a cross-site form cannot save", async () => {
    const { POST } = await import("./route");
    const response = await POST(post(`trackId=${TRACK}&saved=true`, "application/x-www-form-urlencoded"));
    expect(response.status).toBe(415);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("requires a signed-in session", async () => {
    getSessionActor.mockResolvedValue(null);
    const { POST } = await import("./route");
    const response = await POST(post({ trackId: TRACK, saved: true }));
    expect(response.status).toBe(401);
    expect(await response.json()).toMatchObject({ reason: "signin" });
  });

  it("asks to reconnect when the connection lacks the library scope, without calling Spotify", async () => {
    refreshSpotifyAccessTokenForUser.mockResolvedValue({
      accessToken: "tok",
      scopes: ["user-read-email", "playlist-modify-private", "playlist-modify-public"],
    });
    const { POST } = await import("./route");
    const response = await POST(post({ trackId: TRACK, saved: true }));
    expect(response.status).toBe(409);
    expect(await response.json()).toMatchObject({ reason: "connect" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("saves the track when the scope is granted", async () => {
    refreshSpotifyAccessTokenForUser.mockResolvedValue({ accessToken: "tok", scopes: ["user-library-modify"] });
    const { POST } = await import("./route");
    const response = await POST(post({ trackId: TRACK, saved: true }));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ saved: true });
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "PUT" });
  });

  it("rejects invalid track ids", async () => {
    const { POST } = await import("./route");
    const response = await POST(post({ trackId: "nope", saved: true }));
    expect(response.status).toBe(400);
    expect(refreshSpotifyAccessTokenForUser).not.toHaveBeenCalled();
  });
});
