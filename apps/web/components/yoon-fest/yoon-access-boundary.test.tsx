// @vitest-environment jsdom
import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { YoonAccessBoundary } from "./yoon-access-boundary";

const { useSession } = vi.hoisted(() => ({ useSession: vi.fn() }));
vi.mock("next-auth/react", () => ({ useSession }));

describe("page-load-only Yoon membership checks", () => {
  let root: Root;
  let container: HTMLDivElement;
  const cleanup = vi.fn();
  const fetchMock = vi.fn().mockResolvedValue({ ok: false });
  const authenticated = (id: string) => ({ status: "authenticated", data: { user: { id } } });
  function PrivateContent() {
    useEffect(() => cleanup, []);
    return <div data-testid="private-content">Already authorized recording</div>;
  }
  const render = async () => {
    await act(async () => root.render(<YoonAccessBoundary viewerId="member"><PrivateContent /></YoonAccessBoundary>));
  };

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal("fetch", fetchMock);
    useSession.mockReturnValue(authenticated("member"));
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("uses the server page authorization without a duplicate client access request", async () => {
    await render();
    expect(container.querySelector('[data-testid="private-content"]')).not.toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("keeps the loaded page through time, focus and visibility changes without membership requests", async () => {
    await render();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10 * 60_000);
      window.dispatchEvent(new Event("focus"));
      vi.spyOn(document, "hidden", "get").mockReturnValue(true);
      document.dispatchEvent(new Event("visibilitychange"));
      vi.spyOn(document, "hidden", "get").mockReturnValue(false);
      document.dispatchEvent(new Event("visibilitychange"));
      window.dispatchEvent(new Event("focus"));
    });
    // Even a failing access endpoint cannot tear down an already-authorized page:
    // it is deliberately not queried. New server requests still authorize anew.
    expect(fetchMock).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
    expect(container.querySelector('[data-testid="private-content"]')).not.toBeNull();
    expect(cleanup).not.toHaveBeenCalled();
  });

  it.each([
    { name: "sign-out", session: { status: "unauthenticated", data: null } },
    { name: "account change", session: authenticated("another-member") },
    { name: "missing authenticated identity", session: { status: "authenticated", data: { user: {} } } },
  ])("still tears down private children on $name", async ({ session }) => {
    await render();
    useSession.mockReturnValue(session);
    await render();
    expect(container.querySelector('[data-testid="private-content"]')).toBeNull();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("Private access is no longer available");
    expect(cleanup).toHaveBeenCalledOnce();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not discard server-authorized content while the session is loading", async () => {
    useSession.mockReturnValue({ status: "loading", data: null });
    await render();
    expect(container.querySelector('[data-testid="private-content"]')).not.toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
