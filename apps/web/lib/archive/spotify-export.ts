import type {
  ArchiveArtistSummary,
  ArchiveSetDetail,
  SpotifyExportConfidenceFilter,
} from "@/lib/archive/types";
import { extractSpotifyTrackId } from "@/lib/archive/utils";

export type SpotifyExportTrackCandidate = {
  archiveKey: string;
  confidence: "HIGH" | "MEDIUM" | "LOW" | "UNCERTAIN";
  spotifyTrackId: string;
};

export type SpotifyExportCounts = Record<SpotifyExportConfidenceFilter, number>;

export const SPOTIFY_EXPORT_FILTERS: SpotifyExportConfidenceFilter[] = [
  "all",
  "HIGH",
  "MEDIUM",
  "LOW",
];

const createEmptyCounts = (): SpotifyExportCounts => ({
  all: 0,
  HIGH: 0,
  MEDIUM: 0,
  LOW: 0,
});

const matchesConfidenceFilter = (
  confidence: SpotifyExportTrackCandidate["confidence"],
  filter: SpotifyExportConfidenceFilter,
) => filter === "all" || confidence === filter;

export const buildSetSpotifyExportCandidates = (
  detail: Pick<ArchiveSetDetail, "tracks">,
  filter: SpotifyExportConfidenceFilter = "all",
): SpotifyExportTrackCandidate[] =>
  detail.tracks.flatMap((track) => {
    if (track.title === "Unknown Track" || !matchesConfidenceFilter(track.conf, filter)) {
      return [];
    }

    const spotifyTrackId = extractSpotifyTrackId(track.spotifyUrl);
    if (!spotifyTrackId) {
      return [];
    }

    return [
      {
        archiveKey: `set-track:${track.idx}`,
        confidence: track.conf,
        spotifyTrackId,
      },
    ];
  });

export const buildSetSpotifyExportCounts = (
  detail: Pick<ArchiveSetDetail, "tracks">,
): SpotifyExportCounts =>
  SPOTIFY_EXPORT_FILTERS.reduce<SpotifyExportCounts>((counts, filter) => {
    counts[filter] = buildSetSpotifyExportCandidates(detail, filter).length;
    return counts;
  }, createEmptyCounts());

export const buildArtistSpotifyExportCandidates = (
  artist: Pick<ArchiveArtistSummary, "atlasTracks">,
  filter: SpotifyExportConfidenceFilter = "all",
): SpotifyExportTrackCandidate[] => {
  const seenTrackKeys = new Set<string>();
  const seenSpotifyTrackIds = new Set<string>();
  const candidates: SpotifyExportTrackCandidate[] = [];

  for (const track of artist.atlasTracks) {
    if (!matchesConfidenceFilter(track.confidence, filter)) {
      continue;
    }

    const spotifyTrackId = extractSpotifyTrackId(track.spotifyUrl);
    if (!spotifyTrackId) {
      continue;
    }

    if (seenTrackKeys.has(track.trackKey)) {
      continue;
    }

    seenTrackKeys.add(track.trackKey);

    if (seenSpotifyTrackIds.has(spotifyTrackId)) {
      continue;
    }

    seenSpotifyTrackIds.add(spotifyTrackId);
    candidates.push({
      archiveKey: track.trackKey,
      confidence: track.confidence,
      spotifyTrackId,
    });
  }

  return candidates;
};

export const buildArtistSpotifyExportCounts = (
  artist: Pick<ArchiveArtistSummary, "atlasTracks">,
): SpotifyExportCounts =>
  SPOTIFY_EXPORT_FILTERS.reduce<SpotifyExportCounts>((counts, filter) => {
    counts[filter] = buildArtistSpotifyExportCandidates(artist, filter).length;
    return counts;
  }, createEmptyCounts());

export const hasSpotifyExportCandidates = (counts: SpotifyExportCounts) => counts.all > 0;

export const buildArchiveCanonicalUrl = ({
  baseUrl,
  entityType,
  slug,
}: {
  baseUrl?: string;
  entityType: "artist" | "set";
  slug: string;
}) => {
  const path = entityType === "artist" ? `/artists/${slug}` : `/sets/${slug}`;

  if (!baseUrl) {
    return path;
  }

  try {
    return new URL(path, baseUrl).toString();
  } catch {
    return path;
  }
};

export const buildSpotifyPlaylistDescription = (canonicalPageUrl: string) =>
  `Built from Set Signal Archive - ${canonicalPageUrl}`;
