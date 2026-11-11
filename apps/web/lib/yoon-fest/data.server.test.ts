import { readFileSync } from "node:fs";
import { PgDialect } from "drizzle-orm/pg-core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { actor, fixture } from "./fixtures.test-support";
const { select, authorize, joins, predicates, queue } = vi.hoisted(() => ({ select: vi.fn(), authorize: vi.fn(), joins: [] as unknown[], predicates: [] as unknown[], queue: [] as unknown[][] }));
vi.mock("@/lib/db/client", () => ({ getDb: () => ({ select }) }));
vi.mock("./access.server", () => ({ assertYoonAccess: authorize }));
vi.mock("next/cache", () => ({ unstable_noStore: vi.fn() }));
import { getYoonSet, getYoonSetByAsset, loadYoonCollection, toYoonSetDetail } from "./data.server";
const example = fixture.sets[0]!;
describe("private collection reader", () => {
  it.skipIf(!process.env.YOON_PARITY_PLAN_FILE)("projects the local private production receipt end to end (fixture is never committed)", async () => {
    const input = JSON.parse(readFileSync(process.env.YOON_PARITY_PLAN_FILE!, "utf8"));
    const publication = input.publication;
    const plan = input.plan;
    const set = publication.set;
    const media = publication.media[0];
    queue.push([{ id: set.id, slug: set.slug, title: set.title, metadata: plan.set_metadata,
      audioId: media.id, revision: media.revision, duration: String(media.duration_seconds), contentType: media.content_type,
      sourceSpans: media.source_spans, sources: media.recording_sources }],
      plan.entries.map((entry: { position: number; metadata: Record<string, unknown> }) => {
        const m = entry.metadata;
        return { setId: set.id, position: entry.position, artist: m.artist, title: m.title,
          start: Math.round(Number(m.start_time)), end: Math.round(Number(m.end_time)), confidence: m.confidence,
          detectionCount: m.detection_count, clusterDensity: String(m.cluster_density), clusterSpan: m.cluster_span, metadata: m };
      }));
    const detail = toYoonSetDetail((await loadYoonCollection(actor())).sets[0]!);
    expect(detail.tracks.length).toBe(23);
    for (const [field, count] of [["spotifyUrl",16],["albumArt",16],["youtubeUrl",14],["discogsUrl",16],["bpm",14]] as const) {
      expect(detail.tracks.filter((track) => track[field] != null).length).toBe(count);
    }
    expect(detail.tracks.filter((track) => track.title === "Unknown Track").length).toBe(5);
    expect(detail.journeyPoints.length).toBe(14); expect(detail.stats.identifiedTracks).toBe(18);
    expect(Boolean(detail.generatedAt)).toBe(true);
    expect(detail.recognitionRate).toBeCloseTo(100 * plan.set_metadata.summary.recognitionCoverage.matchedWindows / plan.set_metadata.summary.recognitionCoverage.expectedWindows);
    expect(detail.heroImageUrl === (plan.set_metadata.mixInfo.artist_profile_image ?? null)).toBe(true);
    const serialized = JSON.stringify(detail);
    expect(serialized.includes("privateRecognitionProvenance")).toBe(false);
    expect(serialized.includes("sourceSpans")).toBe(false);
    for (const source of media.recording_sources) expect(serialized.includes(source.url)).toBe(false);
  });
  it("projects production-shaped metadata with shared ordinary mapping and no private evidence", async () => {
    const spotify = "https://open.spotify.com/track/syntheticA";
    const youtube = "https://www.youtube.com/watch?v=abcdefghijk";
    const metadata = { spotify_url: spotify, youtube_url: youtube, discogs_url: "https://www.discogs.com/release/123",
      spotify_album_art: "https://i.scdn.co/image/test", spotify_preview_url: null, bpm: 124, key: "8A", energy: 0.7,
      danceability: 0.8, discogs_styles: ["Deep House"], discogs_genres: ["Electronic"], spotify_genres: ["House"],
      discogs_label: "Synthetic Label", discogs_label_url: "https://www.discogs.com/label/123",
      link_matching_version: 2, platform_matches: { spotify: { status: "matched", url: spotify }, youtube: { status: "matched", url: youtube } },
      privateRecognitionProvenance: { private: "DO NOT SHIP" }, source_deep_link: "DO NOT SHIP" };
    queue.push([{ id: example.id, slug: example.slug, title: example.title,
      metadata: { mixInfo: { artist_name: example.performer, artist_profile_image: "https://example.invalid/profile.jpg" },
        summary: { generated_at: "2026-11-10T10:00:00Z", recognitionCoverage: { expectedWindows: 100, validResponses: 100, matchedWindows: 69 }, privateRecognitionProvenance: "DO NOT SHIP" },
        boundaryStatus: example.boundaryStatus, boundaryNote: example.boundaryNote },
      audioId: example.audio.assetId, revision: example.audio.revision, duration: "20", contentType: "audio/wav", sourceSpans: example.spans, sources: example.audio.sources }],
      [{ setId: example.id, position: 1, artist: "Synthetic", title: "First", start: 0, end: 12, confidence: "HIGH", detectionCount: 3, clusterDensity: "0.5", clusterSpan: 4, metadata },
       { setId: example.id, position: 2, artist: "Unknown", title: "Unknown Track", start: 12, end: 20, confidence: "UNCERTAIN", metadata: {} }]);
    const collection = await loadYoonCollection(actor());
    const detail = toYoonSetDetail(collection.sets[0]!);
    expect(detail.tracks[0]).toMatchObject({ albumArt: metadata.spotify_album_art, youtubeUrl: youtube, discogsUrl: metadata.discogs_url,
      bpm: 124, key: "8A", energy: 0.7, dance: 0.8, genres: ["Deep House"], detailGenres: ["Deep House", "Electronic", "House"],
      label: metadata.discogs_label, labelUrl: metadata.discogs_label_url, detectionCount: 3, clusterDensity: 0.5, clusterSpan: 4,
      linkStatus: { spotify: "confirmed", youtube: "confirmed", discogs: "legacy" } });
    expect(detail.heroImageUrl).toBe("https://example.invalid/profile.jpg");
    expect(detail.generatedAt).toBe("2026-11-10T10:00:00Z"); expect(detail.recognitionRate).toBe(69);
    expect(detail.journeyPoints).toHaveLength(1); expect(detail.highlightedTracks).toHaveLength(1);
    expect(detail.stats).toMatchObject({ totalTracks: 2, identifiedTracks: 1 });
    expect(detail.tracks[1]).toMatchObject({ title: "Unknown Track", spotifyUrl: null, albumArt: null });
    expect(JSON.stringify(detail)).not.toContain("DO NOT SHIP");
    expect(JSON.stringify(detail)).not.toContain(example.audio.sources[0]!.url);
    expect(detail.sourceLinks).toEqual([]); expect(detail.sourceUrl).toBeNull();
  });

  beforeEach(() => {
    vi.clearAllMocks(); joins.length = 0; predicates.length = 0; queue.length = 0;
    authorize.mockResolvedValue(undefined);
    select.mockImplementation(() => { const rows = queue.shift() ?? []; const builder = { innerJoin: (_table: unknown, condition: unknown) => { joins.push(condition); return builder; }, where: (condition: unknown) => { predicates.push(condition); return builder; }, orderBy: async () => rows }; return { from: () => builder }; });
  });
  it("does not look up recordings before authorization", async () => {
    authorize.mockRejectedValue(new Error("Not found")); await expect(loadYoonCollection(actor("outsider"))).rejects.toThrow("Not found"); expect(select).not.toHaveBeenCalled();
  });
  it("ships no recordings when the protected collection contains no rows", async () => expect((await loadYoonCollection(actor())).sets).toEqual([]));
  it("does not equate identified-only cards with full recognition coverage", () => {
    expect(toYoonSetDetail(example).recognitionRate).toBeNull();
    expect(toYoonSetDetail({ ...example, recognitionCoverage: {
      expectedWindows: 479, validResponses: 479, matchedWindows: 376,
    } }).recognitionRate).toBeCloseTo(78.496868, 5);
  });
  it("loads the existing set/entry/media tables with membership on both queries", async () => {
    queue.push([{ id: example.id, slug: example.slug, title: example.title,
      metadata: { mixInfo: { artist_name: example.performer }, boundaryStatus: example.boundaryStatus, boundaryNote: example.boundaryNote },
      audioId: example.audio.assetId, revision: example.audio.revision, duration: "20", contentType: "audio/wav", sourceSpans: example.spans, sources: example.audio.sources }],
    example.tracks.map((track) => ({ setId: example.id, position: track.position, artist: track.artist, title: track.title,
      start: track.startSeconds, end: track.endSeconds, confidence: track.confidence, metadata: { spotify_url: track.spotifyUrl, private_raw_evidence: "not a client prop" } })));
    const result = await loadYoonCollection(actor()); expect(result.sets).toMatchObject(fixture.sets);
    const compile = (value: unknown) => new PgDialect().sqlToQuery(value as Parameters<PgDialect["sqlToQuery"]>[0]);
    expect(joins.map(compile).filter((q) => q.params.includes(actor().userId))).toHaveLength(2);
    const [selection, entries] = predicates.map(compile);
    expect(selection!.params).toEqual(["private", "yoon-fest", true]);
    expect(selection!.sql).toContain("app.yoon_version_readable");
    expect(entries!.sql).toContain("app.yoon_version_readable");
    expect(entries!.sql).toContain(", false)");
    expect(entries!.params).toEqual(["private", "yoon-fest", example.id]);
    expect(JSON.stringify(result)).not.toContain("private_raw_evidence");
  });
});

describe("version identity query boundaries", () => {
  beforeEach(() => {
    vi.clearAllMocks(); joins.length = 0; predicates.length = 0; queue.length = 0;
    authorize.mockResolvedValue(undefined);
    select.mockImplementation(() => {
      const rows = queue.shift() ?? [];
      const builder = { innerJoin: (_table: unknown, condition: unknown) => { joins.push(condition); return builder; },
        where: (condition: unknown) => { predicates.push(condition); return builder; }, orderBy: async () => rows };
      return { from: () => builder };
    });
  });
  const compile = (value: unknown) => new PgDialect().sqlToQuery(value as Parameters<PgDialect["sqlToQuery"]>[0]);
  const row = (id = example.id, slug = example.slug, audioId = example.audio.assetId) => ({
    id, slug, title: example.title,
    metadata: { mixInfo: { artist_name: example.performer }, boundaryStatus: example.boundaryStatus, boundaryNote: example.boundaryNote },
    audioId, revision: example.audio.revision, duration: "20", contentType: "audio/wav", sourceSpans: example.spans, sources: example.audio.sources,
  });
  it.each(["slug", "asset"] as const)("resolves released history by exact %s without a selected-only collection lookup", async (kind) => {
    queue.push([row()], []);
    const result = kind === "slug" ? await getYoonSet(actor(), example.slug) : await getYoonSetByAsset(actor(), example.audio.assetId);
    expect(result?.id).toBe(example.id);
    const [lookup, entries] = predicates.map(compile);
    expect(lookup!.sql).toContain("app.yoon_version_readable");
    expect(lookup!.params).toEqual(["private", "yoon-fest", false, kind === "slug" ? example.slug : example.audio.assetId]);
    expect(entries!.params).toEqual(["private", "yoon-fest", example.id]);
    expect(joins.map(compile).filter((q) => q.params.includes(actor().userId))).toHaveLength(2);
    expect(JSON.stringify(toYoonSetDetail(result!))).not.toContain(example.audio.sources[0]!.url);
  });
  it("pins selected results and media to the same resolved version even across a pointer switch", async () => {
    const v2Id = "00000000-0000-4000-8000-000000000002";
    const v2Asset = "00000000-0000-4000-8000-000000000003";
    queue.push([row(v2Id, "synthetic-v2", v2Asset)], [{ setId: v2Id, position: 1, artist: "V2", title: "Fresh results", start: 0, end: 20, confidence: "HIGH", metadata: {} }]);
    const selected = (await loadYoonCollection(actor())).sets;
    expect(selected).toHaveLength(1);
    expect(selected[0]).toMatchObject({ id: v2Id, audio: { assetId: v2Asset }, tracks: [{ artist: "V2", title: "Fresh results" }] });
    const [lookup, entries] = predicates.map(compile);
    expect(lookup!.params).toContain(true);
    expect(entries!.params).toContain(v2Id);
    expect(entries!.params).not.toContain(example.id);
    expect(entries!.sql).toContain(", false)");
  });
  it.each(["staged", "unknown", "malformed"])("returns no detail, media or entries when the registry excludes %s", async (identity) => {
    expect(await getYoonSet(actor(), identity)).toBeNull();
    expect(await getYoonSetByAsset(actor(), "00000000-0000-4000-8000-000000000099")).toBeNull();
    expect(select).toHaveBeenCalledTimes(2); // No entry reads for excluded rows.
    for (const q of predicates.map(compile)) expect(q.sql).toContain("app.yoon_version_readable");
  });
  it("denies malformed asset identifiers without a UUID cast or database lookup", async () => {
    expect(await getYoonSetByAsset(actor(), "not-a-uuid")).toBeNull();
    expect(select).not.toHaveBeenCalled();
  });
  it.each([actor("outsider"), actor("outsider", { isAdmin: true })])("does not resolve historical identity for an unauthorized actor", async (viewer) => {
    authorize.mockRejectedValue(new Error("Not found"));
    await expect(getYoonSet(viewer, example.slug)).rejects.toThrow("Not found");
    await expect(getYoonSetByAsset(viewer, example.audio.assetId)).rejects.toThrow("Not found");
    expect(select).not.toHaveBeenCalled();
  });
});
