import { beforeEach, describe, expect, it, vi } from "vitest";
import { actor, fixture } from "@/lib/yoon-fest/fixtures.test-support";
const mocks = vi.hoisted(() => ({ actor: vi.fn(), sets: vi.fn(), set: vi.fn(), detail: vi.fn() }));
vi.mock("@/lib/yoon-fest/access.server", () => ({ getYoonActor: mocks.actor }));
vi.mock("@/lib/yoon-fest/data.server", () => ({ getYoonSets: mocks.sets, getYoonSet: mocks.set, toYoonSetDetail: mocks.detail }));
vi.mock("next/navigation", () => ({ notFound: () => { throw new Error("NOT_FOUND"); } }));
vi.mock("@/components/yoon-fest/yoon-access-boundary", () => ({ YoonAccessBoundary: () => null }));
vi.mock("@/components/yoon-fest/yoon-collection", () => ({ YoonCollection: () => null }));
vi.mock("@/components/archive/archive-set-explorer", () => ({ ArchiveSetExplorer: () => null }));
describe("private page and RSC entry gates", () => {
  beforeEach(() => { vi.resetAllMocks(); mocks.sets.mockReturnValue(fixture.sets); mocks.set.mockReturnValue(fixture.sets[0]); mocks.detail.mockReturnValue({}); });
  it.each(["./page", "./sets/[slug]/page"])("denies before data projection in %s", async (path) => { mocks.actor.mockResolvedValue(null); const page = await import(path); await expect(page.default({ params: Promise.resolve({ slug: "synthetic-set" }) })).rejects.toThrow("NOT_FOUND"); expect(mocks.sets).not.toHaveBeenCalled(); expect(mocks.set).not.toHaveBeenCalled(); expect(mocks.detail).not.toHaveBeenCalled(); expect(JSON.stringify(page.metadata)).not.toContain("Synthetic"); });
  it("projects only after an authorized session", async () => { mocks.actor.mockResolvedValue(actor()); const page = await import("./sets/[slug]/page"); await page.default({ params: Promise.resolve({ slug: "synthetic-set" }) }); expect(mocks.set).toHaveBeenCalledWith(actor(), "synthetic-set"); expect(mocks.detail).toHaveBeenCalledOnce(); });
});
