import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("Spotify official iFrame API loader", () => {
  const scripts: { remove: ReturnType<typeof vi.fn>; onerror?: () => void; src?: string }[] = [];
  const target: Record<string, unknown> = {};
  beforeEach(() => {
    vi.resetModules(); vi.useFakeTimers(); scripts.length = 0;
    for (const key of Object.keys(target)) delete target[key];
    Object.assign(target, { setTimeout, clearTimeout });
    vi.stubGlobal("window", target);
    vi.stubGlobal("document", {
      createElement: vi.fn(() => ({ remove: vi.fn() })),
      head: { appendChild: vi.fn((script) => scripts.push(script)) },
    });
  });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
  it("shares one lazy load across previews and retains the loaded API", async () => {
    const { loadSpotifyIframeApi } = await import("./spotify-iframe");
    const a = loadSpotifyIframeApi(), b = loadSpotifyIframeApi();
    expect(a).toBe(b); expect(scripts).toHaveLength(1);
    expect(scripts[0].src).toBe("https://open.spotify.com/embed/iframe-api/v1");
    const api = { createController: vi.fn() };
    (target.onSpotifyIframeApiReady as (value: unknown) => void)(api);
    expect(await a).toBe(api); expect(await loadSpotifyIframeApi()).toBe(api);
    vi.advanceTimersByTime(20000);
    expect(scripts[0].remove).not.toHaveBeenCalled();
  });
  it("cleans a failed script and permits deliberate retry", async () => {
    const prior = vi.fn(); target.onSpotifyIframeApiReady = prior;
    const { loadSpotifyIframeApi } = await import("./spotify-iframe");
    const failed = loadSpotifyIframeApi(); const rejected = expect(failed).rejects.toThrow("could not load");
    scripts[0].onerror?.(); await rejected;
    expect(scripts[0].remove).toHaveBeenCalledOnce();
    expect(target.onSpotifyIframeApiReady).toBe(prior);
    const retry = loadSpotifyIframeApi();
    expect(scripts).toHaveLength(2);
    const api = { createController: vi.fn() };
    (target.onSpotifyIframeApiReady as (value: unknown) => void)(api);
    expect(await retry).toBe(api); expect(prior).toHaveBeenCalledWith(api);
  });
  it("times out instead of leaving an uncoordinated iframe", async () => {
    const { loadSpotifyIframeApi } = await import("./spotify-iframe");
    const pending = loadSpotifyIframeApi(); const rejected = expect(pending).rejects.toThrow("could not load");
    vi.advanceTimersByTime(15000); await rejected;
    expect(scripts[0].remove).toHaveBeenCalledOnce();
  });
});
