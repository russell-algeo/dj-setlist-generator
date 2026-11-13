import "server-only";

// Saves or removes one track in the signed-in user's Spotify library
// ("Liked Songs") without leaving the page. The embed's own "+" control runs
// inside Spotify's cross-origin iframe, needs a separate Spotify login there,
// and its iFrame API exposes no save method, so the site does it itself.
//
// Uses the URI-based /me/library endpoint. Development-mode apps were moved to
// it in March 2026; the older /me/tracks endpoint is no longer available to them.
// https://developer.spotify.com/documentation/web-api/reference/save-library-items

export const SPOTIFY_LIBRARY_SCOPE = "user-library-modify";

export class SpotifyLibraryScopeError extends Error {}
export class SpotifyLibraryRemoteError extends Error {}

const SPOTIFY_TRACK_ID = /^[A-Za-z0-9]{22}$/;

export const isSpotifyTrackId = (value: unknown): value is string =>
  typeof value === "string" && SPOTIFY_TRACK_ID.test(value);

export const ensureSpotifyLibraryScope = (scopes: string[]) => {
  if (!scopes.includes(SPOTIFY_LIBRARY_SCOPE)) {
    throw new SpotifyLibraryScopeError(
      "Spotify needs permission to save to your library. Reconnect Spotify to allow it.",
    );
  }
};

export const setSpotifyTrackSaved = async ({
  accessToken,
  fetchFn = fetch,
  saved,
  trackId,
}: {
  accessToken: string;
  fetchFn?: typeof fetch;
  saved: boolean;
  trackId: string;
}) => {
  if (!isSpotifyTrackId(trackId)) {
    throw new SpotifyLibraryRemoteError("Invalid Spotify track id");
  }

  const url = new URL("https://api.spotify.com/v1/me/library");
  url.searchParams.set("uris", `spotify:track:${trackId}`);

  const response = await fetchFn(url, {
    method: saved ? "PUT" : "DELETE",
    headers: { authorization: `Bearer ${accessToken}` },
  });

  if (response.status === 401 || response.status === 403) {
    // A token issued before the library scope was granted is refused here.
    throw new SpotifyLibraryScopeError(
      "Spotify refused the library change. Reconnect Spotify to allow saving.",
    );
  }

  if (!response.ok) {
    const errorText = await response.text().catch(() => "unknown error");
    throw new SpotifyLibraryRemoteError(
      `Spotify library ${saved ? "save" : "removal"} failed (${response.status}): ${errorText.slice(0, 200)}`,
    );
  }
};
