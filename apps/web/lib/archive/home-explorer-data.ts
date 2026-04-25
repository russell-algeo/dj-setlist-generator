import "server-only";

import { unstable_cache, unstable_noStore as noStore } from "next/cache";
import { and, asc, eq, isNull } from "drizzle-orm";
import { sql } from "drizzle-orm";

import type {
  ArchiveHomeAtlasSelectionPayload,
  ArchiveHomeArtistCard,
  ArchiveHomeBootstrapPayload,
  ArchiveHomeCompareMode,
  ArchiveHomeHeroSet,
  ArchiveHomeNetworkArtist,
  ArchiveHomeNetworkEdge,
  ArchiveHomeNetworkIndexPayload,
  ArchiveHomePairBucket,
  ArchiveHomePairSelectionPayload,
  ArchiveHomePairTrack,
  ArchiveHomeSetLibraryItem,
  ArchiveHomeSetLibraryPagePayload,
  ArchiveHomeSetLibraryTrack,
  ArchiveHomeSetTracklistPayload,
  ArchiveHomeSetSort,
  ArchiveHomeTrackArtistRef,
  ArchiveHomeTrackCatalogItem,
  ArchiveHomeTrackSetRef,
} from "@/lib/archive/home-explorer-types";
import { ARCHIVE_SET_LIBRARY_PAGE_SIZE } from "@/lib/archive/constants";
import type { ArchiveConfidence } from "@/lib/archive/types";
import {
  applyArtistCardImageFallbacks,
  buildHomeHeroPayload,
} from "@/lib/archive/home-visuals";
import {
  asRecord,
  buildTrackKey,
  formatDuration,
  getNumber,
  getString,
  getStringArray,
  normalizeArchiveConfidence,
} from "@/lib/archive/utils";
import { getDb } from "@/lib/db/client";
import { artists, setArtists, setEntries, setRuns, sets, tracks } from "@/lib/db/schema";

const HOME_TAGS = {
  atlas: "archive:home-atlas",
  home: "archive:home",
  lists: "archive:lists",
  network: "archive:home-network",
  pair: "archive:home-pair",
  setTracklist: (slug: string) => `archive:home-set-tracklist:${slug}`,
} as const;

const PAGE_SIZE = ARCHIVE_SET_LIBRARY_PAGE_SIZE;
const THRESHOLD_LEVELS = [1, 2, 3, 5, 8, 12] as const;

type HomeArtistCardRow = {
  id: string;
  imageUrl: string | null;
  name: string;
  setCount: number | string;
  slug: string;
  totalAppearances: number | string;
  uniqueTracks: number | string;
};

type HomeArtistCoverImageRow = {
  artistSlug: string;
  imageUrl: string | null;
};

type HomeGlobalStatsRow = {
  generatedAt: string | null;
  highCount: number | string;
  lowCount: number | string;
  mediumCount: number | string;
  totalAppearances: number | string;
  totalArtists: number | string;
  totalSets: number | string;
  totalTrackEntries: number | string;
  totalUniqueTracks: number | string;
  uncertainCount: number | string;
};

type HomeHeroSetRow = {
  artistName: string | null;
  artistSlug: string | null;
  duration: number | string | null;
  id: string;
  recognitionRate: number | string | null;
  slug: string;
  thumbnailUrl: string | null;
  title: string;
  totalTracks: number | string;
};

type HomeAtlasRow = {
  albumArt: string | null;
  appearances: number | string;
  artistImage: string | null;
  artistName: string;
  artistProfileImage: string | null;
  artistSlug: string;
  confidenceCounts: unknown;
  genres: unknown;
  label: string | null;
  labelUrl: string | null;
  primaryConfidence: string | null;
  setRefs: unknown;
  spotifyUrl: string | null;
  trackArtist: string;
  trackKey: string;
  trackTitle: string;
};

type HomeNetworkEdgeRow = {
  artistA: string;
  artistASlug: string;
  artistB: string;
  artistBSlug: string;
  normalizedScore: number | string;
  score: number | string;
  sharedArtistsCount: number | string;
  sharedGenresCount: number | string;
  sharedLabelsCount: number | string;
  sharedTracksCount: number | string;
};

type HomePairRow = {
  artistAName: string;
  artistASlug: string;
  artistBName: string;
  artistBSlug: string;
  normalizedScore: number | string;
  score: number | string;
  sharedGenres: unknown;
  sharedGenresCount: number | string;
  sharedLabels: unknown;
  sharedLabelsCount: number | string;
  sharedMusicArtists: unknown;
  sharedMusicArtistsCount: number | string;
  sharedTracks: unknown;
  sharedTracksCount: number | string;
};

type HomeSetLibraryRow = {
  artistName: string | null;
  artistSlug: string | null;
  confidenceCounts: unknown;
  duration: number | string;
  id: string;
  miniTimeline: unknown;
  recognitionRate: number | string | null;
  slug: string;
  sourcePlatform: string | null;
  sourceUrl: string | null;
  thumbnailUrl: string | null;
  title: string;
  totalTracks: number | string;
};

type HomeSetTracklistRow = {
  confidence: string;
  displayArtist: string;
  displayTitle: string;
  position: number;
  sourceDeepLink: string | null;
  startTimeSeconds: number;
  trackId: string | null;
  trackMetadata: unknown;
  trackSpotifyUrl: string | null;
};

type ViewerSubmittedScope = {
  artistSlugs: Set<string>;
  setIds: Set<string>;
};

const asJsonArray = <T>(value: unknown): T[] => {
  if (Array.isArray(value)) {
    return value as T[];
  }

  if (typeof value === "string" && value.trim().length > 0) {
    try {
      const parsed = JSON.parse(value) as unknown;
      return Array.isArray(parsed) ? (parsed as T[]) : [];
    } catch {
      return [];
    }
  }

  return [];
};

const asRows = <T>(rows: unknown[]): T[] => rows as T[];

const numberOrZero = (value: number | string | null | undefined) =>
  Number.isFinite(Number(value ?? 0)) ? Number(value ?? 0) : 0;

const nullableNumber = (value: number | string | null | undefined) => {
  if (value == null || value === "") {
    return null;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const numberFromUnknown = (value: unknown) => numberOrZero(getNumber(value) ?? getString(value));

const emptyConfidenceCounts = (): Record<ArchiveConfidence, number> => ({
  HIGH: 0,
  LOW: 0,
  MEDIUM: 0,
  UNCERTAIN: 0,
});

const normalizeConfidenceCounts = (value: unknown): Record<ArchiveConfidence, number> => {
  const safe = asRecord(value);
  return {
    HIGH: numberFromUnknown(safe.HIGH),
    LOW: numberFromUnknown(safe.LOW),
    MEDIUM: numberFromUnknown(safe.MEDIUM),
    UNCERTAIN: numberFromUnknown(safe.UNCERTAIN),
  };
};

const primaryConfidenceFromCounts = (
  counts: Record<ArchiveConfidence, number>,
): ArchiveConfidence => {
  let best: ArchiveConfidence = "UNCERTAIN";

  for (const level of ["HIGH", "MEDIUM", "LOW", "UNCERTAIN"] as const) {
    if (counts[level] > counts[best]) {
      best = level;
    }
  }

  return best;
};

const buildTickerItems = ({
  edgeCount,
  stats,
}: {
  edgeCount: number;
  stats: ArchiveHomeBootstrapPayload["globalStats"];
}) => [
  `Artists ${stats.totalArtists.toLocaleString("en-US")}`,
  `Sets ${stats.totalSets.toLocaleString("en-US")}`,
  `Unique tracks ${stats.totalUniqueTracks.toLocaleString("en-US")}`,
  `Appearances ${stats.totalAppearances.toLocaleString("en-US")}`,
  `Connection edges ${edgeCount.toLocaleString("en-US")}`,
];

const buildPairLookupKey = (leftSlug: string, rightSlug: string) =>
  [leftSlug, rightSlug].sort().join("::");

const mapArtistCardRow = (row: HomeArtistCardRow): ArchiveHomeArtistCard => ({
  id: row.id,
  imageUrl: row.imageUrl,
  name: row.name,
  setCount: numberOrZero(row.setCount),
  slug: row.slug,
  totalAppearances: numberOrZero(row.totalAppearances),
  uniqueTracks: numberOrZero(row.uniqueTracks),
});

const mapSetRef = (value: unknown): ArchiveHomeTrackSetRef[] =>
  asJsonArray<Record<string, unknown>>(value).map((row) => ({
    confidence: normalizeArchiveConfidence(row.confidence),
    setSlug: getString(row.setSlug) ?? "",
    title: getString(row.title) ?? "Untitled Set",
    trackPosition: numberFromUnknown(row.trackPosition),
  }));

const mapPairBuckets = (value: unknown): ArchiveHomePairBucket[] =>
  asJsonArray<Record<string, unknown>>(value).map((row) => ({
    countA: numberFromUnknown(row.countA ?? row.count_a),
    countB: numberFromUnknown(row.countB ?? row.count_b),
    id: getString(row.id) ?? getString(row.name) ?? "unknown",
    name: getString(row.name) ?? getString(row.id) ?? "Unknown",
    trackKeys: getStringArray(row.trackKeys ?? row.track_keys),
  }));

const mapPairTrack = (value: unknown): ArchiveHomePairTrack[] =>
  asJsonArray<Record<string, unknown>>(value).map((row) => ({
    albumArt: getString(row.albumArt),
    appearancesA: numberFromUnknown(row.appearancesA),
    appearancesB: numberFromUnknown(row.appearancesB),
    artist: getString(row.artist) ?? "Unknown Artist",
    artistImage: getString(row.artistImage),
    artistProfileImage: getString(row.artistProfileImage),
    confidence: normalizeArchiveConfidence(row.confidence),
    confidenceCounts: normalizeConfidenceCounts(row.confidenceCounts),
    genres: getStringArray(row.genres),
    label: getString(row.label),
    labelUrl: getString(row.labelUrl),
    setsA: mapSetRef(row.setsA),
    setsB: mapSetRef(row.setsB),
    spotifyUrl: getString(row.spotifyUrl),
    title: getString(row.title) ?? "Unknown Track",
    trackKey:
      getString(row.trackKey) ??
      buildTrackKey(getString(row.artist) ?? "Unknown Artist", getString(row.title) ?? "Unknown Track"),
  }));

const mapAtlasRowsToPayload = ({
  compareMode,
  generatedAt,
  selectedArtistSlugs,
  rows,
}: {
  compareMode: ArchiveHomeCompareMode;
  generatedAt: string | null;
  selectedArtistSlugs: string[];
  rows: HomeAtlasRow[];
}): ArchiveHomeAtlasSelectionPayload => {
  const grouped = new Map<
    string,
    {
      albumArt: string | null;
      artist: string;
      artistImage: string | null;
      artistProfileImage: string | null;
      artistRefs: ArchiveHomeTrackArtistRef[];
      confidenceCounts: Record<ArchiveConfidence, number>;
      genres: Set<string>;
      label: string | null;
      labelUrl: string | null;
      spotifyUrl: string | null;
      title: string;
      totalAppearances: number;
      trackKey: string;
    }
  >();

  for (const row of rows) {
    const confidenceCounts = normalizeConfidenceCounts(row.confidenceCounts);
    const track = grouped.get(row.trackKey) ?? {
      albumArt: row.albumArt,
      artist: row.trackArtist,
      artistImage: row.artistImage,
      artistProfileImage: row.artistProfileImage,
      artistRefs: [],
      confidenceCounts: emptyConfidenceCounts(),
      genres: new Set<string>(),
      label: row.label,
      labelUrl: row.labelUrl,
      spotifyUrl: row.spotifyUrl,
      title: row.trackTitle,
      totalAppearances: 0,
      trackKey: row.trackKey,
    };

    for (const level of ["HIGH", "MEDIUM", "LOW", "UNCERTAIN"] as const) {
      track.confidenceCounts[level] += confidenceCounts[level];
    }

    track.totalAppearances += numberOrZero(row.appearances);
    if (!track.albumArt && row.albumArt) {
      track.albumArt = row.albumArt;
    }
    if (!track.artistImage && row.artistImage) {
      track.artistImage = row.artistImage;
    }
    if (!track.artistProfileImage && row.artistProfileImage) {
      track.artistProfileImage = row.artistProfileImage;
    }
    if (!track.spotifyUrl && row.spotifyUrl) {
      track.spotifyUrl = row.spotifyUrl;
    }
    if (!track.label && row.label) {
      track.label = row.label;
    }
    if (!track.labelUrl && row.labelUrl) {
      track.labelUrl = row.labelUrl;
    }

    for (const genre of getStringArray(row.genres)) {
      track.genres.add(genre);
    }

    track.artistRefs.push({
      appearances: numberOrZero(row.appearances),
      artistName: row.artistName,
      artistSlug: row.artistSlug,
      setRefs: mapSetRef(row.setRefs),
    });

    grouped.set(row.trackKey, track);
  }

  const trackCatalog = Array.from(grouped.values())
    .map<ArchiveHomeTrackCatalogItem>((track) => ({
      albumArt: track.albumArt,
      artist: track.artist,
      artistImage: track.artistImage,
      artistProfileImage: track.artistProfileImage,
      artistRefs: track.artistRefs.sort((left, right) => left.artistName.localeCompare(right.artistName)),
      artistsCount: track.artistRefs.length,
      confidence: primaryConfidenceFromCounts(track.confidenceCounts),
      confidenceCounts: track.confidenceCounts,
      genres: Array.from(track.genres),
      label: track.label,
      labelUrl: track.labelUrl,
      spotifyUrl: track.spotifyUrl,
      title: track.title,
      totalAppearances: track.totalAppearances,
      trackKey: track.trackKey,
    }))
    .sort((left, right) => {
      if (right.totalAppearances !== left.totalAppearances) {
        return right.totalAppearances - left.totalAppearances;
      }
      if (right.artistsCount !== left.artistsCount) {
        return right.artistsCount - left.artistsCount;
      }
      return `${left.artist} ${left.title}`.localeCompare(`${right.artist} ${right.title}`);
    });

  return {
    compareMode,
    focusArtistSlug: selectedArtistSlugs[0] ?? null,
    generatedAt,
    selectedArtistSlugs,
    trackCatalog,
  };
};

const mapNetworkEdgeRow = (row: HomeNetworkEdgeRow): ArchiveHomeNetworkEdge => ({
  artistA: row.artistA,
  artistASlug: row.artistASlug,
  artistB: row.artistB,
  artistBSlug: row.artistBSlug,
  normalizedScore: numberOrZero(row.normalizedScore),
  score: numberOrZero(row.score),
  sharedArtistsCount: numberOrZero(row.sharedArtistsCount),
  sharedGenresCount: numberOrZero(row.sharedGenresCount),
  sharedLabelsCount: numberOrZero(row.sharedLabelsCount),
  sharedTracksCount: numberOrZero(row.sharedTracksCount),
});

const mapSetLibraryRow = (row: HomeSetLibraryRow): ArchiveHomeSetLibraryItem => ({
  artistName: row.artistName ?? "Unknown Artist",
  artistSlug: row.artistSlug ?? "",
  confidenceCounts: normalizeConfidenceCounts(row.confidenceCounts),
  duration: numberOrZero(row.duration),
  id: row.id,
  miniTimeline: asJsonArray<Record<string, unknown>>(row.miniTimeline).map((segment) => ({
    confidence: normalizeArchiveConfidence(segment.confidence),
    startPct: numberFromUnknown(segment.startPct),
    widthPct: numberFromUnknown(segment.widthPct),
  })),
  recognitionRate: nullableNumber(row.recognitionRate),
  slug: row.slug,
  sourcePlatform: row.sourcePlatform,
  sourceUrl: row.sourceUrl,
  thumbnailUrl: row.thumbnailUrl,
  title: row.title,
  totalTracks: numberOrZero(row.totalTracks),
});

const withSubmittedByViewer = <T extends { id: string }>(
  item: T,
  submittedSetIds: ReadonlySet<string> | null,
) => ({
  ...item,
  submittedByViewer: submittedSetIds?.has(item.id) ?? false,
});

const buildTracklistTrack = (slug: string, row: HomeSetTracklistRow): ArchiveHomeSetLibraryTrack => {
  const trackMetadata = asRecord(row.trackMetadata);

  return {
    artist: row.displayArtist,
    confidence: normalizeArchiveConfidence(row.confidence),
    position: row.position,
    spotifyUrl: row.trackSpotifyUrl ?? getString(trackMetadata.spotify_url),
    startTimeFormatted:
      getString(trackMetadata.start_time_formatted) ??
      getString(trackMetadata.startTimeFormatted) ??
      formatDuration(row.startTimeSeconds),
    title: row.displayTitle,
    trackKey: buildTrackKey(row.displayArtist, row.displayTitle, row.trackId),
    setSlug: slug,
  };
};

const getHomeArtistCardsUncached = async () => {
  const db = getDb();
  const result = await db.execute(sql<HomeArtistCardRow>`
    WITH set_counts AS (
      SELECT
        sa.artist_id,
        count(DISTINCT sa.set_id)::int AS "setCount"
      FROM "app"."set_artists" sa
      INNER JOIN "app"."sets" s
        ON s.id = sa.set_id
      WHERE sa.role = 'primary'
      GROUP BY sa.artist_id
    ),
    atlas_counts AS (
      SELECT
        artist_id,
        count(*)::int AS "uniqueTracks",
        COALESCE(sum(appearances), 0)::int AS "totalAppearances"
      FROM "app"."archive_home_artist_atlas_mv"
      GROUP BY artist_id
    ),
    cover_images AS (
      SELECT DISTINCT ON (artist_slug)
        artist_slug,
        thumbnail_url
      FROM "app"."archive_home_set_library_index_mv"
      WHERE thumbnail_url IS NOT NULL AND thumbnail_url <> ''
      ORDER BY artist_slug, sort_recognition_rate DESC, set_slug
    )
    SELECT
      a.id::text AS id,
      a.slug,
      a.name,
      COALESCE(NULLIF(a.image_url, ''), cover_images.thumbnail_url) AS "imageUrl",
      COALESCE(set_counts."setCount", 0)::int AS "setCount",
      COALESCE(atlas_counts."uniqueTracks", 0)::int AS "uniqueTracks",
      COALESCE(atlas_counts."totalAppearances", 0)::int AS "totalAppearances"
    FROM "app"."artists" a
    LEFT JOIN set_counts
      ON set_counts.artist_id = a.id
    LEFT JOIN atlas_counts
      ON atlas_counts.artist_id = a.id
    LEFT JOIN cover_images
      ON cover_images.artist_slug = a.slug
    WHERE COALESCE(set_counts."setCount", 0) > 0
    ORDER BY a.name ASC
  `);

  return asRows<HomeArtistCardRow>(result.rows).map(mapArtistCardRow);
};

const getHomeArtistCards = unstable_cache(
  async () => getHomeArtistCardsUncached(),
  ["archive-home-artist-cards-v1"],
  { tags: [HOME_TAGS.home, HOME_TAGS.atlas, HOME_TAGS.lists] },
);

const getHomeGlobalStatsUncached = async () => {
  const db = getDb();
  const result = await db.execute(sql<HomeGlobalStatsRow>`
    WITH confidence_counts AS (
      SELECT
        count(*) FILTER (WHERE upper(COALESCE(confidence, 'UNCERTAIN')) = 'HIGH')::int AS "highCount",
        count(*) FILTER (WHERE upper(COALESCE(confidence, 'UNCERTAIN')) = 'MEDIUM')::int AS "mediumCount",
        count(*) FILTER (WHERE upper(COALESCE(confidence, 'UNCERTAIN')) = 'LOW')::int AS "lowCount",
        count(*) FILTER (WHERE upper(COALESCE(confidence, 'UNCERTAIN')) = 'UNCERTAIN')::int AS "uncertainCount",
        count(*)::int AS "totalTrackEntries"
      FROM "app"."set_entries"
    ),
    artist_counts AS (
      SELECT count(*)::int AS "totalArtists"
      FROM (
        SELECT DISTINCT a.id
        FROM "app"."artists" a
        LEFT JOIN "app"."set_artists" sa
          ON sa.artist_id = a.id
        WHERE sa.set_id IS NOT NULL
      ) artist_ids
    ),
    set_counts AS (
      SELECT count(*)::int AS "totalSets" FROM "app"."sets"
    ),
    atlas_counts AS (
      SELECT
        count(DISTINCT track_key)::int AS "totalUniqueTracks",
        COALESCE(sum(appearances), 0)::int AS "totalAppearances"
      FROM "app"."archive_home_artist_atlas_mv"
    ),
    generated_at AS (
      SELECT max(updated_at)::text AS "generatedAt" FROM "app"."sets"
    )
    SELECT
      generated_at."generatedAt",
      confidence_counts."highCount",
      confidence_counts."mediumCount",
      confidence_counts."lowCount",
      confidence_counts."uncertainCount",
      confidence_counts."totalTrackEntries",
      artist_counts."totalArtists",
      set_counts."totalSets",
      atlas_counts."totalUniqueTracks",
      atlas_counts."totalAppearances"
    FROM confidence_counts
    CROSS JOIN artist_counts
    CROSS JOIN set_counts
    CROSS JOIN atlas_counts
    CROSS JOIN generated_at
  `);

  const row = asRows<HomeGlobalStatsRow>(result.rows)[0];
  const totalTrackEntries = numberOrZero(row?.totalTrackEntries);
  const totalAppearances = numberOrZero(row?.totalAppearances);

  return {
    generatedAt: row?.generatedAt ?? null,
    globalStats: {
      confidenceBreakdown: {
        HIGH: numberOrZero(row?.highCount),
        LOW: numberOrZero(row?.lowCount),
        MEDIUM: numberOrZero(row?.mediumCount),
        UNCERTAIN: numberOrZero(row?.uncertainCount),
      },
      totalAppearances,
      totalArtists: numberOrZero(row?.totalArtists),
      totalSets: numberOrZero(row?.totalSets),
      totalUniqueTracks: numberOrZero(row?.totalUniqueTracks),
      unknownRatio:
        totalTrackEntries > 0 ? (totalTrackEntries - totalAppearances) / totalTrackEntries : 0,
    },
  };
};

const getHomeGlobalStats = unstable_cache(
  async () => getHomeGlobalStatsUncached(),
  ["archive-home-global-stats-v1"],
  { tags: [HOME_TAGS.home, HOME_TAGS.lists] },
);

const getWorkspaceGlobalStats = async (userId: string) => {
  const db = getDb();

  const statsResult = await db.execute(sql<{
    totalSets: number | string;
    totalArtists: number | string;
    totalUniqueTracks: number | string;
    totalAppearances: number | string;
    unknownRatio: number | string | null;
  }>`
    SELECT
      COUNT(DISTINCT s.id)::int AS "totalSets",
      COUNT(DISTINCT sa.artist_id)::int AS "totalArtists",
      COUNT(DISTINCT se.track_id)::int AS "totalUniqueTracks",
      COUNT(se.id)::int AS "totalAppearances",
      COUNT(se.id) FILTER (WHERE t.title ILIKE 'Unknown Track%')::float / NULLIF(COUNT(se.id), 0) AS "unknownRatio"
    FROM (
      SELECT DISTINCT s2.id, s2.source_url FROM "app"."sets" s2
      JOIN "ops"."set_runs" sr2
        ON sr2.source_url = s2.source_url
       AND sr2.requested_by = ${userId}
       AND sr2.archive_removed_at IS NULL
    ) s
    LEFT JOIN "app"."set_artists" sa ON sa.set_id = s.id
    LEFT JOIN "app"."set_entries" se ON se.set_id = s.id
    LEFT JOIN "app"."tracks" t ON t.id = se.track_id
  `);

  const confResult = await db.execute(sql<{ confidence: string; count: number | string }>`
    SELECT se.confidence, COUNT(*)::int AS count
    FROM (
      SELECT DISTINCT s2.id FROM "app"."sets" s2
      JOIN "ops"."set_runs" sr2
        ON sr2.source_url = s2.source_url
       AND sr2.requested_by = ${userId}
       AND sr2.archive_removed_at IS NULL
    ) s
    JOIN "app"."set_entries" se ON se.set_id = s.id
    GROUP BY se.confidence
  `);

  const statsRow = asRows<{
    totalSets: number | string;
    totalArtists: number | string;
    totalUniqueTracks: number | string;
    totalAppearances: number | string;
    unknownRatio: number | string | null;
  }>(statsResult.rows)[0];

  const totalAppearances = numberOrZero(statsRow?.totalAppearances);
  const unknownRatioRaw = statsRow?.unknownRatio;
  const unknownRatio =
    unknownRatioRaw != null && unknownRatioRaw !== ""
      ? Number(unknownRatioRaw)
      : 0;

  const confidenceBreakdown = emptyConfidenceCounts();
  for (const row of asRows<{ confidence: string; count: number | string }>(confResult.rows)) {
    const level = normalizeArchiveConfidence(row.confidence);
    confidenceBreakdown[level] += numberOrZero(row.count);
  }

  return {
    generatedAt: null as string | null,
    globalStats: {
      confidenceBreakdown,
      totalAppearances,
      totalArtists: numberOrZero(statsRow?.totalArtists),
      totalSets: numberOrZero(statsRow?.totalSets),
      totalUniqueTracks: numberOrZero(statsRow?.totalUniqueTracks),
      unknownRatio: Number.isFinite(unknownRatio) ? unknownRatio : 0,
    },
  };
};

const getHeroSetCandidatesUncached = async () => {
  const db = getDb();
  const result = await db.execute(sql<HomeHeroSetRow>`
    SELECT
      set_id::text AS id,
      set_slug AS slug,
      set_title AS title,
      artist_slug AS "artistSlug",
      artist_name AS "artistName",
      thumbnail_url AS "thumbnailUrl",
      duration_seconds AS duration,
      recognition_rate AS "recognitionRate",
      total_tracks AS "totalTracks"
    FROM "app"."archive_home_set_library_index_mv"
    WHERE thumbnail_url IS NOT NULL AND thumbnail_url <> ''
    ORDER BY sort_recognition_rate DESC, set_slug ASC
    LIMIT 160
  `);

  return asRows<HomeHeroSetRow>(result.rows).map<ArchiveHomeHeroSet>((row) => ({
    artistName: row.artistName ?? "Unknown Artist",
    artistSlug: row.artistSlug ?? "",
    duration: numberOrZero(row.duration),
    id: row.id,
    recognitionRate: nullableNumber(row.recognitionRate),
    slug: row.slug,
    thumbnailUrl: row.thumbnailUrl,
    title: row.title,
    totalTracks: numberOrZero(row.totalTracks),
  }));
};

const getHeroSetCandidates = unstable_cache(
  async () => getHeroSetCandidatesUncached(),
  ["archive-home-hero-candidates-v1"],
  { tags: [HOME_TAGS.home, HOME_TAGS.lists] },
);

const getArchiveHomeNetworkPayloadUncached = async (): Promise<ArchiveHomeNetworkIndexPayload> => {
  const [artistCards, db] = await Promise.all([getHomeArtistCards(), Promise.resolve(getDb())]);
  const edgeResult = await db.execute(sql<HomeNetworkEdgeRow>`
    SELECT
      artist_a_name AS "artistA",
      artist_a_slug AS "artistASlug",
      artist_b_name AS "artistB",
      artist_b_slug AS "artistBSlug",
      normalized_score AS "normalizedScore",
      score,
      shared_music_artists_count AS "sharedArtistsCount",
      shared_genres_count AS "sharedGenresCount",
      shared_labels_count AS "sharedLabelsCount",
      shared_tracks_count AS "sharedTracksCount"
    FROM "app"."archive_home_pair_summaries_mv"
    WHERE score > 0
    ORDER BY score DESC, artist_a_name ASC, artist_b_name ASC
  `);

  const artists: ArchiveHomeNetworkArtist[] = artistCards.map((artistCard) => ({
    id: artistCard.id,
    name: artistCard.name,
    setCount: artistCard.setCount,
    slug: artistCard.slug,
  }));

  return {
    artists,
    edges: asRows<HomeNetworkEdgeRow>(edgeResult.rows).map(mapNetworkEdgeRow),
  };
};

export const getArchiveHomeNetworkPayload = unstable_cache(
  async () => getArchiveHomeNetworkPayloadUncached(),
  ["archive-home-network-v1"],
  { tags: [HOME_TAGS.home, HOME_TAGS.network] },
);

const getArchiveHomeAtlasPayloadUncached = async ({
  compareMode = "union",
  selectedArtistSlugs,
  userId,
}: {
  compareMode?: ArchiveHomeCompareMode;
  selectedArtistSlugs: string[];
  userId?: string;
}): Promise<ArchiveHomeAtlasSelectionPayload> => {
  const [{ generatedAt }, artistCards, db] = await Promise.all([
    getHomeGlobalStats(),
    getHomeArtistCards(),
    Promise.resolve(getDb()),
  ]);

  const expandedSelectedArtistSlugs = selectedArtistSlugs.includes("__ALL__")
    ? artistCards.map((artistCard) => artistCard.slug)
    : selectedArtistSlugs;

  const validSlugs = expandedSelectedArtistSlugs.filter((slug) =>
    artistCards.some((artistCard) => artistCard.slug === slug),
  );
  const resolvedSelected =
    validSlugs.length > 0 ? validSlugs : artistCards[0] ? [artistCards[0].slug] : [];

  if (!resolvedSelected.length) {
    return {
      compareMode,
      focusArtistSlug: null,
      generatedAt,
      selectedArtistSlugs: [],
      trackCatalog: [],
    };
  }

  const slugValues = resolvedSelected.map((slug) => sql`${slug}`);
  const result = await db.execute(sql<HomeAtlasRow>`
    SELECT
      artist_slug AS "artistSlug",
      artist_name AS "artistName",
      track_key AS "trackKey",
      track_artist AS "trackArtist",
      track_title AS "trackTitle",
      spotify_url AS "spotifyUrl",
      album_art AS "albumArt",
      artist_image AS "artistImage",
      artist_profile_image AS "artistProfileImage",
      label,
      label_url AS "labelUrl",
      genres,
      appearances,
      confidence_counts AS "confidenceCounts",
      primary_confidence AS "primaryConfidence",
      set_refs AS "setRefs"
    FROM "app"."archive_home_artist_atlas_mv"
    WHERE artist_slug IN (${sql.join(slugValues, sql`, `)})
    ORDER BY appearances DESC, track_artist ASC, track_title ASC
  `);

  const rows = asRows<HomeAtlasRow>(result.rows);
  const groupedByTrack = new Map<string, HomeAtlasRow[]>();

  for (const row of rows) {
    const bucket = groupedByTrack.get(row.trackKey) ?? [];
    bucket.push(row);
    groupedByTrack.set(row.trackKey, bucket);
  }

  const filteredRows =
    compareMode === "intersection"
      ? Array.from(groupedByTrack.values())
          .filter((bucket) => bucket.length === resolvedSelected.length)
          .flat()
      : rows;

  const payload = mapAtlasRowsToPayload({
    compareMode,
    generatedAt,
    selectedArtistSlugs: resolvedSelected,
    rows: filteredRows,
  });

  if (userId) {
    // Fetch the set slugs belonging to this user's workspace
    const slugResult = await db.execute(sql<{ setSlug: string }>`
      SELECT DISTINCT s.slug AS "setSlug"
      FROM "ops"."set_runs" sr
      JOIN "app"."sets" s ON s.source_url = sr.source_url
      WHERE sr.requested_by = ${userId}
        AND sr.archive_removed_at IS NULL
    `);
    const workspaceSetSlugs = new Set(
      asRows<{ setSlug: string }>(slugResult.rows).map((r) => r.setSlug),
    );

    payload.trackCatalog = payload.trackCatalog
      .map((track) => ({
        ...track,
        artistRefs: track.artistRefs
          .map((artistRef) => ({
            ...artistRef,
            setRefs: artistRef.setRefs.filter((setRef) => workspaceSetSlugs.has(setRef.setSlug)),
          }))
          .filter((artistRef) => artistRef.setRefs.length > 0),
      }))
      .filter((track) => track.artistRefs.length > 0);
  }

  return payload;
};

export const getArchiveHomeAtlasPayload = async ({
  compareMode = "union",
  selectedArtistSlugs,
  userId,
}: {
  compareMode?: ArchiveHomeCompareMode;
  selectedArtistSlugs: string[];
  userId?: string;
}) => {
  // Workspace-scoped queries must not be cached globally
  if (userId) {
    return getArchiveHomeAtlasPayloadUncached({ compareMode, selectedArtistSlugs, userId });
  }

  const selectionKey = [...selectedArtistSlugs].sort().join(",");

  return unstable_cache(
    async () =>
      getArchiveHomeAtlasPayloadUncached({
        compareMode,
        selectedArtistSlugs,
      }),
    ["archive-home-atlas-v1", compareMode, selectionKey],
    { tags: [HOME_TAGS.home, HOME_TAGS.atlas] },
  )();
};

const getArchiveHomePairPayloadUncached = async ({
  artistASlug,
  artistBSlug,
  userId,
}: {
  artistASlug: string;
  artistBSlug: string;
  userId?: string;
}): Promise<ArchiveHomePairSelectionPayload | null> => {
  const [leftSlug, rightSlug] = [artistASlug, artistBSlug].sort();
  if (!leftSlug || !rightSlug || leftSlug === rightSlug) {
    return null;
  }

  const db = getDb();
  const result = await db.execute(sql<HomePairRow>`
    SELECT
      artist_a_name AS "artistAName",
      artist_a_slug AS "artistASlug",
      artist_b_name AS "artistBName",
      artist_b_slug AS "artistBSlug",
      normalized_score AS "normalizedScore",
      score,
      shared_tracks AS "sharedTracks",
      shared_tracks_count AS "sharedTracksCount",
      shared_labels AS "sharedLabels",
      shared_labels_count AS "sharedLabelsCount",
      shared_genres AS "sharedGenres",
      shared_genres_count AS "sharedGenresCount",
      shared_music_artists AS "sharedMusicArtists",
      shared_music_artists_count AS "sharedMusicArtistsCount"
    FROM "app"."archive_home_pair_summaries_mv"
    WHERE artist_a_slug = ${leftSlug}
      AND artist_b_slug = ${rightSlug}
    LIMIT 1
  `);

  const row = asRows<HomePairRow>(result.rows)[0];
  if (!row) {
    return null;
  }

  let sharedTracks = mapPairTrack(row.sharedTracks);
  const sharedLabels = mapPairBuckets(row.sharedLabels);
  const sharedGenres = mapPairBuckets(row.sharedGenres);
  const sharedMusicArtists = mapPairBuckets(row.sharedMusicArtists);

  if (userId) {
    // Filter shared tracks to only those whose set references are in the user's workspace
    const slugResult = await db.execute(sql<{ setSlug: string }>`
      SELECT DISTINCT s.slug AS "setSlug"
      FROM "ops"."set_runs" sr
      JOIN "app"."sets" s ON s.source_url = sr.source_url
      WHERE sr.requested_by = ${userId}
        AND sr.archive_removed_at IS NULL
    `);
    const workspaceSetSlugs = new Set(
      asRows<{ setSlug: string }>(slugResult.rows).map((r) => r.setSlug),
    );

    sharedTracks = sharedTracks
      .map((track) => ({
        ...track,
        setsA: track.setsA.filter((ref) => workspaceSetSlugs.has(ref.setSlug)),
        setsB: track.setsB.filter((ref) => workspaceSetSlugs.has(ref.setSlug)),
      }))
      .filter((track) => track.setsA.length > 0 || track.setsB.length > 0);
  }

  return {
    artistA: {
      id: row.artistASlug,
      name: row.artistAName,
      setCount: 0,
      slug: row.artistASlug,
    },
    artistB: {
      id: row.artistBSlug,
      name: row.artistBName,
      setCount: 0,
      slug: row.artistBSlug,
    },
    normalizedScore: numberOrZero(row.normalizedScore),
    score: numberOrZero(row.score),
    sharedGenres,
    sharedGenresCount: numberOrZero(row.sharedGenresCount),
    sharedLabels,
    sharedLabelsCount: numberOrZero(row.sharedLabelsCount),
    sharedMusicArtists,
    sharedMusicArtistsCount: numberOrZero(row.sharedMusicArtistsCount),
    sharedTracks,
    sharedTracksCount: sharedTracks.length,
  };
};

export const getArchiveHomePairPayload = async ({
  artistASlug,
  artistBSlug,
  userId,
}: {
  artistASlug: string;
  artistBSlug: string;
  userId?: string;
}) => {
  // Workspace-scoped queries must not be cached globally
  if (userId) {
    return getArchiveHomePairPayloadUncached({ artistASlug, artistBSlug, userId });
  }

  const lookupKey = buildPairLookupKey(artistASlug, artistBSlug);

  return unstable_cache(
    async () =>
      getArchiveHomePairPayloadUncached({
        artistASlug,
        artistBSlug,
      }),
    ["archive-home-pair-v1", lookupKey],
    { tags: [HOME_TAGS.home, HOME_TAGS.pair] },
  )();
};

const orderByForSetSort = (sort: ArchiveHomeSetSort) => {
  if (sort === "rate") {
    return sql`ORDER BY sort_recognition_rate DESC, set_slug ASC`;
  }
  if (sort === "tracks") {
    return sql`ORDER BY sort_total_tracks DESC, set_slug ASC`;
  }
  if (sort === "duration") {
    return sql`ORDER BY sort_duration_seconds DESC, set_slug ASC`;
  }

  return sql`ORDER BY sort_artist_name ASC, set_title ASC, set_slug ASC`;
};

const getArchiveHomeSetLibraryPayloadUncached = async ({
  artistFilter = "ALL",
  page = 1,
  query = "",
  sort = "default",
  viewerUserId,
}: {
  artistFilter?: string;
  page?: number;
  query?: string;
  sort?: ArchiveHomeSetSort;
  viewerUserId?: string;
}): Promise<ArchiveHomeSetLibraryPagePayload> => {
  const db = getDb();
  const safePage = Number.isFinite(page) && page > 0 ? Math.floor(page) : 1;
  const safeQuery = query.trim();
  const [artistCards, viewerSetIds] = await Promise.all([
    getHomeArtistCards(),
    viewerUserId ? getUserSetIds(db, viewerUserId) : Promise.resolve(null),
  ]);
  const viewerSetIdSet = viewerSetIds ? new Set(viewerSetIds) : null;

  const artistClause =
    artistFilter !== "ALL"
      ? sql`artist_name = ${artistFilter}`
      : sql`true`;
  const queryClause = safeQuery
    ? sql`(
        set_title ILIKE ${`%${safeQuery}%`}
        OR COALESCE(artist_name, '') ILIKE ${`%${safeQuery}%`}
        OR COALESCE(track_search_text, '') ILIKE ${`%${safeQuery}%`}
      )`
    : sql`true`;
  const whereClause = sql`${artistClause} AND ${queryClause}`;
  const orderByClause = orderByForSetSort(sort);
  const countResult = await db.execute(sql<{ totalItems: number | string }>`
    SELECT count(*)::int AS "totalItems"
    FROM "app"."archive_home_set_library_index_mv"
    WHERE ${whereClause}
  `);

  const totalItems = numberOrZero(asRows<{ totalItems: number | string }>(countResult.rows)[0]?.totalItems);
  const totalPages = Math.max(1, Math.ceil(totalItems / PAGE_SIZE));
  const safeResolvedPage = Math.max(1, Math.min(safePage, totalPages));
  const offset = (safeResolvedPage - 1) * PAGE_SIZE;

  const pageResult = await db.execute(sql<HomeSetLibraryRow>`
    SELECT
      set_id::text AS id,
      set_slug AS slug,
      set_title AS title,
      artist_slug AS "artistSlug",
      artist_name AS "artistName",
      confidence_counts AS "confidenceCounts",
      duration_seconds AS duration,
      mini_timeline AS "miniTimeline",
      recognition_rate AS "recognitionRate",
      source_platform AS "sourcePlatform",
      source_url AS "sourceUrl",
      thumbnail_url AS "thumbnailUrl",
      total_tracks AS "totalTracks"
    FROM "app"."archive_home_set_library_index_mv"
    WHERE ${whereClause}
    ${orderByClause}
    LIMIT ${PAGE_SIZE}
    OFFSET ${offset}
  `);

  return {
    artistFilter,
    artistOptions: ["ALL", ...artistCards.map((artistCard) => artistCard.name)],
    items: asRows<HomeSetLibraryRow>(pageResult.rows).map((row) =>
      withSubmittedByViewer(mapSetLibraryRow(row), viewerSetIdSet),
    ),
    page: safeResolvedPage,
    pageSize: PAGE_SIZE,
    query: safeQuery,
    sort,
    totalItems,
    totalPages,
  };
};

export const getArchiveHomeSetLibraryPayload = async ({
  artistFilter = "ALL",
  page = 1,
  query = "",
  sort = "default",
  viewerUserId,
}: {
  artistFilter?: string;
  page?: number;
  query?: string;
  sort?: ArchiveHomeSetSort;
  viewerUserId?: string;
} = {}) => {
  if (viewerUserId) {
    return getArchiveHomeSetLibraryPayloadUncached({
      artistFilter,
      page,
      query,
      sort,
      viewerUserId,
    });
  }

  return (
  unstable_cache(
    async () =>
      getArchiveHomeSetLibraryPayloadUncached({
        artistFilter,
        page,
        query,
        sort,
      }),
    ["archive-home-set-library-v2", String(PAGE_SIZE), artistFilter, String(page), query, sort],
    { tags: [HOME_TAGS.home, HOME_TAGS.lists] },
  )()
  );
};

const getArchiveHomeSetTracklistPayloadUncached = async (
  slug: string,
): Promise<ArchiveHomeSetTracklistPayload | null> => {
  const db = getDb();
  const [setRecord] = await db
    .select({
      id: sets.id,
      slug: sets.slug,
      updatedAt: sets.updatedAt,
    })
    .from(sets)
    .where(eq(sets.slug, slug))
    .limit(1);

  if (!setRecord) {
    return null;
  }

  const rows = await db
    .select({
      confidence: setEntries.confidence,
      displayArtist: setEntries.displayArtist,
      displayTitle: setEntries.displayTitle,
      position: setEntries.position,
      sourceDeepLink: setEntries.sourceDeepLink,
      startTimeSeconds: setEntries.startTimeSeconds,
      trackId: tracks.id,
      trackMetadata: tracks.metadata,
      trackSpotifyUrl: tracks.spotifyUrl,
    })
    .from(setEntries)
    .leftJoin(tracks, eq(tracks.id, setEntries.trackId))
    .innerJoin(sets, eq(sets.id, setEntries.setId))
    .where(eq(setEntries.setId, setRecord.id))
    .orderBy(asc(setEntries.position));

  return {
    generatedAt: setRecord.updatedAt?.toISOString() ?? null,
    slug: setRecord.slug,
    tracks: rows
      .filter((row) => row.displayTitle !== "Unknown Track")
      .map((row) => buildTracklistTrack(setRecord.slug, row)),
  };
};

export const getArchiveHomeSetTracklistPayload = async (slug: string) =>
  unstable_cache(
    async () => getArchiveHomeSetTracklistPayloadUncached(slug),
    ["archive-home-set-tracklist-v1", slug],
    { tags: [HOME_TAGS.home, HOME_TAGS.lists, HOME_TAGS.setTracklist(slug)] },
  )();

// --- Workspace helpers (uncached, userId-scoped) ---

const getUserSetIds = async (db: ReturnType<typeof getDb>, userId: string): Promise<string[]> => {
  const rows = await db
    .selectDistinct({ id: sets.id })
    .from(sets)
    .innerJoin(
      setRuns,
      and(
        eq(setRuns.sourceUrl, sets.sourceUrl),
        eq(setRuns.requestedBy, userId),
        isNull(setRuns.archiveRemovedAt),
      ),
    );
  return rows.map((r) => r.id);
};

const getViewerSubmittedScope = async (userId: string): Promise<ViewerSubmittedScope> => {
  const db = getDb();
  const result = await db.execute(sql<{ artistSlug: string | null; setId: string }>`
    SELECT DISTINCT
      s.id::text AS "setId",
      a.slug AS "artistSlug"
    FROM "app"."sets" s
    INNER JOIN "ops"."set_runs" sr
      ON sr.source_url = s.source_url
     AND sr.requested_by = ${userId}
     AND sr.archive_removed_at IS NULL
    LEFT JOIN "app"."set_artists" sa
      ON sa.set_id = s.id
    LEFT JOIN "app"."artists" a
      ON a.id = sa.artist_id
  `);
  const rows = asRows<{ artistSlug: string | null; setId: string }>(result.rows);

  return {
    artistSlugs: new Set(rows.map((row) => row.artistSlug).filter((slug): slug is string => Boolean(slug))),
    setIds: new Set(rows.map((row) => row.setId)),
  };
};

export const getWorkspaceArtistCards = async (userId: string): Promise<ArchiveHomeArtistCard[]> => {
  const db = getDb();
  const [rows, coverImageResult] = await Promise.all([
    db
      .select({
        id: artists.id,
        slug: artists.slug,
        name: artists.name,
        imageUrl: artists.imageUrl,
        setCount: sql<number>`count(distinct ${sets.id})`,
      })
      .from(artists)
      .innerJoin(setArtists, and(eq(setArtists.artistId, artists.id), eq(setArtists.role, "primary")))
      .innerJoin(sets, eq(sets.id, setArtists.setId))
      .innerJoin(
        setRuns,
        and(
          eq(setRuns.sourceUrl, sets.sourceUrl),
          eq(setRuns.requestedBy, userId),
          isNull(setRuns.archiveRemovedAt),
        ),
      )
      .groupBy(artists.id, artists.slug, artists.name, artists.imageUrl)
      .orderBy(asc(artists.name)),
    db.execute(sql<HomeArtistCoverImageRow>`
      WITH user_sets AS (
        SELECT DISTINCT s.id
        FROM "app"."sets" s
        JOIN "ops"."set_runs" sr
          ON sr.source_url = s.source_url
         AND sr.requested_by = ${userId}
         AND sr.archive_removed_at IS NULL
      )
      SELECT DISTINCT ON (library.artist_slug)
        library.artist_slug AS "artistSlug",
        library.thumbnail_url AS "imageUrl"
      FROM "app"."archive_home_set_library_index_mv" library
      JOIN user_sets
        ON user_sets.id = library.set_id
      WHERE library.thumbnail_url IS NOT NULL
        AND library.thumbnail_url <> ''
      ORDER BY library.artist_slug, library.sort_recognition_rate DESC, library.set_slug ASC
    `),
  ]);

  const artistCards = rows.map((row) => ({
    id: row.id,
    imageUrl: row.imageUrl,
    name: row.name,
    setCount: numberOrZero(row.setCount),
    slug: row.slug,
    totalAppearances: 0,
    uniqueTracks: 0,
  }));
  const fallbackImageBySlug = new Map(
    asRows<HomeArtistCoverImageRow>(coverImageResult.rows).map((row) => [row.artistSlug, row.imageUrl]),
  );

  return applyArtistCardImageFallbacks(artistCards, fallbackImageBySlug);
};

export const getWorkspaceSetLibraryPayload = async ({
  artistFilter = "ALL",
  page = 1,
  query = "",
  sort = "default",
  userId,
}: {
  artistFilter?: string;
  page?: number;
  query?: string;
  sort?: ArchiveHomeSetSort;
  userId: string;
}): Promise<ArchiveHomeSetLibraryPagePayload> => {
  const db = getDb();
  const safePage = Number.isFinite(page) && page > 0 ? Math.floor(page) : 1;
  const safeQuery = query.trim();

  const setIds = await getUserSetIds(db, userId);

  if (!setIds.length) {
    const artistCards = await getWorkspaceArtistCards(userId);
    return {
      artistFilter,
      artistOptions: ["ALL", ...artistCards.map((a) => a.name)],
      items: [],
      page: 1,
      pageSize: PAGE_SIZE,
      query: safeQuery,
      sort,
      totalItems: 0,
      totalPages: 1,
    };
  }

  const artistClause =
    artistFilter !== "ALL" ? sql`artist_name = ${artistFilter}` : sql`true`;
  const queryClause = safeQuery
    ? sql`(
        set_title ILIKE ${`%${safeQuery}%`}
        OR COALESCE(artist_name, '') ILIKE ${`%${safeQuery}%`}
        OR COALESCE(track_search_text, '') ILIKE ${`%${safeQuery}%`}
      )`
    : sql`true`;
  const setIdValues = setIds.map((id) => sql`${id}::uuid`);
  const setIdClause = sql`set_id IN (${sql.join(setIdValues, sql`, `)})`;
  const whereClause = sql`${setIdClause} AND ${artistClause} AND ${queryClause}`;
  const orderByClause = orderByForSetSort(sort);

  const countResult = await db.execute(sql<{ totalItems: number | string }>`
    SELECT count(*)::int AS "totalItems"
    FROM "app"."archive_home_set_library_index_mv"
    WHERE ${whereClause}
  `);

  const totalItems = numberOrZero(
    asRows<{ totalItems: number | string }>(countResult.rows)[0]?.totalItems,
  );
  const totalPages = Math.max(1, Math.ceil(totalItems / PAGE_SIZE));
  const safeResolvedPage = Math.max(1, Math.min(safePage, totalPages));
  const offset = (safeResolvedPage - 1) * PAGE_SIZE;

  const pageResult = await db.execute(sql<HomeSetLibraryRow>`
    SELECT
      set_id::text AS id,
      set_slug AS slug,
      set_title AS title,
      artist_slug AS "artistSlug",
      artist_name AS "artistName",
      confidence_counts AS "confidenceCounts",
      duration_seconds AS duration,
      mini_timeline AS "miniTimeline",
      recognition_rate AS "recognitionRate",
      source_platform AS "sourcePlatform",
      source_url AS "sourceUrl",
      thumbnail_url AS "thumbnailUrl",
      total_tracks AS "totalTracks"
    FROM "app"."archive_home_set_library_index_mv"
    WHERE ${whereClause}
    ${orderByClause}
    LIMIT ${PAGE_SIZE}
    OFFSET ${offset}
  `);

  const artistCards = await getWorkspaceArtistCards(userId);
  return {
    artistFilter,
    artistOptions: ["ALL", ...artistCards.map((a) => a.name)],
    items: asRows<HomeSetLibraryRow>(pageResult.rows).map(mapSetLibraryRow),
    page: safeResolvedPage,
    pageSize: PAGE_SIZE,
    query: safeQuery,
    sort,
    totalItems,
    totalPages,
  };
};

const getWorkspaceHeroSetCandidates = async (userId: string): Promise<ArchiveHomeHeroSet[]> => {
  const db = getDb();
  const result = await db.execute(sql<HomeHeroSetRow>`
    WITH user_sets AS (
      SELECT DISTINCT s.id
      FROM "app"."sets" s
      JOIN "ops"."set_runs" sr
        ON sr.source_url = s.source_url
       AND sr.requested_by = ${userId}
       AND sr.archive_removed_at IS NULL
    )
    SELECT
      library.set_id::text AS id,
      library.set_slug AS slug,
      library.set_title AS title,
      library.artist_slug AS "artistSlug",
      library.artist_name AS "artistName",
      library.thumbnail_url AS "thumbnailUrl",
      library.duration_seconds AS duration,
      library.recognition_rate AS "recognitionRate",
      library.total_tracks AS "totalTracks"
    FROM "app"."archive_home_set_library_index_mv" library
    JOIN user_sets
      ON user_sets.id = library.set_id
    WHERE library.thumbnail_url IS NOT NULL
      AND library.thumbnail_url <> ''
    ORDER BY library.sort_recognition_rate DESC, library.set_slug ASC
    LIMIT 160
  `);

  return asRows<HomeHeroSetRow>(result.rows).map<ArchiveHomeHeroSet>((row) => ({
    artistName: row.artistName ?? "Unknown Artist",
    artistSlug: row.artistSlug ?? "",
    duration: numberOrZero(row.duration),
    id: row.id,
    recognitionRate: nullableNumber(row.recognitionRate),
    slug: row.slug,
    thumbnailUrl: row.thumbnailUrl,
    title: row.title,
    totalTracks: numberOrZero(row.totalTracks),
  }));
};

export const getWorkspaceNetworkPayload = async (
  userId: string,
): Promise<ArchiveHomeNetworkIndexPayload> => {
  const artistCards = await getWorkspaceArtistCards(userId);
  if (!artistCards.length) {
    return { artists: [], edges: [] };
  }

  const slugSet = new Set(artistCards.map((a) => a.slug));
  const slugValues = [...slugSet].map((slug) => sql`${slug}`);

  const db = getDb();
  const edgeResult = await db.execute(sql<HomeNetworkEdgeRow>`
    SELECT
      artist_a_name AS "artistA",
      artist_a_slug AS "artistASlug",
      artist_b_name AS "artistB",
      artist_b_slug AS "artistBSlug",
      normalized_score AS "normalizedScore",
      score,
      shared_music_artists_count AS "sharedArtistsCount",
      shared_genres_count AS "sharedGenresCount",
      shared_labels_count AS "sharedLabelsCount",
      shared_tracks_count AS "sharedTracksCount"
    FROM "app"."archive_home_pair_summaries_mv"
    WHERE score > 0
      AND artist_a_slug IN (${sql.join(slugValues, sql`, `)})
      AND artist_b_slug IN (${sql.join(slugValues, sql`, `)})
    ORDER BY score DESC, artist_a_name ASC, artist_b_name ASC
  `);

  const networkArtists: ArchiveHomeNetworkArtist[] = artistCards.map((a) => ({
    id: a.id,
    name: a.name,
    setCount: a.setCount,
    slug: a.slug,
  }));

  return {
    artists: networkArtists,
    edges: asRows<HomeNetworkEdgeRow>(edgeResult.rows).map(mapNetworkEdgeRow),
  };
};

export const getArchiveHomeExplorerInitial = async ({
  artistFilter = "ALL",
  compareMode = "union",
  page = 1,
  query = "",
  scope = "global",
  selectedArtistSlugs,
  sort = "default",
  userId,
  viewerUserId,
}: {
  artistFilter?: string;
  compareMode?: ArchiveHomeCompareMode;
  page?: number;
  query?: string;
  scope?: "mine" | "global";
  selectedArtistSlugs?: string[];
  sort?: ArchiveHomeSetSort;
  userId?: string;
  viewerUserId?: string;
} = {}): Promise<ArchiveHomeBootstrapPayload> => {
  noStore();

  const isWorkspace = scope === "mine" && Boolean(userId);

  const [artistCardsRaw, globalStatsResult, initialNetwork, initialSetLibrary, heroSetCandidatesRaw, viewerScope] =
    await Promise.all([
      isWorkspace ? getWorkspaceArtistCards(userId!) : getHomeArtistCards(),
      isWorkspace ? getWorkspaceGlobalStats(userId!) : getHomeGlobalStats(),
      isWorkspace ? getWorkspaceNetworkPayload(userId!) : getArchiveHomeNetworkPayload(),
      isWorkspace
        ? getWorkspaceSetLibraryPayload({ artistFilter, page, query, sort, userId: userId! })
        : getArchiveHomeSetLibraryPayload({
            artistFilter,
            page,
            query,
            sort,
            viewerUserId,
          }),
      isWorkspace ? getWorkspaceHeroSetCandidates(userId!) : getHeroSetCandidates(),
      viewerUserId ? getViewerSubmittedScope(viewerUserId) : Promise.resolve(null),
    ]);
  const artistCards = viewerScope
    ? artistCardsRaw.map((artistCard) => ({
        ...artistCard,
        submittedByViewer: viewerScope.artistSlugs.has(artistCard.slug),
      }))
    : artistCardsRaw;
  const heroSetCandidates = viewerScope
    ? heroSetCandidatesRaw.map((setItem) => withSubmittedByViewer(setItem, viewerScope.setIds))
    : heroSetCandidatesRaw;

  const resolvedSelected =
    selectedArtistSlugs && selectedArtistSlugs.length > 0
      ? selectedArtistSlugs
      : artistCards[0]
        ? [artistCards[0].slug]
        : [];
  const initialAtlas = await getArchiveHomeAtlasPayload({
    compareMode,
    selectedArtistSlugs: resolvedSelected,
    userId: isWorkspace ? userId : undefined,
  });
  const tickerItems = buildTickerItems({
    edgeCount: initialNetwork.edges.length,
    stats: globalStatsResult.globalStats,
  });

  return {
    artistCards,
    generatedAt: globalStatsResult.generatedAt,
    globalStats: globalStatsResult.globalStats,
    hero: buildHomeHeroPayload({
      artistCards,
      heroSetCandidates,
      tickerItems,
    }),
    initialAtlas,
    initialNetwork,
    initialSetLibrary,
    scope,
  };
};


export const getArchiveHomeThresholdLevels = () => [...THRESHOLD_LEVELS];

export const archiveHomeTags = HOME_TAGS;
