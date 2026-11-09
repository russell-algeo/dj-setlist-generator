import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { dropboxPlaybackUrl } from "./dropbox-source.server";

// Structurally representative only. No real source capability or recording name.
const base = "https://www.dropbox.com/scl/fo/synthetic-folder/synthetic-token/";
const query = "?rlkey=synthetic-key&dl=1";
const source = `${base}fixture.wav${query}`;
const raw = `${base}fixture.wav?rlkey=synthetic-key&raw=1`;
afterEach(() => vi.unstubAllEnvs());
beforeEach(() => {
  vi.stubEnv("APP_ENVIRONMENT", "development");
  vi.stubEnv("VERCEL_ENV", "preview");
  vi.stubEnv("NODE_ENV", "production");
});

describe("reviewed folder-capability concrete audio file", () => {
  it("preserves both path capabilities and rlkey, normalizing only media mode", () => {
    expect(dropboxPlaybackUrl(source)).toBe(raw);
    expect(dropboxPlaybackUrl(raw)).toBe(raw);
  });
  it.each(["fixture.wav", "fixture.FLAC", "fixture.m4a", "fixture.mp4", "fixture.mp3", "Live%20Set%20%28Part%201%29.wav", "caf%C3%A9.wav", "fixture%2Ewav"])("accepts one explicit audio filename %s", (name) => {
    expect(dropboxPlaybackUrl(`${base}${name}${query}`)).toBe(`${base}${name}?rlkey=synthetic-key&raw=1`);
  });
  it.each([
    ["folder root", "https://www.dropbox.com/scl/fo/synthetic-folder/synthetic-token?rlkey=synthetic-key&dl=1"],
    ["folder slash", `${base}${query}`],
    ["ZIP", `${base}archive.zip${query}`],
    ["disguised ZIP", `${base}fixture.wav.zip${query}`],
    ["no filename extension", `${base}fixture${query}`],
    ["missing basename", `${base}.wav${query}`],
    ["nested file", `${base}nested/fixture.wav${query}`],
    ["trailing slash", `${base}fixture.wav/${query}`],
    ["query-selected file", `${base.slice(0, -1)}?rlkey=synthetic-key&preview=fixture.wav`],
    ["listing query", `${base}fixture.wav?rlkey=synthetic-key&view=list`],
    ["ZIP query", `${base}fixture.wav?rlkey=synthetic-key&zip=1`],
    ["missing capability", `${base}fixture.wav?raw=1`],
    ["empty capability", `${base}fixture.wav?rlkey=&dl=1`],
    ["duplicate capability", `${base}fixture.wav?rlkey=one&rlkey=two`],
    ["query injection", `${base}fixture.wav?rlkey=a%26path%3Db`],
    ["unexpected raw value", `${base}fixture.wav?rlkey=synthetic-key&raw=true`],
    ["unexpected download value", `${base}fixture.wav?rlkey=synthetic-key&dl=2`],
    ["duplicate media mode", `${base}fixture.wav?rlkey=synthetic-key&raw=0&raw=1`],
    ["duplicate download mode", `${base}fixture.wav?rlkey=synthetic-key&dl=0&dl=1`],
    ["unsupported CDN folder path", source.replace("www.dropbox.com", "dl.dropboxusercontent.com")],
    ["HTTP", source.replace("https:", "http:")],
    ["lookalike host", source.replace("www.dropbox.com", "www.dropbox.com.evil.invalid")],
    ["explicit port", source.replace("www.dropbox.com", "www.dropbox.com:443")],
    ["credentials", source.replace("www.dropbox.com", "user:pass@www.dropbox.com")],
    ["fragment", `${source}#preview`],
  ])("rejects %s", (_, value) => expect(dropboxPlaybackUrl(value)).toBeNull());
  it.each(["..", "%2e%2e", ".", "%2e", "nested%2ffixture.wav", "nested%5cfixture.wav", "nested%252ffixture.wav", "%252e%252e.wav", "fi%00xture.wav", "fi%0axture.wav", "fi%7fxture.wav", "fi%3fxture.wav", "fi%23xture.wav", "bad%ZZ.wav"])("rejects encoded traversal, separator or control %s", (name) => expect(dropboxPlaybackUrl(`${base}${name}${query}`)).toBeNull());
});

describe("development and Preview-only folder approval", () => {
  it.each([
    ["production", "development", "development"],
    ["preview", "production", "production"],
    [" PRODUCTION ", "development", "development"],
    [undefined, undefined, "production"],
    [undefined, "development", "production"],
    ["development", "development", "production"],
    ["staging", "development", "development"],
    ["preview", "unknown", "production"],
    [undefined, undefined, "test"],
  ])("denies Vercel %s / app %s / Node %s", (vercel, app, node) => {
    vi.stubEnv("VERCEL_ENV", vercel); vi.stubEnv("APP_ENVIRONMENT", app); vi.stubEnv("NODE_ENV", node);
    expect(dropboxPlaybackUrl(source)).toBeNull();
  });
  it.each([
    ["preview", "development", "production"],
    ["preview", undefined, "production"],
    ["development", "development", "development"],
    [undefined, undefined, "development"],
  ])("allows Vercel %s / app %s / Node %s", (vercel, app, node) => {
    vi.stubEnv("VERCEL_ENV", vercel); vi.stubEnv("APP_ENVIRONMENT", app); vi.stubEnv("NODE_ENV", node);
    expect(dropboxPlaybackUrl(source)).toBe(raw);
  });
});

describe("legacy standalone file sharing", () => {
  it.each(["production", "preview", "unknown"])("retains existing standalone links in %s", (target) => {
    vi.stubEnv("VERCEL_ENV", target); vi.stubEnv("APP_ENVIRONMENT", "production");
    for (const prefix of ["https://www.dropbox.com/scl/fi", "https://dropbox.com/s", "https://dl.dropboxusercontent.com/s"]) {
      expect(dropboxPlaybackUrl(`${prefix}/synthetic-id/Live%20Set.wav?rlkey=synthetic&dl=0`)).toBe(`${prefix}/synthetic-id/Live%20Set.wav?rlkey=synthetic&raw=1`);
    }
  });
  it.each([
    "https://www.dropbox.com/scl/fo/folder/token/../../../fi/id/fixture.wav?rlkey=synthetic",
    "https://www.dropbox.com/scl/fi/id/nested/../fixture.wav",
    "https://www.dropbox.com/scl/fi/id/nested/%2e%2e/fixture.wav",
    "https://www.dropbox.com/scl/fi/id/fi\nxture.wav",
    "https://www.dropbox.com:443/scl/fi/id/fixture.wav",
  ])("rejects pre-normalization ambiguity %s", (value) => expect(dropboxPlaybackUrl(value)).toBeNull());
});

describe("validated collection and media route integration", () => {
  it("accepts a synthetic folder file in Preview without serializing its bearer capability", async () => {
    const { yoonCollectionSchema } = await import("./collection-model.server");
    const { toYoonSetDetail } = await import("./data.server");
    const { fixture } = await import("./fixtures.test-support");
    const collection = structuredClone(fixture);
    collection.sets[0]!.audio.sources[0]!.url = source;
    const parsed = yoonCollectionSchema.parse(collection);
    expect(parsed.sets[0]!.audio.sources[0]!.url).toBe(raw);
    expect(JSON.stringify(toYoonSetDetail(parsed.sets[0]!))).not.toMatch(/dropbox|synthetic-key|synthetic-folder|rlkey/);
    vi.stubEnv("VERCEL_ENV", "production");
    expect(yoonCollectionSchema.safeParse(collection).success).toBe(false);
  });
  it.each(["GET", "HEAD"])("releases only the member's reviewed file on %s and denies it in Production", async (method) => {
    const { serveYoonMedia } = await import("./media.server");
    const { fixture, actor, authorizeFixture } = await import("./fixtures.test-support");
    const collection = structuredClone(fixture);
    collection.sets[0]!.audio.sources[0]!.url = source;
    const assetId = collection.sets[0]!.audio.assetId;
    const request = new Request(`https://example.test/api/yoon-fest/media/${assetId}`, { method });
    const deps = { actor: async () => actor(), authorize: authorizeFixture, collection: vi.fn().mockReturnValue(collection) };
    const response = await serveYoonMedia(request, assetId, deps);
    expect(response.status).toBe(307);
    expect(response.headers.get("Location")).toBe(raw);
    expect(response.headers.get("Cache-Control")).toContain("no-store");
    expect(response.headers.get("Vercel-CDN-Cache-Control")).toBe("no-store");
    expect(response.headers.get("Referrer-Policy")).toBe("no-referrer");
    expect(await response.text()).toBe("");
    vi.stubEnv("VERCEL_ENV", "production");
    const denied = await serveYoonMedia(request, assetId, deps);
    expect(denied.status).toBe(404);
    expect(denied.headers.get("Location")).toBeNull();
  });
  it.each(["anonymous", "nonmember"])("never reads or releases a folder capability to %s", async (principal) => {
    const { serveYoonMedia } = await import("./media.server");
    const { actor, authorizeFixture } = await import("./fixtures.test-support");
    const collection = vi.fn();
    const response = await serveYoonMedia(new Request("https://example.test/api/yoon-fest/media/synthetic"), "synthetic", {
      actor: async () => principal === "anonymous" ? null : actor("outsider"), authorize: authorizeFixture, collection,
    });
    expect(response.status).toBe(404);
    expect(response.headers.get("Location")).toBeNull();
    expect(collection).not.toHaveBeenCalled();
  });
});
