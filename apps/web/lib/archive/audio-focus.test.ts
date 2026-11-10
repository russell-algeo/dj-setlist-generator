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
