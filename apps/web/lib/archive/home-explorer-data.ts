import "server-only";

import fs from "node:fs/promises";
import path from "node:path";

import { and, asc, eq, inArray, isNotNull } from "drizzle-orm";

import type {
  ArchiveHomeAtlasPayload,
  ArchiveHomeArtistCard,
  ArchiveHomeCompareMode,
  ArchiveHomeExplorerInitialPayload,
  ArchiveHomeNetworkArtist,
  ArchiveHomeNetworkEdge,
  ArchiveHomeNetworkPayload,
  ArchiveHomePairBucket,
  ArchiveHomePairPayload,
  ArchiveHomePairTrack,
  ArchiveHomeSetLibraryItem,
  ArchiveHomeSetLibraryPayload,
  ArchiveHomeSetLibraryTrack,
  ArchiveHomeSetSort,
  ArchiveHomeTrackArtistRef,
  ArchiveHomeTrackCatalogItem,
  ArchiveHomeTrackSetRef,
} from "@/lib/archive/home-explorer-types";
import type { ArchiveConfidence } from "@/lib/archive/types";
import {
  asRecord,
  buildSearchBlob,
  buildTrackKey,
  buildYouTubeThumbnail,
  formatDuration,
  getString,
  getNumber,
  getStringArray,
  normalizeLegacyPath,
  normalizeArchiveConfidence,
  normalizeSearchText,
} from "@/lib/archive/utils";
import { getDb } from "@/lib/db/client";
import { artists, setArtists, setEntries, sets, tracks } from "@/lib/db/schema";

const THRESHOLD_LEVELS = [1, 2, 3, 5, 8, 12] as const;
const EXCLUDED_HOME_GENRES = new Set(["House"]);
const HOME_EXPLORER_MAX_AGE_MS = 5 * 60 * 1000;

let homeExplorerIndexPromise: Promise<HomeExplorerIndex> | null = null;
let homeExplorerIndexResolvedAt = 0;
let homeExplorerSnapshotPromise: Promise<HomeExplorerIndex> | null = null;

type EntryRow = {
  confidence: string;
  detectionCount: number;
  displayArtist: string;
  displayTitle: string;
  endTimeSeconds: number | null;
  entryMetadata: unknown;
  position: number;
  setId: string;
  sourceDeepLink: string | null;
  startTimeSeconds: number;
  trackDiscogsUrl: string | null;
  trackId: string | null;
  trackMetadata: unknown;
  trackSpotifyUrl: string | null;
  trackYoutubeUrl: string | null;
};

type InternalSetTrack = {
  albumArt: string | null;
  artist: string;
  confidence: ArchiveConfidence;
  detailGenres: string[];
  discogsUrl: string | null;
  end: number | null;
  endTimeFormatted: string | null;
  genres: string[];
  key: string | null;
  label: string | null;
  labelUrl: string | null;
  position: number;
  previewUrl: string | null;
  sourceDeepLink: string | null;
  spotifyUrl: string | null;
  start: number;
  startTimeFormatted: string;
  title: string;
  youtubeUrl: string | null;
};

type InternalArtistTrack = {
  albumArt: string | null;
  artist: string;
  artistImage: string | null;
  artistProfileImage: string | null;
  appearances: number;
  confidenceCounts: Record<ArchiveConfidence, number>;
  genres: string[];
  label: string | null;
  labelUrl: string | null;
  setRefs: ArchiveHomeTrackSetRef[];
  spotifyUrl: string | null;
  title: string;
  trackKey: string;
};

type InternalArtistState = {
  artistCard: ArchiveHomeArtistCard;
  coverImageUrl: string | null;
  genreCounts: Map<string, number>;
  imageUrl: string | null;
  labelCounts: Map<string, number>;
  musicArtistCounts: Map<string, number>;
  name: string;
  slug: string;
  tracks: Map<string, InternalArtistTrack>;
};

type HomeExplorerIndex = {
  allSets: ArchiveHomeSetLibraryItem[];
  artistCards: ArchiveHomeArtistCard[];
  connectionEdgeCount: number;
  generatedAt: string | null;
  globalStats: ArchiveHomeExplorerInitialPayload["globalStats"];
  networkArtists: ArchiveHomeNetworkArtist[];
  networkEdges: ArchiveHomeNetworkEdge[];
  pairMap: Map<string, ArchiveHomePairPayload>;
  tickerItems: string[];
  trackCatalog: ArchiveHomeTrackCatalogItem[];
};

const emptyConfidenceCounts = (): Record<ArchiveConfidence, number> => ({
  HIGH: 0,
  LOW: 0,
  MEDIUM: 0,
  UNCERTAIN: 0,
});

const incrementConfidence = (
  counts: Record<ArchiveConfidence, number>,
  confidence: ArchiveConfidence,
) => {
  counts[confidence] += 1;
};

const formatHomeGenre = (value: string) =>
  value
    .trim()
    .toLowerCase()
    .replace(/\b[a-z]/g, (letter) => letter.toUpperCase());

const normalizeHomeGenres = (metadata: Record<string, unknown>) =>
  Array.from(
    new Set(
      [
        ...getStringArray(metadata.discogs_styles),
        ...getStringArray(metadata.spotify_genres),
        ...getStringArray(metadata.discogs_genres),
      ]
        .map(formatHomeGenre)
        .filter((genre) => genre.length > 0 && !EXCLUDED_HOME_GENRES.has(genre)),
    ),
  );

const formatHomeGeneratedAt = (value: Date | null) => {
  if (!value) {
    return null;
  }

  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  const hours = String(value.getHours()).padStart(2, "0");
  const minutes = String(value.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day} ${hours}:${minutes}`;
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

const pairKey = (artistASlug: string, artistBSlug: string) =>
  [artistASlug, artistBSlug].sort().join("::");

const randomShuffle = <T,>(items: T[]) => {
  const output = [...items];
  for (let index = output.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    [output[index], output[swapIndex]] = [output[swapIndex]!, output[index]!];
  }
  return output;
};

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

const buildArtifactCandidates = (filename: string) => {
  const cwd = process.cwd();
  const segments = ["output", filename];

  return Array.from(
    new Set([
      path.resolve(cwd, ...segments),
      path.resolve(cwd, "..", ...segments),
      path.resolve(cwd, "..", "..", ...segments),
    ]),
  );
};

const readFirstExistingJson = async <T>(filename: string): Promise<T> => {
  for (const candidate of buildArtifactCandidates(filename)) {
    try {
      return JSON.parse(await fs.readFile(candidate, "utf8")) as T;
    } catch (error) {
      if (
        error &&
        typeof error === "object" &&
        "code" in error &&
        (error as NodeJS.ErrnoException).code === "ENOENT"
      ) {
        continue;
      }
      throw error;
    }
  }

  throw new Error(`Unable to locate archive artifact: ${filename}`);
};

const normalizeConfidenceCounts = (
  value: unknown,
): Record<ArchiveConfidence, number> => {
  const safe = asRecord(value);
  return {
    HIGH: Math.max(0, Number(getNumber(safe.HIGH) ?? 0)),
    LOW: Math.max(0, Number(getNumber(safe.LOW) ?? 0)),
    MEDIUM: Math.max(0, Number(getNumber(safe.MEDIUM) ?? 0)),
    UNCERTAIN: Math.max(0, Number(getNumber(safe.UNCERTAIN) ?? 0)),
  };
};

const buildSnapshotSlug = (legacyPath: string | null, fallbackLabel?: string | null) =>
  legacyPath
    ? `legacy:${normalizeLegacyPath(legacyPath)}`
    : `legacy:${normalizeSearchText(fallbackLabel ?? "unknown").replace(/\s+/gu, "-")}`;

const parseTrackPositionFromHref = (href: string | null | undefined) => {
  const matched = String(href ?? "").match(/#track-(\d+)$/u);
  return matched ? Number(matched[1]) : 0;
};

type SnapshotArtist = {
  artist_image?: unknown;
  cover_image?: unknown;
  html_rel?: unknown;
  name?: unknown;
  sets_analyzed?: unknown;
  total_appearances?: unknown;
  unique_tracks?: unknown;
};

type SnapshotTrackArtistRef = {
  appearances?: unknown;
  artist_name?: unknown;
  dir_name?: unknown;
  set_refs?: unknown;
};

type SnapshotTrackCatalogItem = {
  album_art?: unknown;
  artist?: unknown;
  artist_image?: unknown;
  artist_profile_image?: unknown;
  artist_refs?: unknown;
  artists_count?: unknown;
  confidence?: unknown;
  confidence_counts?: unknown;
  genres?: unknown;
  label?: unknown;
  label_url?: unknown;
  spotify_url?: unknown;
  title?: unknown;
  total_appearances?: unknown;
  track_key?: unknown;
};

type SnapshotSet = {
  artist_html_rel?: unknown;
  artist_name?: unknown;
  confidence_counts?: unknown;
  duration?: unknown;
  mini_timeline?: unknown;
  recognition_rate?: unknown;
  set_html_master_rel?: unknown;
  thumbnail_url?: unknown;
  title?: unknown;
  total_tracks?: unknown;
  track_search_text?: unknown;
  tracks?: unknown;
  url?: unknown;
};

type SnapshotPairBucket = {
  count_a?: unknown;
  count_b?: unknown;
  genre?: unknown;
  label?: unknown;
  music_artist?: unknown;
  track_keys?: unknown;
};

type SnapshotPairTrack = {
  appearances_a?: unknown;
  appearances_b?: unknown;
  confidence?: unknown;
  confidence_counts?: unknown;
  discogs_label?: unknown;
  discogs_label_url?: unknown;
  display_artist?: unknown;
  display_title?: unknown;
  genres?: unknown;
  sets_a?: unknown;
  sets_b?: unknown;
  spotify_album_art?: unknown;
  spotify_artist_profile_image?: unknown;
  spotify_url?: unknown;
  track_key?: unknown;
};

type SnapshotSimilarity = {
  artist_a?: unknown;
  artist_b?: unknown;
  normalized_score?: unknown;
  score?: unknown;
  shared_artists_count?: unknown;
  shared_genres?: unknown;
  shared_genres_count?: unknown;
  shared_labels?: unknown;
  shared_labels_count?: unknown;
  shared_music_artists?: unknown;
  shared_tracks?: unknown;
  shared_tracks_count?: unknown;
};

type SnapshotExplorerData = {
  all_sets?: SnapshotSet[];
  artists?: SnapshotArtist[];
  generated_at?: unknown;
  global_stats?: unknown;
  similarity?: SnapshotSimilarity[];
  track_catalog?: SnapshotTrackCatalogItem[];
};

const buildSnapshotSetRef = ({
  href,
  setLegacyByHref,
  setSlugByLegacyPath,
  title,
  trackPosition,
}: {
  href: string | null;
  setLegacyByHref: Map<string, string>;
  setSlugByLegacyPath: Map<string, string>;
  title: string;
  trackPosition: number | null;
}): ArchiveHomeTrackSetRef => {
  const normalizedHref = href ? normalizeLegacyPath(href.split("#")[0] ?? href) : null;
  const setLegacyPath = normalizedHref ? setLegacyByHref.get(normalizedHref) ?? normalizedHref : null;
  return {
    confidence: normalizeArchiveConfidence("UNCERTAIN"),
    setLegacyPath,
    setSlug: setLegacyPath ? (setSlugByLegacyPath.get(setLegacyPath) ?? buildSnapshotSlug(setLegacyPath)) : "",
    title,
    trackPosition: Math.max(0, trackPosition ?? (href ? parseTrackPositionFromHref(href) : 0)),
  };
};

const mapEntryToTrack = (row: EntryRow): InternalSetTrack => {
  const entryMetadata = asRecord(row.entryMetadata);
  const trackMetadata = asRecord(row.trackMetadata);
  const merged = { ...trackMetadata, ...entryMetadata };
  const confidence = normalizeArchiveConfidence(row.confidence);

  return {
    albumArt:
      getString(merged.spotify_album_art) ??
      getString(merged.albumArt) ??
      null,
    artist: row.displayArtist,
    confidence,
    detailGenres: Array.from(
      new Set(
        [
          ...getStringArray(merged.discogs_styles),
          ...getStringArray(merged.discogs_genres),
          ...getStringArray(merged.spotify_genres),
        ].filter((genre) => genre.trim().length > 0),
      ),
    ),
    discogsUrl: row.trackDiscogsUrl ?? getString(merged.discogs_url),
    end: row.endTimeSeconds,
    endTimeFormatted:
      getString(merged.end_time_formatted) ??
      getString(merged.endTimeFormatted) ??
      (row.endTimeSeconds != null ? formatDuration(row.endTimeSeconds) : null),
    genres: normalizeHomeGenres(merged),
    key: getString(merged.key),
    label: getString(merged.discogs_label),
    labelUrl: getString(merged.discogs_label_url),
    position: row.position,
    previewUrl:
      getString(merged.spotify_preview_url) ??
      getString(merged.previewUrl) ??
      null,
    sourceDeepLink: row.sourceDeepLink ?? getString(merged.source_deep_link),
    spotifyUrl: row.trackSpotifyUrl ?? getString(merged.spotify_url),
    start: row.startTimeSeconds,
    startTimeFormatted:
      getString(merged.start_time_formatted) ??
      getString(merged.startTimeFormatted) ??
      formatDuration(row.startTimeSeconds),
    title: row.displayTitle,
    youtubeUrl: row.trackYoutubeUrl ?? getString(merged.youtube_url),
  };
};

const buildSetLibraryTrack = (
  setSlug: string,
  setLegacyPath: string | null,
  track: InternalSetTrack,
): ArchiveHomeSetLibraryTrack => ({
  artist: track.artist,
  confidence: track.confidence,
  position: track.position,
  spotifyUrl: track.spotifyUrl,
  startTimeFormatted: track.startTimeFormatted,
  title: track.title,
  trackKey: buildTrackKey(track.artist, track.title),
  trackLegacyPath: setLegacyPath,
  trackSetSlug: setSlug,
});

const buildMiniTimeline = (
  setTracks: InternalSetTrack[],
  duration: number,
): ArchiveHomeSetLibraryItem["miniTimeline"] => {
  if (duration <= 0) {
    return [];
  }

  return setTracks.map((track) => {
    const end = track.end ?? duration;
    return {
      confidence: track.confidence,
      startPct: Math.max(0, Math.min(100, (track.start / duration) * 100)),
      widthPct: Math.max(1, Math.min(100, ((end - track.start) / duration) * 100)),
    };
  });
};

const buildExplorerIndexUncached = async (): Promise<HomeExplorerIndex> => {
  const db = getDb();
  const [artistRows, setJoinRows] = await Promise.all([
    db
      .select({
        id: artists.id,
        imageUrl: artists.imageUrl,
        legacyPath: artists.legacyPath,
        metadata: artists.metadata,
        name: artists.name,
        slug: artists.slug,
      })
      .from(artists)
      .where(isNotNull(artists.legacyPath))
      .orderBy(asc(artists.name)),
    db
      .select({
        artistId: artists.id,
        artistLegacyPath: artists.legacyPath,
        artistName: artists.name,
        artistSlug: artists.slug,
        durationSeconds: sets.durationSeconds,
        id: sets.id,
        imageUrl: sets.imageUrl,
        legacyPath: sets.legacyPath,
        metadata: sets.metadata,
        recognitionRate: sets.recognitionRate,
        slug: sets.slug,
        sourcePlatform: sets.sourcePlatform,
        sourceUrl: sets.sourceUrl,
        title: sets.title,
        updatedAt: sets.updatedAt,
      })
      .from(setArtists)
      .innerJoin(artists, eq(artists.id, setArtists.artistId))
      .innerJoin(sets, eq(sets.id, setArtists.setId))
      .where(
        and(
          eq(setArtists.role, "primary"),
          isNotNull(artists.legacyPath),
          isNotNull(sets.legacyPath),
        ),
      )
      .orderBy(asc(artists.name), asc(sets.title)),
  ]);

  const artistStates = new Map<string, InternalArtistState>();
  for (const artistRow of artistRows) {
    artistStates.set(artistRow.id, {
      artistCard: {
        id: artistRow.id,
        imageUrl: artistRow.imageUrl,
        legacyPath: artistRow.legacyPath,
        name: artistRow.name,
        setCount: 0,
        slug: artistRow.slug,
        totalAppearances: 0,
        uniqueTracks: 0,
      },
      coverImageUrl: null,
      genreCounts: new Map(),
      imageUrl: artistRow.imageUrl,
      labelCounts: new Map(),
      musicArtistCounts: new Map(),
      name: artistRow.name,
      slug: artistRow.slug,
      tracks: new Map(),
    });
  }

  const setRows = setJoinRows;
  const setIds = Array.from(new Set(setRows.map((row) => row.id)));
  const entryRows = setIds.length
    ? await db
        .select({
          confidence: setEntries.confidence,
          detectionCount: setEntries.detectionCount,
          displayArtist: setEntries.displayArtist,
          displayTitle: setEntries.displayTitle,
          endTimeSeconds: setEntries.endTimeSeconds,
          entryMetadata: setEntries.metadata,
          position: setEntries.position,
          setId: setEntries.setId,
          sourceDeepLink: setEntries.sourceDeepLink,
          startTimeSeconds: setEntries.startTimeSeconds,
          trackDiscogsUrl: tracks.discogsUrl,
          trackId: tracks.id,
          trackMetadata: tracks.metadata,
          trackSpotifyUrl: tracks.spotifyUrl,
          trackYoutubeUrl: tracks.youtubeUrl,
        })
        .from(setEntries)
        .leftJoin(tracks, eq(tracks.id, setEntries.trackId))
        .where(inArray(setEntries.setId, setIds))
        .orderBy(asc(setEntries.setId), asc(setEntries.position))
    : [];

  const rowsBySetId = new Map<string, EntryRow[]>();
  for (const row of entryRows) {
    if (!rowsBySetId.has(row.setId)) {
      rowsBySetId.set(row.setId, []);
    }
    rowsBySetId.get(row.setId)!.push(row);
  }

  const allSets: ArchiveHomeSetLibraryItem[] = [];
  const allConfidenceCounts = emptyConfidenceCounts();
  let unknownTracks = 0;
  let totalTrackEntries = 0;
  let latestUpdatedAt: Date | null = null;

  for (const setRow of setRows) {
    const setTracks = (rowsBySetId.get(setRow.id) ?? []).map(mapEntryToTrack);
    const artistState = artistStates.get(setRow.artistId);
    if (!artistState) {
      continue;
    }

    const duration = Number(setRow.durationSeconds ?? 0);
    const confidenceCounts = emptyConfidenceCounts();
    const recognizedTracks: InternalSetTrack[] = [];

    for (const track of setTracks) {
      totalTrackEntries += 1;
      incrementConfidence(allConfidenceCounts, track.confidence);
      incrementConfidence(confidenceCounts, track.confidence);

      if (normalizeSearchText(track.title) === "unknown track") {
        unknownTracks += 1;
        continue;
      }

      recognizedTracks.push(track);
      const trackKey = buildTrackKey(track.artist, track.title);
      const existing =
        artistState.tracks.get(trackKey) ??
        {
          albumArt: track.albumArt,
          artist: track.artist,
          artistImage: track.albumArt,
          artistProfileImage: track.albumArt,
          appearances: 0,
          confidenceCounts: emptyConfidenceCounts(),
          genres: track.genres,
          label: track.label,
          labelUrl: track.labelUrl,
          setRefs: [],
          spotifyUrl: track.spotifyUrl,
          title: track.title,
          trackKey,
        };

      existing.appearances += 1;
      incrementConfidence(existing.confidenceCounts, track.confidence);
      if (!existing.albumArt && track.albumArt) {
        existing.albumArt = track.albumArt;
      }
      if (!existing.spotifyUrl && track.spotifyUrl) {
        existing.spotifyUrl = track.spotifyUrl;
      }
      if (!existing.label && track.label) {
        existing.label = track.label;
      }
      if (!existing.labelUrl && track.labelUrl) {
        existing.labelUrl = track.labelUrl;
      }
      if (!existing.genres.length && track.genres.length) {
        existing.genres = [...track.genres];
      }
      existing.setRefs.push({
        confidence: track.confidence,
        setLegacyPath: setRow.legacyPath,
        setSlug: setRow.slug,
        title: setRow.title,
        trackPosition: track.position,
      });

      artistState.tracks.set(trackKey, existing);
    }

    const item: ArchiveHomeSetLibraryItem = {
      artistLegacyPath: setRow.artistLegacyPath,
      artistName: setRow.artistName,
      artistSlug: setRow.artistSlug,
      confidenceCounts,
      duration,
      id: setRow.id,
      legacyPath: setRow.legacyPath,
      miniTimeline: buildMiniTimeline(setTracks, duration),
      recognitionRate:
        setRow.recognitionRate != null
          ? Number(setRow.recognitionRate)
          : setTracks.length > 0
            ? (recognizedTracks.length / setTracks.length) * 100
            : null,
      slug: setRow.slug,
      sourceUrl: setRow.sourceUrl,
      thumbnailUrl: resolveDirectSetImage(setRow),
      title: setRow.title,
      totalTracks: setTracks.length,
      tracks: recognizedTracks.map((track) =>
        buildSetLibraryTrack(setRow.slug, setRow.legacyPath, track),
      ),
      trackSearchText: buildSearchBlob(
        ...recognizedTracks.flatMap((track) => [track.artist, track.title]),
      ),
    };

    allSets.push(item);
    artistState.artistCard.setCount += 1;
    if (!artistState.coverImageUrl && item.thumbnailUrl) {
      artistState.coverImageUrl = item.thumbnailUrl;
      artistState.artistCard.imageUrl = artistState.artistCard.imageUrl ?? item.thumbnailUrl;
    }
    if (setRow.updatedAt && (!latestUpdatedAt || setRow.updatedAt > latestUpdatedAt)) {
      latestUpdatedAt = setRow.updatedAt;
    }
  }

  const artistCards = Array.from(artistStates.values())
    .map<ArchiveHomeArtistCard>((state) => {
      state.genreCounts.clear();
      state.labelCounts.clear();
      state.musicArtistCounts.clear();
      for (const track of state.tracks.values()) {
        if (track.label?.trim()) {
          state.labelCounts.set(track.label, (state.labelCounts.get(track.label) ?? 0) + 1);
        }
        if (track.artist.trim() && normalizeSearchText(track.artist) !== "unknown") {
          state.musicArtistCounts.set(
            track.artist,
            (state.musicArtistCounts.get(track.artist) ?? 0) + 1,
          );
        }
        for (const genre of track.genres) {
          if (!genre.trim()) {
            continue;
          }
          state.genreCounts.set(genre, (state.genreCounts.get(genre) ?? 0) + 1);
        }
      }
      state.artistCard.uniqueTracks = state.tracks.size;
      state.artistCard.totalAppearances = Array.from(state.tracks.values()).reduce(
        (total, track) => total + track.appearances,
        0,
      );
      state.artistCard.imageUrl = state.artistCard.imageUrl ?? state.coverImageUrl;
      return state.artistCard;
    })
    .filter((card) => card.setCount > 0)
    .sort((left, right) => left.name.localeCompare(right.name));

  const networkArtists: ArchiveHomeNetworkArtist[] = artistCards.map((card) => ({
    id: card.id,
    legacyPath: card.legacyPath,
    name: card.name,
    setCount: card.setCount,
    slug: card.slug,
  }));

  const trackCatalogMap = new Map<string, ArchiveHomeTrackCatalogItem>();
  for (const state of artistStates.values()) {
    if (!state.artistCard.setCount) {
      continue;
    }

    for (const track of state.tracks.values()) {
      const artistRef: ArchiveHomeTrackArtistRef = {
        appearances: track.appearances,
        artistLegacyPath: state.artistCard.legacyPath,
        artistName: state.name,
        artistSlug: state.slug,
        setRefs: [...track.setRefs],
      };

      const existing = trackCatalogMap.get(track.trackKey);
      if (!existing) {
        trackCatalogMap.set(track.trackKey, {
          albumArt: track.albumArt,
          artist: track.artist,
          artistImage: track.artistImage ?? state.artistCard.imageUrl,
          artistProfileImage: track.artistProfileImage ?? state.artistCard.imageUrl,
          artistRefs: [artistRef],
          artistsCount: 1,
          confidence: primaryConfidenceFromCounts(track.confidenceCounts),
          confidenceCounts: { ...track.confidenceCounts },
          genres: [...track.genres],
          label: track.label,
          labelUrl: track.labelUrl,
          spotifyUrl: track.spotifyUrl,
          title: track.title,
          totalAppearances: track.appearances,
          trackKey: track.trackKey,
        });
        continue;
      }

      existing.artistRefs.push(artistRef);
      existing.artistsCount = existing.artistRefs.length;
      existing.totalAppearances += track.appearances;
      for (const level of ["HIGH", "MEDIUM", "LOW", "UNCERTAIN"] as const) {
        existing.confidenceCounts[level] += track.confidenceCounts[level];
      }
      existing.confidence = primaryConfidenceFromCounts(existing.confidenceCounts);
      if (!existing.albumArt && track.albumArt) {
        existing.albumArt = track.albumArt;
      }
      if (!existing.spotifyUrl && track.spotifyUrl) {
        existing.spotifyUrl = track.spotifyUrl;
      }
      if (!existing.label && track.label) {
        existing.label = track.label;
      }
      if (!existing.labelUrl && track.labelUrl) {
        existing.labelUrl = track.labelUrl;
      }
      if (!existing.artistImage && state.artistCard.imageUrl) {
        existing.artistImage = state.artistCard.imageUrl;
      }
      if (!existing.artistProfileImage && state.artistCard.imageUrl) {
        existing.artistProfileImage = state.artistCard.imageUrl;
      }
      if (!existing.genres.length && track.genres.length) {
        existing.genres = [...track.genres];
      }
    }
  }

  const trackCatalog = Array.from(trackCatalogMap.values()).sort((left, right) => {
    if (right.totalAppearances !== left.totalAppearances) {
      return right.totalAppearances - left.totalAppearances;
    }
    return `${left.artist} ${left.title}`.localeCompare(`${right.artist} ${right.title}`);
  });

  const pairMap = new Map<string, ArchiveHomePairPayload>();
  const networkEdges: ArchiveHomeNetworkEdge[] = [];
  const artistStatesList = Array.from(artistStates.values()).filter(
    (state) => state.artistCard.setCount > 0,
  );

  let maxPairScore = 1;
  const rawPairs: Array<{
    artistA: InternalArtistState;
    artistB: InternalArtistState;
    payload: ArchiveHomePairPayload;
  }> = [];

  for (let leftIndex = 0; leftIndex < artistStatesList.length; leftIndex += 1) {
    for (
      let rightIndex = leftIndex + 1;
      rightIndex < artistStatesList.length;
      rightIndex += 1
    ) {
      const artistA = artistStatesList[leftIndex]!;
      const artistB = artistStatesList[rightIndex]!;
      const sharedTrackKeys = Array.from(artistA.tracks.keys()).filter((trackKey) =>
        artistB.tracks.has(trackKey),
      );

      const sharedTracks: ArchiveHomePairTrack[] = sharedTrackKeys
        .map((trackKey) => {
          const leftTrack = artistA.tracks.get(trackKey)!;
          const rightTrack = artistB.tracks.get(trackKey)!;
          const confidenceCounts = emptyConfidenceCounts();
          for (const level of ["HIGH", "MEDIUM", "LOW", "UNCERTAIN"] as const) {
            confidenceCounts[level] =
              leftTrack.confidenceCounts[level] + rightTrack.confidenceCounts[level];
          }
          return {
            albumArt: leftTrack.albumArt ?? rightTrack.albumArt,
            appearancesA: leftTrack.appearances,
            appearancesB: rightTrack.appearances,
            artist: leftTrack.artist,
            artistImage: leftTrack.artistImage ?? rightTrack.artistImage,
            artistProfileImage:
              leftTrack.artistProfileImage ?? rightTrack.artistProfileImage,
            confidence: primaryConfidenceFromCounts(confidenceCounts),
            confidenceCounts,
            genres: leftTrack.genres.length ? leftTrack.genres : rightTrack.genres,
            label: leftTrack.label ?? rightTrack.label,
            labelUrl: leftTrack.labelUrl ?? rightTrack.labelUrl,
            setsA: [...leftTrack.setRefs],
            setsB: [...rightTrack.setRefs],
            spotifyUrl: leftTrack.spotifyUrl ?? rightTrack.spotifyUrl,
            title: leftTrack.title,
            trackKey,
          };
        })
        .sort((left, right) => {
          const leftTotal = left.appearancesA + left.appearancesB;
          const rightTotal = right.appearancesA + right.appearancesB;
          if (rightTotal !== leftTotal) {
            return rightTotal - leftTotal;
          }
          return `${left.artist} ${left.title}`.localeCompare(`${right.artist} ${right.title}`);
        });

      const buildBucketMap = ({
        leftCounts,
        rightCounts,
        pickTrackKeys,
      }: {
        leftCounts: Map<string, number>;
        pickTrackKeys: (track: ArchiveHomePairTrack, key: string) => boolean;
        rightCounts: Map<string, number>;
      }): ArchiveHomePairBucket[] => {
        const sharedKeys = Array.from(leftCounts.keys()).filter((key) => rightCounts.has(key));
        return sharedKeys
          .map((key) => ({
            countA: leftCounts.get(key) ?? 0,
            countB: rightCounts.get(key) ?? 0,
            id: key,
            name: key,
            trackKeys: sharedTracks
              .filter((track) => pickTrackKeys(track, key))
              .map((track) => track.trackKey),
          }))
          .sort((left, right) => {
            const leftTotal = left.countA + left.countB;
            const rightTotal = right.countA + right.countB;
            if (rightTotal !== leftTotal) {
              return rightTotal - leftTotal;
            }
            return left.name.localeCompare(right.name);
          });
      };

      const sharedLabels = buildBucketMap({
        leftCounts: artistA.labelCounts,
        pickTrackKeys: (track, key) => track.label === key,
        rightCounts: artistB.labelCounts,
      });
      const sharedMusicArtists = buildBucketMap({
        leftCounts: artistA.musicArtistCounts,
        pickTrackKeys: (track, key) => track.artist === key,
        rightCounts: artistB.musicArtistCounts,
      });
      const sharedGenres = buildBucketMap({
        leftCounts: artistA.genreCounts,
        pickTrackKeys: (track, key) => track.genres.includes(key),
        rightCounts: artistB.genreCounts,
      });
      const score = sharedTracks.length * 3 + sharedLabels.length + sharedMusicArtists.length;
      maxPairScore = Math.max(maxPairScore, score);

      rawPairs.push({
        artistA,
        artistB,
        payload: {
          artistA: {
            id: artistA.artistCard.id,
            legacyPath: artistA.artistCard.legacyPath,
            name: artistA.name,
            setCount: artistA.artistCard.setCount,
            slug: artistA.slug,
          },
          artistB: {
            id: artistB.artistCard.id,
            legacyPath: artistB.artistCard.legacyPath,
            name: artistB.name,
            setCount: artistB.artistCard.setCount,
            slug: artistB.slug,
          },
          normalizedScore: 0,
          score,
          sharedGenres,
          sharedGenresCount: sharedGenres.length,
          sharedLabels,
          sharedLabelsCount: sharedLabels.length,
          sharedMusicArtists,
          sharedMusicArtistsCount: sharedMusicArtists.length,
          sharedTracks,
          sharedTracksCount: sharedTracks.length,
        },
      });
    }
  }

  for (const pair of rawPairs) {
    const normalizedScore =
      maxPairScore > 0 ? Math.round((pair.payload.score / maxPairScore) * 100) : 0;
    const payload: ArchiveHomePairPayload = {
      ...pair.payload,
      normalizedScore,
    };

    pairMap.set(pairKey(pair.artistA.slug, pair.artistB.slug), payload);
    if (payload.score <= 0) {
      continue;
    }

    networkEdges.push({
      artistA: pair.artistA.name,
      artistALegacyPath: pair.artistA.artistCard.legacyPath,
      artistASlug: pair.artistA.slug,
      artistB: pair.artistB.name,
      artistBLegacyPath: pair.artistB.artistCard.legacyPath,
      artistBSlug: pair.artistB.slug,
      normalizedScore,
      score: payload.score,
      sharedArtistsCount: payload.sharedMusicArtistsCount,
      sharedGenresCount: payload.sharedGenresCount,
      sharedLabelsCount: payload.sharedLabelsCount,
      sharedTracksCount: payload.sharedTracksCount,
    });
  }

  networkEdges.sort((left, right) => {
    if (right.score !== left.score) {
      return right.score - left.score;
    }
    return `${left.artistA} ${left.artistB}`.localeCompare(
      `${right.artistA} ${right.artistB}`,
    );
  });

  const generatedAt = formatHomeGeneratedAt(latestUpdatedAt);
  const totalAppearances = trackCatalog.reduce(
    (total, track) => total + track.totalAppearances,
    0,
  );
  const tickerBase = [
    `Artists ${artistCards.length.toLocaleString("en-US")}`,
    `Sets ${artistCards
      .reduce((total, artistCard) => total + artistCard.setCount, 0)
      .toLocaleString("en-US")}`,
    `Unique tracks ${trackCatalog.length.toLocaleString("en-US")}`,
    `Appearances ${totalAppearances.toLocaleString("en-US")}`,
    `Connection edges ${networkEdges.length.toLocaleString("en-US")}`,
  ];

  return {
    allSets,
    artistCards,
    connectionEdgeCount: networkEdges.length,
    generatedAt,
    globalStats: {
      confidenceBreakdown: allConfidenceCounts,
      totalAppearances,
      totalArtists: artistCards.length,
      totalSets: artistCards.reduce((total, artistCard) => total + artistCard.setCount, 0),
      totalUniqueTracks: trackCatalog.length,
      unknownRatio: totalTrackEntries > 0 ? unknownTracks / totalTrackEntries : 0,
    },
    networkArtists,
    networkEdges,
    pairMap,
    tickerItems: tickerBase,
    trackCatalog,
  };
};

const getHomeExplorerIndex = async () => {
  const now = Date.now();
  if (
    homeExplorerIndexPromise &&
    now - homeExplorerIndexResolvedAt < HOME_EXPLORER_MAX_AGE_MS
  ) {
    return homeExplorerIndexPromise;
  }

  homeExplorerIndexPromise = buildExplorerIndexUncached().then((value) => {
    homeExplorerIndexResolvedAt = Date.now();
    return value;
  });

  return homeExplorerIndexPromise;
};

const buildHeroPayload = (index: HomeExplorerIndex) => {
  const candidateSets = index.allSets.filter((setItem) => Boolean(setItem.thumbnailUrl?.trim()));
  const railBase = candidateSets.length ? candidateSets : index.allSets;
  const shuffledSets = randomShuffle(railBase);
  const railSets: ArchiveHomeExplorerInitialPayload["hero"]["railSets"] = [];
  if (shuffledSets.length) {
    const targetCount = Math.max(8, Math.min(12, shuffledSets.length * 2));
    for (let indexValue = 0; indexValue < targetCount; indexValue += 1) {
      const setItem = shuffledSets[indexValue % shuffledSets.length]!;
      railSets.push({
        artistLegacyPath: setItem.artistLegacyPath,
        artistName: setItem.artistName,
        artistSlug: setItem.artistSlug,
        duration: setItem.duration,
        id: setItem.id,
        legacyPath: setItem.legacyPath,
        recognitionRate: setItem.recognitionRate,
        slug: setItem.slug,
        thumbnailUrl: setItem.thumbnailUrl,
        title: setItem.title,
        totalTracks: setItem.totalTracks,
      });
    }
  }

  const imagePool = index.artistCards.filter((artistCard) => Boolean(artistCard.imageUrl));
  const heroArtist = imagePool.length ? randomShuffle(imagePool)[0]! : null;
  const heroImage = heroArtist?.imageUrl ?? railSets.find((setItem) => setItem.thumbnailUrl)?.thumbnailUrl ?? null;

  return {
    imageAlt: heroArtist ? `${heroArtist.name} artist profile image` : "Set signal visual",
    imageUrl: heroImage,
    railSets,
    tickerItems: index.tickerItems,
  };
};

const buildAtlasPayload = ({
  compareMode,
  index,
  selectedArtistSlugs,
}: {
  compareMode: ArchiveHomeCompareMode;
  index: HomeExplorerIndex;
  selectedArtistSlugs: string[];
}): ArchiveHomeAtlasPayload => {
  const validSlugs = selectedArtistSlugs.filter((slug) =>
    index.artistCards.some((artistCard) => artistCard.slug === slug),
  );
  const resolvedSelected =
    validSlugs.length > 0 ? validSlugs : index.artistCards[0] ? [index.artistCards[0].slug] : [];

  return {
    allArtistsSelected:
      resolvedSelected.length > 0 && resolvedSelected.length === index.artistCards.length,
    artistCards: index.artistCards,
    compareMode,
    focusArtistSlug: resolvedSelected[0] ?? null,
    generatedAt: index.generatedAt,
    selectedArtistSlugs: resolvedSelected,
    tickerItems: index.tickerItems,
    trackCatalog: index.trackCatalog,
  };
};

const buildSetLibraryPayload = ({
  artistFilter,
  index,
  page,
  pageSize,
  query,
  sort,
}: {
  artistFilter: string;
  index: HomeExplorerIndex;
  page: number;
  pageSize: number;
  query: string;
  sort: ArchiveHomeSetSort;
}): ArchiveHomeSetLibraryPayload => {
  const normalizedQuery = normalizeSearchText(query);
  let items = index.allSets.filter((setItem) => {
    if (artistFilter !== "ALL" && setItem.artistName !== artistFilter) {
      return false;
    }
    if (!normalizedQuery) {
      return true;
    }
    return normalizeSearchText(
      `${setItem.title} ${setItem.artistName} ${setItem.trackSearchText}`,
    ).includes(normalizedQuery);
  });

  items = [...items].sort((left, right) => {
    if (sort === "rate") {
      return (right.recognitionRate ?? 0) - (left.recognitionRate ?? 0);
    }
    if (sort === "tracks") {
      return right.totalTracks - left.totalTracks;
    }
    if (sort === "duration") {
      return right.duration - left.duration;
    }
    return left.artistName.localeCompare(right.artistName) || left.title.localeCompare(right.title);
  });

  const safePageSize = Math.max(1, Math.min(48, Math.floor(pageSize)));
  const totalItems = items.length;
  const totalPages = Math.max(1, Math.ceil(totalItems / safePageSize));
  const safePage = Math.max(1, Math.min(totalPages, Math.floor(page)));
  const startIndex = (safePage - 1) * safePageSize;

  return {
    artistFilter,
    artistOptions: ["ALL", ...index.artistCards.map((artistCard) => artistCard.name)],
    items: items.slice(startIndex, startIndex + safePageSize),
    page: safePage,
    pageSize: safePageSize,
    query,
    sort,
    totalItems,
    totalPages,
  };
};

const buildHomeExplorerInitialPayload = ({
  artistFilter = "ALL",
  compareMode = "union",
  index,
  page = 1,
  query = "",
  selectedArtistSlugs,
  sort = "default",
}: {
  artistFilter?: string;
  compareMode?: ArchiveHomeCompareMode;
  index: HomeExplorerIndex;
  page?: number;
  query?: string;
  selectedArtistSlugs?: string[];
  sort?: ArchiveHomeSetSort;
}): ArchiveHomeExplorerInitialPayload => ({
  allSetLibraryItems: index.allSets,
  artistCards: index.artistCards,
  edgeCount: index.networkEdges.length,
  generatedAt: index.generatedAt,
  globalStats: index.globalStats,
  hero: buildHeroPayload(index),
  initialAtlas: buildAtlasPayload({
    compareMode,
    index,
    selectedArtistSlugs:
      selectedArtistSlugs && selectedArtistSlugs.length > 0
        ? selectedArtistSlugs
        : index.artistCards[0]
          ? [index.artistCards[0].slug]
          : [],
  }),
  initialNetwork: {
    artists: index.networkArtists,
    edges: index.networkEdges,
  },
  initialSetLibrary: buildSetLibraryPayload({
    artistFilter,
    index,
    page,
    pageSize: 24,
    query,
    sort,
  }),
  pairPayloads: Object.fromEntries(index.pairMap.entries()),
});

const buildSnapshotHomeExplorerIndexUncached = async (): Promise<HomeExplorerIndex> => {
  const snapshot = await readFirstExistingJson<SnapshotExplorerData>("explorer_data.json");
  const artistRows = Array.isArray(snapshot.artists) ? snapshot.artists : [];
  const setRows = Array.isArray(snapshot.all_sets) ? snapshot.all_sets : [];
  const similarityRows = Array.isArray(snapshot.similarity) ? snapshot.similarity : [];
  const trackRows = Array.isArray(snapshot.track_catalog) ? snapshot.track_catalog : [];

  const artistPathByName = new Map<
    string,
    {
      legacyPath: string | null;
      slug: string;
    }
  >();

  const artistCards: ArchiveHomeArtistCard[] = artistRows.map((artistRow) => {
    const legacyPath = getString(artistRow.html_rel)
      ? normalizeLegacyPath(getString(artistRow.html_rel)!)
      : null;
    const slug = buildSnapshotSlug(legacyPath, getString(artistRow.name));
    const card: ArchiveHomeArtistCard = {
      id: slug,
      imageUrl:
        getString(artistRow.artist_image) ??
        getString(artistRow.cover_image) ??
        null,
      legacyPath,
      name: getString(artistRow.name) ?? "Unknown Artist",
      setCount: Math.max(0, Number(getNumber(artistRow.sets_analyzed) ?? 0)),
      slug,
      totalAppearances: Math.max(0, Number(getNumber(artistRow.total_appearances) ?? 0)),
      uniqueTracks: Math.max(0, Number(getNumber(artistRow.unique_tracks) ?? 0)),
    };

    artistPathByName.set(card.name, {
      legacyPath: card.legacyPath,
      slug: card.slug,
    });

    return card;
  });

  const setLegacyByHref = new Map<string, string>();
  const setSlugByLegacyPath = new Map<string, string>();
  const setLibraryItems: ArchiveHomeSetLibraryItem[] = setRows.map((setRow) => {
    const legacyPath = getString(setRow.set_html_master_rel)
      ? normalizeLegacyPath(getString(setRow.set_html_master_rel)!)
      : null;
    const artistLegacyPath = getString(setRow.artist_html_rel)
      ? normalizeLegacyPath(getString(setRow.artist_html_rel)!)
      : null;
    const slug = buildSnapshotSlug(legacyPath, getString(setRow.title));
    const sourceUrl = getString(setRow.url);

    if (legacyPath) {
      setLegacyByHref.set(legacyPath, legacyPath);
      setSlugByLegacyPath.set(legacyPath, slug);
    }

    return {
      artistLegacyPath,
      artistName: getString(setRow.artist_name) ?? "Unknown Artist",
      artistSlug: buildSnapshotSlug(artistLegacyPath),
      confidenceCounts: normalizeConfidenceCounts(setRow.confidence_counts),
      duration: Math.max(0, Number(getNumber(setRow.duration) ?? 0)),
      id: slug,
      legacyPath,
      miniTimeline: Array.isArray(setRow.mini_timeline)
        ? setRow.mini_timeline.map((segment) => {
            const safe = asRecord(segment);
            return {
              confidence: normalizeArchiveConfidence(safe.confidence),
              startPct: Number(getNumber(safe.start_pct) ?? 0),
              widthPct: Number(getNumber(safe.width_pct) ?? 0),
            };
          })
        : [],
      recognitionRate: getNumber(setRow.recognition_rate),
      slug,
      sourceUrl,
      thumbnailUrl:
        getString(setRow.thumbnail_url) ??
        buildYouTubeThumbnail(sourceUrl) ??
        null,
      title: getString(setRow.title) ?? "Untitled Set",
      totalTracks: Math.max(0, Number(getNumber(setRow.total_tracks) ?? 0)),
      tracks: Array.isArray(setRow.tracks)
        ? setRow.tracks.map((trackRow) => {
            const safe = asRecord(trackRow);
            const trackHref = getString(safe.track_href);
            return {
              artist: getString(safe.artist) ?? "Unknown Artist",
              confidence: normalizeArchiveConfidence(safe.confidence),
              position: Math.max(0, Number(getNumber(safe.position) ?? getNumber(safe.track_position) ?? parseTrackPositionFromHref(trackHref))),
              spotifyUrl: getString(safe.spotify_url),
              startTimeFormatted: getString(safe.start_time_formatted) ?? "0:00",
              title: getString(safe.title) ?? "Unknown Track",
              trackKey:
                getString(safe.track_key) ??
                buildTrackKey(getString(safe.artist) ?? "Unknown Artist", getString(safe.title) ?? "Unknown Track"),
              trackLegacyPath: legacyPath,
              trackSetSlug: slug,
            };
          })
        : [],
      trackSearchText: getString(setRow.track_search_text) ?? "",
    };
  });

  for (const setItem of setLibraryItems) {
    if (setItem.legacyPath) {
      setLegacyByHref.set(normalizeLegacyPath(setItem.legacyPath), setItem.legacyPath);
    }
  }

  const trackCatalog = trackRows.map<ArchiveHomeTrackCatalogItem>((trackRow) => {
    const artistRefs = Array.isArray(trackRow.artist_refs)
      ? trackRow.artist_refs.map<ArchiveHomeTrackArtistRef>((artistRefRow) => {
          const safeArtistRef = asRecord(artistRefRow as SnapshotTrackArtistRef);
          const artistName = getString(safeArtistRef.artist_name) ?? getString(safeArtistRef.dir_name) ?? "Unknown Artist";
          const artistMeta = artistPathByName.get(artistName);
          const setRefs = Array.isArray(safeArtistRef.set_refs)
            ? safeArtistRef.set_refs.map((setRefRow) => {
                const safeSetRef = asRecord(setRefRow);
                const href = getString(safeSetRef.href);
                const built = buildSnapshotSetRef({
                  href,
                  setLegacyByHref,
                  setSlugByLegacyPath,
                  title: getString(safeSetRef.title) ?? "Untitled Set",
                  trackPosition: getNumber(safeSetRef.track_position),
                });
                return {
                  ...built,
                  confidence: normalizeArchiveConfidence(safeSetRef.confidence),
                };
              })
            : [];

          return {
            appearances: Math.max(0, Number(getNumber(safeArtistRef.appearances) ?? setRefs.length)),
            artistLegacyPath: artistMeta?.legacyPath ?? null,
            artistName,
            artistSlug: artistMeta?.slug ?? buildSnapshotSlug(null, artistName),
            setRefs,
          };
        })
      : [];

    return {
      albumArt: getString(trackRow.album_art),
      artist: getString(trackRow.artist) ?? "Unknown Artist",
      artistImage: getString(trackRow.artist_image),
      artistProfileImage: getString(trackRow.artist_profile_image),
      artistRefs,
      artistsCount: Math.max(0, Number(getNumber(trackRow.artists_count) ?? artistRefs.length)),
      confidence: normalizeArchiveConfidence(trackRow.confidence),
      confidenceCounts: normalizeConfidenceCounts(trackRow.confidence_counts),
      genres: getStringArray(trackRow.genres),
      label: getString(trackRow.label),
      labelUrl: getString(trackRow.label_url),
      spotifyUrl: getString(trackRow.spotify_url),
      title: getString(trackRow.title) ?? "Unknown Track",
      totalAppearances: Math.max(0, Number(getNumber(trackRow.total_appearances) ?? 0)),
      trackKey:
        getString(trackRow.track_key) ??
        buildTrackKey(getString(trackRow.artist) ?? "Unknown Artist", getString(trackRow.title) ?? "Unknown Track"),
    };
  });

  const pairMap = new Map<string, ArchiveHomePairPayload>();
  const networkEdges = similarityRows.map<ArchiveHomeNetworkEdge>((pairRow) => {
    const artistAName = getString(pairRow.artist_a) ?? "Unknown Artist";
    const artistBName = getString(pairRow.artist_b) ?? "Unknown Artist";
    const artistAMeta = artistPathByName.get(artistAName);
    const artistBMeta = artistPathByName.get(artistBName);
    const sharedTracks = Array.isArray(pairRow.shared_tracks)
      ? pairRow.shared_tracks.map<ArchiveHomePairTrack>((trackRow) => {
          const safeTrack = asRecord(trackRow as SnapshotPairTrack);
          const setsA = Array.isArray(safeTrack.sets_a)
            ? safeTrack.sets_a.map((setRefRow) => {
                const safeSetRef = asRecord(setRefRow);
                const href = getString(safeSetRef.href);
                const built = buildSnapshotSetRef({
                  href,
                  setLegacyByHref,
                  setSlugByLegacyPath,
                  title: getString(safeSetRef.title) ?? "Untitled Set",
                  trackPosition: getNumber(safeSetRef.track_position),
                });
                return {
                  ...built,
                  confidence: normalizeArchiveConfidence(safeSetRef.confidence),
                };
              })
            : [];
          const setsB = Array.isArray(safeTrack.sets_b)
            ? safeTrack.sets_b.map((setRefRow) => {
                const safeSetRef = asRecord(setRefRow);
                const href = getString(safeSetRef.href);
                const built = buildSnapshotSetRef({
                  href,
                  setLegacyByHref,
                  setSlugByLegacyPath,
                  title: getString(safeSetRef.title) ?? "Untitled Set",
                  trackPosition: getNumber(safeSetRef.track_position),
                });
                return {
                  ...built,
                  confidence: normalizeArchiveConfidence(safeSetRef.confidence),
                };
              })
            : [];

          return {
            albumArt: getString(safeTrack.spotify_album_art),
            appearancesA: Math.max(0, Number(getNumber(safeTrack.appearances_a) ?? 0)),
            appearancesB: Math.max(0, Number(getNumber(safeTrack.appearances_b) ?? 0)),
            artist: getString(safeTrack.display_artist) ?? "Unknown Artist",
            artistImage: getString(safeTrack.spotify_artist_profile_image),
            artistProfileImage: getString(safeTrack.spotify_artist_profile_image),
            confidence: normalizeArchiveConfidence(safeTrack.confidence),
            confidenceCounts: normalizeConfidenceCounts(safeTrack.confidence_counts),
            genres: getStringArray(safeTrack.genres),
            label: getString(safeTrack.discogs_label),
            labelUrl: getString(safeTrack.discogs_label_url),
            setsA,
            setsB,
            spotifyUrl: getString(safeTrack.spotify_url),
            title: getString(safeTrack.display_title) ?? "Unknown Track",
            trackKey:
              getString(safeTrack.track_key) ??
              buildTrackKey(getString(safeTrack.display_artist) ?? "Unknown Artist", getString(safeTrack.display_title) ?? "Unknown Track"),
          };
        })
      : [];

    const mapBucketGroup = (
      value: unknown,
      nameKey: "genre" | "label" | "music_artist",
    ): ArchiveHomePairBucket[] =>
      Array.isArray(value)
        ? value.map((bucketRow) => {
            const safeBucket = asRecord(bucketRow as SnapshotPairBucket);
            const key =
              getString(safeBucket[nameKey]) ??
              getString(safeBucket.label) ??
              getString(safeBucket.genre) ??
              getString(safeBucket.music_artist) ??
              "Unknown";
            return {
              countA: Math.max(0, Number(getNumber(safeBucket.count_a) ?? 0)),
              countB: Math.max(0, Number(getNumber(safeBucket.count_b) ?? 0)),
              id: key,
              name: key,
              trackKeys: getStringArray(safeBucket.track_keys),
            };
          })
        : [];

    const payload: ArchiveHomePairPayload = {
      artistA: {
        id: artistAMeta?.slug ?? buildSnapshotSlug(null, artistAName),
        legacyPath: artistAMeta?.legacyPath ?? null,
        name: artistAName,
        setCount: artistCards.find((artist) => artist.name === artistAName)?.setCount ?? 0,
        slug: artistAMeta?.slug ?? buildSnapshotSlug(null, artistAName),
      },
      artistB: {
        id: artistBMeta?.slug ?? buildSnapshotSlug(null, artistBName),
        legacyPath: artistBMeta?.legacyPath ?? null,
        name: artistBName,
        setCount: artistCards.find((artist) => artist.name === artistBName)?.setCount ?? 0,
        slug: artistBMeta?.slug ?? buildSnapshotSlug(null, artistBName),
      },
      normalizedScore: Math.max(0, Number(getNumber(pairRow.normalized_score) ?? 0)),
      score: Math.max(0, Number(getNumber(pairRow.score) ?? 0)),
      sharedGenres: mapBucketGroup(pairRow.shared_genres, "genre"),
      sharedGenresCount: Math.max(0, Number(getNumber(pairRow.shared_genres_count) ?? 0)),
      sharedLabels: mapBucketGroup(pairRow.shared_labels, "label"),
      sharedLabelsCount: Math.max(0, Number(getNumber(pairRow.shared_labels_count) ?? 0)),
      sharedMusicArtists: mapBucketGroup(pairRow.shared_music_artists, "music_artist"),
      sharedMusicArtistsCount: Math.max(0, Number(getNumber(pairRow.shared_artists_count) ?? 0)),
      sharedTracks,
      sharedTracksCount: Math.max(0, Number(getNumber(pairRow.shared_tracks_count) ?? sharedTracks.length)),
    };

    pairMap.set(pairKey(payload.artistA.slug, payload.artistB.slug), payload);

    return {
      artistA: payload.artistA.name,
      artistALegacyPath: payload.artistA.legacyPath,
      artistASlug: payload.artistA.slug,
      artistB: payload.artistB.name,
      artistBLegacyPath: payload.artistB.legacyPath,
      artistBSlug: payload.artistB.slug,
      normalizedScore: payload.normalizedScore,
      score: payload.score,
      sharedArtistsCount: payload.sharedMusicArtistsCount,
      sharedGenresCount: payload.sharedGenresCount,
      sharedLabelsCount: payload.sharedLabelsCount,
      sharedTracksCount: payload.sharedTracksCount,
    };
  });

  return {
    allSets: setLibraryItems,
    artistCards,
    generatedAt: getString(snapshot.generated_at),
    globalStats: {
      confidenceBreakdown: normalizeConfidenceCounts(asRecord(snapshot.global_stats).confidence_breakdown),
      totalAppearances: Math.max(0, Number(getNumber(asRecord(snapshot.global_stats).total_appearances) ?? 0)),
      totalArtists: Math.max(0, Number(getNumber(asRecord(snapshot.global_stats).total_artists) ?? artistCards.length)),
      totalSets: Math.max(0, Number(getNumber(asRecord(snapshot.global_stats).total_sets) ?? setLibraryItems.length)),
      totalUniqueTracks: Math.max(0, Number(getNumber(asRecord(snapshot.global_stats).total_unique_tracks) ?? trackCatalog.length)),
      unknownRatio: Number(getNumber(asRecord(snapshot.global_stats).unknown_ratio) ?? 0),
    },
    networkArtists: artistCards.map((artist) => ({
      id: artist.id,
      legacyPath: artist.legacyPath,
      name: artist.name,
      setCount: artist.setCount,
      slug: artist.slug,
    })),
    networkEdges,
    connectionEdgeCount: similarityRows.filter((row) => Math.max(0, Number(getNumber(row.score) ?? 0)) > 0).length,
    pairMap,
    tickerItems: [
      `Artists ${Math.max(0, Number(getNumber(asRecord(snapshot.global_stats).total_artists) ?? artistCards.length)).toLocaleString("en-US")}`,
      `Sets ${Math.max(0, Number(getNumber(asRecord(snapshot.global_stats).total_sets) ?? setLibraryItems.length)).toLocaleString("en-US")}`,
      `Unique tracks ${Math.max(0, Number(getNumber(asRecord(snapshot.global_stats).total_unique_tracks) ?? trackCatalog.length)).toLocaleString("en-US")}`,
      `Appearances ${Math.max(0, Number(getNumber(asRecord(snapshot.global_stats).total_appearances) ?? 0)).toLocaleString("en-US")}`,
      `Connection edges ${similarityRows.filter((row) => Math.max(0, Number(getNumber(row.score) ?? 0)) > 0).length.toLocaleString("en-US")}`,
    ],
    trackCatalog,
  };
};

const getHomeExplorerSnapshotIndex = async () => {
  if (!homeExplorerSnapshotPromise) {
    homeExplorerSnapshotPromise = buildSnapshotHomeExplorerIndexUncached();
  }

  return homeExplorerSnapshotPromise;
};

export const getArchiveHomeExplorerInitial = async ({
  artistFilter = "ALL",
  compareMode = "union",
  page = 1,
  query = "",
  selectedArtistSlugs,
  sort = "default",
}: {
  artistFilter?: string;
  compareMode?: ArchiveHomeCompareMode;
  page?: number;
  query?: string;
  selectedArtistSlugs?: string[];
  sort?: ArchiveHomeSetSort;
} = {}): Promise<ArchiveHomeExplorerInitialPayload> => {
  const index = await getHomeExplorerIndex();
  return buildHomeExplorerInitialPayload({
    artistFilter,
    compareMode,
    index,
    page,
    query,
    selectedArtistSlugs,
    sort,
  });
};

export const getArchiveHomeExplorerInitialPreview = async ({
  artistFilter = "ALL",
  compareMode = "union",
  page = 1,
  query = "",
  selectedArtistSlugs,
  sort = "default",
}: {
  artistFilter?: string;
  compareMode?: ArchiveHomeCompareMode;
  page?: number;
  query?: string;
  selectedArtistSlugs?: string[];
  sort?: ArchiveHomeSetSort;
} = {}): Promise<ArchiveHomeExplorerInitialPayload> => {
  try {
    return await getArchiveHomeExplorerInitial({
      artistFilter,
      compareMode,
      page,
      query,
      selectedArtistSlugs,
      sort,
    });
  } catch (error) {
    if (process.env.NODE_ENV === "production") {
      throw error;
    }

    console.warn("[archive-home] Falling back to local explorer snapshot for preview.", error);
    const snapshotIndex = await getHomeExplorerSnapshotIndex();
    return buildHomeExplorerInitialPayload({
      artistFilter,
      compareMode,
      index: snapshotIndex,
      page,
      query,
      selectedArtistSlugs,
      sort,
    });
  }
};

export const getArchiveHomeAtlasPayload = async ({
  compareMode = "union",
  selectedArtistSlugs,
}: {
  compareMode?: ArchiveHomeCompareMode;
  selectedArtistSlugs: string[];
}) => {
  const index = await getHomeExplorerIndex();
  return buildAtlasPayload({
    compareMode,
    index,
    selectedArtistSlugs,
  });
};

export const getArchiveHomeNetworkPayload = async (): Promise<ArchiveHomeNetworkPayload> => {
  const index = await getHomeExplorerIndex();
  return {
    artists: index.networkArtists,
    edges: index.networkEdges,
  };
};

export const getArchiveHomePairPayload = async ({
  artistASlug,
  artistBSlug,
}: {
  artistASlug: string;
  artistBSlug: string;
}) => {
  const index = await getHomeExplorerIndex();
  return index.pairMap.get(pairKey(artistASlug, artistBSlug)) ?? null;
};

export const getArchiveHomeSetLibraryPayload = async ({
  artistFilter = "ALL",
  page = 1,
  query = "",
  sort = "default",
}: {
  artistFilter?: string;
  page?: number;
  query?: string;
  sort?: ArchiveHomeSetSort;
} = {}) => {
  const index = await getHomeExplorerIndex();
  return buildSetLibraryPayload({
    artistFilter,
    index,
    page,
    pageSize: 24,
    query,
    sort,
  });
};

export const getArchiveHomeThresholdLevels = () => [...THRESHOLD_LEVELS];
