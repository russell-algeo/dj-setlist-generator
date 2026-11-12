// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ArchiveSetDetail } from "@/lib/archive/types";
import { ArchiveSetExplorer } from "./archive-set-explorer";

// Retain the real coordinator to assert focus ownership, without replacing
// its behavior or the player's provider callbacks.
const focusState = vi.hoisted(() => ({
  current: null as ReturnType<typeof import("@/lib/archive/audio-focus").createSetAudioFocus> | null,
}));
vi.mock("@/lib/archive/audio-focus", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/archive/audio-focus")>();
  return { ...actual, createSetAudioFocus: (port: Parameters<typeof actual.createSetAudioFocus>[0]) => {
    const focus = actual.createSetAudioFocus(port); focusState.current = focus; return focus;
  } };
});

vi.mock("./archive-header", () => ({ ArchiveHeader: () => null }));
vi.mock("./archive-delete-control", () => ({ ArchiveDeleteControl: () => null, SubmittedByYouBadge: () => null }));
vi.mock("./spotify-export-button", () => ({ SpotifyExportButton: () => null }));

const detail: ArchiveSetDetail = {
  id: "synthetic-stale-source", slug: "synthetic-stale-source", title: "Synthetic stale source", artistName: null,
  artists: [], heroImageUrl: null, thumbnailUrl: null, sourcePlatform: "soundcloud", sourceUrl: "https://soundcloud.com/synthetic/first",
  sourceLinks: [{ id: "alternate", platform: "youtube", url: "https://www.youtube.com/watch?v=abcdefghijk", title: null, durationSeconds: 600, isPrimary: false, matchConfidence: null }],
  embedUrl: null, duration: 600, durationFmt: "10:00", recognitionRate: null, generatedAt: null,
  stats: { totalTracks: 0, identifiedTracks: 0, highOrMediumTracks: 0, distinctArtists: 0 },
  highlightedTracks: [], timeline: [], tracks: [], journeyPoints: [],
};
type EventData = { currentPosition?: number; loadProgress?: number } | undefined;
type Widget = {
  bind: (name: string, callback: (data?: EventData) => void) => void;
  getPosition: (callback: (milliseconds: number) => void) => void;
  isPaused: (callback: (paused: boolean) => void) => void;
  play: ReturnType<typeof vi.fn>; pause: ReturnType<typeof vi.fn>; seekTo: ReturnType<typeof vi.fn>;
  setVolume?: ReturnType<typeof vi.fn>;
};
type Record = {
  frame: HTMLIFrameElement; widget: Widget; events: { [name: string]: (data?: EventData) => void };
  positions: Array<(milliseconds: number) => void>; pausedReads: Array<(paused: boolean) => void>;
  defer: boolean; paused: boolean; position: number;
};

describe("retired SoundCloud callback generations", () => {
  let root: Root | null;
  let host: HTMLDivElement;
  let scripts: HTMLScriptElement[];
  let records: Record[];
  let latest: Record;
  let reuseWidget: boolean;
  let warmup: boolean;
  let ytState: number;
  let ytEvents: { onReady: () => void; onStateChange: (event: { data: number }) => void };
  let yt: { playVideo: ReturnType<typeof vi.fn>; pauseVideo: ReturnType<typeof vi.fn>; seekTo: ReturnType<typeof vi.fn>; destroy: ReturnType<typeof vi.fn>; getCurrentTime: () => number; getPlayerState: () => number };
  const time = () => host.querySelector("#dockCurrentTime")!.textContent;
  const playing = () => host.querySelector(".dock-play-btn")!.classList.contains("is-playing");
  const storage = () => localStorage.getItem(`set-signal:playback:v1:${detail.id}`);
  const render = async (value = detail) => act(async () => root!.render(<ArchiveSetExplorer detail={value} initialListened={null} initialQuery=""
    management={{ canDeleteSet: false, deleteImpact: null, setWillBeRemoved: false, submittedByViewer: false }} />));
  const emit = async (record: Record, name: string, data?: EventData) => act(async () => record.events[name](data));
  const seek = async (seconds: number) => act(async () => {
    const slider = host.querySelector<HTMLInputElement>("#dockProgress")!;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(slider, String(seconds));
    slider.dispatchEvent(new Event("input", { bubbles: true }));
  });
  const toYouTube = async (isPlaying = true) => {
    await act(async () => [...host.querySelectorAll<HTMLButtonElement>(".source-switcher-option")].find(button => button.textContent === "Youtube")!.click());
    ytState = isPlaying ? 1 : 2;
    await act(async () => { ytEvents.onReady(); ytEvents.onStateChange({ data: ytState }); });
    await act(async () => vi.advanceTimersByTime(2000)); // Beyond the existing seek lock.
    expect(time()).toBe("0:42"); expect(playing()).toBe(isPlaying);
    yt.playVideo.mockClear(); yt.pauseVideo.mockClear(); yt.seekTo.mockClear();
  };

  beforeEach(async () => {
    vi.useFakeTimers(); localStorage.clear(); vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1)); vi.stubGlobal("cancelAnimationFrame", vi.fn());
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ progress: null }), { status: 200 })));
    records = []; reuseWidget = false; warmup = false; ytState = 2;
    const WidgetFactory = Object.assign((frame: HTMLIFrameElement) => {
      const record = { frame, events: {}, positions: [], pausedReads: [], defer: false, paused: false, position: 12000 } as unknown as Record;
      latest = record;
      const active = () => reuseWidget ? latest : record;
      record.widget = reuseWidget && records[0] ? records[0].widget : {
        bind: (name, callback) => { active().events[name] = callback; },
        getPosition: (callback) => { const r = active(); if (r.defer) r.positions.push(callback); else callback(r.position); },
        isPaused: (callback) => { const r = active(); if (r.defer) r.pausedReads.push(callback); else callback(r.paused); },
        play: vi.fn(), pause: vi.fn(), seekTo: vi.fn(), ...(warmup ? { setVolume: vi.fn() } : {}),
      };
      records.push(record); return record.widget;
    }, { Events: Object.fromEntries(["READY", "LOAD_PROGRESS", "PLAY", "PAUSE", "FINISH", "SEEK", "PLAY_PROGRESS"].map(name => [name, name])) });
    yt = { playVideo: vi.fn(), pauseVideo: vi.fn(), seekTo: vi.fn(), destroy: vi.fn(), getCurrentTime: () => 42, getPlayerState: () => ytState };
    Object.assign(window, { SC: { Widget: WidgetFactory }, YT: { PlayerState: { PLAYING: 1, PAUSED: 2, BUFFERING: 3, ENDED: 0, CUED: 5 },
      Player: function (_host: HTMLElement, config: { events: typeof ytEvents }) { ytEvents = config.events; return yt; } } });
    scripts = ["https://w.soundcloud.com/player/api.js", "https://www.youtube.com/iframe_api"].map(src => {
      const script = document.createElement("script"); script.src = src; script.dataset.loaded = "1"; document.head.append(script); return script;
    });
    host = document.createElement("div"); document.body.append(host); root = createRoot(host);
    await render(); await emit(latest, "READY"); await emit(latest, "PLAY"); expect(time()).toBe("0:12");
  });
  afterEach(async () => {
    if (root) await act(async () => root!.unmount());
    host.remove(); scripts.forEach(script => script.remove()); Reflect.deleteProperty(window, "SC"); Reflect.deleteProperty(window, "YT");
    vi.useRealTimers(); vi.unstubAllGlobals();
  });

  it("rejects old asynchronous poll and persistence replies after source replacement", async () => {
    const old = latest; old.defer = true;
    await act(async () => { vi.advanceTimersByTime(400); window.dispatchEvent(new Event("pagehide")); });
    expect(old.positions.length).toBeGreaterThanOrEqual(2); expect(old.pausedReads.length).toBeGreaterThan(0);
    await toYouTube(); const before = storage();
    await act(async () => { old.positions.forEach(callback => callback(222000)); old.pausedReads.forEach(callback => callback(true)); });
    expect(time()).toBe("0:42"); expect(playing()).toBe(true); expect(storage()).toBe(before);
  });

  it.each(["PLAY", "PAUSE", "FINISH", "SEEK", "PLAY_PROGRESS", "LOAD_PROGRESS"])("rejects an old %s event without altering the replacement", async (event) => {
    const old = latest; await toYouTube(event !== "PLAY"); const before = storage();
    await emit(old, event, { currentPosition: 222000, loadProgress: 1 });
    expect(time()).toBe("0:42"); expect(playing()).toBe(event !== "PLAY"); expect(storage()).toBe(before);
    expect(yt.playVideo).not.toHaveBeenCalled(); expect(yt.pauseVideo).not.toHaveBeenCalled(); expect(yt.seekTo).not.toHaveBeenCalled();
  });

  it("does not restart warmup on a retired READY event", async () => {
    const old = latest; old.widget.setVolume = vi.fn(); await toYouTube();
    old.widget.play.mockClear(); old.widget.pause.mockClear();
    await emit(old, "READY");
    expect(old.widget.setVolume).not.toHaveBeenCalled(); expect(old.widget.play).not.toHaveBeenCalled();
    await act(async () => vi.advanceTimersByTime(6000)); expect(old.widget.pause).not.toHaveBeenCalled(); expect(playing()).toBe(true);
  });

  it("rejects an old PAUSE while the new SoundCloud generation is warming up", async () => {
    const old = latest; warmup = true;
    await render({ ...detail, sourceUrl: "https://soundcloud.com/synthetic/second" }); const current = latest;
    await emit(current, "READY"); expect(current.widget.setVolume).toHaveBeenCalledWith(0);
    await emit(old, "PAUSE"); await emit(current, "PLAY_PROGRESS", { currentPosition: 1000 });
    expect(current.widget.pause).toHaveBeenCalledOnce();
    await emit(current, "PAUSE"); await act(async () => vi.advanceTimersByTime(120));
    expect(host.querySelector<HTMLInputElement>("#dockProgress")!.disabled).toBe(false);
  });

  it("rejects old callbacks even when the SDK reuses the same iframe and widget", async () => {
    const old = latest; old.defer = true; reuseWidget = true;
    await act(async () => vi.advanceTimersByTime(400));
    await render({ ...detail, sourceUrl: "https://soundcloud.com/synthetic/second" }); const current = latest;
    expect(current.frame).toBe(old.frame); expect(current.widget).toBe(old.widget);
    await emit(current, "READY"); await emit(current, "PLAY");
    await act(async () => vi.advanceTimersByTime(2000));
    await emit(current, "PLAY_PROGRESS", { currentPosition: 42000 }); const before = storage();
    await act(async () => { old.positions.forEach(callback => callback(222000)); old.pausedReads.forEach(callback => callback(true)); });
    await emit(old, "PAUSE");
    expect(time()).toBe("0:42"); expect(playing()).toBe(true); expect(storage()).toBe(before);
  });

  it("does not let a retired warmup completion ready a reused widget generation", async () => {
    const old = latest; old.widget.setVolume = vi.fn();
    await emit(old, "READY"); await emit(old, "PLAY_PROGRESS", { currentPosition: 1000 }); await emit(old, "PAUSE");
    reuseWidget = true;
    await render({ ...detail, sourceUrl: "https://soundcloud.com/synthetic/second" }); const current = latest;
    expect(current.frame).toBe(old.frame); expect(current.widget).toBe(old.widget);
    await emit(current, "READY");
    await act(async () => vi.advanceTimersByTime(120));
    expect(host.querySelector<HTMLInputElement>("#dockProgress")!.disabled).toBe(true);
    await emit(current, "PLAY_PROGRESS", { currentPosition: 1000 }); await emit(current, "PAUSE");
    await act(async () => vi.advanceTimersByTime(120));
    expect(host.querySelector<HTMLInputElement>("#dockProgress")!.disabled).toBe(false);
  });

  it("preserves replacement buffering intent when an old PAUSE arrives", async () => {
    const old = latest; await toYouTube();
    await act(async () => { ytState = 3; ytEvents.onStateChange({ data: 3 }); vi.advanceTimersByTime(400); });
    expect(playing()).toBe(false);
    await emit(old, "PAUSE"); await seek(100);
    expect(yt.seekTo.mock.calls).toEqual([[100, true]]);
    expect(yt.playVideo).toHaveBeenCalledOnce(); expect(yt.pauseVideo).not.toHaveBeenCalled();
  });

  it("preserves a newer explicit Pause when an old PLAY arrives", async () => {
    const old = latest; await toYouTube();
    await act(async () => host.querySelector<HTMLButtonElement>(".dock-play-btn")!.click());
    // Provider still reports playing until its pending pause is acknowledged.
    yt.playVideo.mockClear(); yt.pauseVideo.mockClear();
    await emit(old, "PLAY"); await seek(100);
    expect(yt.seekTo.mock.calls).toEqual([[100, true]]);
    expect(yt.pauseVideo).toHaveBeenCalledOnce(); expect(yt.playVideo).not.toHaveBeenCalled();
  });

  it("does not let an old PLAY steal active Spotify-preview focus", async () => {
    const old = latest; await toYouTube(); const previewPause = vi.fn();
    const focus = focusState.current!;
    focus.register("synthetic-preview", previewPause);
    await act(async () => focus.playing("synthetic-preview"));
    await act(async () => { ytState = 2; ytEvents.onStateChange({ data: 2 }); });
    yt.playVideo.mockClear(); yt.pauseVideo.mockClear();
    await emit(old, "PLAY");
    expect(previewPause).not.toHaveBeenCalled(); expect(playing()).toBe(false);
    expect(yt.playVideo).not.toHaveBeenCalled(); expect(yt.pauseVideo).not.toHaveBeenCalled();
    await act(async () => focus.stopped("synthetic-preview"));
    expect(yt.playVideo).toHaveBeenCalledOnce();
  });

  it("ignores retired replies after unmount instead of rewriting saved playback", async () => {
    const old = latest; old.defer = true; await act(async () => vi.advanceTimersByTime(400));
    const mountedRoot = root!; root = null; await act(async () => mountedRoot.unmount()); const before = storage();
    await act(async () => { old.positions.forEach(callback => callback(222000)); old.pausedReads.forEach(callback => callback(true)); });
    expect(storage()).toBe(before);
  });

  it("still accepts current-generation replies and pause/playing events", async () => {
    latest.position = 33000; await act(async () => vi.advanceTimersByTime(400)); expect(time()).toBe("0:33");
    latest.paused = true; await emit(latest, "PAUSE"); expect(playing()).toBe(false);
    latest.paused = false; await emit(latest, "PLAY"); expect(playing()).toBe(true);
  });
});
