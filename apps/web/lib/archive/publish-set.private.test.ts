import { getTableName } from "drizzle-orm";
import { PgDialect } from "drizzle-orm/pg-core";
import { describe, expect, it, vi } from "vitest";
import { upsertArchiveSet } from "./publish-set";
const id = "10000000-0000-4000-8000-000000000001";
const collectionId = "20000000-0000-4000-8000-000000000001";
const target = { id, slug: "reviewed-target", visibility: "private", collectionId, metadata: { boundaryStatus: "reviewed", boundaryNote: "Synthetic review" } };
const payload = { mix_info: { title: "Private title", artist_name: "Private performer", url: "https://private.invalid/source", duration: 10 }, metadata: {}, tracks: [{ artist: "Synthetic artist", title: "Synthetic track", start_time: 0, end_time: 10, confidence: "HIGH", spotify_url: "https://open.spotify.com/track/synthetic" }] };
function mockDb(row: unknown = target) {
  const where = vi.fn().mockReturnValue({ returning: vi.fn().mockResolvedValue([{ id }]) });
  const set = vi.fn().mockReturnValue({ where });
  const values = vi.fn().mockResolvedValue(undefined);
  return { select: vi.fn().mockReturnValue({ from: vi.fn().mockReturnValue({ where: vi.fn().mockReturnValue({ limit: vi.fn().mockResolvedValue(row ? [row] : []) }) }) }),
    update: vi.fn().mockReturnValue({ set }), insert: vi.fn().mockReturnValue({ values }),
    delete: vi.fn().mockReturnValue({ where: vi.fn().mockResolvedValue(undefined) }), set, where, values };
}
describe("private publisher", () => {
  it("updates only its precreated protected target and entries without shared catalog writes", async () => {
    const db = mockDb();
    const result = await upsertArchiveSet({ db: db as unknown as NonNullable<Parameters<typeof upsertArchiveSet>[0]["db"]>, payload, access: { visibility: "private", setId: id, collectionId }, provenance: { source: "worker" } });
    expect(result).toEqual({ setId: id, slug: target.slug, affectedArtistSlugs: [] });
    expect(db.insert.mock.calls.map(([table]) => getTableName(table))).toEqual(["set_entries"]);
    expect(db.update.mock.calls.map(([table]) => getTableName(table))).toEqual(["sets"]);
    expect(db.values).toHaveBeenCalledWith(expect.objectContaining({ trackId: null, setId: id, metadata: payload.tracks[0] }));
    expect(db.set.mock.calls[0]![0]).not.toHaveProperty("collectionId");
    expect(db.set.mock.calls[0]![0]).not.toHaveProperty("sourceUrl");
    expect(db.set.mock.calls[0]![0].metadata).toMatchObject(target.metadata);
    const query = new PgDialect().sqlToQuery(db.where.mock.calls[0]![0]);
    expect(query.params).toEqual([id, "private", collectionId]);
  });
  it.each([null, { ...target, collectionId: id }, { ...target, visibility: "public" }])("rejects target %j before any write", async (row) => {
    const db = mockDb(row);
    await expect(upsertArchiveSet({ db: db as unknown as NonNullable<Parameters<typeof upsertArchiveSet>[0]["db"]>, payload, access: { visibility: "private", setId: id, collectionId }, provenance: { source: "worker" } })).rejects.toThrow();
    expect(db.insert).not.toHaveBeenCalled(); expect(db.update).not.toHaveBeenCalled(); expect(db.delete).not.toHaveBeenCalled();
  });
});
