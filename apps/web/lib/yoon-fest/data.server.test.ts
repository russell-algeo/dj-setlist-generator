import { PgDialect } from "drizzle-orm/pg-core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { actor, fixture } from "./fixtures.test-support";
const { select, authorize, joins, predicates, queue } = vi.hoisted(() => ({ select: vi.fn(), authorize: vi.fn(), joins: [] as unknown[], predicates: [] as unknown[], queue: [] as unknown[][] }));
vi.mock("@/lib/db/client", () => ({ getDb: () => ({ select }) }));
vi.mock("./access.server", () => ({ assertYoonAccess: authorize }));
vi.mock("next/cache", () => ({ unstable_noStore: vi.fn() }));
import { loadYoonCollection } from "./data.server";
const example = fixture.sets[0]!;
describe("private collection reader", () => {
  beforeEach(() => {
    vi.clearAllMocks(); joins.length = 0; predicates.length = 0; queue.length = 0;
    authorize.mockResolvedValue(undefined);
    select.mockImplementation(() => { const rows = queue.shift() ?? []; const builder = { innerJoin: (_table: unknown, condition: unknown) => { joins.push(condition); return builder; }, where: (condition: unknown) => { predicates.push(condition); return builder; }, orderBy: async () => rows }; return { from: () => builder }; });
  });
  it("does not look up recordings before authorization", async () => {
    authorize.mockRejectedValue(new Error("Not found")); await expect(loadYoonCollection(actor("outsider"))).rejects.toThrow("Not found"); expect(select).not.toHaveBeenCalled();
  });
  it("ships no recordings when the protected collection contains no rows", async () => expect((await loadYoonCollection(actor())).sets).toEqual([]));
  it("loads the existing set/entry/media tables with membership on both queries", async () => {
    queue.push([{ id: example.id, slug: example.slug, title: example.title,
      metadata: { mixInfo: { artist_name: example.performer }, boundaryStatus: example.boundaryStatus, boundaryNote: example.boundaryNote },
      audioId: example.audio.assetId, revision: example.audio.revision, duration: "20", contentType: "audio/wav", sourceSpans: example.spans, sources: example.audio.sources }],
    example.tracks.map((track) => ({ setId: example.id, position: track.position, artist: track.artist, title: track.title,
      start: track.startSeconds, end: track.endSeconds, confidence: track.confidence, metadata: { spotify_url: track.spotifyUrl, private_raw_evidence: "not a client prop" } })));
    const result = await loadYoonCollection(actor()); expect(result.sets).toEqual(fixture.sets);
    const compile = (value: unknown) => new PgDialect().sqlToQuery(value as Parameters<PgDialect["sqlToQuery"]>[0]);
    expect(joins.map(compile).filter((q) => q.params.includes(actor().userId))).toHaveLength(2);
    for (const query of predicates.map(compile)) expect(query.params).toEqual(["private", "yoon-fest"]);
    expect(JSON.stringify(result)).not.toContain("private_raw_evidence");
  });
});
