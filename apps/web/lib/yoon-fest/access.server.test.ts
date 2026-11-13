import { PgDialect } from "drizzle-orm/pg-core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { actor } from "./fixtures.test-support";
const { select, where, limit, join } = vi.hoisted(() => ({ select: vi.fn(), where: vi.fn(), limit: vi.fn(), join: vi.fn() }));
vi.mock("@/lib/db/client", () => ({ getDb: () => ({ select }) }));
vi.mock("next/cache", () => ({ unstable_noStore: vi.fn() }));
import { hasYoonAccess } from "./access.server";
describe("same-Neon collection membership", () => {
  beforeEach(() => { vi.clearAllMocks(); limit.mockResolvedValue([]); where.mockReturnValue({ limit }); join.mockReturnValue({ where }); select.mockReturnValue({ from: () => ({ innerJoin: join }) }); });
  it.each([null, actor("synthetic-user", { authType: "api_token" })])("denies absent session before querying", async (viewer) => { expect(await hasYoonAccess(viewer)).toBe(false); expect(select).not.toHaveBeenCalled(); });
  it("does not let global admin substitute for membership", async () => {
    expect(await hasYoonAccess(actor("outsider", { isAdmin: true }))).toBe(false);
    const memberQuery = new PgDialect().sqlToQuery(join.mock.calls[0]![1]);
    expect(memberQuery.params).toEqual(["outsider"]); expect(memberQuery.sql).toContain('"user_id"');
    expect(new PgDialect().sqlToQuery(where.mock.calls[0]![0]).params).toEqual(["yoon-fest"]);
  });
  it("requires the pinned audience on every access decision", async () => {
    await hasYoonAccess(actor());
    const query = new PgDialect().sqlToQuery(where.mock.calls[0]![0]);
    expect(query.sql).toContain('app.yoon_audience_intact("app"."archive_collections"."id")');
  });
  it("reflects membership revocation on the next request rather than caching an allow", async () => {
    limit.mockResolvedValueOnce([{ id: "synthetic-collection" }]).mockResolvedValueOnce([]);
    expect(await hasYoonAccess(actor())).toBe(true); expect(await hasYoonAccess(actor())).toBe(false);
    expect(select).toHaveBeenCalledTimes(2);
  });
});
