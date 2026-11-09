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
  it("waits for metadata, applying only latest cross-file seek", () => { const audio = make(); const c = createNativeAudioController(audio, 20, vi.fn()); c.seek(9, true); c.seek(12, false); expect(audio.play).not.toHaveBeenCalled(); expect(audio.currentTime).toBe(0); audio.readyState = 1; c.ready(); expect(audio.currentTime).toBe(12); expect(audio.play).not.toHaveBeenCalled(); });
  it("uses actual play/pause and clamps endpoints", () => { const audio = make(); audio.readyState = 1; const c = createNativeAudioController(audio, 20, vi.fn()); c.seek(99, true); expect(audio.currentTime).toBe(20); expect(audio.play).toHaveBeenCalledOnce(); c.seek(4, false); expect(audio.currentTime).toBe(4); expect(audio.play).toHaveBeenCalledOnce(); c.pause(); expect(audio.pause).toHaveBeenCalled(); });
  it("ignores stale rejection after newer seek", async () => { const audio = make(); audio.readyState = 1; let reject!: (error: Error) => void; audio.play.mockReturnValue(new Promise((_, fail) => { reject = fail; })); const error = vi.fn(); const c = createNativeAudioController(audio, 20, error); c.seek(2, true); c.seek(12, false); reject(new Error("interrupted")); await Promise.resolve(); expect(error).not.toHaveBeenCalled(); });
  it("reports current autoplay denial and ignores disposed player", async () => { const audio = make(); audio.readyState = 1; audio.play.mockRejectedValue(new Error("autoplay")); const error = vi.fn(); const c = createNativeAudioController(audio, 20, error); c.seek(2, true); await Promise.resolve(); expect(error).toHaveBeenCalledOnce(); c.dispose(); c.seek(12, true); expect(audio.currentTime).toBe(2); });
});

describe("original recording windows", () => {
  const segments = [{ src: "/part-a", startSeconds: 52 * 60, durationSeconds: 10 }, { src: "/part-b", startSeconds: 20, durationSeconds: 10 }];
  const make = () => ({ src: "/part-a", load: vi.fn(), paused: true, currentTime: 0, readyState: 1, play: vi.fn().mockResolvedValue(undefined), pause: vi.fn() });
  it("offsets playback into the original file without downloading or transcoding it", () => { const audio = make(); const c = createNativeAudioController(audio, 20, vi.fn(), segments); c.seek(2, false); expect(audio.currentTime).toBe(52 * 60 + 2); expect(c.position()).toBe(2); });
  it("seeks across files and waits for the new metadata", () => { const audio = make(); const c = createNativeAudioController(audio, 20, vi.fn(), segments); c.seek(12, true); expect(audio.src).toBe("/part-b"); expect(audio.load).toHaveBeenCalledOnce(); expect(audio.play).not.toHaveBeenCalled(); c.ready(); expect(audio.currentTime).toBe(22); expect(c.position()).toBe(12); expect(audio.play).toHaveBeenCalledOnce(); });
  it("switches naturally at the set seam and stops at the reviewed end", () => { const audio = make(); audio.paused = false; const c = createNativeAudioController(audio, 20, vi.fn(), segments); audio.currentTime = 52 * 60 + 10; expect(c.tick()).toBe(10); expect(audio.src).toBe("/part-b"); c.ready(); audio.currentTime = 30; expect(c.tick()).toBe(20); expect(audio.currentTime).toBe(30); expect(audio.pause).toHaveBeenCalled(); });
  it("replaces a pending cross-file seek with the latest target", () => { const audio = make(); const c = createNativeAudioController(audio, 20, vi.fn(), segments); c.seek(12, true); c.seek(3, false); expect(audio.src).toBe("/part-a"); c.ready(); expect(audio.currentTime).toBe(52 * 60 + 3); expect(audio.play).not.toHaveBeenCalled(); });
  it("clamps native scrubbing outside the approved source window", () => { const audio = make(); const c = createNativeAudioController(audio, 20, vi.fn(), segments); audio.currentTime = 0; expect(c.tick()).toBe(0); expect(audio.currentTime).toBe(52 * 60); });
});
