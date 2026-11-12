// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ArchiveSetDetail } from "@/lib/archive/types";
import { ArchiveSetExplorer } from "./archive-set-explorer";

vi.mock("./archive-header", () => ({ ArchiveHeader: () => null }));
vi.mock("./archive-delete-control", () => ({ ArchiveDeleteControl: () => null, SubmittedByYouBadge: () => null }));
vi.mock("./spotify-export-button", () => ({ SpotifyExportButton: () => null }));

const detail: ArchiveSetDetail = {
  id: "synthetic-youtube", slug: "synthetic-youtube", title: "Synthetic player", artistName: null,
  artists: [], heroImageUrl: null, thumbnailUrl: null, sourcePlatform: "youtube", sourceUrl: "https://www.youtube.com/watch?v=abcdefghijk",
  sourceLinks: [], embedUrl: null, duration: 600, durationFmt: "10:00", recognitionRate: null,
  generatedAt: null, stats: { totalTracks: 0, identifiedTracks: 0, highOrMediumTracks: 0, distinctArtists: 0 },
  highlightedTracks: [], timeline: [], tracks: [], journeyPoints: [],
};

describe("embedded set scrubbing intent", () => {
  let root: Root;
  let host: HTMLDivElement;
  let script: HTMLScriptElement;
  let state: number;
  let events: { onReady: () => void; onStateChange: (event: { data: number }) => void };
  let player: { playVideo: ReturnType<typeof vi.fn<() => void>>; pauseVideo: ReturnType<typeof vi.fn<() => void>>;
    seekTo: ReturnType<typeof vi.fn<(seconds: number, ahead: boolean) => void>>; getCurrentTime: () => number; getPlayerState: () => number; destroy: () => void };
  const slider = () => host.querySelector<HTMLInputElement>("#dockProgress")!;
  const pointer = async (type: string) => act(async () => {
    const event = new MouseEvent(type, { button: 0, bubbles: true });
    Object.defineProperties(event, { pointerId: { value: 1 }, isPrimary: { value: true } });
    slider().dispatchEvent(event);
  });
  const change = async (seconds: number) => act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(slider(), String(seconds));
    slider().dispatchEvent(new Event("input", { bubbles: true }));
  });
  const toggle = async () => act(async () => host.querySelector<HTMLButtonElement>(".dock-play-btn")!.click());
  const transition = async (next: number) => act(async () => { state = next; events.onStateChange({ data: next }); });

  beforeEach(async () => {
    vi.useFakeTimers(); localStorage.clear(); vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1)); vi.stubGlobal("cancelAnimationFrame", vi.fn());
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ progress: null }), { status: 200 })));
    state = 2;
    player = { playVideo: vi.fn(), pauseVideo: vi.fn(), seekTo: vi.fn(), getCurrentTime: () => 10, getPlayerState: () => state, destroy: vi.fn() };
    Object.assign(window, { YT: { PlayerState: { PLAYING: 1, PAUSED: 2, BUFFERING: 3, ENDED: 0, CUED: 5 },
      Player: function (_host: HTMLElement, config: { events: typeof events }) { events = config.events; return player; } } });
    script = document.createElement("script"); script.src = "https://www.youtube.com/iframe_api"; script.dataset.loaded = "1"; document.head.append(script);
    host = document.createElement("div"); document.body.append(host); root = createRoot(host);
    await act(async () => root.render(<ArchiveSetExplorer detail={detail} initialListened={null} initialQuery=""
      management={{ canDeleteSet: false, deleteImpact: null, setWillBeRemoved: false, submittedByViewer: false }} />));
    await act(async () => events.onReady());
    player.playVideo.mockClear(); player.pauseVideo.mockClear(); player.seekTo.mockClear();
  });
  afterEach(async () => { await act(async () => root.unmount()); host.remove(); script.remove(); Reflect.deleteProperty(window, "YT"); vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("does not turn a paused embed on when a drag commits", async () => {
    await pointer("pointerdown"); await change(30); await change(40);
    expect(player.seekTo).not.toHaveBeenCalled();
    expect(host.querySelector("#dockCurrentTime")!.textContent).toBe("0:40");
    expect(host.querySelector(".dock-time")!.lastElementChild!.textContent).toBe("10:00");
    expect(host.textContent).not.toContain("Seek to");
    await pointer("pointerup"); expect(player.seekTo.mock.calls).toEqual([[40, true]]);
    expect(player.pauseVideo).toHaveBeenCalledOnce(); expect(player.playVideo).not.toHaveBeenCalled();
  });

  it("preserves playing intent through a buffering poll", async () => {
    await toggle(); await transition(1); await pointer("pointerdown"); await change(40);
    await transition(3); await act(async () => vi.advanceTimersByTime(400));
    player.playVideo.mockClear(); player.pauseVideo.mockClear();
    await pointer("pointerup"); expect(player.seekTo.mock.calls).toEqual([[40, true]]);
    expect(player.playVideo).toHaveBeenCalledOnce(); expect(player.pauseVideo).not.toHaveBeenCalled();
  });

  it("keeps an unacknowledged Pause across a paused scrub and a second Pause", async () => {
    await toggle(); await transition(1); await toggle(); // Pause has not been acknowledged.
    await pointer("pointerdown"); await change(40); await pointer("pointerup");
    expect(player.seekTo.mock.calls).toEqual([[40, true]]);
    await toggle(); // Repeated Pause while the fake provider still reports PLAYING.
    await transition(1); // Queued PLAY must not revive the intent after either action.
    player.playVideo.mockClear(); player.pauseVideo.mockClear(); player.seekTo.mockClear();
    await pointer("pointerdown"); await change(60); await pointer("pointerup");
    expect(player.seekTo.mock.calls).toEqual([[60, true]]);
    expect(player.pauseVideo).toHaveBeenCalledOnce(); expect(player.playVideo).not.toHaveBeenCalled();
  });

  it("a later explicit Pause wins even before the provider acknowledges it", async () => {
    await toggle(); await transition(1); await pointer("pointerdown"); await change(40);
    await toggle(); // Pause command, while fake provider still returns PLAYING.
    await transition(1); // A queued old playing acknowledgement must not revive intent.
    await transition(3); await act(async () => vi.advanceTimersByTime(400));
    player.playVideo.mockClear(); player.pauseVideo.mockClear();
    await pointer("pointerup"); expect(player.seekTo.mock.calls).toEqual([[40, true]]);
    expect(player.pauseVideo).toHaveBeenCalledOnce(); expect(player.playVideo).not.toHaveBeenCalled();
  });
});
