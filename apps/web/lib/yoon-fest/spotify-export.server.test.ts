import { describe, expect, it, vi } from "vitest";
import { buildYoonExportPlan, exportYoonPlaylist, type YoonExportDeps } from "./spotify-export.server";
import { actor, authorizeFixture, fixture, principals } from "./fixtures.test-support";
const request = (body: unknown = { entityType: "set", slug: "synthetic-set", confidenceFilter: "all" }, origin = "https://example.test") => new Request("https://example.test/api/yoon-fest/spotify/export", { method: "POST", headers: { "content-type": "application/json", origin }, body: JSON.stringify(body) });
const make = (): YoonExportDeps => ({ actor: vi.fn().mockResolvedValue(actor()), authorize: authorizeFixture, collection: vi.fn().mockReturnValue(fixture),
  refresh: vi.fn().mockResolvedValue({ accessToken: "synthetic-secret-not-for-response", spotifyUserId: "synthetic-spotify-account", scopes: ["playlist-modify-private"], expiresIn: 60 }),
  fetch: vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ id: "synthetic-playlist", name: "Synthetic Set", external_urls: { spotify: "https://open.spotify.com/playlist/synthetic-playlist" } }) }).mockResolvedValue({ ok: true }),
});
describe("private Yoon Spotify export", () => {
  it.each([null, actor("outsider"), actor("outsider", { isAdmin: true, isAllowlisted: true })])("denies before data resolution or Spotify access", async (viewer) => { const deps = make(); deps.actor = async () => viewer; expect((await exportYoonPlaylist(request(), deps)).status).toBe(404); expect(deps.collection).not.toHaveBeenCalled(); expect(deps.refresh).not.toHaveBeenCalled(); expect(deps.fetch).not.toHaveBeenCalled(); });
  it.each(["https://outsider.test", "null", ""])("rejects cross-origin/originless write %s", async (origin) => { const deps = make(); expect((await exportYoonPlaylist(request(undefined, origin), deps)).status).toBe(403); expect(deps.collection).not.toHaveBeenCalled(); expect(deps.fetch).not.toHaveBeenCalled(); });
  it("creates the requested playlist only in the authenticated actor's account", async () => {
    const deps = make(); const response = await exportYoonPlaylist(request(), deps);
    expect(response.status).toBe(201); expect(deps.refresh).toHaveBeenCalledWith(principals.russellUserId);
    const create = vi.mocked(deps.fetch).mock.calls[0]!; expect(create[0]).toBe("https://api.spotify.com/v1/users/synthetic-spotify-account/playlists");
    const metadata = JSON.parse(String(create[1]!.body)); expect(metadata.public).toBe(false); expect(metadata.name).toBe("Synthetic Set");
    expect(metadata.description).not.toContain("/sets/"); expect(metadata.description).not.toContain("/collections/"); expect(metadata.description).not.toContain("synthetic-a");
    expect(JSON.parse(String(vi.mocked(deps.fetch).mock.calls[1]![1]!.body)).uris).toEqual(["spotify:track:syntheticA", "spotify:track:syntheticB"]);
    expect(response.headers.get("Cache-Control")).toContain("no-store"); expect(await response.text()).not.toContain("synthetic-secret");
  });
  it("supports Hal using Hal's own connected account", async () => { const deps = make(); deps.actor = async () => actor(principals.halUserId); expect((await exportYoonPlaylist(request(), deps)).status).toBe(201); expect(deps.refresh).toHaveBeenCalledWith(principals.halUserId); });
  it("keeps festival order and deduplicates after confidence filtering", () => {
    const data = structuredClone(fixture); data.sets.push({ ...structuredClone(data.sets[0]!), slug: "second-set", tracks: [
      { ...data.sets[0]!.tracks[1]!, confidence: "HIGH" }, { ...data.sets[0]!.tracks[0]!, confidence: "HIGH" },
    ] });
    expect(buildYoonExportPlan(data, { entityType: "festival", slug: "yoon-fest", confidenceFilter: "HIGH" })?.spotifyTrackIds).toEqual(["syntheticA", "syntheticB"]);
    expect(buildYoonExportPlan(data, { entityType: "festival", slug: "other", confidenceFilter: "all" })).toBeNull();
  });
  it("rejects arbitrary recipients, fields and unknown set slugs", async () => {
    const deps = make(); expect((await exportYoonPlaylist(request({ entityType: "set", slug: "synthetic-set", confidenceFilter: "all", userId: "outsider" }), deps)).status).toBe(400);
    expect((await exportYoonPlaylist(request({ entityType: "set", slug: "missing", confidenceFilter: "all" }), deps)).status).toBe(404); expect(deps.fetch).not.toHaveBeenCalled();
  });
  it("does not write an empty playlist", async () => { const deps = make(); expect((await exportYoonPlaylist(request({ entityType: "set", slug: "synthetic-set", confidenceFilter: "MEDIUM" }), deps)).status).toBe(422); expect(deps.refresh).not.toHaveBeenCalled(); expect(deps.fetch).not.toHaveBeenCalled(); });
  it("uses 100-track batches for a festival", async () => {
    const data = structuredClone(fixture); data.sets[0]!.tracks = Array.from({ length: 201 }, (_, i) => ({ ...fixture.sets[0]!.tracks[0]!, position: i + 1, spotifyUrl: `https://open.spotify.com/track/synthetic${i}` }));
    const deps = make(); deps.collection = () => data;
    expect((await exportYoonPlaylist(request({ entityType: "festival", slug: "yoon-fest", confidenceFilter: "all" }), deps)).status).toBe(201);
    expect(vi.mocked(deps.fetch).mock.calls.slice(1).map((call) => JSON.parse(String(call[1]!.body)).uris.length)).toEqual([100, 100, 1]);
  });
  it("reports partial creation without retrying or exposing raw errors", async () => { const deps = make(); vi.mocked(deps.fetch).mockReset().mockResolvedValueOnce({ ok: true, json: async () => ({ id: "partial", name: "Synthetic" }) } as Response).mockResolvedValueOnce({ ok: false, text: async () => "sensitive remote details" } as Response); const r = await exportYoonPlaylist(request(), deps); expect(r.status).toBe(502); const body = await r.text(); expect(body).toContain("Check it in Spotify"); expect(body).not.toContain("sensitive remote details"); expect(deps.fetch).toHaveBeenCalledTimes(2); });
  it("does not create when the existing grant lacks playlist permission", async () => { const deps = make(); vi.mocked(deps.refresh).mockResolvedValue({ accessToken: "secret", spotifyUserId: "id", scopes: [], expiresIn: 60 }); expect((await exportYoonPlaylist(request(), deps)).status).toBe(502); expect(deps.fetch).not.toHaveBeenCalled(); });
});
