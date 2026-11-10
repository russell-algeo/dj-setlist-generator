import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { createSetAudioFocus } from "./audio-focus";
import { spotifyPlaybackState } from "./spotify-iframe";

function setup(playing = true) {
  const port = { isSetPlaying: vi.fn(() => playing), pauseSet: vi.fn(), resumeSet: vi.fn() };
  const focus = createSetAudioFocus(port);
  const pauseA = vi.fn(() => focus.stopped("a"));
  const pauseB = vi.fn(() => focus.stopped("b"));
  const closeA = focus.register("a", pauseA);
  const closeB = focus.register("b", pauseB);
  return { focus, port, closeA, closeB, pauseA, pauseB };
}

describe("set and Spotify audio focus", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());
  it("does not pause a set merely for opening or an initial paused event", () => {
    const { focus, port, closeA } = setup();
    focus.stopped("a"); closeA();
    expect(port.pauseSet).not.toHaveBeenCalled();
    expect(port.resumeSet).not.toHaveBeenCalled();
  });
  it("pauses once on playing and resumes once on pause/end", () => {
    const { focus, port } = setup();
    focus.playing("a"); focus.playing("a");
    expect(port.pauseSet).toHaveBeenCalledTimes(1);
    focus.stopped("a"); focus.stopped("a");
    vi.advanceTimersByTime(150);
    expect(port.resumeSet).toHaveBeenCalledTimes(1);
  });
  it("never starts a set that was already paused", () => {
    const { focus, port, closeA } = setup(false);
    focus.playing("a"); closeA();
    expect(port.resumeSet).not.toHaveBeenCalled();
  });
  it("close resumes the interrupted set and ignores removed player callbacks", () => {
    const { focus, port, closeA } = setup();
    focus.playing("a"); closeA(); focus.playing("a");
    expect(port.pauseSet).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(150);
    expect(port.resumeSet).toHaveBeenCalledTimes(1);
  });
  it("switches previews without resuming between them or on a late old pause", () => {
    const { focus, port, closeA, pauseA } = setup();
    focus.playing("a"); focus.playing("b");
    expect(pauseA).toHaveBeenCalledOnce();
    closeA(); focus.stopped("a");
    expect(port.resumeSet).not.toHaveBeenCalled();
    focus.stopped("b");
    vi.advanceTimersByTime(150);
    expect(port.resumeSet).toHaveBeenCalledOnce();
  });
  it("explicit pause/play/seek discards the pending automatic resume", () => {
    const { focus, port, pauseA, closeA } = setup();
    focus.playing("a"); focus.setIntent(); closeA();
    expect(pauseA).toHaveBeenCalledOnce();
    expect(port.resumeSet).not.toHaveBeenCalled();
  });
  it("stops previews on navigation/unmount without waking the old set", () => {
    const { focus, port, closeA, pauseA } = setup();
    focus.playing("a"); focus.reset(); closeA();
    expect(pauseA).toHaveBeenCalledOnce();
    expect(port.resumeSet).not.toHaveBeenCalled();
    focus.dispose(); focus.playing("b");
    expect(port.pauseSet).toHaveBeenCalledTimes(1);
  });
  it("guards a late source PLAY until paused then allows embedded user takeover", () => {
    const { focus, port, pauseA } = setup();
    focus.playing("a");
    expect(focus.guardSetPlayback()).toBe(true);
    expect(port.pauseSet).toHaveBeenCalledTimes(2);
    focus.setPaused();
    expect(focus.guardSetPlayback()).toBe(false);
    expect(pauseA).toHaveBeenCalledOnce();
    focus.stopped("a");
    expect(port.resumeSet).not.toHaveBeenCalled();
  });
  it("ignores stale Spotify playing updates while a programmatic pause is pending", () => {
    const { focus, port } = setup();
    const pause = vi.fn(); focus.register("a", pause);
    focus.playing("a"); focus.setPaused(); focus.setIntent();
    focus.playing("a");
    expect(port.pauseSet).toHaveBeenCalledTimes(1);
    expect(pause).toHaveBeenCalledOnce();
    focus.stopped("a"); focus.playing("a");
    expect(port.pauseSet).toHaveBeenCalledTimes(2);
  });
  it("does not let a queued old Spotify update steal a new preview's focus", () => {
    const { focus, port } = setup();
    focus.register("a", vi.fn());
    focus.playing("a"); focus.setPaused(); focus.playing("b"); focus.playing("a");
    expect(port.pauseSet).toHaveBeenCalledTimes(2);
    focus.stopped("a");
    expect(port.resumeSet).not.toHaveBeenCalled();
    focus.stopped("b"); vi.advanceTimersByTime(150);
    expect(port.resumeSet).toHaveBeenCalledOnce();
  });
  it("preserves an outstanding source pause acknowledgement across previews", () => {
    const { focus, port, pauseB } = setup();
    focus.playing("a");
    port.isSetPlaying.mockReturnValue(false);
    focus.playing("b");
    expect(focus.guardSetPlayback()).toBe(true);
    expect(pauseB).not.toHaveBeenCalled();
    focus.setPaused();
    expect(focus.guardSetPlayback()).toBe(false);
    expect(pauseB).toHaveBeenCalledOnce();
  });
  it("coalesces Spotify's old-pause-before-new-play handover", () => {
    const { focus, port } = setup();
    focus.playing("a"); focus.stopped("a");
    port.isSetPlaying.mockReturnValue(false);
    focus.playing("b"); vi.advanceTimersByTime(150);
    expect(port.resumeSet).not.toHaveBeenCalled();
    focus.stopped("b"); vi.advanceTimersByTime(150);
    expect(port.resumeSet).toHaveBeenCalledOnce();
  });
  it("lets a user start an initially paused embedded set", () => {
    const { focus, pauseA, port } = setup(false);
    focus.playing("a");
    expect(focus.guardSetPlayback()).toBe(false);
    expect(pauseA).toHaveBeenCalledOnce();
    vi.advanceTimersByTime(150);
    expect(port.resumeSet).not.toHaveBeenCalled();
  });
  it("cancels a scheduled resume on user action or navigation", () => {
    const { focus, port } = setup();
    focus.playing("a"); focus.stopped("a"); focus.setIntent();
    vi.advanceTimersByTime(150);
    expect(port.resumeSet).not.toHaveBeenCalled();
    focus.playing("a"); focus.stopped("a"); focus.reset();
    vi.advanceTimersByTime(150);
    expect(port.resumeSet).not.toHaveBeenCalled();
  });
  it("supports repeated listening comparisons", () => {
    const { focus, port } = setup();
    for (let i = 0; i < 3; i++) { focus.playing("a"); focus.stopped("a"); vi.advanceTimersByTime(150); }
    expect(port.pauseSet).toHaveBeenCalledTimes(3);
    expect(port.resumeSet).toHaveBeenCalledTimes(3);
  });
});

describe("documented Spotify playback state", () => {
  const data = { isPaused: false, isBuffering: false, position: 100, duration: 30000 };
  it("recognizes playing, pause and natural preview completion", () => {
    expect(spotifyPlaybackState({ data })).toBe("playing");
    expect(spotifyPlaybackState({ data: { ...data, isPaused: true } })).toBe("stopped");
    expect(spotifyPlaybackState({ data: { ...data, position: 30000 } })).toBe("stopped");
  });
  it("never treats temporary buffering as a user pause", () => {
    expect(spotifyPlaybackState({ data: { ...data, isPaused: true, isBuffering: true } })).toBe("buffering");
  });
  it("ignores invalid payloads rather than inventing playback", () => {
    expect(spotifyPlaybackState({ data: {} } as never)).toBeNull();
  });
});

describe("low-latency handoff without overlapping audio", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());
  it("resumes synchronously after the only preview reports stopped", () => {
    const { focus, port, closeB } = setup(); closeB();
    focus.playing("a"); focus.stopped("a");
    expect(port.resumeSet).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });
  it("resumes synchronously when the only active preview is destroyed", () => {
    const { focus, port, closeA, closeB } = setup(); closeB();
    focus.playing("a"); closeA();
    expect(port.resumeSet).toHaveBeenCalledOnce();
  });
  it("waits for actual Spotify silence on direct Play, then skips the handover timer", () => {
    const { focus, port } = setup();
    const pause = vi.fn(); focus.register("a", pause);
    focus.playing("a"); const play = vi.fn();
    focus.requestSetPlayback(play);
    expect(pause).toHaveBeenCalledOnce();
    expect(play).not.toHaveBeenCalled();
    focus.playing("a"); // delayed update from the requested pause
    expect(port.pauseSet).toHaveBeenCalledOnce();
    focus.stopped("a");
    expect(play).toHaveBeenCalledOnce();
    expect(port.resumeSet).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });
  it("direct Play needs no wait if Spotify was already stopped", () => {
    const { focus } = setup(false); const play = vi.fn();
    focus.requestSetPlayback(play); expect(play).toHaveBeenCalledOnce();
  });
  it.each(["setIntent", "reset", "dispose"] as const)("%s cancels a return still awaiting Spotify", (action) => {
    const { focus } = setup(); focus.register("a", vi.fn());
    focus.playing("a"); const play = vi.fn(); focus.requestSetPlayback(play);
    focus[action](); focus.stopped("a");
    expect(play).not.toHaveBeenCalled();
  });
  it("repeated Play replaces, rather than duplicates, the pending request", () => {
    const { focus } = setup(); focus.register("a", vi.fn()); focus.playing("a");
    const old = vi.fn(), latest = vi.fn();
    focus.requestSetPlayback(old); focus.requestSetPlayback(latest); focus.stopped("a");
    expect(old).not.toHaveBeenCalled(); expect(latest).toHaveBeenCalledOnce();
  });
  it("closing the paused preview satisfies an explicit pending return", () => {
    const { focus } = setup(); const close = focus.register("a", vi.fn());
    focus.playing("a"); const play = vi.fn(); focus.requestSetPlayback(play); close();
    expect(play).toHaveBeenCalledOnce();
  });
  it("a later different Spotify preview cancels the pending direct Play", () => {
    const { focus } = setup(); focus.register("a", vi.fn());
    focus.playing("a"); const play = vi.fn(); focus.requestSetPlayback(play);
    focus.playing("b"); focus.stopped("a");
    expect(play).not.toHaveBeenCalled();
  });
});

describe("reviewed delayed acknowledgement races", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());
  function asynchronousPreview() {
    const state = setup();
    state.port.pauseSet.mockImplementation(() => state.port.isSetPlaying.mockReturnValue(false));
    const closeA = state.focus.register("a", vi.fn());
    state.focus.playing("a"); state.focus.setPaused(); state.focus.playing("b");
    return { ...state, closeA };
  }
  it("closing the new preview waits for the previous preview to acknowledge pause", () => {
    const { focus, port, closeB } = asynchronousPreview();
    closeB(); expect(port.resumeSet).not.toHaveBeenCalled();
    focus.stopped("a"); expect(port.resumeSet).toHaveBeenCalledOnce();
    focus.stopped("a"); vi.runAllTimers(); expect(port.resumeSet).toHaveBeenCalledOnce();
  });
  it("even an expired handover timer cannot overlap an unacknowledged preview", () => {
    const { focus, port } = asynchronousPreview();
    focus.stopped("b"); vi.advanceTimersByTime(150);
    expect(port.resumeSet).not.toHaveBeenCalled();
    focus.stopped("a"); expect(port.resumeSet).toHaveBeenCalledOnce();
  });
  it("destroying the last pending preview safely releases the automatic return", () => {
    const { port, closeA, closeB } = asynchronousPreview();
    closeB();
    expect(port.resumeSet).not.toHaveBeenCalled(); closeA();
    expect(port.resumeSet).toHaveBeenCalledOnce();
  });
  it("a source embedded Play then Pause cancels the old automatic timer", () => {
    const { focus, port } = setup();
    focus.playing("a"); focus.setPaused(); focus.stopped("a");
    expect(focus.guardSetPlayback()).toBe(false);
    focus.setPaused(); vi.advanceTimersByTime(150);
    expect(port.resumeSet).not.toHaveBeenCalled();
  });
  it("a stale source Play before its pause acknowledgement keeps the return pending", () => {
    const { focus, port } = setup();
    focus.playing("a"); focus.stopped("a");
    expect(focus.guardSetPlayback()).toBe(true);
    focus.setPaused(); vi.advanceTimersByTime(150);
    expect(port.resumeSet).toHaveBeenCalledOnce();
  });
  it("an embedded user takeover waits for Spotify silence, then resumes exactly once", () => {
    const { focus, port } = setup(); focus.register("a", vi.fn());
    focus.playing("a"); focus.setPaused();
    expect(focus.guardSetPlayback()).toBe(true);
    expect(port.resumeSet).not.toHaveBeenCalled();
    focus.stopped("a"); expect(port.resumeSet).toHaveBeenCalledOnce();
  });
});

it("never manufactures a return from a stale source Play after explicit Pause", () => {
  const { focus, port } = setup(); focus.register("a", vi.fn());
  focus.playing("a"); // Source pause is still unacknowledged.
  focus.setIntent(); // User explicitly pauses.
  expect(focus.guardSetPlayback()).toBe(true); // Old source PLAY was queued.
  focus.setPaused(); focus.stopped("a");
  expect(port.resumeSet).not.toHaveBeenCalled();
});

it("preserves an explicit pending seek while a stale source Play arrives", () => {
  const { focus, port } = setup(); focus.register("a", vi.fn());
  focus.playing("a"); focus.setPaused();
  const seek = vi.fn(); focus.requestSetPlayback(seek);
  expect(focus.guardSetPlayback()).toBe(true);
  focus.stopped("a");
  expect(seek).toHaveBeenCalledOnce(); expect(port.resumeSet).not.toHaveBeenCalled();
});
