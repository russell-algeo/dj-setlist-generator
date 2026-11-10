import type { ArchiveSetTrack, ArchiveSetTimelineSegment, ArchiveJourneyPoint } from "./types";
import { resolveArchiveTrackLinks } from "./track-links";
import { asRecord, getString, getStringArray, getNumber, normalizeArchiveConfidence, formatDuration } from "./utils";
const percent = (value: number, total: number) => total > 0 ? Math.max(0, Math.min(100, (value / total) * 100)) : 0;

const EXCLUDED_ARCHIVE_GENRES = new Set(["House"]);

const formatArchiveGenre = (value: string) =>
  value
    .trim()
    .toLowerCase()
    .replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
export const mapSetTrack = (row: {
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
  const links = resolveArchiveTrackLinks({
    entryMetadata,
    trackMetadata,
    spotifyUrl: row.trackSpotifyUrl,
    youtubeUrl: row.trackYoutubeUrl,
    discogsUrl: row.trackDiscogsUrl,
  });
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
    albumArt: links.linkStatus.spotify === "unverified"
      ? null
      : getString(merged.spotify_album_art) ?? getString(merged.albumArt),
    previewUrl: links.linkStatus.spotify === "unverified"
      ? null
      : getString(merged.spotify_preview_url) ?? getString(merged.previewUrl),
    bpm: getNumber(merged.bpm),
    energy: getNumber(merged.energy),
    dance: getNumber(merged.danceability) ?? getNumber(merged.dance),
    key: getString(merged.key),
    genres,
    detailGenres,
    label: getString(merged.discogs_label),
    labelUrl: getString(merged.discogs_label_url),
    ...links,
    detectionCount: Number(row.detectionCount ?? 0),
    clusterDensity: getNumber(row.clusterDensity),
    clusterSpan: row.clusterSpan,
    sourceDeepLink: row.sourceDeepLink ?? getString(merged.source_deep_link),
  };
};

export const buildTimeline = (
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

export const buildJourneyPoints = (tracks: ArchiveSetTrack[]): ArchiveJourneyPoint[] =>
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

