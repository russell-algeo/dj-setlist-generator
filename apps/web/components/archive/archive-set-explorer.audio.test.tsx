// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ArchiveSetDetail } from "@/lib/archive/types";
import { ArchiveSetExplorer } from "./archive-set-explorer";
import { stubStandbyAudio } from "@/test/standby-audio.test-support";

vi.mock("./archive-header", () => ({ ArchiveHeader: () => null }));
vi.mock("./archive-delete-control", () => ({ ArchiveDeleteControl: () => null, SubmittedByYouBadge: () => null }));
vi.mock("./spotify-export-button", () => ({ SpotifyExportButton: () => null }));

const detail: ArchiveSetDetail = {
  id: "synthetic-set", slug: "synthetic-set", title: "Synthetic two-file recording", artistName: null,
  artists: [], heroImageUrl: null, thumbnailUrl: null, sourcePlatform: null, sourceUrl: null,
  sourceLinks: [], embedUrl: null, duration: 20, durationFmt: "0:20", recognitionRate: null,
  generatedAt: null, stats: { totalTracks: 0, identifiedTracks: 0, highOrMediumTracks: 0, distinctArtists: 0 },
  highlightedTracks: [], timeline: [], tracks: [], journeyPoints: [],
};
const privateContext = {
  collectionHref: "/synthetic-collection", boundaryNote: "Synthetic test fixture",
  audio: { src: "/synthetic-a", revision: "synthetic", segments: [
    { src: "/synthetic-a", startSeconds: 3120, durationSeconds: 10 },
    { src: "/synthetic-b", startSeconds: 20, durationSeconds: 10 },
  ] },
};

describe("recording browser-event integration", () => {
  let root: Root;
  let container: HTMLDivElement;
  let audio: HTMLAudioElement;
  let paused: boolean;
  let ended: boolean;
  let readyState: number;
  let pendingPlay: { resolve: () => void; reject: (error: Error) => void } | null;

  const emit = (name: string) => audio.dispatchEvent(new Event(name));
  const button = (label: string) => container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)!;
  const slider = () => container.querySelector<HTMLInputElement>('input[aria-label="Seek within set"]')!;
  const click = async (label: string) => { await act(async () => { button(label).click(); }); };
  const metadata = async (state = 4) => {
    await act(async () => { readyState = state; ended = false; emit("loadedmetadata"); });
  };
  const scrub = async (seconds: number) => {
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(slider(), String(seconds));
      slider().dispatchEvent(new Event("input", { bubbles: true }));
    });
  };

  beforeEach(async () => {
    stubStandbyAudio();
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    paused = true; ended = false; readyState = 0; pendingPlay = null;
    vi.spyOn(HTMLMediaElement.prototype, "paused", "get").mockImplementation(() => paused);
    vi.spyOn(HTMLMediaElement.prototype, "ended", "get").mockImplementation(() => ended);
    vi.spyOn(HTMLMediaElement.prototype, "readyState", "get").mockImplementation(() => readyState);
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(function (this: HTMLMediaElement) {
      const changed = !paused;
      paused = true;
      pendingPlay?.reject(new DOMException("Interrupted by pause", "AbortError"));
      pendingPlay = null;
      if (changed) queueMicrotask(() => this.dispatchEvent(new Event("pause")));
    });
    vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(function (this: HTMLMediaElement) {
      paused = true; ended = false; readyState = 0; this.currentTime = 0;
      this.dispatchEvent(new Event("loadstart"));
    });
    vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(function (this: HTMLMediaElement) {
      paused = false;
      queueMicrotask(() => this.dispatchEvent(new Event("play")));
      if (readyState < 1) return new Promise<void>((resolve, reject) => { pendingPlay = { resolve, reject }; });
      queueMicrotask(() => this.dispatchEvent(new Event("playing")));
      return Promise.resolve();
    });
    container = document.createElement("div"); document.body.append(container);
    root = createRoot(container);
    await act(async () => root.render(<ArchiveSetExplorer detail={detail} initialListened={null} initialQuery=""
      management={{ canDeleteSet: false, deleteImpact: null, setWillBeRemoved: false, submittedByViewer: false }}
      privateContext={privateContext} />));
    audio = container.querySelector("audio")!;
    await metadata();
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals();
  });

  it("starts paused at the approved offset and does not reset on repeated metadata", async () => {
    expect(audio.currentTime).toBe(3120); expect(paused).toBe(true);
    await click("Play set");
    await act(async () => { audio.currentTime = 3124; emit("timeupdate"); });
    await metadata(1);
    expect(audio.currentTime).toBe(3124); expect(paused).toBe(false);
    expect(slider().value).toBe("4");
  });

  it.each([["ended", 1], ["ended", 4], ["timeupdate", 1], ["timeupdate", 4]] as const)("continues through the seam after %s with readyState %s", async (event, state) => {
    await click("Play set");
    await act(async () => {
      audio.currentTime = 3130;
      if (event === "ended") { paused = true; ended = true; emit("pause"); }
      emit(event);
    });
    expect(audio.getAttribute("src")).toBe("/synthetic-b");
    await metadata(state);
    expect(audio.currentTime).toBe(20);
    expect(paused).toBe(false);
    expect(button("Pause set")).not.toBeNull();
    await act(async () => { audio.currentTime = 22; emit("seeked"); emit("timeupdate"); });
    expect(slider().value).toBe("12");
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it("preserves a playing cross-file seek after metadata arrives", async () => {
    await click("Play set"); await scrub(14); await metadata();
    expect(audio.currentTime).toBe(24); expect(paused).toBe(false);
    expect(slider().value).toBe("14"); expect(button("Pause set")).not.toBeNull();
  });

  it("keeps a paused cross-file seek paused", async () => {
    await scrub(14); await metadata();
    expect(audio.currentTime).toBe(24); expect(paused).toBe(true);
    expect(button("Play set")).not.toBeNull();
  });

  it("honors Pause during source loading and does not restart on metadata", async () => {
    await click("Play set"); await scrub(14); await click("Pause set"); await metadata();
    expect(audio.currentTime).toBe(24); expect(paused).toBe(true);
    expect(button("Play set")).not.toBeNull();
  });

  it("supports repeated forward/backward file changes and endpoint/replay behavior", async () => {
    await click("Play set"); await scrub(14);
    await metadata(); await scrub(4); await metadata();
    expect(audio.currentTime).toBe(3124); expect(paused).toBe(false);
    await scrub(20); await metadata();
    expect(audio.currentTime).toBe(30); expect(paused).toBe(true);
    expect(button("Replay set")).not.toBeNull();
    await click("Replay set"); await metadata();
    expect(audio.currentTime).toBe(3120); expect(paused).toBe(false);
  });
  const pointer = async (type: string, target = slider()) => {
    await act(async () => {
      const event = new MouseEvent(type, { bubbles: true, button: 0 });
      Object.defineProperties(event, { pointerId: { value: 1 }, pointerType: { value: "touch" }, isPrimary: { value: true } });
      target.dispatchEvent(event);
    });
  };

  it("does not pause, restart or seek native playback for intermediate drag samples", async () => {
    await click("Play set");
    const pauses = vi.mocked(HTMLMediaElement.prototype.pause).mock.calls.length;
    const plays = vi.mocked(HTMLMediaElement.prototype.play).mock.calls.length;
    await pointer("pointerdown");
    for (const seconds of [1, 2, 3, 4, 5, 6, 7]) await scrub(seconds);
    expect(audio.currentTime).toBe(3120);
    expect(container.querySelector(".recorded-set-time span")!.textContent).toBe("0:07");
    expect(container.textContent).not.toContain("Seek to");
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalledTimes(pauses);
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(plays);
    await pointer("pointerup");
    expect(audio.currentTime).toBe(3127); expect(paused).toBe(false);
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalledTimes(pauses + 1);
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(plays + 1);
  });

  it("keeps paused dragging paused and respects a later system pause", async () => {
    await pointer("pointerdown"); await scrub(3); await pointer("pointerup");
    expect(audio.currentTime).toBe(3123); expect(paused).toBe(true);
    await click("Play set"); await pointer("pointerdown"); await scrub(7);
    await act(async () => { audio.pause(); });
    await pointer("pointerup");
    expect(audio.currentTime).toBe(3127); expect(paused).toBe(true);
  });

  it("the dock also commits once and does not turn a paused set on", async () => {
    const dock = container.querySelector<HTMLInputElement>("#dockProgress")!;
    await pointer("pointerdown", dock);
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(dock, "6");
      dock.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(audio.currentTime).toBe(3120);
    await pointer("pointerup", dock);
    expect(audio.currentTime).toBe(3126); expect(paused).toBe(true);
  });

  it("source revision replacement discards the old recording and dock gestures", async () => {
    await pointer("pointerdown"); await scrub(7); const oldSlider = slider();
    await act(async () => root.render(<ArchiveSetExplorer detail={detail} initialListened={null} initialQuery=""
      management={{ canDeleteSet: false, deleteImpact: null, setWillBeRemoved: false, submittedByViewer: false }}
      privateContext={{ ...privateContext, audio: { ...privateContext.audio, revision: "new-revision" } }} />));
    audio = container.querySelector("audio")!; await metadata();
    await pointer("pointerup", oldSlider);
    expect(audio.currentTime).toBe(3120); expect(paused).toBe(true); expect(slider().value).toBe("0");
  });

  it("mapping replacement with the same source and revision discards an old gesture", async () => {
    await pointer("pointerdown"); await scrub(7); const oldSlider = slider();
    await act(async () => root.render(<ArchiveSetExplorer detail={detail} initialListened={null} initialQuery=""
      management={{ canDeleteSet: false, deleteImpact: null, setWillBeRemoved: false, submittedByViewer: false }}
      privateContext={{ ...privateContext, audio: { ...privateContext.audio,
        segments: [{ ...privateContext.audio.segments[0]!, startSeconds: 4000 }, privateContext.audio.segments[1]!] } }} />));
    await metadata(); await pointer("pointerup", oldSlider);
    expect(audio.currentTime).toBe(4000); expect(paused).toBe(true);
  });


  it("reconnects a playing recording at the same position after a provider network error", async () => {
    await click("Play set"); await scrub(14); await metadata();
    await act(async () => { audio.currentTime = 25.5; emit("timeupdate"); });
    const loads = vi.mocked(HTMLMediaElement.prototype.load).mock.calls.length;
    await act(async () => { emit("error"); });
    expect(HTMLMediaElement.prototype.load).toHaveBeenCalledTimes(loads + 1);
    expect(audio.getAttribute("src")).toBe("/synthetic-b");
    expect(container.querySelector('[role="alert"]')).toBeNull();
    await metadata();
    expect(audio.currentTime).toBe(25.5); expect(paused).toBe(false);
    expect(button("Pause set")).not.toBeNull();
  });

  it("keeps a paused recording paused when it reconnects, then reports a persistent failure", async () => {
    await scrub(6); await metadata();
    await act(async () => { emit("error"); }); await metadata();
    expect(audio.currentTime).toBe(3126); expect(paused).toBe(true);
    await act(async () => { emit("error"); }); await metadata();
    expect(container.querySelector('[role="alert"]')).toBeNull();
    await act(async () => { emit("error"); });
    expect(container.textContent).toContain("The private recording is unavailable");
  });

  it("reconnects a playing recording whose stream stalls without progress", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      await click("Play set");
      await act(async () => { audio.currentTime = 3125; emit("timeupdate"); emit("waiting"); });
      const loads = vi.mocked(HTMLMediaElement.prototype.load).mock.calls.length;
      await act(async () => { vi.advanceTimersByTime(14_000); });
      expect(HTMLMediaElement.prototype.load).toHaveBeenCalledTimes(loads);
      await act(async () => { vi.advanceTimersByTime(1_500); });
      expect(HTMLMediaElement.prototype.load).toHaveBeenCalledTimes(loads + 1);
      await metadata();
      expect(audio.currentTime).toBe(3125); expect(paused).toBe(false);
    } finally { vi.useRealTimers(); }
  });

  it("does not reload a slow stream that is still downloading", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    try {
      await click("Play set");
      await act(async () => { audio.currentTime = 3125; emit("waiting"); });
      const loads = vi.mocked(HTMLMediaElement.prototype.load).mock.calls.length;
      for (let i = 0; i < 8; i += 1) await act(async () => { vi.advanceTimersByTime(5_000); emit("progress"); });
      expect(HTMLMediaElement.prototype.load).toHaveBeenCalledTimes(loads);
      await act(async () => { vi.advanceTimersByTime(31_000); });
      expect(HTMLMediaElement.prototype.load).toHaveBeenCalledTimes(loads + 1);
    } finally { vi.useRealTimers(); }
  });

  it("does not reconnect a stall that recovers or a paused recording", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      await click("Play set");
      await act(async () => { audio.currentTime = 3125; emit("waiting"); });
      await act(async () => { audio.currentTime = 3126; emit("playing"); });
      const loads = vi.mocked(HTMLMediaElement.prototype.load).mock.calls.length;
      await act(async () => { vi.advanceTimersByTime(30_000); });
      await act(async () => { emit("waiting"); });
      await click("Pause set");
      await act(async () => { vi.advanceTimersByTime(30_000); });
      expect(HTMLMediaElement.prototype.load).toHaveBeenCalledTimes(loads);
    } finally { vi.useRealTimers(); }
  });
});
