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
  id: "synthetic-source-switch", slug: "synthetic-source-switch", title: "Synthetic source switch", artistName: null,
  artists: [], heroImageUrl: null, thumbnailUrl: null, sourcePlatform: "soundcloud", sourceUrl: "https://soundcloud.com/synthetic/set",
  sourceLinks: [{ id: "alternate", platform: "youtube", url: "https://www.youtube.com/watch?v=abcdefghijk", title: null, durationSeconds: 600, isPrimary: false, matchConfidence: null }],
  embedUrl: null, duration: 600, durationFmt: "10:00", recognitionRate: null, generatedAt: null,
  stats: { totalTracks: 0, identifiedTracks: 0, highOrMediumTracks: 0, distinctArtists: 0 },
  highlightedTracks: [], timeline: [], tracks: [], journeyPoints: [],
};

describe("SoundCloud source teardown persistence", () => {
  let root: Root | null;
  let host: HTMLDivElement;
  let scripts: HTMLScriptElement[];
  let frame: HTMLIFrameElement;
  let events: Record<string, () => void>;
  let getPosition: ReturnType<typeof vi.fn<(callback: (milliseconds: number) => void) => void>>;
  let paused: boolean;
  const savedPosition = () => JSON.parse(localStorage.getItem(`set-signal:playback:v1:${detail.id}`)!).currentTime;
  const switchTo = async (label: string) => act(async () => {
    [...host.querySelectorAll<HTMLButtonElement>(".source-switcher-option")].find(button => button.textContent === label)!.click();
  });

  beforeEach(async () => {
    vi.useFakeTimers(); localStorage.clear(); vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1)); vi.stubGlobal("cancelAnimationFrame", vi.fn());
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ progress: null }), { status: 200 })));
    paused = true; events = {};
    const Widget = Object.assign((element: HTMLIFrameElement) => {
      frame = element;
      getPosition = vi.fn((callback: (milliseconds: number) => void) => {
        // The real SDK posts to iframe.contentWindow and throws after removal.
        if (!element.isConnected) throw new TypeError("Cannot read properties of null (reading 'postMessage')");
        callback(12000);
      });
      return { bind: (name: string, callback: () => void) => { events[name] = callback; }, getPosition,
        isPaused: (callback: (value: boolean) => void) => callback(paused), pause: vi.fn(), play: vi.fn(), seekTo: vi.fn() };
    }, { Events: Object.fromEntries(["READY", "LOAD_PROGRESS", "PLAY", "PAUSE", "FINISH", "SEEK", "PLAY_PROGRESS"].map(name => [name, name])) });
    Object.assign(window, { SC: { Widget }, YT: { PlayerState: { PLAYING: 1, PAUSED: 2, ENDED: 0, CUED: 5 },
      Player: function () { return { destroy: vi.fn(), getCurrentTime: () => 12, getPlayerState: () => 2 }; } } });
    scripts = ["https://w.soundcloud.com/player/api.js", "https://www.youtube.com/iframe_api"].map(src => {
      const script = document.createElement("script"); script.src = src; script.dataset.loaded = "1"; document.head.append(script); return script;
    });
    host = document.createElement("div"); document.body.append(host); root = createRoot(host);
    await act(async () => root!.render(<ArchiveSetExplorer detail={detail} initialListened={null} initialQuery=""
      management={{ canDeleteSet: false, deleteImpact: null, setWillBeRemoved: false, submittedByViewer: false }} />));
    await act(async () => events.READY());
    await act(async () => { paused = false; events.PLAY(); });
    expect(savedPosition()).toBe(12);
    getPosition.mockClear();
  });
  afterEach(async () => {
    if (root) await act(async () => root!.unmount());
    host.remove(); scripts.forEach(script => script.remove()); Reflect.deleteProperty(window, "SC"); Reflect.deleteProperty(window, "YT");
    vi.useRealTimers(); vi.unstubAllGlobals();
  });

  it.each([true, false])("switches a paused=%s source without querying its detached iframe", async (pauseFirst) => {
    if (pauseFirst) await act(async () => { paused = true; events.PAUSE(); });
    getPosition.mockClear(); const oldFrame = frame;
    await switchTo("Youtube");
    expect(oldFrame.isConnected).toBe(false);
    expect(getPosition).not.toHaveBeenCalled();
    expect(savedPosition()).toBe(12);
    expect(host.querySelector(".youtube-player-host")).not.toBeNull();
  });

  it("keeps normal attached page-hide persistence using the provider clock", async () => {
    await act(async () => window.dispatchEvent(new Event("pagehide")));
    expect(getPosition).toHaveBeenCalled(); expect(savedPosition()).toBe(12);
  });

  it("unmounts safely and retains the latest cached position", async () => {
    const mountedRoot = root!; root = null;
    await act(async () => mountedRoot.unmount());
    expect(frame.isConnected).toBe(false); expect(getPosition).not.toHaveBeenCalled(); expect(savedPosition()).toBe(12);
  });
});
