import { eq } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import {
  artists,
  setArtists,
  setEntries,
  sets,
  trackArtists,
  tracks,
} from "@/lib/db/schema";
import {
  detectSourcePlatform,
  hashSuffix,
  makeSlug,
  normalizeText,
} from "@/lib/archive/import-helpers";

export type ArchiveSetPayload = {
  mix_info: Record<string, unknown>;
  metadata: {
    total_tracks?: number;
    uncertain_tracks?: number;
    [key: string]: unknown;
  };
  tracks: Array<Record<string, unknown>>;
};

type DbClient = ReturnType<typeof getDb>;

type PublishSource = "output" | "worker";

type UpsertArchiveSetInput = {
  db?: DbClient;
  payload: ArchiveSetPayload;
  provenance: {
    source: PublishSource;
    relativeJsonPath?: string;
    relativeHtmlPath?: string;
    setRunId?: string;
  };
};

export const upsertArtist = async (
  db: DbClient,
  artistName: string,
  metadata: Record<string, unknown> = {},
) => {
  const normalizedName = normalizeText(artistName);
  const slug = makeSlug(artistName);
  const [existingArtist] = await db.select().from(artists).where(eq(artists.slug, slug)).limit(1);
  const nextImageUrl =
    (metadata.artist_profile_image as string | undefined) ?? existingArtist?.imageUrl ?? null;
  const nextSpotifyArtistUrl =
    (metadata.spotify_artist_profile_url as string | undefined) ??
    existingArtist?.spotifyArtistUrl ??
    null;
  const nextDiscogsArtistUrl =
    (metadata.discogs_artist_profile_url as string | undefined) ??
    existingArtist?.discogsArtistUrl ??
    null;

  await db
    .insert(artists)
    .values({
      slug,
      name: artistName,
      normalizedName,
      metadata,
      imageUrl: nextImageUrl,
      spotifyArtistUrl: nextSpotifyArtistUrl,
      discogsArtistUrl: nextDiscogsArtistUrl,
    })
    .onConflictDoUpdate({
      target: artists.slug,
      set: {
        name: artistName,
        normalizedName,
        metadata,
        imageUrl: nextImageUrl,
        spotifyArtistUrl: nextSpotifyArtistUrl,
        discogsArtistUrl: nextDiscogsArtistUrl,
        updatedAt: new Date(),
      },
    });

  const [artist] = await db.select().from(artists).where(eq(artists.slug, slug)).limit(1);
  return artist;
};

const trackKeyForRow = (row: Record<string, unknown>) => {
  const shazamTrackId = row.shazam_track_id as string | undefined;
  const artist = String(row.artist ?? "");
  const title = String(row.title ?? "");

  if (shazamTrackId) {
    return `shazam:${shazamTrackId}`;
  }

  return `fallback:${normalizeText(`${artist} ${title}`)}`;
};

const upsertTrack = async (db: DbClient, row: Record<string, unknown>) => {
  const artistName = String(row.artist ?? "Unknown");
  const title = String(row.title ?? "Unknown Track");
  const trackKey = trackKeyForRow(row);
  const suffix = hashSuffix(trackKey);
  const slug = makeSlug(`${artistName}-${title}`, suffix);

  await db
    .insert(tracks)
    .values({
      slug,
      title,
      normalizedTitle: normalizeText(title),
      primaryArtistName: artistName,
      shazamTrackId: (row.shazam_track_id as string | undefined) ?? null,
      spotifyUrl: (row.spotify_url as string | undefined) ?? null,
      youtubeUrl: (row.youtube_url as string | undefined) ?? null,
      discogsUrl: (row.discogs_url as string | undefined) ?? null,
      metadata: row,
    })
    .onConflictDoUpdate({
      target: tracks.slug,
      set: {
        title,
        normalizedTitle: normalizeText(title),
        primaryArtistName: artistName,
        shazamTrackId: (row.shazam_track_id as string | undefined) ?? null,
        spotifyUrl: (row.spotify_url as string | undefined) ?? null,
        youtubeUrl: (row.youtube_url as string | undefined) ?? null,
        discogsUrl: (row.discogs_url as string | undefined) ?? null,
        metadata: row,
        updatedAt: new Date(),
      },
    });

  const [track] = await db.select().from(tracks).where(eq(tracks.slug, slug)).limit(1);
  const artist = await upsertArtist(db, artistName);

  await db
    .insert(trackArtists)
    .values({ trackId: track.id, artistId: artist.id, role: "primary" })
    .onConflictDoNothing();

  return track;
};

export const upsertArchiveSet = async ({
  db = getDb(),
  payload,
  provenance,
}: UpsertArchiveSetInput) => {
  const mixInfo = payload.mix_info;
  const setTitle = String(mixInfo.title ?? "Unknown Set");
  const sourceUrl = (mixInfo.url as string | undefined) ?? null;
  const mixArtistName = String(mixInfo.artist_name ?? "").trim();
  const artistName = mixArtistName || null;
  const artist = artistName ? await upsertArtist(db, artistName, mixInfo) : null;
  const proposedSetSlug = makeSlug(setTitle, hashSuffix(sourceUrl ?? setTitle));
  const [existingSet] = sourceUrl
    ? await db.select().from(sets).where(eq(sets.sourceUrl, sourceUrl)).limit(1)
    : [];
  const setSlug = existingSet?.slug ?? proposedSetSlug;
  const totalTracks = Number(payload.metadata.total_tracks ?? payload.tracks.length ?? 0);
  const uncertainTracks = Number(payload.metadata.uncertain_tracks ?? 0);
  const recognitionRate =
    totalTracks > 0 ? (((totalTracks - uncertainTracks) / totalTracks) * 100).toFixed(2) : null;
  const setValues = {
    slug: setSlug,
    title: setTitle,
    normalizedTitle: normalizeText(setTitle),
    sourcePlatform: detectSourcePlatform(sourceUrl),
    sourceUrl,
    durationSeconds: Math.round(Number(mixInfo.duration ?? 0)),
    uploader: (mixInfo.uploader as string | undefined) ?? null,
    imageUrl: (mixInfo.artist_profile_image as string | undefined) ?? null,
    recognitionRate,
    metadata: {
      mixInfo,
      summary: payload.metadata,
      importProvenance: provenance,
    },
  } as const;

  const upsertSet = db.insert(sets).values(setValues);

  if (sourceUrl) {
    await upsertSet.onConflictDoUpdate({
      target: sets.sourceUrl,
      set: { ...setValues, updatedAt: new Date() },
    });
  } else {
    await upsertSet.onConflictDoUpdate({
      target: sets.slug,
      set: { ...setValues, updatedAt: new Date() },
    });
  }

  const [setRecord] = await db
    .select()
    .from(sets)
    .where(sourceUrl ? eq(sets.sourceUrl, sourceUrl) : eq(sets.slug, setSlug))
    .limit(1);

  if (!setRecord) {
    throw new Error(`Failed to upsert set ${setTitle}`);
  }

  if (artist) {
    await db
      .insert(setArtists)
      .values({ setId: setRecord.id, artistId: artist.id, role: "primary" })
      .onConflictDoNothing();
  }

  await db.delete(setEntries).where(eq(setEntries.setId, setRecord.id));

  for (const [index, trackRow] of payload.tracks.entries()) {
    const isUnknown = String(trackRow.artist ?? "") === "Unknown";
    const trackRecord = isUnknown ? null : await upsertTrack(db, trackRow);

    await db.insert(setEntries).values({
      setId: setRecord.id,
      trackId: trackRecord?.id ?? null,
      position: Number(trackRow.position ?? index + 1),
      displayArtist: String(trackRow.artist ?? "Unknown"),
      displayTitle: String(trackRow.title ?? "Unknown Track"),
      startTimeSeconds: Math.round(Number(trackRow.start_time ?? 0)),
      endTimeSeconds:
        trackRow.end_time == null ? null : Math.round(Number(trackRow.end_time)),
      confidence: String(trackRow.confidence ?? "UNCERTAIN"),
      detectionCount: Number(trackRow.detection_count ?? 0),
      clusterDensity:
        trackRow.cluster_density == null ? null : String(trackRow.cluster_density),
      clusterSpan:
        trackRow.cluster_span == null ? null : Number(trackRow.cluster_span),
      sourceDeepLink: (trackRow.source_deep_link as string | undefined) ?? null,
      metadata: trackRow,
    });
  }

  return {
    setId: setRecord.id,
    slug: setRecord.slug,
    affectedArtistSlugs: artist ? [artist.slug] : [],
  };
};
