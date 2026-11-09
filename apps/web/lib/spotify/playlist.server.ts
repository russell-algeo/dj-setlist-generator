import "server-only";

export class SpotifyExportScopeError extends Error {}
export class SpotifyExportRemoteError extends Error {}

export const ensureSpotifyPlaylistScope = (scopes: string[]) => {
  if (!scopes.includes("playlist-modify-private")) {
    throw new SpotifyExportScopeError(
      "Spotify connection is missing playlist permissions. Reconnect Spotify and try again.",
    );
  }
};

export const createPlaylist = async ({
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
      // This controls profile/search listing, not access privacy.
      // https://developer.spotify.com/documentation/web-api/concepts/playlists
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

export const addPlaylistTracks = async ({
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

