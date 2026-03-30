import "server-only";

import { unstable_cache } from "next/cache";
import {
  and,
  asc,
  count,
  countDistinct,
  desc,
  eq,
  inArray,
  isNotNull,
  ne,
  or,
  sql,
} from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import {
  artists,
  setArtists,
  setEntries,
  setRuns,
  sets,
  submissions,
  tracks,
} from "@/lib/db/schema";
import type {
  ArchiveArtistAtlasTrack,
  ArchiveArtistSet,
  ArchiveArtistSummary,
  ArchiveConfidence,
  ArchiveHomeBaseSummary,
  ArchiveHomeConnection,
  ArchiveHomeConnectionsResponse,
  ArchiveHomeSetCard,
  ArchiveJourneyPoint,
  ArchiveRecurringTrack,
  ArchiveSetDetail,
  ArchiveSetTimelineSegment,
  ArchiveSetTrack,
} from "@/lib/archive/types";
import {
  asRecord,
  buildArchiveEmbed,
  buildTrackKey,
  buildYouTubeThumbnail,
  formatCompactDuration,
  formatDuration,
  getNumber,
  getString,
  getStringArray,
  normalizeArchiveConfidence,
} from "@/lib/archive/utils";

// Archive pages are projected from normalized rows at runtime; whole-page HTML is never read from Neon.
const ARCHIVE_TAGS = {
  artist: (slug: string) => `archive:artist:${slug}`,
  connections: "archive:home-connections",
  home: "archive:home",
  legacy: (pagePath: string) => `archive:legacy:${pagePath}`,
  lists: "archive:lists",
  set: (slug: string) => `archive:set:${slug}`,
} as const;

const emptyConfidenceCounts = (): Record<ArchiveConfidence, number> => ({
  HIGH: 0,
  MEDIUM: 0,
  LOW: 0,
  UNCERTAIN: 0,
});

const incrementConfidence = (
  counts: Record<ArchiveConfidence, number>,
  confidence: ArchiveConfidence,
) => {
  counts[confidence] += 1;
};

const percent = (value: number, total: number) =>
  total > 0 ? Math.max(0, Math.min(100, (value / total) * 100)) : 0;

const EXCLUDED_ARCHIVE_GENRES = new Set(["House"]);

const formatArchiveGenre = (value: string) =>
  value
    .trim()
    .toLowerCase()
    .replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
const mapSetTrack = (row: {
  position: number;
  displayArtist: string;
  displayTitle: string;
  startTimeSeconds: number;
  endTimeSeconds: number | null;
  confidence: string;
  detectionCount: number;
  clusterDensity: string | null;
  clusterSpan: number | null;
  sourceDeepLink: string | null;
  entryMetadata: unknown;
  trackId: string | null;
  trackMetadata: unknown;
  trackSpotifyUrl: string | null;
  trackYoutubeUrl: string | null;
  trackDiscogsUrl: string | null;
}): ArchiveSetTrack => {
  const entryMetadata = asRecord(row.entryMetadata);
  const trackMetadata = asRecord(row.trackMetadata);
  const merged = {
    ...trackMetadata,
    ...entryMetadata,
  };
  const confidence = normalizeArchiveConfidence(row.confidence);
  const detailGenres = Array.from(
    new Set(
      [
        ...getStringArray(merged.discogs_styles),
        ...getStringArray(merged.discogs_genres),
        ...getStringArray(merged.spotify_genres),
      ].filter((genre) => genre.trim().length > 0),
    ),
  );
  const preferredGenres = [
    ...getStringArray(merged.discogs_styles),
    ...getStringArray(merged.spotify_genres),
  ];
  const fallbackGenres = getStringArray(merged.discogs_genres);
  const genres = Array.from(
    new Set(
      (preferredGenres.length > 0 ? preferredGenres : fallbackGenres)
        .map(formatArchiveGenre)
        .filter((genre) => genre.length > 0 && !EXCLUDED_ARCHIVE_GENRES.has(genre)),
    ),
  );

  return {
    idx: row.position,
    artist: row.displayArtist,
    title: row.displayTitle,
    start: row.startTimeSeconds,
    end: row.endTimeSeconds,
    startFmt:
      getString(merged.start_time_formatted) ??
      getString(merged.startTimeFormatted) ??
      formatDuration(row.startTimeSeconds),
    endFmt:
      getString(merged.end_time_formatted) ??
      getString(merged.endTimeFormatted) ??
      (row.endTimeSeconds != null ? formatDuration(row.endTimeSeconds) : null),
    conf: confidence,
    albumArt:
      getString(merged.spotify_album_art) ??
      getString(merged.albumArt) ??
      null,
    previewUrl:
      getString(merged.spotify_preview_url) ??
      getString(merged.previewUrl) ??
      null,
    bpm: getNumber(merged.bpm),
    energy: getNumber(merged.energy),
    dance: getNumber(merged.danceability) ?? getNumber(merged.dance),
    key: getString(merged.key),
    genres,
    detailGenres,
    label: getString(merged.discogs_label),
    labelUrl: getString(merged.discogs_label_url),
    spotifyUrl: row.trackSpotifyUrl ?? getString(merged.spotify_url),
    youtubeUrl: row.trackYoutubeUrl ?? getString(merged.youtube_url),
    discogsUrl: row.trackDiscogsUrl ?? getString(merged.discogs_url),
    detectionCount: Number(row.detectionCount ?? 0),
    clusterDensity: getNumber(row.clusterDensity),
    clusterSpan: row.clusterSpan,
    sourceDeepLink: row.sourceDeepLink ?? getString(merged.source_deep_link),
  };
};

const buildTimeline = (
  tracks: ArchiveSetTrack[],
  duration: number,
): ArchiveSetTimelineSegment[] => {
  if (duration <= 0) {
    return [];
  }

  return tracks.map((track) => {
    const safeEnd = track.end ?? duration;
    return {
      idx: track.idx,
      leftPct: percent(track.start, duration),
      widthPct: Math.max(percent(safeEnd - track.start, duration), 1),
      conf: track.conf,
      label: `${track.artist} - ${track.title}`,
      timeRange: track.endFmt ? `${track.startFmt} - ${track.endFmt}` : track.startFmt,
    };
  });
};

const buildJourneyPoints = (tracks: ArchiveSetTrack[]): ArchiveJourneyPoint[] =>
  tracks
    .filter((track) => track.bpm != null || track.energy != null || track.dance != null)
    .map((track) => ({
      idx: track.idx,
      start: track.start,
      artist: track.artist,
      title: track.title,
      bpm: track.bpm,
      energy: track.energy,
      dance: track.dance,
    }));

const resolveDirectSetImage = (value: {
  imageUrl: string | null | undefined;
  metadata?: unknown;
  sourcePlatform: string | null | undefined;
  sourceUrl: string | null | undefined;
}) => {
  const setMetadata = asRecord(value.metadata);
  const mixInfo = asRecord(setMetadata.mixInfo);

  return (
    getString(mixInfo.thumbnail_url) ??
    getString(mixInfo.thumbnail) ??
    getString(mixInfo.image_url) ??
    getString(mixInfo.image) ??
    getString(mixInfo.artwork_url) ??
    getString(mixInfo.artwork) ??
    getString(mixInfo.cover_image) ??
    getString(mixInfo.coverUrl) ??
    getString(mixInfo.poster_url) ??
    value.imageUrl ??
    (value.sourcePlatform === "youtube" ? buildYouTubeThumbnail(value.sourceUrl ?? null) : null)
  );
};

const getArchiveSetDetailUncached = async (slug: string): Promise<ArchiveSetDetail | null> => {
  const db = getDb();
  const [setRecord] = await db.select().from(sets).where(eq(sets.slug, slug)).limit(1);

  if (!setRecord) {
    return null;
  }

  const [artistRows, entryRows] = await Promise.all([
    db
      .select({
        id: artists.id,
        imageUrl: artists.imageUrl,
        name: artists.name,
        role: setArtists.role,
        slug: artists.slug,
      })
      .from(setArtists)
      .innerJoin(artists, eq(artists.id, setArtists.artistId))
      .where(eq(setArtists.setId, setRecord.id))
      .orderBy(sql`case when ${setArtists.role} = 'primary' then 0 else 1 end`, asc(artists.name)),
    db
      .select({
        position: setEntries.position,
        displayArtist: setEntries.displayArtist,
        displayTitle: setEntries.displayTitle,
        startTimeSeconds: setEntries.startTimeSeconds,
        endTimeSeconds: setEntries.endTimeSeconds,
        confidence: setEntries.confidence,
        detectionCount: setEntries.detectionCount,
        clusterDensity: setEntries.clusterDensity,
        clusterSpan: setEntries.clusterSpan,
        sourceDeepLink: setEntries.sourceDeepLink,
        entryMetadata: setEntries.metadata,
        trackId: tracks.id,
        trackMetadata: tracks.metadata,
        trackSpotifyUrl: tracks.spotifyUrl,
        trackYoutubeUrl: tracks.youtubeUrl,
        trackDiscogsUrl: tracks.discogsUrl,
      })
      .from(setEntries)
      .leftJoin(tracks, eq(tracks.id, setEntries.trackId))
      .where(eq(setEntries.setId, setRecord.id))
      .orderBy(asc(setEntries.position)),
  ]);

  const trackCards = entryRows.map(mapSetTrack);
  const recognizedTracks = trackCards.filter((track) => track.title !== "Unknown Track");
  const setMetadata = asRecord(setRecord.metadata);
  const mixInfo = asRecord(setMetadata.mixInfo);
  const primaryArtists = artistRows.filter((artist) => artist.role === "primary");
  const preferredArtists = primaryArtists.length > 0 ? primaryArtists : artistRows;
  const duration =
    getNumber(mixInfo.duration) ??
    getNumber(setRecord.durationSeconds) ??
    0;
  const setImageSource = resolveDirectSetImage(setRecord);
  const artistImageSource =
    preferredArtists.find((artist) => artist.imageUrl)?.imageUrl ??
    getString(mixInfo.artist_profile_image) ??
    getString(mixInfo.artist_image);
  const currentArtistIds = preferredArtists.map((artist) => artist.id);
  let relatedSetFallbackImage: string | null = null;
  let archiveFallbackImage: string | null = null;

  if (!setImageSource && !artistImageSource && currentArtistIds.length > 0) {
    const relatedFallbackSets = await db
      .select({
        imageUrl: sets.imageUrl,
        sourcePlatform: sets.sourcePlatform,
        sourceUrl: sets.sourceUrl,
      })
      .from(sets)
      .innerJoin(setArtists, eq(setArtists.setId, sets.id))
      .where(
        and(
          ne(sets.id, setRecord.id),
          inArray(setArtists.artistId, currentArtistIds),
          or(isNotNull(sets.imageUrl), eq(sets.sourcePlatform, "youtube")),
        ),
      )
      .groupBy(sets.id, sets.imageUrl, sets.sourcePlatform, sets.sourceUrl)
      .orderBy(sql`random()`)
      .limit(12);

    relatedSetFallbackImage =
      relatedFallbackSets
        .map((fallbackSet) => resolveDirectSetImage(fallbackSet))
        .find((image): image is string => Boolean(image)) ??
      null;
  }

  if (!setImageSource && !artistImageSource && !relatedSetFallbackImage) {
    const [fallbackSet] = await db
      .select({
        imageUrl: sets.imageUrl,
        sourcePlatform: sets.sourcePlatform,
        sourceUrl: sets.sourceUrl,
      })
      .from(sets)
      .where(
        and(
          ne(sets.id, setRecord.id),
          or(isNotNull(sets.imageUrl), eq(sets.sourcePlatform, "youtube")),
        ),
      )
      .orderBy(sql`random()`)
      .limit(1);

    archiveFallbackImage = fallbackSet ? resolveDirectSetImage(fallbackSet) : null;
  }

  const heroImageUrl =
    setImageSource ??
    artistImageSource ??
    relatedSetFallbackImage ??
    archiveFallbackImage ??
    null;
  const generatedAt =
    getString(asRecord(setMetadata.summary).generated_at) ??
    setRecord.updatedAt?.toISOString() ??
    null;

  return {
    id: setRecord.id,
    slug: setRecord.slug,
    title: setRecord.title,
    artistName: artistRows[0]?.name ?? null,
    artists: artistRows.map((artist) => ({
      id: artist.id,
      name: artist.name,
      slug: artist.slug,
    })),
    heroImageUrl,
    thumbnailUrl: resolveDirectSetImage(setRecord),
    sourcePlatform: setRecord.sourcePlatform,
    sourceUrl: setRecord.sourceUrl,
    embedUrl: buildArchiveEmbed({
      sourcePlatform: setRecord.sourcePlatform,
      sourceUrl: setRecord.sourceUrl,
    }),
    duration,
    durationFmt: formatDuration(duration),
    recognitionRate:
      setRecord.recognitionRate != null ? Number(setRecord.recognitionRate) : null,
    generatedAt,
    stats: {
      totalTracks: trackCards.length,
      identifiedTracks: recognizedTracks.length,
      highOrMediumTracks: trackCards.filter(
        (track) => track.conf === "HIGH" || track.conf === "MEDIUM",
      ).length,
      distinctArtists: new Set(recognizedTracks.map((track) => track.artist)).size,
    },
    highlightedTracks: buildJourneyPoints(trackCards)
      .slice(0, 8)
      .map((point) => trackCards.find((track) => track.idx === point.idx))
      .filter((track): track is ArchiveSetTrack => Boolean(track)),
    timeline: buildTimeline(trackCards, duration),
    tracks: trackCards,
    journeyPoints: buildJourneyPoints(trackCards),
  };
};

export const getArchiveSetDetailBySlug = async (slug: string) =>
  unstable_cache(
    async () => getArchiveSetDetailUncached(slug),
    ["archive-set-detail-v2", slug],
    { tags: [ARCHIVE_TAGS.set(slug)] },
  )();

const getArtistSummaryUncached = async (slug: string): Promise<ArchiveArtistSummary | null> => {
  const db = getDb();
  const [artistRecord] = await db.select().from(artists).where(eq(artists.slug, slug)).limit(1);

  if (!artistRecord) {
    return null;
  }

  const [setRows, failedSetRunRows] = await Promise.all([
    db
      .select({
        id: sets.id,
        slug: sets.slug,
        title: sets.title,
        sourcePlatform: sets.sourcePlatform,
        sourceUrl: sets.sourceUrl,
        durationSeconds: sets.durationSeconds,
        imageUrl: sets.imageUrl,
        recognitionRate: sets.recognitionRate,
        updatedAt: sets.updatedAt,
        metadata: sets.metadata,
      })
      .from(setArtists)
      .innerJoin(sets, eq(sets.id, setArtists.setId))
      .where(eq(setArtists.artistId, artistRecord.id))
      .orderBy(desc(sets.updatedAt), asc(sets.title)),
    db
      .select({
        id: setRuns.id,
        sourceUrl: setRuns.sourceUrl,
        setTitle: setRuns.setTitle,
        errorSummary: setRuns.errorSummary,
        stage: setRuns.stage,
        updatedAt: setRuns.updatedAt,
      })
      .from(setRuns)
      .innerJoin(submissions, eq(submissions.id, setRuns.submissionId))
      .where(and(eq(setRuns.status, "failed"), sql`lower(${submissions.artistName}) = lower(${artistRecord.name})`))
      .orderBy(desc(setRuns.updatedAt)),
  ]);

  const setIds = setRows.map((row) => row.id);
  const entryRows = setIds.length
    ? await db
        .select({
          setId: setEntries.setId,
          position: setEntries.position,
          displayArtist: setEntries.displayArtist,
          displayTitle: setEntries.displayTitle,
          startTimeSeconds: setEntries.startTimeSeconds,
          endTimeSeconds: setEntries.endTimeSeconds,
          confidence: setEntries.confidence,
          detectionCount: setEntries.detectionCount,
          clusterDensity: setEntries.clusterDensity,
          clusterSpan: setEntries.clusterSpan,
          sourceDeepLink: setEntries.sourceDeepLink,
          entryMetadata: setEntries.metadata,
          trackId: tracks.id,
          trackMetadata: tracks.metadata,
          trackSpotifyUrl: tracks.spotifyUrl,
          trackYoutubeUrl: tracks.youtubeUrl,
          trackDiscogsUrl: tracks.discogsUrl,
        })
        .from(setEntries)
        .leftJoin(tracks, eq(tracks.id, setEntries.trackId))
        .where(inArray(setEntries.setId, setIds))
        .orderBy(asc(setEntries.setId), asc(setEntries.position))
    : [];

  const rowsBySet = new Map<string, ArchiveSetTrack[]>();
  const recurringMap = new Map<
    string,
    {
      trackKey: string;
      artist: string;
      title: string;
      appearances: number;
      confidenceCounts: Record<ArchiveConfidence, number>;
      albumArt: string | null;
      spotifyUrl: string | null;
      genres: Set<string>;
      label: string | null;
      setRefs: ArchiveRecurringTrack["setRefs"];
    }
  >();
  const atlasTracks: ArchiveArtistAtlasTrack[] = [];
  const genreCounter = new Map<string, number>();
  const labelCounter = new Map<string, number>();

  for (const row of entryRows) {
    const track = mapSetTrack(row);
    const setTrackList = rowsBySet.get(row.setId) ?? [];
    setTrackList.push(track);
    rowsBySet.set(row.setId, setTrackList);

    if (track.title === "Unknown Track") {
      continue;
    }

    for (const genre of track.genres) {
      genreCounter.set(genre, (genreCounter.get(genre) ?? 0) + 1);
    }

    if (track.label) {
      labelCounter.set(track.label, (labelCounter.get(track.label) ?? 0) + 1);
    }

    const trackKey = buildTrackKey(track.artist, track.title, row.trackId);
    const recurring =
      recurringMap.get(trackKey) ??
      {
        trackKey,
        artist: track.artist,
        title: track.title,
        appearances: 0,
        confidenceCounts: emptyConfidenceCounts(),
        albumArt: track.albumArt,
        spotifyUrl: track.spotifyUrl,
        genres: new Set<string>(),
        label: track.label,
        setRefs: [],
      };

    recurring.appearances += 1;
    incrementConfidence(recurring.confidenceCounts, track.conf);
    if (!recurring.albumArt && track.albumArt) {
      recurring.albumArt = track.albumArt;
    }
    if (!recurring.spotifyUrl && track.spotifyUrl) {
      recurring.spotifyUrl = track.spotifyUrl;
    }
    if (!recurring.label && track.label) {
      recurring.label = track.label;
    }
    for (const genre of track.genres) {
      recurring.genres.add(genre);
    }

    const setRow = setRows.find((entry) => entry.id === row.setId);
    recurring.setRefs.push({
      setTitle: setRow?.title ?? "Unknown Set",
      href: setRow ? `/sets/${setRow.slug}#track-${track.idx}` : null,
      confidence: track.conf,
      position: track.idx,
    });
    recurringMap.set(trackKey, recurring);

    atlasTracks.push({
      idx: track.idx,
      trackKey,
      artist: track.artist,
      title: track.title,
      confidence: track.conf,
      time: track.startFmt,
      genres: track.genres,
      label: track.label,
      labelUrl: track.labelUrl,
      spotifyUrl: track.spotifyUrl,
      youtubeUrl: track.youtubeUrl,
      discogsUrl: track.discogsUrl,
      albumArt: track.albumArt,
      setId: row.setId,
      setSlug: setRow?.slug ?? "",
      setHref: setRow ? `/sets/${setRow.slug}#track-${track.idx}` : null,
      sourceDeepLink: track.sourceDeepLink,
      timeRange: track.endFmt ? `${track.startFmt} - ${track.endFmt}` : track.startFmt,
      setTitle: setRow?.title ?? "Unknown Set",
    });
  }

  const setsSummary: ArchiveArtistSet[] = setRows.map((setRow) => {
    const setTracks = rowsBySet.get(setRow.id) ?? [];
    const recognizedTracks = setTracks.filter((track) => track.title !== "Unknown Track");
    const confidenceCounts = emptyConfidenceCounts();
    for (const track of setTracks) {
      incrementConfidence(confidenceCounts, track.conf);
    }

    return {
      id: setRow.id,
      slug: setRow.slug,
      title: setRow.title,
      sourceUrl: setRow.sourceUrl,
      thumbnailUrl: resolveDirectSetImage(setRow),
      duration: Number(setRow.durationSeconds ?? 0),
      durationFmt: formatCompactDuration(Number(setRow.durationSeconds ?? 0)),
      totalTracks: setTracks.length,
      recognizedTracks: recognizedTracks.length,
      recognitionRate:
        setRow.recognitionRate != null ? Number(setRow.recognitionRate) : null,
      confidenceCounts,
      trackSearchText: setTracks
        .map((track) => `${track.artist} ${track.title}`)
        .join(" ")
        .trim(),
      tracks: setTracks.map((track) => ({
        end: track.end,
        endTimeFormatted: track.endFmt,
        isUnknown: track.title === "Unknown Track",
        position: track.idx,
        artist: track.artist,
        start: track.start,
        title: track.title,
        startTimeFormatted: track.startFmt,
        confidence: track.conf,
        spotifyUrl: track.spotifyUrl,
        trackHref: `/sets/${setRow.slug}#track-${track.idx}`,
        trackKey: buildTrackKey(track.artist, track.title),
      })),
    };
  });

  const recurringTracks = Array.from(recurringMap.values())
    .map<ArchiveRecurringTrack>((entry) => ({
      trackKey: entry.trackKey,
      artist: entry.artist,
      title: entry.title,
      appearances: entry.appearances,
      confidenceCounts: entry.confidenceCounts,
      albumArt: entry.albumArt,
      spotifyUrl: entry.spotifyUrl,
      genres: Array.from(entry.genres),
      label: entry.label,
      setRefs: entry.setRefs,
    }))
    .sort((left, right) => {
      if (right.appearances !== left.appearances) {
        return right.appearances - left.appearances;
      }
      return left.title.localeCompare(right.title);
    });

  const latestSet = setRows[0];
  const failedSetMap = new Map<
    string,
    {
      title: string;
      url: string | null;
      reason: string | null;
    }
  >();

  for (const row of failedSetRunRows) {
    const dedupeKey = row.sourceUrl ?? row.setTitle ?? row.id;
    if (failedSetMap.has(dedupeKey)) {
      continue;
    }

    failedSetMap.set(dedupeKey, {
      title: row.setTitle ?? row.sourceUrl ?? "Unknown set",
      url: row.sourceUrl ?? null,
      reason: row.errorSummary ?? row.stage ?? "failed",
    });
  }

  const setOrderById = new Map(setRows.map((setRow, index) => [setRow.id, index]));
  const uniqueTracks = new Set(
    Array.from(recurringMap.values()).map((entry) => entry.trackKey),
  );
  const recognizedTrackCount = Array.from(rowsBySet.values()).reduce(
    (total, setTrackList) =>
      total + setTrackList.filter((track) => track.title !== "Unknown Track").length,
    0,
  );

  return {
    id: artistRecord.id,
    slug: artistRecord.slug,
    name: artistRecord.name,
    imageUrl: artistRecord.imageUrl,
    heroImageUrl:
      artistRecord.imageUrl ??
      (latestSet ? resolveDirectSetImage(latestSet) : null),
    generatedAt: latestSet?.updatedAt?.toISOString() ?? artistRecord.updatedAt?.toISOString() ?? null,
    stats: {
      setsAnalyzed: setRows.length,
      uniqueTracks: uniqueTracks.size,
      totalDetections: recognizedTrackCount,
      recurringTracks: recurringTracks.filter((track) => track.appearances > 1).length,
    },
    topGenres: Array.from(genreCounter.entries())
      .sort((left, right) => right[1] - left[1])
      .slice(0, 6)
      .map(([name]) => name),
    topLabels: Array.from(labelCounter.entries())
      .sort((left, right) => right[1] - left[1])
      .slice(0, 8)
      .map(([name, count]) => ({ name, count })),
    recurringTracks,
    sets: setsSummary,
    atlasTracks: atlasTracks.sort((left, right) => {
      const leftIndex = setOrderById.get(left.setId) ?? Number.MAX_SAFE_INTEGER;
      const rightIndex = setOrderById.get(right.setId) ?? Number.MAX_SAFE_INTEGER;

      if (leftIndex !== rightIndex) {
        return leftIndex - rightIndex;
      }

      if (left.idx !== right.idx) {
        return left.idx - right.idx;
      }

      return `${left.artist} ${left.title}`.localeCompare(`${right.artist} ${right.title}`);
    }),
    failedSets: Array.from(failedSetMap.values()),
  };
};

export const getArchiveArtistSummaryBySlug = async (slug: string) =>
  unstable_cache(
    async () => getArtistSummaryUncached(slug),
    ["archive-artist-summary-v2", slug],
    { tags: [ARCHIVE_TAGS.artist(slug)] },
  )();

const getHomeSummaryUncached = async ({
  page,
  pageSize,
  query,
}: {
  page: number;
  pageSize: number;
  query: string;
}): Promise<ArchiveHomeBaseSummary> => {
  const db = getDb();
  const safePage = Number.isFinite(page) && page > 0 ? Math.floor(page) : 1;
  const safePageSize = Number.isFinite(pageSize) && pageSize > 0 ? Math.min(pageSize, 36) : 24;
  const normalizedQuery = query.trim();

  const [[artistCountRow], [setCountRow], [trackEntryRow], [recognizedTrackRow]] =
    await Promise.all([
      db
        .select({ count: countDistinct(artists.id) })
        .from(artists)
        .leftJoin(setArtists, eq(setArtists.artistId, artists.id))
        .where(isNotNull(setArtists.setId)),
      db.select({ count: count(sets.id) }).from(sets),
      db.select({ count: count(setEntries.id) }).from(setEntries),
      db
        .select({ count: count(setEntries.id) })
        .from(setEntries)
        .where(ne(setEntries.displayTitle, "Unknown Track")),
    ]);

  const featuredArtistsBase = await db
    .select({
      id: artists.id,
      slug: artists.slug,
      name: artists.name,
      imageUrl: artists.imageUrl,
      setCount: sql<number>`count(distinct ${setArtists.setId})`,
    })
    .from(artists)
    .leftJoin(setArtists, eq(setArtists.artistId, artists.id))
    .where(isNotNull(setArtists.setId))
    .groupBy(artists.id)
    .orderBy(desc(sql`count(distinct ${setArtists.setId})`), asc(artists.name))
    .limit(18);

  const featuredArtistIds = featuredArtistsBase.map((artist) => artist.id);
  const featuredArtistLatestSets = featuredArtistIds.length
    ? await db
        .select({
          artistId: setArtists.artistId,
          setTitle: sets.title,
          updatedAt: sets.updatedAt,
        })
        .from(setArtists)
        .innerJoin(sets, eq(sets.id, setArtists.setId))
        .where(inArray(setArtists.artistId, featuredArtistIds))
        .orderBy(desc(sets.updatedAt))
    : [];

  const latestSetByArtist = new Map<string, { setTitle: string }>();
  for (const row of featuredArtistLatestSets) {
    if (!latestSetByArtist.has(row.artistId)) {
      latestSetByArtist.set(row.artistId, {
        setTitle: row.setTitle,
      });
    }
  }

  const featuredArtists = featuredArtistsBase.map((artist) => {
    const latestSet = latestSetByArtist.get(artist.id);
    return {
      id: artist.id,
      slug: artist.slug,
      name: artist.name,
      imageUrl: artist.imageUrl,
      setCount: Number(artist.setCount ?? 0),
      recognizedTracks: 0,
      latestSetTitle: latestSet?.setTitle ?? null,
    };
  });

  const searchFilter = normalizedQuery
    ? sql`(
        ${sets.title} ilike ${`%${normalizedQuery}%`}
        or coalesce(${sets.uploader}, '') ilike ${`%${normalizedQuery}%`}
      )`
    : undefined;

  const [setPageCount] = await db
    .select({ count: count(sets.id) })
    .from(sets)
    .where(searchFilter);

  const setRows = await db
    .select({
      id: sets.id,
      slug: sets.slug,
      title: sets.title,
      sourcePlatform: sets.sourcePlatform,
      sourceUrl: sets.sourceUrl,
      imageUrl: sets.imageUrl,
      metadata: sets.metadata,
      durationSeconds: sets.durationSeconds,
      recognitionRate: sets.recognitionRate,
      artistName: artists.name,
    })
    .from(sets)
    .leftJoin(setArtists, and(eq(setArtists.setId, sets.id), eq(setArtists.role, "primary")))
    .leftJoin(artists, eq(artists.id, setArtists.artistId))
    .where(searchFilter)
    .orderBy(desc(sets.updatedAt), asc(sets.title))
    .limit(safePageSize)
    .offset((safePage - 1) * safePageSize);

  const setIds = setRows.map((row) => row.id);
  const perSetTrackCounts = setIds.length
    ? await db
        .select({
          setId: setEntries.setId,
          count: count(setEntries.id),
        })
        .from(setEntries)
        .where(inArray(setEntries.setId, setIds))
        .groupBy(setEntries.setId)
    : [];
  const trackCountMap = new Map(
    perSetTrackCounts.map((row) => [row.setId, Number(row.count ?? 0)]),
  );

  const setLibrary: ArchiveHomeSetCard[] = setRows.map((row) => ({
    id: row.id,
    slug: row.slug,
    title: row.title,
    artistName: row.artistName ?? null,
    sourceUrl: row.sourceUrl,
    thumbnailUrl: resolveDirectSetImage(row),
    duration: Number(row.durationSeconds ?? 0),
    durationFmt: formatCompactDuration(Number(row.durationSeconds ?? 0)),
    totalTracks: trackCountMap.get(row.id) ?? 0,
    recognitionRate: row.recognitionRate != null ? Number(row.recognitionRate) : null,
  }));

  const totalTrackEntries = Number(trackEntryRow?.count ?? 0);
  const totalRecognizedTracks = Number(recognizedTrackRow?.count ?? 0);

  return {
    generatedAt: new Date().toISOString(),
    globalStats: {
      totalArtists: Number(artistCountRow?.count ?? 0),
      totalSets: Number(setCountRow?.count ?? 0),
      totalRecognizedTracks,
      totalTrackEntries,
      unknownRatio:
        totalTrackEntries > 0
          ? (totalTrackEntries - totalRecognizedTracks) / totalTrackEntries
          : 0,
    },
    featuredArtists,
    setLibrary: {
      items: setLibrary,
      page: safePage,
      pageSize: safePageSize,
      totalItems: Number(setPageCount?.count ?? 0),
      query: normalizedQuery,
    },
  };
};

const getHomeConnectionsUncached = async (): Promise<ArchiveHomeConnectionsResponse> => {
  const db = getDb();
  const connectionRows = await db
    .select({
      artistId: artists.id,
      artistName: artists.name,
      artistSlug: artists.slug,
      trackId: setEntries.trackId,
      displayArtist: setEntries.displayArtist,
      displayTitle: setEntries.displayTitle,
    })
    .from(setArtists)
    .innerJoin(artists, eq(artists.id, setArtists.artistId))
    .innerJoin(setEntries, eq(setEntries.setId, setArtists.setId))
    .where(ne(setEntries.displayTitle, "Unknown Track"));

  const trackToArtists = new Map<
    string,
    Map<string, { name: string; slug: string }>
  >();
  for (const row of connectionRows) {
    const trackKey = buildTrackKey(row.displayArtist, row.displayTitle, row.trackId);
    const bucket = trackToArtists.get(trackKey) ?? new Map();
    bucket.set(row.artistId, {
      name: row.artistName,
      slug: row.artistSlug,
    });
    trackToArtists.set(trackKey, bucket);
  }

  const connectionCounter = new Map<string, ArchiveHomeConnection>();
  for (const artistMap of trackToArtists.values()) {
    const participants = Array.from(artistMap.entries());
    for (let index = 0; index < participants.length; index += 1) {
      for (let peer = index + 1; peer < participants.length; peer += 1) {
        const [artistAId, artistA] = participants[index];
        const [artistBId, artistB] = participants[peer];
        const key = [artistAId, artistBId].sort().join(":");
        const existing = connectionCounter.get(key);

        if (existing) {
          existing.sharedTracks += 1;
          continue;
        }

        connectionCounter.set(key, {
          artistA: artistA.name,
          artistASlug: artistA.slug,
          artistB: artistB.name,
          artistBSlug: artistB.slug,
          sharedTracks: 1,
        });
      }
    }
  }

  return {
    connections: Array.from(connectionCounter.values())
      .sort((left, right) => right.sharedTracks - left.sharedTracks)
      .slice(0, 20),
    generatedAt: new Date().toISOString(),
  };
};

export const getArchiveHomeSummary = async ({
  page = 1,
  pageSize = 24,
  query = "",
}: {
  page?: number;
  pageSize?: number;
  query?: string;
}) =>
  unstable_cache(
    async () =>
      getHomeSummaryUncached({
        page,
        pageSize,
        query,
      }),
    ["archive-home-summary", String(page), String(pageSize), query],
    { tags: [ARCHIVE_TAGS.home, ARCHIVE_TAGS.lists] },
  )();

export const getArchiveHomeConnections = async () =>
  unstable_cache(
    async () => getHomeConnectionsUncached(),
    ["archive-home-connections"],
    { tags: [ARCHIVE_TAGS.home, ARCHIVE_TAGS.connections] },
  )();

export const archiveCacheTags = ARCHIVE_TAGS;
