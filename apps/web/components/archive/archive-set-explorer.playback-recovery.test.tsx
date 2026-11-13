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
  id: "synthetic-recovery-source", slug: "synthetic-recovery-source", title: "Synthetic stale source", artistName: null,
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

describe("provider play/pause state while loading or buffering", () => {
  let root: Root | null;
  let host: HTMLDivElement;
  let scripts: HTMLScriptElement[];
  let latest: Record;
  let ytState: number;
  let ytEvents: { onReady: () => void; onStateChange: (event: { data: number }) => void };
  let yt: { playVideo: ReturnType<typeof vi.fn>; pauseVideo: ReturnType<typeof vi.fn>; seekTo: ReturnType<typeof vi.fn>; destroy: ReturnType<typeof vi.fn>; getCurrentTime: () => number; getPlayerState: () => number };
  const playing = () => host.querySelector(".dock-play-btn")!.classList.contains("is-playing");
  const dockPlay = async () => act(async () => host.querySelector<HTMLButtonElement>(".dock-play-btn")!.click());
  const render = async (value = detail) => act(async () => root!.render(<ArchiveSetExplorer detail={value} initialListened={null} initialQuery=""
    management={{ canDeleteSet: false, deleteImpact: null, setWillBeRemoved: false, submittedByViewer: false }} />));
  const emit = async (record: Record, name: string, data?: EventData) => act(async () => record.events[name](data));

  beforeEach(async () => {
    vi.useFakeTimers(); localStorage.clear(); vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1)); vi.stubGlobal("cancelAnimationFrame", vi.fn());
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ progress: null }), { status: 200 })));
    ytState = 2;
    const WidgetFactory = Object.assign((frame: HTMLIFrameElement) => {
      const record = { frame, events: {}, positions: [], pausedReads: [], defer: false, paused: true, position: 0 } as unknown as Record;
      latest = record;
      record.widget = {
        bind: (name, callback) => { record.events[name] = callback; },
        getPosition: (callback) => callback(record.position),
        isPaused: (callback) => callback(record.paused),
        play: vi.fn(() => { record.paused = false; }), pause: vi.fn(() => { record.paused = true; }), seekTo: vi.fn(), setVolume: vi.fn(),
      };
      return record.widget;
    }, { Events: Object.fromEntries(["READY", "LOAD_PROGRESS", "PLAY", "PAUSE", "FINISH", "SEEK", "PLAY_PROGRESS"].map(name => [name, name])) });
    yt = { playVideo: vi.fn(), pauseVideo: vi.fn(), seekTo: vi.fn(), destroy: vi.fn(), getCurrentTime: () => 42, getPlayerState: () => ytState };
    Object.assign(window, { SC: { Widget: WidgetFactory }, YT: { PlayerState: { PLAYING: 1, PAUSED: 2, BUFFERING: 3, ENDED: 0, CUED: 5 },
      Player: function (_host: HTMLElement, config: { events: typeof ytEvents }) { ytEvents = config.events; return yt; } } });
    scripts = ["https://w.soundcloud.com/player/api.js", "https://www.youtube.com/iframe_api"].map(src => {
      const script = document.createElement("script"); script.src = src; script.dataset.loaded = "1"; document.head.append(script); return script;
    });
    host = document.createElement("div"); document.body.append(host); root = createRoot(host);
    await render();
  });
  afterEach(async () => {
    if (root) await act(async () => root!.unmount());
    host.remove(); scripts.forEach(script => script.remove()); Reflect.deleteProperty(window, "SC"); Reflect.deleteProperty(window, "YT");
    vi.useRealTimers(); vi.unstubAllGlobals();
  });

  const finishWarmup = async () => {
    const record = latest;
    await emit(record, "READY"); expect(record.widget.setVolume).toHaveBeenCalledWith(0);
    await emit(record, "PLAY_PROGRESS", { currentPosition: 300 }); expect(record.widget.pause).toHaveBeenCalledOnce();
    await emit(record, "PAUSE"); await act(async () => vi.advanceTimersByTime(120));
    expect(host.querySelector<HTMLButtonElement>(".dock-play-btn")!.disabled).toBe(false);
    record.widget.play.mockClear(); record.widget.pause.mockClear();
    return record;
  };

  it("does not let late SoundCloud warmup progress turn the first Play press into Pause", async () => {
    const record = await finishWarmup();
    // Queued warmup progress arrives after the controls are enabled.
    await emit(record, "PLAY_PROGRESS", { currentPosition: 600 });
    expect(playing()).toBe(false);
    await dockPlay();
    expect(record.widget.play).toHaveBeenCalledOnce(); expect(record.widget.pause).not.toHaveBeenCalled();
    await emit(record, "PLAY"); await emit(record, "PLAY_PROGRESS", { currentPosition: 1000 });
    expect(playing()).toBe(true);
    await dockPlay(); expect(record.widget.pause).toHaveBeenCalledOnce();
  });

  it("still follows a genuine SoundCloud play right after warmup", async () => {
    const record = await finishWarmup();
    record.paused = false;
    await emit(record, "PLAY"); expect(playing()).toBe(true);
  });

  it("keeps YouTube buffering mid-play as playing so the next press pauses", async () => {
    await act(async () => [...host.querySelectorAll<HTMLButtonElement>(".source-switcher-option")].find(button => button.textContent === "Youtube")!.click());
    await act(async () => { ytEvents.onReady(); });
    ytState = 1; await act(async () => { ytEvents.onStateChange({ data: 1 }); });
    expect(playing()).toBe(true);
    ytState = 3; await act(async () => { ytEvents.onStateChange({ data: 3 }); vi.advanceTimersByTime(1200); });
    expect(playing()).toBe(true);
    yt.playVideo.mockClear();
    await dockPlay();
    expect(yt.pauseVideo).toHaveBeenCalled(); expect(yt.playVideo).not.toHaveBeenCalled();
  });

  it("does not show a paused YouTube set as playing while it buffers before Play", async () => {
    await act(async () => [...host.querySelectorAll<HTMLButtonElement>(".source-switcher-option")].find(button => button.textContent === "Youtube")!.click());
    await act(async () => { ytEvents.onReady(); });
    ytState = 3; await act(async () => { vi.advanceTimersByTime(1200); });
    expect(playing()).toBe(false);
    await dockPlay();
    expect(yt.pauseVideo).not.toHaveBeenCalled();
  });
});
