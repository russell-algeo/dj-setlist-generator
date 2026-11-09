import { describe, expect, it, vi } from "vitest";
import { serveYoonMedia, type YoonMediaDeps } from "./media.server";
import { dropboxPlaybackUrl } from "./dropbox-source.server";
import { actor, authorizeFixture, fixture } from "./fixtures.test-support";
const id = fixture.sets[0]!.audio.assetId;
const make = (): YoonMediaDeps => ({ actor: vi.fn().mockResolvedValue(actor()), authorize: authorizeFixture, collection: vi.fn().mockReturnValue(fixture) });
const request = (part = "0", method = "GET") => new Request(`https://example.test/api/yoon-fest/media/${id}?part=${part}`, { method, headers: { Range: "bytes=100-199" } });
describe("authorized Dropbox URL release", () => {
  it.each([null, actor("outsider"), actor("outsider", { isAdmin: true })])("denies before looking up a bearer link", async (viewer) => { const deps = make(); deps.actor = async () => viewer; const response = await serveYoonMedia(request(), id, deps); expect(response.status).toBe(404); expect(response.headers.get("Location")).toBeNull(); expect(deps.collection).not.toHaveBeenCalled(); });
  it.each(["GET", "HEAD"])("redirects authorized %s directly to the selected Dropbox file without relaying bytes", async (method) => { const response = await serveYoonMedia(request("1", method), id, make()); expect(response.status).toBe(307); expect(response.headers.get("Location")).toBe(fixture.sets[0]!.audio.sources[1]!.url); expect(await response.text()).toBe(""); expect(response.headers.get("Cache-Control")).toContain("no-store"); expect(response.headers.get("Referrer-Policy")).toBe("no-referrer"); expect(response.headers.get("Access-Control-Allow-Origin")).toBeNull(); });
  it.each(["-1", "2", "1.5", "00", "NaN", "99999999999999999"])("does not disclose an invalid part %s", async (part) => expect((await serveYoonMedia(request(part), id, make())).status).toBe(404));
  it("does not reuse an authorized link response for a later nonmember", async () => { const deps = make(); expect((await serveYoonMedia(request(), id, deps)).status).toBe(307); deps.actor = async () => null; const response = await serveYoonMedia(request(), id, deps); expect(response.status).toBe(404); expect(response.headers.get("Location")).toBeNull(); });
  it("rejects unknown assets", async () => expect((await serveYoonMedia(request(), "missing", make())).status).toBe(404));
  it("normalizes the reviewed file to raw streaming", () => expect(dropboxPlaybackUrl("https://www.dropbox.com/scl/fi/synthetic/file.wav?rlkey=test&dl=0")).toBe("https://www.dropbox.com/scl/fi/synthetic/file.wav?rlkey=test&raw=1"));
  it.each(["http://www.dropbox.com/s/a/file.wav", "https://dropbox.com.evil.invalid/s/a/file.wav", "https://user:password@dropbox.com/s/a/file.wav", "https://dropbox.com/login", "https://example.invalid/file.wav", "javascript:alert(1)"])("never redirects to an unreviewed target %s", (value) => expect(dropboxPlaybackUrl(value)).toBeNull());
});
