import "server-only";

import { env } from "@/lib/env";
import { ensureSpotifyPlaylistScope, createPlaylist, addPlaylistTracks } from "@/lib/spotify/playlist.server";
import {
  getArchiveArtistSummaryBySlug,
  getArchiveArtistSummaryBySlugForUser,
  getArchiveSetDetailBySlug,
} from "@/lib/archive/data";
import {
  buildArchiveCanonicalUrl,
  buildArtistSpotifyExportCandidates,
  buildSetSpotifyExportCandidates,
  buildSpotifyPlaylistDescription,
} from "@/lib/archive/spotify-export";
import type {
  ArchiveArtistSummary,
  ArchiveSetDetail,
  SpotifyExportRequest,
  SpotifyExportResponse,
} from "@/lib/archive/types";
import {
  refreshSpotifyAccessTokenForUser,
  type RefreshedSpotifyAccessToken,
} from "@/lib/spotify/server";

export class SpotifyExportNotFoundError extends Error {}
export class SpotifyExportNoTracksError extends Error {}
export { SpotifyExportScopeError, SpotifyExportRemoteError } from "@/lib/spotify/playlist.server";

type SpotifyExportServiceDeps = {
  appBaseUrl?: string;
  fetchFn?: typeof fetch;
  getArtistGlobal?: (slug: string) => Promise<ArchiveArtistSummary | null>;
  getArtistForUser?: (slug: string, userId: string) => Promise<ArchiveArtistSummary | null>;
  getSet?: (slug: string) => Promise<ArchiveSetDetail | null>;
  refreshAccessTokenForUser?: (userId: string) => Promise<RefreshedSpotifyAccessToken>;
};

const DEFAULT_DEPS: Required<SpotifyExportServiceDeps> = {
  appBaseUrl: env.appBaseUrl ?? "",
  fetchFn: fetch,
  getArtistGlobal: getArchiveArtistSummaryBySlug,
  getArtistForUser: getArchiveArtistSummaryBySlugForUser,
  getSet: getArchiveSetDetailBySlug,
  refreshAccessTokenForUser: refreshSpotifyAccessTokenForUser,
};

export const executeSpotifyExport = async (
  actorUserId: string,
  input: SpotifyExportRequest,
  deps: SpotifyExportServiceDeps = {},
): Promise<SpotifyExportResponse> => {
  const resolvedDeps = { ...DEFAULT_DEPS, ...deps };
  const canonicalPageUrl = buildArchiveCanonicalUrl({
    baseUrl: resolvedDeps.appBaseUrl || undefined,
    entityType: input.entityType,
    slug: input.slug,
  });

  let exportedTrackIds: string[] = [];
  let resolvedPlaylistName = "";

  if (input.entityType === "artist") {
    const artist =
      input.scope === "mine"
        ? await resolvedDeps.getArtistForUser(input.slug, actorUserId)
        : await resolvedDeps.getArtistGlobal(input.slug);

    if (!artist) {
      throw new SpotifyExportNotFoundError("Artist not found");
    }

    exportedTrackIds = buildArtistSpotifyExportCandidates(artist, input.confidenceFilter).map(
      (track) => track.spotifyTrackId,
    );
    resolvedPlaylistName = artist.name;
  } else {
    const detail = await resolvedDeps.getSet(input.slug);

    if (!detail) {
      throw new SpotifyExportNotFoundError("Set not found");
    }

    exportedTrackIds = buildSetSpotifyExportCandidates(detail, input.confidenceFilter).map(
      (track) => track.spotifyTrackId,
    );
    resolvedPlaylistName = detail.title;
  }

  if (exportedTrackIds.length === 0) {
    throw new SpotifyExportNoTracksError("No Spotify-resolved tracks are available for export");
  }

  const accessToken = await resolvedDeps.refreshAccessTokenForUser(actorUserId);
  ensureSpotifyPlaylistScope(accessToken.scopes);

  const playlist = await createPlaylist({
    accessToken: accessToken.accessToken,
    description: buildSpotifyPlaylistDescription(canonicalPageUrl),
    fetchFn: resolvedDeps.fetchFn,
    name: resolvedPlaylistName,
    spotifyUserId: accessToken.spotifyUserId,
  });

  await addPlaylistTracks({
    accessToken: accessToken.accessToken,
    fetchFn: resolvedDeps.fetchFn,
    playlistId: playlist.playlistId,
    spotifyTrackIds: exportedTrackIds,
  });

  return {
    confidenceFilter: input.confidenceFilter,
    playlistId: playlist.playlistId,
    playlistName: playlist.playlistName,
    playlistUrl: playlist.playlistUrl,
    tracksAdded: exportedTrackIds.length,
  };
};
