import { expect, it, vi } from "vitest";
import { createNativeAudioController, locateRecordingTime, spanDuration } from "./playback";
import { yoonCollectionSchema } from "./collection-model.server";
import { fixture } from "./fixtures.test-support";

const span = { recordingId: "synthetic-grisha", startSample: 217628352, endSample: 535148352, sampleRate: 44100 };
it("retains fractional Grisha source bounds and exact integer sample coordinates", () => {
  expect(spanDuration(span)).toBe(7200);
  expect(locateRecordingTime([span], 0)).toMatchObject({ sourceSample: 217628352, sourceSeconds: 217628352 / 44100 });
  expect(locateRecordingTime([span], 7200).sourceSample).toBe(535148352);
  expect(locateRecordingTime([span], 15).sourceSample).toBe(217628352 + 15 * 44100);
  const audio = { src: "/synthetic", load: vi.fn(), paused: true, currentTime: 0, readyState: 1, play: vi.fn().mockResolvedValue(undefined), pause: vi.fn() };
  const c = createNativeAudioController(audio, 7200, vi.fn(), [{ src: "/synthetic", startSeconds: span.startSample / span.sampleRate, durationSeconds: 7200 }]);
  c.seek(15, false);
  expect(audio.currentTime).toBe(span.startSample / span.sampleRate + 15);
  expect(Number.isInteger(audio.currentTime)).toBe(false);
  c.dispose();
});
it("accepts source media with sample-exact Grisha bounds without schema changes", () => {
  const data = structuredClone(fixture);
  const set = data.sets[0]!;
  set.spans = [span];
  set.audio.durationSeconds = 7200;
  set.audio.sources = [{ ...set.audio.sources[0]!, recordingId: span.recordingId }];
  expect(yoonCollectionSchema.parse(data).sets[0]!.spans).toEqual([span]);
});
