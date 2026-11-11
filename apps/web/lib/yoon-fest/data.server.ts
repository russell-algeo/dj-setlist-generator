import "server-only";
import { and, asc, eq, inArray, sql } from "drizzle-orm";
import { unstable_noStore as noStore } from "next/cache";
import type { SessionActor } from "@/lib/auth/session";
import type { ArchiveSetDetail } from "@/lib/archive/types";
import { mapSetTrack, buildTimeline, buildJourneyPoints } from "@/lib/archive/set-projection";
import { getString } from "@/lib/archive/utils";
import { formatDuration } from "@/lib/archive/utils";
import { getDb } from "@/lib/db/client";
import { archiveCollections, archiveCollectionMembers, sets, setMedia, setEntries } from "@/lib/db/schema";
import { assertYoonAccess } from "./access.server";
import { yoonCollectionSchema, type YoonSet, type YoonCollection } from "./collection-model.server";

const record = (value: unknown): Record<string, unknown> => value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};

// Same Neon tables as the public archive. Membership is part of each data query,
// not just a page guard. No shared cache, fixture fallback, or URL-based ownership.
type VersionLookup = { kind: "selected" } | { kind: "slug"; slug: string } | { kind: "asset"; assetId: string };

// No exported all-history collection reader: historical access requires an exact identity.
async function loadYoonVersions(actor: SessionActor, lookup: VersionLookup): Promise<YoonCollection> {
  noStore();
  await assertYoonAccess(actor);
  // A route segment is untrusted text; never let an invalid UUID become a DB error.
  if (lookup.kind === "asset" && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(lookup.assetId)) {
    return { collection: "yoon-fest", revision: "neon", sets: [] };
  }
  const db = getDb();
  const membership = and(eq(archiveCollectionMembers.collectionId, sets.collectionId), eq(archiveCollectionMembers.userId, actor.userId));
  const privateCollection = and(eq(sets.visibility, "private"), eq(archiveCollections.slug, "yoon-fest"));
  const version = sql`app.yoon_version_readable(${sets.id}, ${lookup.kind === "selected"})`;
  const identity = lookup.kind === "slug" ? eq(sets.slug, lookup.slug)
    : lookup.kind === "asset" ? eq(setMedia.id, lookup.assetId) : undefined;
  const rows = await db.select({ id: sets.id, slug: sets.slug, title: sets.title, metadata: sets.metadata, updatedAt: sets.updatedAt,
    audioId: setMedia.id, revision: setMedia.revision, duration: setMedia.durationSeconds,
    contentType: setMedia.contentType, sourceSpans: setMedia.sourceSpans, sources: setMedia.recordingSources })
    .from(sets).innerJoin(archiveCollections, eq(archiveCollections.id, sets.collectionId))
    .innerJoin(archiveCollectionMembers, membership).innerJoin(setMedia, eq(setMedia.setId, sets.id))
    .where(and(privateCollection, version, identity)).orderBy(asc(sets.createdAt), asc(sets.id));
  const entries = rows.length ? await db.select({ setId: setEntries.setId, position: setEntries.position,
    artist: setEntries.displayArtist, title: setEntries.displayTitle, start: setEntries.startTimeSeconds,
    end: setEntries.endTimeSeconds, detectionCount: setEntries.detectionCount, clusterDensity: setEntries.clusterDensity, clusterSpan: setEntries.clusterSpan, confidence: setEntries.confidence, metadata: setEntries.metadata })
    .from(setEntries).innerJoin(sets, eq(sets.id, setEntries.setId))
    .innerJoin(archiveCollections, eq(archiveCollections.id, sets.collectionId))
    .innerJoin(archiveCollectionMembers, membership)
    // Pin entries to the resolved immutable versions, not a second selection snapshot.
    // Released history remains readable if promotion happens between these queries.
    .where(and(privateCollection, inArray(sets.id, rows.map((row) => row.id)),
      sql`app.yoon_version_readable(${sets.id}, false)`))
    .orderBy(asc(setEntries.position)) : [];
  return yoonCollectionSchema.parse({ collection: "yoon-fest", revision: "neon", sets: rows.map((row) => {
    const metadata = record(row.metadata); const mixInfo = record(metadata.mixInfo);
    const coverage = record(metadata.summary).recognitionCoverage;
    return { id: row.id, slug: row.slug, title: row.title,
      performer: typeof mixInfo.artist_name === "string" ? mixInfo.artist_name : "Unknown",
      generatedAt: getString(record(metadata.summary).generated_at) ?? row.updatedAt?.toISOString() ?? null,
      artistProfileImage: getString(mixInfo.artist_profile_image) ?? getString(mixInfo.artist_image),
      boundaryStatus: metadata.boundaryStatus ?? "provisional",
      boundaryNote: metadata.boundaryNote ?? "Recording boundaries have not been reviewed.",
      ...(coverage ? { recognitionCoverage: coverage } : {}),
      spans: row.sourceSpans,
      audio: { assetId: row.audioId, revision: row.revision, durationSeconds: Number(row.duration), contentType: row.contentType, sources: row.sources },
      tracks: entries.filter((entry) => entry.setId === row.id).map((entry) => {
        const presentation = mapSetTrack({ position: entry.position, displayArtist: entry.artist,
          displayTitle: entry.title, startTimeSeconds: entry.start, endTimeSeconds: entry.end ?? Number(row.duration),
          confidence: entry.confidence, detectionCount: entry.detectionCount ?? 0,
          clusterDensity: entry.clusterDensity ?? null, clusterSpan: entry.clusterSpan ?? null,
          entryMetadata: entry.metadata, trackMetadata: {}, trackId: null,
          trackSpotifyUrl: null, trackYoutubeUrl: null, trackDiscogsUrl: null, sourceDeepLink: null });
        // Private recording deep links and recognition evidence must never enter page props.
        presentation.sourceDeepLink = null;
        return { position: entry.position, artist: entry.artist, title: entry.title,
          startSeconds: entry.start, endSeconds: entry.end ?? Number(row.duration), confidence: entry.confidence,
          spotifyUrl: presentation.spotifyUrl, presentation };
      }) };
  }) });
}

export async function loadYoonCollection(actor: SessionActor): Promise<YoonCollection> {
  return loadYoonVersions(actor, { kind: "selected" });
}

export async function getYoonSetByAsset(actor: SessionActor, assetId: string): Promise<YoonSet | null> {
  return (await loadYoonVersions(actor, { kind: "asset", assetId })).sets[0] ?? null;
}

export async function getYoonSets(actor: SessionActor) { return (await loadYoonCollection(actor)).sets; }
export async function getYoonSet(actor: SessionActor, slug: string) {
  return (await loadYoonVersions(actor, { kind: "slug", slug })).sets[0] ?? null;
}

// Explicit projection: never serialize the private source metadata into React props.
export function toYoonSetDetail(set: YoonSet): ArchiveSetDetail {
  const tracks = set.tracks.map((track) => track.presentation ?? mapSetTrack({
    position: track.position, displayArtist: track.artist, displayTitle: track.title,
    startTimeSeconds: track.startSeconds, endTimeSeconds: track.endSeconds, confidence: track.confidence,
    entryMetadata: { spotify_url: track.spotifyUrl }, trackMetadata: {}, trackId: null,
    trackSpotifyUrl: null, trackYoutubeUrl: null, trackDiscogsUrl: null, detectionCount: 0,
    clusterDensity: null, clusterSpan: null, sourceDeepLink: null,
  }));
  const identified = tracks.filter((track) => track.title !== "Unknown Track");
  return {
    id: set.id, slug: set.slug, title: set.title, artistName: set.performer, artists: [],
    heroImageUrl: set.artistProfileImage ?? null, thumbnailUrl: null, sourcePlatform: null, sourceUrl: null,
    sourceLinks: [], embedUrl: null, duration: set.audio.durationSeconds,
    durationFmt: formatDuration(set.audio.durationSeconds),
    // The private importer intentionally inserts identified clusters only. Their
    // proportion of displayed cards is not the proportion of recognized audio.
    recognitionRate: set.recognitionCoverage
      ? 100 * set.recognitionCoverage.matchedWindows / set.recognitionCoverage.expectedWindows : null,
    generatedAt: set.generatedAt ?? null, stats: { totalTracks: tracks.length, identifiedTracks: identified.length,
      highOrMediumTracks: tracks.filter((track) => ["HIGH", "MEDIUM"].includes(track.conf)).length,
      distinctArtists: new Set(identified.map((track) => track.artist)).size },
    highlightedTracks: buildJourneyPoints(tracks).slice(0, 8)
      .flatMap((point) => tracks.filter((track) => track.idx === point.idx)),
    timeline: buildTimeline(tracks, set.audio.durationSeconds),
    tracks, journeyPoints: buildJourneyPoints(tracks),
  };
}
