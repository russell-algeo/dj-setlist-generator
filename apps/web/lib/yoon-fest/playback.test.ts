import { describe, expect, it, vi } from "vitest";
import { createNativeAudioController, locateRecordingTime, spanDuration } from "./playback";
import { fixture } from "./fixtures.test-support";
const spans = fixture.sets[0]!.spans;
describe("cross-file sample mapping", () => {
  it.each([[0, "synthetic-a", 1], [9, "synthetic-a", 10], [10, "synthetic-b", 0], [12, "synthetic-b", 2], [20, "synthetic-b", 10]])("maps set second %s", (seconds, recordingId, sourceSeconds) => expect(locateRecordingTime(spans, Number(seconds))).toMatchObject({ recordingId, sourceSeconds }));
  it("preserves last sample and clamps only outside the set", () => { expect(locateRecordingTime(spans, 20 - 1 / 44100).sourceSample).toBe(440999); expect(locateRecordingTime(spans, 100).sourceSample).toBe(441000); expect(locateRecordingTime(spans, -1).sourceSample).toBe(44100); });
  it("rejects malformed spans and seeks", () => { expect(() => spanDuration({ ...spans[0]!, endSample: 1 })).toThrow(); expect(() => locateRecordingTime(spans, NaN)).toThrow(); expect(() => locateRecordingTime([], 0)).toThrow(); });
});
describe("real native audio adapter", () => {
  const make = () => ({ src: "/synthetic-a", load: vi.fn(), paused: true, currentTime: 0, readyState: 0, play: vi.fn().mockResolvedValue(undefined), pause: vi.fn() });
  it("waits for metadata, applying only latest cross-file seek", () => { const audio = make(); const c = createNativeAudioController(audio, 20, vi.fn()); c.seek(9, true); expect(audio.play).toHaveBeenCalledOnce(); c.seek(12, false); expect(audio.currentTime).toBe(0); audio.readyState = 1; c.ready(); expect(audio.currentTime).toBe(12); expect(audio.play).toHaveBeenCalledOnce(); expect(c.isPlayRequested()).toBe(false); });
  it("uses actual play/pause and clamps endpoints", () => { const audio = make(); audio.readyState = 1; const c = createNativeAudioController(audio, 20, vi.fn()); c.seek(99, true); expect(audio.currentTime).toBe(20); expect(audio.play).not.toHaveBeenCalled(); c.seek(4, true); expect(audio.currentTime).toBe(4); expect(audio.play).toHaveBeenCalledOnce(); c.pause(); expect(audio.pause).toHaveBeenCalled(); });
  it("ignores stale rejection after newer seek", async () => { const audio = make(); audio.readyState = 1; let reject!: (error: Error) => void; audio.play.mockReturnValue(new Promise((_, fail) => { reject = fail; })); const error = vi.fn(); const c = createNativeAudioController(audio, 20, error); c.seek(2, true); c.seek(12, false); reject(new Error("interrupted")); await Promise.resolve(); expect(error).not.toHaveBeenCalled(); });
  it("reports current autoplay denial and ignores disposed player", async () => { const audio = make(); audio.readyState = 1; audio.play.mockRejectedValue(new Error("autoplay")); const error = vi.fn(); const c = createNativeAudioController(audio, 20, error); c.seek(2, true); await Promise.resolve(); expect(error).toHaveBeenCalledOnce(); c.dispose(); c.seek(12, true); expect(audio.currentTime).toBe(2); });
});

describe("original recording windows", () => {
  const segments = [{ src: "/part-a", startSeconds: 52 * 60, durationSeconds: 10 }, { src: "/part-b", startSeconds: 20, durationSeconds: 10 }];
  const make = () => ({ src: "/part-a", load: vi.fn(), paused: true, currentTime: 0, readyState: 1, play: vi.fn().mockResolvedValue(undefined), pause: vi.fn() });
  it("offsets playback into the original file without downloading or transcoding it", () => { const audio = make(); const c = createNativeAudioController(audio, 20, vi.fn(), segments); c.seek(2, false); expect(audio.currentTime).toBe(52 * 60 + 2); expect(c.position()).toBe(2); });
  it("seeks across files and waits for the new metadata", () => { const audio = make(); const c = createNativeAudioController(audio, 20, vi.fn(), segments); c.seek(12, true); expect(audio.src).toBe("/part-b"); expect(audio.load).toHaveBeenCalledOnce(); expect(audio.play).toHaveBeenCalledOnce(); expect(c.isPending()).toBe(true); c.ready(); expect(audio.currentTime).toBe(22); expect(c.position()).toBe(12); expect(audio.play).toHaveBeenCalledTimes(2); });
  it("switches naturally at the set seam and stops at the reviewed end", () => { const audio = make(); audio.paused = false; const c = createNativeAudioController(audio, 20, vi.fn(), segments); c.seek(0, true); audio.currentTime = 52 * 60 + 10; expect(c.tick()).toBe(10); expect(audio.src).toBe("/part-b"); c.ready(); audio.currentTime = 30; expect(c.tick()).toBe(20); expect(audio.currentTime).toBe(30); expect(audio.pause).toHaveBeenCalled(); });
  it("replaces a pending cross-file seek with the latest target", () => { const audio = make(); const c = createNativeAudioController(audio, 20, vi.fn(), segments); c.seek(12, true); c.seek(3, false); expect(audio.src).toBe("/part-a"); c.ready(); expect(audio.currentTime).toBe(52 * 60 + 3); expect(audio.play).toHaveBeenCalledOnce(); expect(c.isPlayRequested()).toBe(false); });
  it("clamps native scrubbing outside the approved source window", () => { const audio = make(); const c = createNativeAudioController(audio, 20, vi.fn(), segments); audio.currentTime = 0; expect(c.tick()).toBe(0); expect(audio.currentTime).toBe(52 * 60); });
});

describe("set-relative controls over original recordings", () => {
  const make = () => ({
    src: "/synthetic-recording", load: vi.fn(), paused: true, currentTime: 0, readyState: 1,
    play: vi.fn().mockResolvedValue(undefined), pause: vi.fn(),
  });
  const window = [{ src: "/synthetic-recording", startSeconds: 3120, durationSeconds: 7200 }];

  it("maps the two-hour set clock at its start, middle and endpoint", () => {
    const audio = make();
    const controller = createNativeAudioController(audio, 7200, vi.fn(), window);
    for (const [setTime, sourceTime] of [[0, 3120], [3600, 6720], [7200, 10320]]) {
      controller.seek(setTime!, false);
      expect(audio.currentTime).toBe(sourceTime);
      expect(controller.position()).toBe(setTime);
    }
    controller.seek(8000, true);
    expect(audio.currentTime).toBe(10320);
    expect(controller.isPlayRequested()).toBe(false);
    expect(audio.play).not.toHaveBeenCalled();
  });

  it("starts within the gesture before metadata and cancels a pending start on Pause", () => {
    const audio = make(); audio.readyState = 0;
    const controller = createNativeAudioController(audio, 7200, vi.fn(), window);
    controller.seek(0, true);
    expect(audio.play).toHaveBeenCalledOnce();
    expect(controller.isPlayRequested()).toBe(true);
    controller.pause();
    audio.readyState = 1; controller.ready();
    expect(audio.currentTime).toBe(3120);
    expect(audio.play).toHaveBeenCalledOnce();
    expect(controller.isPlayRequested()).toBe(false);
  });

  it("keeps playback intent through repeated seeks despite internal pauses", () => {
    const audio = make();
    const controller = createNativeAudioController(audio, 7200, vi.fn(), window);
    controller.seek(1, true);
    for (const target of [10, 3500, 2800, 12]) controller.seek(target, controller.isPlayRequested());
    expect(audio.currentTime).toBe(3132);
    expect(controller.position()).toBe(12);
    expect(controller.isPlayRequested()).toBe(true);
    expect(audio.play).toHaveBeenCalledTimes(5);
    controller.pause();
    controller.seek(40, controller.isPlayRequested());
    expect(audio.currentTime).toBe(3160);
    expect(audio.play).toHaveBeenCalledTimes(5);
  });

  it("cancels only the current denied play, keeps its position and permits retry", async () => {
    const audio = make(); audio.readyState = 0;
    audio.play.mockRejectedValueOnce(new Error("permission"));
    const error = vi.fn();
    const controller = createNativeAudioController(audio, 7200, error, window);
    controller.seek(20, true);
    await Promise.resolve();
    expect(error).toHaveBeenCalledOnce();
    expect(controller.isPlayRequested()).toBe(false);
    audio.readyState = 1; controller.ready();
    expect(audio.currentTime).toBe(3140);
    expect(audio.play).toHaveBeenCalledOnce();
    controller.seek(20, true);
    expect(audio.play).toHaveBeenCalledTimes(2);
  });

  it("stops at the set boundary and can restart from zero", () => {
    const audio = make(); audio.paused = false;
    const controller = createNativeAudioController(audio, 7200, vi.fn(), window);
    controller.seek(7199, true);
    audio.currentTime = 10321;
    expect(controller.tick()).toBe(7200);
    expect(audio.currentTime).toBe(10320);
    expect(controller.isPlayRequested()).toBe(false);
    controller.seek(0, true);
    expect(audio.currentTime).toBe(3120);
    expect(controller.isPlayRequested()).toBe(true);
  });

  it("keeps the latest repeated cross-file target and ignores invalid/disposed input", () => {
    const audio = make(); const error = vi.fn();
    const controller = createNativeAudioController(audio, 20, error, [
      { src: "/synthetic-recording", startSeconds: 3120, durationSeconds: 10 },
      { src: "/synthetic-second", startSeconds: 20, durationSeconds: 10 },
    ]);
    for (const target of [12, 3, 15, 4, 17]) controller.seek(target, true);
    controller.ready();
    expect(audio.src).toBe("/synthetic-second");
    expect(audio.currentTime).toBe(27);
    expect(controller.position()).toBe(17);
    controller.seek(NaN, true);
    expect(audio.currentTime).toBe(27);
    controller.dispose(); controller.ready(); controller.seek(1, true);
    expect(controller.isPlayRequested()).toBe(false);
    expect(audio.currentTime).toBe(27);
    expect(error).not.toHaveBeenCalled();
  });
});

describe("asynchronous native pause/play event ordering", () => {
  // Deliberately model a stricter ordering than browsers normally expose:
  // play() leaves paused=true until its deferred promise resolves. Pause
  // events are delivered in later tasks, never synchronously by pause().
  const make = () => {
    const requests: { resolve: () => void; reject: (error: Error) => void }[] = [];
    let onPause = () => {};
    const audio = {
      src: "/synthetic-recording", load: vi.fn(), paused: false, currentTime: 3121, readyState: 1,
      play: vi.fn(() => new Promise<void>((resolve, reject) => requests.push({
        resolve: () => { audio.paused = false; resolve(); }, reject,
      }))),
      pause: vi.fn(() => {
        const changed = !audio.paused;
        audio.paused = true;
        if (changed) setTimeout(() => onPause(), 0);
      }),
    };
    const paused = vi.fn();
    const error = vi.fn();
    const controller = createNativeAudioController(audio, 7200, error, [
      { src: "/synthetic-recording", startSeconds: 3120, durationSeconds: 7200 },
    ]);
    onPause = () => { void controller.observePause(paused); };
    const flushPauseEvents = () => new Promise<void>((resolve) => setTimeout(resolve, 0));
    const settle = async (index: number) => {
      requests[index]!.resolve();
      await Promise.resolve(); await Promise.resolve();
    };
    return { audio, controller, paused, error, requests, flushPauseEvents, settle };
  };

  it("does not cancel a new play when an internal queued pause arrives after the seek applied", async () => {
    const { audio, controller, paused, flushPauseEvents, settle } = make();
    controller.seek(20, true);
    expect(controller.isPending()).toBe(false);
    expect(audio.paused).toBe(true);
    await flushPauseEvents();
    // This is the exact state in which the former onPause guard called pause().
    expect(controller.isPlayRequested()).toBe(true);
    expect(paused).not.toHaveBeenCalled();
    await settle(0);
    expect(audio.paused).toBe(false);
    expect(controller.isPlayRequested()).toBe(true);
    expect(paused).not.toHaveBeenCalled();
  });

  it("does recognize a later external pause after playback has settled", async () => {
    const { audio, controller, paused, flushPauseEvents, settle } = make();
    controller.seek(20, true);
    await flushPauseEvents(); await settle(0);
    audio.pause();
    await flushPauseEvents();
    expect(controller.isPlayRequested()).toBe(false);
    expect(paused).toHaveBeenCalledOnce();
  });

  it.each([0, 1])("lets explicit user Pause cancel immediately while readyState=%s without waiting for play", async (readyState) => {
    const { audio, controller, paused, error, requests, flushPauseEvents } = make();
    audio.readyState = readyState;
    controller.seek(20, true);
    expect(audio.play).toHaveBeenCalledOnce(); // Initial gesture is not deferred.
    await flushPauseEvents();
    controller.pause();
    expect(controller.isPlayRequested()).toBe(false);
    audio.readyState = 1; controller.ready();
    expect(audio.currentTime).toBe(3140);
    expect(audio.play).toHaveBeenCalledOnce();
    requests[0]!.reject(new Error("interrupted by user pause"));
    await Promise.resolve(); await Promise.resolve();
    expect(paused).not.toHaveBeenCalled(); // Obsolete queued observer is ignored.
    expect(error).not.toHaveBeenCalled();
  });

  it("ignores an obsolete observer/rejection after a newer repeated seek starts", async () => {
    const { audio, controller, paused, error, requests, flushPauseEvents, settle } = make();
    controller.seek(20, true);
    await flushPauseEvents();
    controller.seek(50, true);
    requests[0]!.reject(new Error("superseded"));
    await Promise.resolve(); await Promise.resolve();
    expect(controller.isPlayRequested()).toBe(true);
    expect(paused).not.toHaveBeenCalled(); expect(error).not.toHaveBeenCalled();
    await settle(1);
    expect(audio.currentTime).toBe(3170);
    expect(controller.isPlayRequested()).toBe(true);
  });

  it("keeps the metadata-ready play current when the pre-metadata attempt rejects later", async () => {
    const { audio, controller, paused, error, requests, flushPauseEvents, settle } = make();
    audio.readyState = 0;
    controller.seek(20, true);
    await flushPauseEvents();
    audio.readyState = 1; controller.ready();
    expect(audio.currentTime).toBe(3140);
    expect(audio.play).toHaveBeenCalledTimes(2);
    requests[0]!.reject(new Error("superseded by metadata seek"));
    await Promise.resolve(); await Promise.resolve();
    expect(controller.isPlayRequested()).toBe(true);
    await settle(1);
    expect(audio.paused).toBe(false);
    expect(paused).not.toHaveBeenCalled(); expect(error).not.toHaveBeenCalled();
  });

  it("keeps replay intent after stopping at the endpoint with an older observer waiting", async () => {
    const { audio, controller, paused, error, requests, flushPauseEvents, settle } = make();
    controller.seek(20, true);
    await flushPauseEvents();
    controller.seek(7200, true);
    expect(audio.currentTime).toBe(10320);
    expect(controller.isPlayRequested()).toBe(false);
    controller.seek(0, true);
    requests[0]!.reject(new Error("superseded by replay"));
    await Promise.resolve(); await Promise.resolve();
    await settle(1);
    expect(audio.currentTime).toBe(3120);
    expect(controller.isPlayRequested()).toBe(true);
    expect(paused).not.toHaveBeenCalled(); expect(error).not.toHaveBeenCalled();
  });

  it("reports a current play denial rather than silently cancelling it via onPause", async () => {
    const { controller, error, requests, flushPauseEvents } = make();
    controller.seek(20, true);
    await flushPauseEvents();
    requests[0]!.reject(new Error("autoplay denied"));
    await Promise.resolve(); await Promise.resolve();
    expect(controller.isPlayRequested()).toBe(false);
    expect(error).toHaveBeenCalledOnce();
  });

  it("does not let an obsolete observer touch the endpoint or disposed player", async () => {
    const { audio, controller, paused, error, requests, flushPauseEvents } = make();
    controller.seek(20, true);
    await flushPauseEvents();
    controller.seek(7200, true);
    expect(audio.currentTime).toBe(10320);
    expect(controller.isPlayRequested()).toBe(false);
    controller.dispose();
    requests[0]!.reject(new Error("disposed"));
    await Promise.resolve(); await Promise.resolve();
    expect(controller.isPlayRequested()).toBe(false);
    expect(paused).not.toHaveBeenCalled(); expect(error).not.toHaveBeenCalled();
  });
});


describe("Spotify interruption at a recording seam", () => {
  it("preserves a natural pause-before-ended transition between original files", async () => {
    const audio = { src: "/part-a", load: vi.fn(), paused: false, ended: false, currentTime: 0, readyState: 1,
      play: vi.fn().mockResolvedValue(undefined), pause: vi.fn() };
    const controller = createNativeAudioController(audio, 20, vi.fn(), [
      { src: "/part-a", startSeconds: 0, durationSeconds: 10 },
      { src: "/part-b", startSeconds: 0, durationSeconds: 10 },
    ]);
    controller.seek(9, true); audio.currentTime = 10; audio.paused = true; audio.ended = true;
    const paused = vi.fn(); await controller.observePause(paused);
    expect(paused).not.toHaveBeenCalled();
    expect(controller.isPlayRequested()).toBe(true);
    expect(controller.ended()).toBe(10);
    expect(audio.src).toBe("/part-b");
    controller.ready(); expect(controller.isPlayRequested()).toBe(true);
    // An explicit comparison pause still wins even if the element is ended.
    controller.pause(); await controller.observePause(paused);
    expect(controller.isPlayRequested()).toBe(false);
    expect(paused).toHaveBeenCalledOnce();
  });
  it("does not let a queued ended event restart a paused recording", () => {
    const audio = { src: "/part-a", load: vi.fn(), paused: false, currentTime: 0, readyState: 1,
      play: vi.fn().mockResolvedValue(undefined), pause: vi.fn() };
    const controller = createNativeAudioController(audio, 20, vi.fn(), [
      { src: "/part-a", startSeconds: 0, durationSeconds: 10 },
      { src: "/part-b", startSeconds: 0, durationSeconds: 10 },
    ]);
    controller.seek(9, true); audio.currentTime = 10;
    controller.pause(); audio.paused = true;
    expect(controller.ended()).toBe(10);
    expect(controller.isPlayRequested()).toBe(false);
    expect(audio.src).toBe("/part-a");
    expect(audio.play).toHaveBeenCalledOnce();
    // Resuming after the comparison crosses the seam normally.
    controller.seek(controller.position(), true); controller.ready();
    expect(audio.src).toBe("/part-b");
    expect(controller.isPlayRequested()).toBe(true);
  });
});

describe("warm native resume", () => {
  function setup() {
    const audio = { src: "/part-a", readyState: 4, paused: true, currentTime: 3122.25,
      load: vi.fn(), pause: vi.fn(), play: vi.fn().mockResolvedValue(undefined) };
    const controller = createNativeAudioController(audio, 20, vi.fn(), [
      { src: "/part-a", startSeconds: 3120, durationSeconds: 10 },
      { src: "/part-b", startSeconds: 20, durationSeconds: 10 },
    ]);
    return { audio, controller };
  }
  it("resumes exact paused position without seek, load, or another pause", () => {
    const { audio, controller } = setup();
    const setTime = vi.fn(); let seconds = audio.currentTime;
    Object.defineProperty(audio, "currentTime", { get: () => seconds, set: value => { setTime(value); seconds = value; } });
    controller.resume();
    expect(audio.play).toHaveBeenCalledOnce();
    expect(setTime).not.toHaveBeenCalled(); expect(audio.load).not.toHaveBeenCalled(); expect(audio.pause).not.toHaveBeenCalled();
    expect(controller.position()).toBe(2.25); expect(controller.isPlayRequested()).toBe(true);
  });
  it("preserves a pending cross-file seek rather than resuming the wrong file", () => {
    const { audio, controller } = setup();
    controller.seek(12, false); controller.resume(); controller.ready();
    expect(audio.src).toBe("/part-b"); expect(audio.currentTime).toBe(22); expect(controller.isPlayRequested()).toBe(true);
  });
  it("crosses a file boundary and replays only at the final set endpoint", () => {
    const { audio, controller } = setup(); audio.currentTime = 3130;
    controller.resume(); controller.ready();
    expect(audio.src).toBe("/part-b"); expect(audio.currentTime).toBe(20);
    audio.currentTime = 30; controller.pause(); controller.resume(); controller.ready();
    expect(audio.src).toBe("/part-a"); expect(audio.currentTime).toBe(3120);
  });
  it("applies the source window when Play is the first action", () => {
    const { audio, controller } = setup(); audio.currentTime = 0;
    controller.resume(); expect(audio.currentTime).toBe(3120);
  });
  it("does not revive disposed audio", () => {
    const { audio, controller } = setup(); controller.dispose(); controller.resume();
    expect(audio.play).not.toHaveBeenCalled();
  });
});

it("does not automatically replay an ended recording when the displayed clock was stale", () => {
  const audio = { src: "/recording", readyState: 4, paused: true, currentTime: 0,
    load: vi.fn(), pause: vi.fn(), play: vi.fn().mockResolvedValue(undefined) };
  const controller = createNativeAudioController(audio, 20, vi.fn());
  controller.seek(19.9, true);
  audio.currentTime = 20; // Reaches end before the displayed UI/ended event catches up.
  controller.pause(); audio.play.mockClear();
  controller.resume(false);
  expect(audio.play).not.toHaveBeenCalled(); expect(audio.currentTime).toBe(20);
  controller.resume(); // A subsequent explicit Play may replay.
  expect(audio.play).toHaveBeenCalledOnce(); expect(audio.currentTime).toBe(0);
});
describe("native audio recovery after a dead provider URL", () => {
  const make = () => ({ src: "/synthetic-a", load: vi.fn(), paused: true, currentTime: 0, readyState: 1, play: vi.fn().mockResolvedValue(undefined), pause: vi.fn() });
  it("reloads the same-origin route and resumes at the set position while playing", () => {
    const audio = make(); const c = createNativeAudioController(audio, 20, vi.fn());
    c.seek(7, true); audio.currentTime = 9.5; audio.play.mockClear();
    expect(c.recover()).toBe(true);
    expect(audio.load).toHaveBeenCalledOnce(); expect(audio.src).toBe("/synthetic-a");
    expect(audio.play).toHaveBeenCalledOnce(); expect(c.isPending()).toBe(true); expect(c.position()).toBe(9.5);
    c.ready(); expect(audio.currentTime).toBe(9.5); expect(c.isPlayRequested()).toBe(true);
  });
  it("keeps a paused recording paused and never plays past the end", () => {
    const audio = make(); const c = createNativeAudioController(audio, 20, vi.fn());
    c.seek(4, false); audio.play.mockClear(); c.recover(); expect(audio.play).not.toHaveBeenCalled(); c.ready(); expect(audio.currentTime).toBe(4);
    c.seek(20, true); audio.play.mockClear(); c.recover(); expect(audio.play).not.toHaveBeenCalled(); expect(c.isPlayRequested()).toBe(false);
  });
  it("reloads the active source window of a multi-file set", () => {
    const audio = make();
    const c = createNativeAudioController(audio, 20, vi.fn(), [{ src: "/part-0", startSeconds: 0, durationSeconds: 10 }, { src: "/part-1", startSeconds: 30, durationSeconds: 10 }]);
    c.seek(14, true); audio.readyState = 1; c.ready(); expect(audio.currentTime).toBe(34);
    audio.load.mockClear(); c.recover(); expect(audio.src).toBe("/part-1"); expect(audio.load).toHaveBeenCalledOnce();
    c.ready(); expect(audio.currentTime).toBe(34); expect(c.position()).toBe(14);
  });
  it("does nothing once disposed", () => { const audio = make(); const c = createNativeAudioController(audio, 20, vi.fn()); c.dispose(); audio.load.mockClear(); expect(c.recover()).toBe(false); expect(audio.load).not.toHaveBeenCalled(); });
});

describe("sample-exact windows in a real browser clock", () => {
  // 136279296 / 44100: a mid-file start that Chrome reports rounded to microseconds.
  const start = 136279296 / 44100;
  const segments = [{ src: "/part-a", startSeconds: start, durationSeconds: 60 }, { src: "/part-b", startSeconds: 0, durationSeconds: 60 }];
  const make = () => ({ src: "/part-a", load: vi.fn(), paused: true, ended: false, currentTime: 0, readyState: 1,
    play: vi.fn().mockResolvedValue(undefined), pause: vi.fn() });

  it("does not re-seek a window start that the browser reports rounded down", () => {
    const audio = make(); const c = createNativeAudioController(audio, 120, vi.fn(), segments);
    c.seek(0, false);
    audio.currentTime = Math.floor(start * 1e6) / 1e6;
    audio.pause.mockClear();
    for (let i = 0; i < 50; i += 1) c.tick();
    expect(audio.pause).not.toHaveBeenCalled();
    expect(audio.currentTime).toBe(Math.floor(start * 1e6) / 1e6);
    expect(c.position()).toBe(0);
  });

  it("continues into the next file when the window ends just before its file ends", () => {
    // The browser reaches its own end a few samples later and is already paused
    // when the timeupdate arrives. Play intent must carry across the seam.
    const audio = make(); const c = createNativeAudioController(audio, 120, vi.fn(), segments);
    c.seek(59, true); audio.paused = true; audio.ended = true;
    audio.currentTime = start + 60 + 3 / 44100;
    c.tick();
    expect(audio.src).toBe("/part-b");
    expect(c.isPlayRequested()).toBe(true);
    const calls = audio.play.mock.calls.length;
    c.ready();
    expect(audio.currentTime).toBe(0);
    expect(audio.play.mock.calls.length).toBe(calls + 1);
  });

  it("asks again when a requested play was dropped after a file seam", async () => {
    vi.useFakeTimers();
    try {
      const audio = make(); const c = createNativeAudioController(audio, 120, vi.fn(), segments);
      c.seek(59, true); audio.paused = false; await Promise.resolve();
      audio.currentTime = start + 60; c.tick();
      expect(audio.src).toBe("/part-b");
      c.ready(); await Promise.resolve(); await Promise.resolve();
      const calls = audio.play.mock.calls.length;
      audio.paused = true; // The browser never started the new file.
      c.tick(); vi.advanceTimersByTime(1300); c.tick();
      expect(audio.play.mock.calls.length).toBe(calls + 1);
      c.pause(); vi.advanceTimersByTime(5000); c.tick(); c.tick();
      expect(audio.play.mock.calls.length).toBe(calls + 1);
    } finally { vi.useRealTimers(); }
  });
});
