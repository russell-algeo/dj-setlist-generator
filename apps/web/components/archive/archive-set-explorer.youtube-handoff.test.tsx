// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ArchiveSetDetail } from "@/lib/archive/types";
import { ArchiveSetExplorer } from "./archive-set-explorer";

vi.mock("./archive-header", () => ({ ArchiveHeader: () => null }));
vi.mock("./archive-delete-control", () => ({ ArchiveDeleteControl: () => null, SubmittedByYouBadge: () => null }));
vi.mock("./spotify-export-button", () => ({ SpotifyExportButton: () => null }));

const base: ArchiveSetDetail = {
  id: "synthetic-youtube-handoff", slug: "synthetic-youtube-handoff", title: "Synthetic YouTube handoff", artistName: null,
  artists: [], heroImageUrl: null, thumbnailUrl: null, sourcePlatform: "youtube", sourceUrl: "https://www.youtube.com/watch?v=abcdefghijk",
  sourceLinks: [], embedUrl: null, duration: 3600, durationFmt: "1:00:00", recognitionRate: null, generatedAt: null,
  stats: { totalTracks: 0, identifiedTracks: 0, highOrMediumTracks: 0, distinctArtists: 0 },
  highlightedTracks: [], timeline: [], tracks: [], journeyPoints: [],
};

describe("N06 timestamped Open Source for YouTube", () => {
  let root: Root | null;
  let host: HTMLDivElement;
  let script: HTMLScriptElement;
  let ytState: number;
  let ytTime: number;
  let ytEvents: { onReady: () => void; onStateChange: (event: { data: number }) => void };
  let yt: { playVideo: ReturnType<typeof vi.fn>; pauseVideo: ReturnType<typeof vi.fn>; seekTo: ReturnType<typeof vi.fn>; destroy: ReturnType<typeof vi.fn>; getCurrentTime: () => number; getPlayerState: () => number };
  const render = async (detail = base) => act(async () => root!.render(<ArchiveSetExplorer detail={detail} initialListened={null} initialQuery=""
    management={{ canDeleteSet: false, deleteImpact: null, setWillBeRemoved: false, submittedByViewer: false }} />));
  const handoff = () => [...host.querySelectorAll<HTMLAnchorElement>(".source-player-open")].find(link => link.textContent === "Open Source") ?? null;
  // Capture the href the browser would navigate to, without leaving jsdom.
  const clickHandoff = async () => {
    let navigatedTo = "";
    const link = handoff()!;
    // Listen on document so React's root handler has already updated href.
    const capture = (event: MouseEvent) => { navigatedTo = (event.target as HTMLAnchorElement).href; event.preventDefault(); };
    document.addEventListener("click", capture);
    await act(async () => link.click());
    document.removeEventListener("click", capture);
    return navigatedTo;
  };

  beforeEach(async () => {
    vi.useFakeTimers(); localStorage.clear(); vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1)); vi.stubGlobal("cancelAnimationFrame", vi.fn());
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ progress: null }), { status: 200 })));
    ytState = 2; ytTime = 0;
    yt = { playVideo: vi.fn(), pauseVideo: vi.fn(() => { ytState = 2; }), seekTo: vi.fn(), destroy: vi.fn(), getCurrentTime: () => ytTime, getPlayerState: () => ytState };
    Object.assign(window, { YT: { PlayerState: { PLAYING: 1, PAUSED: 2, BUFFERING: 3, ENDED: 0, CUED: 5 },
      Player: function (_host: HTMLElement, config: { events: typeof ytEvents }) { ytEvents = config.events; return yt; } } });
    script = document.createElement("script"); script.src = "https://www.youtube.com/iframe_api"; script.dataset.loaded = "1"; document.head.append(script);
    host = document.createElement("div"); document.body.append(host); root = createRoot(host);
    await render();
  });
  afterEach(async () => {
    if (root) await act(async () => root!.unmount());
    host.remove(); script.remove(); Reflect.deleteProperty(window, "YT");
    vi.useRealTimers(); vi.unstubAllGlobals();
  });

  it("keeps the single Open Source link, timestamped for YouTube, with no extra note", () => {
    expect(host.querySelectorAll(".source-player-open")).toHaveLength(1);
    expect(handoff()!.target).toBe("_blank");
    expect(handoff()!.href).toBe("https://www.youtube.com/watch?v=abcdefghijk&t=0s");
    expect(host.textContent).not.toContain("Open in YouTube");
    expect(host.textContent).not.toContain("screen locks");
    expect(host.querySelector(".youtube-player-host")).not.toBeNull();
  });

  it("opens at the live player position and pauses the embedded player first", async () => {
    await act(async () => { ytEvents.onReady(); });
    ytState = 1; await act(async () => { ytEvents.onStateChange({ data: 1 }); });
    // Let the ready-time seek fence settle; during it the requested target wins.
    await act(async () => { vi.advanceTimersByTime(2000); });
    ytTime = 1234.9;
    const url = await clickHandoff();
    expect(url).toBe("https://www.youtube.com/watch?v=abcdefghijk&t=1234s");
    expect(yt.pauseVideo).toHaveBeenCalled();
    expect(host.querySelector(".dock-play-btn")!.classList.contains("is-playing")).toBe(false);
  });

  it("falls back to the page clock when the player reports a non-finite time", async () => {
    await act(async () => { ytEvents.onReady(); });
    ytTime = Number.NaN;
    const url = await clickHandoff();
    expect(url).toMatch(/^https:\/\/www\.youtube\.com\/watch\?v=abcdefghijk&t=\d+s$/u);
  });

  it("leaves the SoundCloud Open Source link as the raw source URL", async () => {
    await render({ ...base, sourcePlatform: "soundcloud", sourceUrl: "https://soundcloud.com/synthetic/set" });
    expect(handoff()!.href).toBe("https://soundcloud.com/synthetic/set");
  });
});
