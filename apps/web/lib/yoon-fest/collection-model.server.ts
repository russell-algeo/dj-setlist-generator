import "server-only";
import { z } from "zod";
import { dropboxPlaybackUrl } from "./dropbox-source.server";
import { spanDuration } from "./playback";

const spotifyTrackUrl = z.string().url().regex(/^https:\/\/open\.spotify\.com\/track\/[A-Za-z0-9]+(?:\?.*)?$/);
const recordingSpan = z.object({
  recordingId: z.string().min(1), startSample: z.number().int().nonnegative(),
  endSample: z.number().int().positive(), sampleRate: z.number().int().positive(),
}).strict();
const track = z.object({
  position: z.number().int().positive(), artist: z.string().min(1), title: z.string().min(1),
  startSeconds: z.number().finite().nonnegative(), endSeconds: z.number().finite().positive(),
  confidence: z.enum(["HIGH", "MEDIUM", "LOW", "UNCERTAIN"]),
  spotifyUrl: spotifyTrackUrl.nullable(),
}).strict();
const set = z.object({
  id: z.string().uuid(), slug: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/),
  title: z.string().min(1), performer: z.string().min(1),
  boundaryStatus: z.enum(["provisional", "reviewed"]), boundaryNote: z.string().min(1),
  spans: z.array(recordingSpan).min(1),
  audio: z.object({ assetId: z.string().uuid(), revision: z.string().min(1), durationSeconds: z.number().finite().positive(),
    contentType: z.enum(["audio/flac", "audio/mp4", "audio/wav", "audio/mpeg"]),
    sources: z.array(z.object({ recordingId: z.string().min(1), url: z.string().refine((value) => Boolean(dropboxPlaybackUrl(value)), "Invalid Dropbox file URL").transform((value) => dropboxPlaybackUrl(value)!) }).strict()).min(1), }).strict(),
  tracks: z.array(track),
}).strict();
export const yoonCollectionSchema = z.object({
  collection: z.literal("yoon-fest"), revision: z.string().min(1), sets: z.array(set),
}).strict().superRefine((value, ctx) => {
  for (const key of ["id", "slug"] as const) {
    if (new Set(value.sets.map((entry) => entry[key])).size !== value.sets.length) ctx.addIssue({ code: "custom", message: `Duplicate set ${key}` });
  }
  if (new Set(value.sets.map((entry) => entry.audio.assetId)).size !== value.sets.length) ctx.addIssue({ code: "custom", message: "Duplicate audio identity" });
  for (const entry of value.sets) {
    try {
      if (new Set(entry.audio.sources.map((source) => source.recordingId)).size !== entry.audio.sources.length ||
        entry.spans.some((span) => !entry.audio.sources.some((source) => source.recordingId === span.recordingId))) throw new Error("Missing or duplicate recording source");
      const duration = entry.spans.reduce((sum, span) => sum + spanDuration(span), 0);
      if (Math.abs(duration - entry.audio.durationSeconds) > 0.25) throw new Error("Derivative duration differs from source spans");
      const positions = entry.tracks.map((item) => item.position);
      if (new Set(positions).size !== positions.length) throw new Error("Duplicate track position");
      let previousStart = -1;
      for (const item of entry.tracks) {
        if (item.startSeconds < previousStart || item.endSeconds <= item.startSeconds || item.endSeconds > entry.audio.durationSeconds) throw new Error("Invalid track timeline");
        previousStart = item.startSeconds;
      }
    } catch (error) { ctx.addIssue({ code: "custom", message: (error as Error).message }); }
  }
});
export type YoonCollection = z.infer<typeof yoonCollectionSchema>;
export type YoonSet = YoonCollection["sets"][number];

