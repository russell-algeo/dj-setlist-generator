import "server-only";
import { and, asc, eq } from "drizzle-orm";
import { unstable_noStore as noStore } from "next/cache";
import type { SessionActor } from "@/lib/auth/session";
import type { ArchiveSetDetail } from "@/lib/archive/types";
import { formatDuration } from "@/lib/archive/utils";
import { getDb } from "@/lib/db/client";
import { archiveCollections, archiveCollectionMembers, sets, setMedia, setEntries } from "@/lib/db/schema";
import { assertYoonAccess } from "./access.server";
import { yoonCollectionSchema, type YoonSet, type YoonCollection } from "./collection-model.server";

const record = (value: unknown): Record<string, unknown> => value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};

// Same Neon tables as the public archive. Membership is part of each data query,
// not just a page guard. No shared cache, fixture fallback, or URL-based ownership.
export async function loadYoonCollection(actor: SessionActor): Promise<YoonCollection> {
  noStore();
  await assertYoonAccess(actor);
  const db = getDb();
  const membership = and(eq(archiveCollectionMembers.collectionId, sets.collectionId), eq(archiveCollectionMembers.userId, actor.userId));
  const privateCollection = and(eq(sets.visibility, "private"), eq(archiveCollections.slug, "yoon-fest"));
  const rows = await db.select({ id: sets.id, slug: sets.slug, title: sets.title, metadata: sets.metadata,
    audioId: setMedia.id, revision: setMedia.revision, duration: setMedia.durationSeconds,
    contentType: setMedia.contentType, sourceSpans: setMedia.sourceSpans, sources: setMedia.recordingSources })
    .from(sets).innerJoin(archiveCollections, eq(archiveCollections.id, sets.collectionId))
    .innerJoin(archiveCollectionMembers, membership).innerJoin(setMedia, eq(setMedia.setId, sets.id))
    .where(privateCollection).orderBy(asc(sets.createdAt), asc(sets.id));
  const entries = rows.length ? await db.select({ setId: setEntries.setId, position: setEntries.position,
    artist: setEntries.displayArtist, title: setEntries.displayTitle, start: setEntries.startTimeSeconds,
    end: setEntries.endTimeSeconds, confidence: setEntries.confidence, metadata: setEntries.metadata })
    .from(setEntries).innerJoin(sets, eq(sets.id, setEntries.setId))
    .innerJoin(archiveCollections, eq(archiveCollections.id, sets.collectionId))
    .innerJoin(archiveCollectionMembers, membership).where(privateCollection)
    .orderBy(asc(setEntries.position)) : [];
  return yoonCollectionSchema.parse({ collection: "yoon-fest", revision: "neon", sets: rows.map((row) => {
    const metadata = record(row.metadata); const mixInfo = record(metadata.mixInfo);
    return { id: row.id, slug: row.slug, title: row.title,
      performer: typeof mixInfo.artist_name === "string" ? mixInfo.artist_name : "Unknown",
      boundaryStatus: metadata.boundaryStatus ?? "provisional",
      boundaryNote: metadata.boundaryNote ?? "Recording boundaries have not been reviewed.",
      spans: row.sourceSpans,
      audio: { assetId: row.audioId, revision: row.revision, durationSeconds: Number(row.duration), contentType: row.contentType, sources: row.sources },
      tracks: entries.filter((entry) => entry.setId === row.id).map((entry) => ({ position: entry.position,
        artist: entry.artist, title: entry.title, startSeconds: entry.start, endSeconds: entry.end ?? Number(row.duration),
        confidence: entry.confidence, spotifyUrl: record(entry.metadata).spotify_url ?? null })) };
  }) });
}

export async function getYoonSets(actor: SessionActor) { return (await loadYoonCollection(actor)).sets; }
export async function getYoonSet(actor: SessionActor, slug: string) {
  return (await getYoonSets(actor)).find((set) => set.slug === slug) ?? null;
}

// Explicit projection: never serialize the private source metadata into React props.
export function toYoonSetDetail(set: YoonSet): ArchiveSetDetail {
  const tracks = set.tracks.map((track) => ({
    idx: track.position, artist: track.artist, title: track.title, start: track.startSeconds,
    end: track.endSeconds, startFmt: formatDuration(track.startSeconds), endFmt: formatDuration(track.endSeconds),
    conf: track.confidence, albumArt: null, previewUrl: null, bpm: null, energy: null,
    dance: null, key: null, genres: [], detailGenres: [], label: null, labelUrl: null,
    spotifyUrl: track.spotifyUrl, youtubeUrl: null, discogsUrl: null, detectionCount: 0,
    clusterDensity: null, clusterSpan: null, sourceDeepLink: null,
  }));
  const identified = tracks.filter((track) => track.title !== "Unknown Track");
  return {
    id: set.id, slug: set.slug, title: set.title, artistName: set.performer, artists: [],
    heroImageUrl: null, thumbnailUrl: null, sourcePlatform: null, sourceUrl: null,
    sourceLinks: [], embedUrl: null, duration: set.audio.durationSeconds,
    durationFmt: formatDuration(set.audio.durationSeconds),
    recognitionRate: tracks.length ? identified.length / tracks.length * 100 : null,
    generatedAt: null, stats: { totalTracks: tracks.length, identifiedTracks: identified.length,
      highOrMediumTracks: tracks.filter((track) => ["HIGH", "MEDIUM"].includes(track.conf)).length,
      distinctArtists: new Set(identified.map((track) => track.artist)).size },
    highlightedTracks: [], timeline: tracks.map((track) => ({ idx: track.idx,
      leftPct: 100 * track.start / set.audio.durationSeconds,
      widthPct: 100 * (track.end - track.start) / set.audio.durationSeconds,
      conf: track.conf, label: `${track.artist} - ${track.title}`, timeRange: `${track.startFmt} - ${track.endFmt}` })),
    tracks, journeyPoints: [],
  };
}
