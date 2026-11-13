// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ArchiveSetDetail, ArchiveSetTrack } from "@/lib/archive/types";
import { ArchiveSetExplorer } from "./archive-set-explorer";

vi.mock("./archive-header", () => ({ ArchiveHeader: () => null }));
vi.mock("./archive-delete-control", () => ({ ArchiveDeleteControl: () => null, SubmittedByYouBadge: () => null }));
vi.mock("./spotify-export-button", () => ({ SpotifyExportButton: () => null }));

const track = (idx: number, start: number, end: number, title: string, artist: string, albumArt: string | null = null): ArchiveSetTrack => ({
  idx, artist, title, start, end, startFmt: `0:${String(start).padStart(2, "0")}`, endFmt: null, conf: "HIGH", albumArt,
  previewUrl: null, bpm: null, energy: null, dance: null, key: null, genres: [], detailGenres: [], label: null, labelUrl: null,
  spotifyUrl: null, youtubeUrl: null, discogsUrl: null, detectionCount: 3, clusterDensity: null, clusterSpan: null, sourceDeepLink: null,
});

const detail: ArchiveSetDetail = {
  id: "synthetic-lock-screen", slug: "synthetic-lock-screen", title: "Synthetic lock-screen set", artistName: "Synthetic DJ",
  artists: [], heroImageUrl: "/synthetic-hero.jpg", thumbnailUrl: null, sourcePlatform: null, sourceUrl: null,
  sourceLinks: [], embedUrl: null, duration: 20, durationFmt: "0:20", recognitionRate: null,
  generatedAt: null, stats: { totalTracks: 3, identifiedTracks: 2, highOrMediumTracks: 2, distinctArtists: 2 },
  highlightedTracks: [], timeline: [], journeyPoints: [],
  tracks: [
    track(1, 0, 8, "Opening Synthetic", "Artist A", "/art-a.png"),
    track(2, 8, 14, "Unknown Track", "Unknown"),
    track(3, 14, 20, "Closing Synthetic", "Artist C"),
  ],
};
const privateContext = {
  collectionHref: "/synthetic-collection", boundaryNote: "Synthetic test fixture",
  audio: { src: "/synthetic-a", revision: "synthetic", segments: [
    { src: "/synthetic-a", startSeconds: 3120, durationSeconds: 10 },
    { src: "/synthetic-b", startSeconds: 20, durationSeconds: 10 },
  ] },
};

type Handler = ((details: MediaSessionActionDetails) => void) | null;

describe("system media controls for recordings", () => {
  let root: Root;
  let container: HTMLDivElement;
  let audio: HTMLAudioElement;
  let paused: boolean;
  let readyState: number;
  let handlers: Map<string, Handler>;
  let registrations: string[];
  let session: { metadata: MediaMetadataInit | null; playbackState: string; positions: Array<MediaPositionState | undefined>;
    setActionHandler: (action: string, handler: Handler) => void; setPositionState: (state?: MediaPositionState) => void };

  const emit = (name: string) => audio.dispatchEvent(new Event(name));
  const press = async (action: string, details: Partial<MediaSessionActionDetails> = {}) => {
    const handler = handlers.get(action);
    expect(handler, `${action} handler`).toBeTypeOf("function");
    await act(async () => { handler!({ action, ...details } as MediaSessionActionDetails); });
  };
  const metadata = async () => { await act(async () => { readyState = 4; emit("loadedmetadata"); }); };
  const tick = async (sourceSeconds: number) => { await act(async () => { audio.currentTime = sourceSeconds; emit("timeupdate"); }); };
  const renderExplorer = (value: ArchiveSetDetail) => act(async () => root.render(<ArchiveSetExplorer detail={value} initialListened={null} initialQuery=""
    management={{ canDeleteSet: false, deleteImpact: null, setWillBeRemoved: false, submittedByViewer: false }}
    privateContext={privateContext} />));

  beforeEach(async () => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    vi.stubGlobal("MediaMetadata", class { constructor(init: MediaMetadataInit) { Object.assign(this, init); } });
    handlers = new Map(); registrations = [];
    session = {
      metadata: null, playbackState: "none", positions: [],
      setActionHandler: (action, handler) => { handlers.set(action, handler); if (handler) registrations.push(action); },
      setPositionState: (state) => { session.positions.push(state); },
    };
    Object.defineProperty(navigator, "mediaSession", { configurable: true, value: session });
    paused = true; readyState = 0;
    vi.spyOn(HTMLMediaElement.prototype, "paused", "get").mockImplementation(() => paused);
    vi.spyOn(HTMLMediaElement.prototype, "ended", "get").mockImplementation(() => false);
    vi.spyOn(HTMLMediaElement.prototype, "readyState", "get").mockImplementation(() => readyState);
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(function (this: HTMLMediaElement) {
      const changed = !paused; paused = true;
      if (changed) queueMicrotask(() => this.dispatchEvent(new Event("pause")));
    });
    vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(function (this: HTMLMediaElement) {
      paused = true; readyState = 0; this.currentTime = 0; this.dispatchEvent(new Event("loadstart"));
    });
    vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(function (this: HTMLMediaElement) {
      paused = false;
      queueMicrotask(() => this.dispatchEvent(new Event("play")));
      if (readyState >= 1) queueMicrotask(() => this.dispatchEvent(new Event("playing")));
      return Promise.resolve();
    });
    container = document.createElement("div"); document.body.append(container);
    root = createRoot(container);
    await renderExplorer(detail);
    audio = container.querySelector("audio")!;
    await metadata();
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals();
    Reflect.deleteProperty(navigator, "mediaSession");
  });

  it("offers track skip rather than +/- seek buttons and registers once", async () => {
    expect([...registrations].sort()).toEqual(["nexttrack", "pause", "play", "previoustrack", "seekto"]);
    expect(handlers.get("seekbackward")).toBeNull();
    expect(handlers.get("seekforward")).toBeNull();
    await renderExplorer({ ...detail });
    expect(registrations).toHaveLength(5);
  });

  it("plays and pauses the recording from the lock screen", async () => {
    await press("play");
    expect(paused).toBe(false); expect(session.playbackState).toBe("playing");
    await press("pause");
    expect(paused).toBe(true); expect(session.playbackState).toBe("paused");
    await press("play");
    expect(paused).toBe(false);
  });

  it("skips to the next track across a file seam and keeps playing", async () => {
    await press("play");
    await tick(3121);
    await press("nexttrack");
    expect(audio.currentTime).toBe(3128);
    await press("nexttrack");
    expect(audio.getAttribute("src")).toBe("/synthetic-b");
    await metadata();
    expect(audio.currentTime).toBe(24); expect(paused).toBe(false);
    expect(session.metadata).toMatchObject({ title: "Closing Synthetic", artist: "Artist C",
      album: "Synthetic DJ · Synthetic lock-screen set" });
  });

  it("restarts the current track, then goes back a track on a quick second press", async () => {
    await press("play"); await press("seekto", { seekTime: 16 }); await metadata();
    await tick(26);
    await press("previoustrack");
    expect(audio.currentTime).toBe(24);
    await press("previoustrack");
    expect(audio.getAttribute("src")).toBe("/synthetic-a");
    await metadata();
    expect(audio.currentTime).toBe(3128); expect(paused).toBe(false);
  });

  it("seeks from the lock-screen scrubber without changing play state", async () => {
    await press("seekto", { seekTime: 6 });
    expect(audio.currentTime).toBe(3126); expect(paused).toBe(true);
    await press("play"); await press("seekto", { seekTime: 16 });
    expect(audio.getAttribute("src")).toBe("/synthetic-b");
    await metadata();
    expect(audio.currentTime).toBe(26); expect(paused).toBe(false);
    await press("seekto", { seekTime: 99 }); await metadata();
    expect(audio.currentTime).toBe(30);
  });

  it("publishes set-level position and track artwork", async () => {
    await press("play"); await tick(3125);
    expect(session.positions.at(-1)).toEqual({ duration: 20, playbackRate: 1, position: 5 });
    expect(session.metadata).toMatchObject({ title: "Opening Synthetic", artist: "Artist A",
      artwork: [{ src: "/art-a.png", sizes: "512x512", type: "image/png" }] });
  });

  it("falls back to the set title for unknown tracks", async () => {
    await press("seekto", { seekTime: 9 });
    expect(session.metadata).toMatchObject({ title: "Synthetic lock-screen set", artist: "Synthetic DJ",
      artwork: [{ src: "/synthetic-hero.jpg", sizes: "512x512", type: "image/jpeg" }] });
  });

  it("clears system controls when the set is left", async () => {
    await act(async () => root.unmount());
    expect(session.metadata).toBeNull();
    for (const action of ["play", "pause", "seekto", "previoustrack", "nexttrack"]) expect(handlers.get(action)).toBeNull();
    root = createRoot(container);
  });
});
