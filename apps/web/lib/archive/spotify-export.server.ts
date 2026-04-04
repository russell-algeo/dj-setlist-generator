import "server-only";

import { env } from "@/lib/env";
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
export class SpotifyExportScopeError extends Error {}
export class SpotifyExportRemoteError extends Error {}

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

const ensureSpotifyPlaylistScope = (scopes: string[]) => {
  if (!scopes.includes("playlist-modify-private")) {
    throw new SpotifyExportScopeError(
      "Spotify connection is missing playlist permissions. Reconnect Spotify and try again.",
    );
  }
};

const createPlaylist = async ({
  accessToken,
  description,
  fetchFn,
  name,
  spotifyUserId,
}: {
  accessToken: string;
  description: string;
  fetchFn: typeof fetch;
  name: string;
  spotifyUserId: string;
}) => {
  const response = await fetchFn(`https://api.spotify.com/v1/users/${spotifyUserId}/playlists`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${accessToken}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      description,
      name,
      public: false,
    }),
  });

  if (!response.ok) {
    const errorText = await response.text().catch(() => "unknown error");
    throw new SpotifyExportRemoteError(`Spotify playlist creation failed: ${errorText}`);
  }

  const payload = (await response.json()) as {
    external_urls?: { spotify?: string };
    id: string;
    name: string;
  };

  return {
    playlistId: payload.id,
    playlistName: payload.name,
    playlistUrl: payload.external_urls?.spotify ?? `https://open.spotify.com/playlist/${payload.id}`,
  };
};

const addPlaylistTracks = async ({
  accessToken,
  fetchFn,
  playlistId,
  spotifyTrackIds,
}: {
  accessToken: string;
  fetchFn: typeof fetch;
  playlistId: string;
  spotifyTrackIds: string[];
}) => {
  for (let index = 0; index < spotifyTrackIds.length; index += 100) {
    const response = await fetchFn(`https://api.spotify.com/v1/playlists/${playlistId}/tracks`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${accessToken}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({
        uris: spotifyTrackIds.slice(index, index + 100).map((trackId) => `spotify:track:${trackId}`),
      }),
    });

    if (!response.ok) {
      const errorText = await response.text().catch(() => "unknown error");
      throw new SpotifyExportRemoteError(`Spotify track add failed: ${errorText}`);
    }
  }
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
