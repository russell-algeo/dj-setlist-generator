import { beforeEach, describe, expect, it, vi } from "vitest";
import { actor, fixture } from "@/lib/yoon-fest/fixtures.test-support";

const mocks = vi.hoisted(() => ({
  session: vi.fn(), access: vi.fn(), sets: vi.fn(), set: vi.fn(), detail: vi.fn(), redirect: vi.fn(),
}));
vi.mock("@/lib/auth/session", () => ({ getSessionActor: mocks.session }));
vi.mock("@/lib/yoon-fest/access.server", () => ({ hasYoonAccess: mocks.access }));
vi.mock("@/lib/yoon-fest/data.server", () => ({ getYoonSets: mocks.sets, getYoonSet: mocks.set, toYoonSetDetail: mocks.detail }));
vi.mock("next/navigation", () => ({
  notFound: () => { throw new Error("NOT_FOUND"); }, redirect: mocks.redirect,
}));
vi.mock("@/components/yoon-fest/yoon-access-boundary", () => ({ YoonAccessBoundary: () => null }));
vi.mock("@/components/yoon-fest/yoon-collection", () => ({ YoonCollection: () => null }));
vi.mock("@/components/archive/archive-set-explorer", () => ({ ArchiveSetExplorer: () => null }));

import CollectionPage, * as collectionModule from "./page";
import SetPage, * as setModule from "./sets/[slug]/page";

const pages = [
  { name: "collection", run: () => CollectionPage(), callback: "/collections/yoon-fest", module: collectionModule },
  { name: "set", run: () => SetPage({ params: Promise.resolve({ slug: "synthetic-set" }) }), callback: "/collections/yoon-fest/sets/synthetic-set", module: setModule },
];
const expectNoProjection = () => {
  expect(mocks.sets).not.toHaveBeenCalled();
  expect(mocks.set).not.toHaveBeenCalled();
  expect(mocks.detail).not.toHaveBeenCalled();
};

describe("private page and RSC entry gates", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.redirect.mockImplementation(() => { throw new Error("REDIRECT"); });
    mocks.session.mockResolvedValue(actor());
    mocks.access.mockResolvedValue(true);
    mocks.sets.mockReturnValue(fixture.sets);
    mocks.set.mockReturnValue(fixture.sets[0]);
    mocks.detail.mockReturnValue({});
  });

  it.each(pages)("redirects anonymous $name navigation before private reads", async ({ run, callback }) => {
    mocks.session.mockResolvedValue(null);
    await expect(run()).rejects.toThrow("REDIRECT");
    expect(mocks.redirect).toHaveBeenCalledExactlyOnceWith(`/api/auth/signin?callbackUrl=${encodeURIComponent(callback)}`);
    expect(mocks.access).not.toHaveBeenCalled();
    expectNoProjection();
  });

  it.each(pages)("keeps signed-in nonmember $name navigation private", async ({ run }) => {
    mocks.session.mockResolvedValue(actor("outsider"));
    mocks.access.mockResolvedValue(false);
    await expect(run()).rejects.toThrow("NOT_FOUND");
    expect(mocks.access).toHaveBeenCalledExactlyOnceWith(actor("outsider"));
    expect(mocks.redirect).not.toHaveBeenCalled();
    expectNoProjection();
  });

  it.each(pages)("does not grant global admins access to $name", async ({ run }) => {
    mocks.session.mockResolvedValue(actor("outsider", { isAdmin: true, isAllowlisted: true }));
    mocks.access.mockResolvedValue(false);
    await expect(run()).rejects.toThrow("NOT_FOUND");
    expect(mocks.redirect).not.toHaveBeenCalled();
    expectNoProjection();
  });

  it.each(pages)("renders $name only after membership succeeds", async ({ run }) => {
    const element = await run();
    expect(element.props.viewerId).toBe(actor().userId);
    expect(mocks.access).toHaveBeenCalledExactlyOnceWith(actor());
    expect(mocks.detail).toHaveBeenCalledOnce();
    expect(mocks.redirect).not.toHaveBeenCalled();
    const dataCallOrder = [...mocks.set.mock.invocationCallOrder, ...mocks.sets.mock.invocationCallOrder][0];
    expect(mocks.access.mock.invocationCallOrder[0]).toBeLessThan(dataCallOrder);
  });

  it("keeps unknown slugs a 404 for authorized members", async () => {
    mocks.set.mockResolvedValue(null);
    await expect(SetPage({ params: Promise.resolve({ slug: "missing-set" }) })).rejects.toThrow("NOT_FOUND");
    expect(mocks.set).toHaveBeenCalledWith(actor(), "missing-set");
    expect(mocks.detail).not.toHaveBeenCalled();
    expect(mocks.redirect).not.toHaveBeenCalled();
  });

  it.each([
    "space and café", "//outside.example/path", "https://outside.example/?q=1#fragment",
    "../outside", "%2F%2Foutside.example", "name?callbackUrl=https://outside.example/", "line\nbreak",
  ])("encodes slug %j as one fixed internal callback segment", async (slug) => {
    mocks.session.mockResolvedValue(null);
    await expect(SetPage({ params: Promise.resolve({ slug }) })).rejects.toThrow("REDIRECT");
    const login = new URL(mocks.redirect.mock.calls[0][0], "https://preview.example.invalid");
    expect(login.origin).toBe("https://preview.example.invalid");
    expect(login.pathname).toBe("/api/auth/signin");
    expect([...login.searchParams.keys()]).toEqual(["callbackUrl"]);
    const callback = login.searchParams.get("callbackUrl")!;
    expect(callback).toBe(`/collections/yoon-fest/sets/${encodeURIComponent(slug)}`);
    const destination = new URL(callback, login.origin);
    expect(destination.origin).toBe(login.origin);
    expect(destination.pathname).toBe(callback);
    expect(destination.search).toBe("");
    expect(destination.hash).toBe("");
    expect(mocks.access).not.toHaveBeenCalled();
    expectNoProjection();
  });

  it.each(["", ".", ".."])("rejects invalid dot/empty slug %j without an unsafe return path", async (slug) => {
    mocks.session.mockResolvedValue(null);
    await expect(SetPage({ params: Promise.resolve({ slug }) })).rejects.toThrow("NOT_FOUND");
    expect(mocks.redirect).not.toHaveBeenCalled();
    expectNoProjection();
  });

  it.each(pages)("keeps $name metadata generic and uncached", ({ module }) => {
    expect(module.metadata.title).toMatch(/^Private (collection|recording)$/);
    expect(module.metadata.robots).toEqual({ index: false, follow: false, noarchive: true });
    expect(module.metadata.referrer).toBe("no-referrer");
    expect(JSON.stringify(module.metadata)).not.toMatch(/Synthetic|Dropbox|Jackson/);
    expect(module.dynamic).toBe("force-dynamic");
    expect(module.revalidate).toBe(0);
  });
});
