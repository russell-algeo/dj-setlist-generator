import { eq } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import {
  artists,
  setArtists,
  setEntries,
  setSourceLinks,
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
import { resolveSetSpecificImageUrl } from "@/lib/archive/set-images";

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

type NormalizedSourceLink = {
  durationSeconds: number | null;
  isPrimary: boolean;
  matchConfidence: string | null;
  metadata: Record<string, unknown>;
  platform: string;
  title: string | null;
  url: string;
};

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

const getString = (value: unknown) =>
  typeof value === "string" && value.trim().length > 0 ? value.trim() : null;

const getNumber = (value: unknown) => {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim().length > 0) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
};

const getBoolean = (value: unknown) => (typeof value === "boolean" ? value : null);

const normalizeSourceLink = (
  value: unknown,
  fallback: {
    durationSeconds: number | null;
    isPrimary: boolean;
    platform: string | null;
    title: string | null;
  },
): NormalizedSourceLink | null => {
  const record = asRecord(value);
  const url = getString(record.url ?? record.source_url ?? record.sourceUrl);
  if (!url) {
    return null;
  }

  const durationSeconds =
    getNumber(record.duration_seconds ?? record.durationSeconds) ?? fallback.durationSeconds;
  const matchConfidence = getNumber(record.match_confidence ?? record.matchConfidence);
  const platform = (
    getString(record.platform ?? record.source_platform ?? record.sourcePlatform) ??
    fallback.platform ??
    detectSourcePlatform(url) ??
    "unknown"
  ).toLowerCase();

  return {
    durationSeconds: durationSeconds == null ? null : Math.round(durationSeconds),
    isPrimary: getBoolean(record.is_primary ?? record.isPrimary) ?? fallback.isPrimary,
    matchConfidence: matchConfidence == null ? null : matchConfidence.toFixed(4),
    metadata: asRecord(record.metadata),
    platform,
    title: getString(record.title ?? record.source_title ?? record.sourceTitle) ?? fallback.title,
    url,
  };
};

const buildSourceLinks = ({
  durationSeconds,
  mixInfo,
  sourcePlatform,
  sourceUrl,
  setTitle,
}: {
  durationSeconds: number | null;
  mixInfo: Record<string, unknown>;
  sourcePlatform: string | null;
  sourceUrl: string | null;
  setTitle: string;
}) => {
  const sourceLinksInput = Array.isArray(mixInfo.source_links)
    ? mixInfo.source_links
    : Array.isArray(mixInfo.sourceLinks)
      ? mixInfo.sourceLinks
      : [];
  const links: NormalizedSourceLink[] = [];

  if (sourceUrl) {
    links.push({
      durationSeconds,
      isPrimary: true,
      matchConfidence: "1.0000",
      metadata: { source: "canonical" },
      platform: sourcePlatform ?? detectSourcePlatform(sourceUrl) ?? "unknown",
      title: setTitle,
      url: sourceUrl,
    });
  }

  for (const sourceLinkInput of sourceLinksInput) {
    const normalized = normalizeSourceLink(sourceLinkInput, {
      durationSeconds,
      isPrimary: false,
      platform: null,
      title: setTitle,
    });
    if (normalized) {
      links.push(normalized);
    }
  }

  const deduped = new Map<string, NormalizedSourceLink>();
  for (const link of links) {
    const key = `${link.platform}:${link.url}`;
    const existing = deduped.get(key);
    deduped.set(key, {
      ...link,
      isPrimary: Boolean(existing?.isPrimary || link.isPrimary),
      metadata: {
        ...(existing?.metadata ?? {}),
        ...link.metadata,
      },
    });
  }

  return [...deduped.values()];
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
  const durationSeconds = Math.round(Number(mixInfo.duration ?? 0));
  const sourcePlatform = detectSourcePlatform(sourceUrl);
  const recognitionRate =
    totalTracks > 0 ? (((totalTracks - uncertainTracks) / totalTracks) * 100).toFixed(2) : null;
  const setValues = {
    slug: setSlug,
    title: setTitle,
    normalizedTitle: normalizeText(setTitle),
    sourcePlatform,
    sourceUrl,
    durationSeconds,
    uploader: (mixInfo.uploader as string | undefined) ?? null,
    imageUrl: resolveSetSpecificImageUrl(mixInfo),
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

  const sourceLinks = buildSourceLinks({
    durationSeconds,
    mixInfo,
    sourcePlatform,
    sourceUrl,
    setTitle,
  });
  for (const sourceLink of sourceLinks) {
    await db
      .insert(setSourceLinks)
      .values({
        setId: setRecord.id,
        platform: sourceLink.platform,
        url: sourceLink.url,
        title: sourceLink.title,
        durationSeconds: sourceLink.durationSeconds,
        isPrimary: sourceLink.isPrimary,
        matchConfidence: sourceLink.matchConfidence,
        metadata: sourceLink.metadata,
      })
      .onConflictDoUpdate({
        target: [
          setSourceLinks.setId,
          setSourceLinks.platform,
          setSourceLinks.url,
        ],
        set: {
          title: sourceLink.title,
          durationSeconds: sourceLink.durationSeconds,
          isPrimary: sourceLink.isPrimary,
          matchConfidence: sourceLink.matchConfidence,
          metadata: sourceLink.metadata,
          updatedAt: new Date(),
        },
      });
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
