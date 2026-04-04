import { describe, expect, it, vi } from "vitest";

import {
  executeSpotifyExport,
  SpotifyExportNoTracksError,
  SpotifyExportRemoteError,
  SpotifyExportScopeError,
} from "./spotify-export.server";

describe("executeSpotifyExport", () => {
  it("creates a private playlist with canonical description and batched track uris", async () => {
    const fetchFn = vi
      .fn()
      .mockResolvedValueOnce({
        json: async () => ({
          external_urls: { spotify: "https://open.spotify.com/playlist/playlist-123" },
          id: "playlist-123",
          name: "Arpiar",
        }),
        ok: true,
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () => "",
      });

    const result = await executeSpotifyExport(
      "user-123",
      {
        confidenceFilter: "HIGH",
        entityType: "artist",
        scope: "mine",
        slug: "arpiar",
      },
      {
        appBaseUrl: "https://dj-setlist-generator.vercel.app",
        fetchFn: fetchFn as never,
        getArtistForUser: async () => ({
          atlasTracks: [
            {
              confidence: "LOW",
              spotifyUrl: "https://open.spotify.com/track/track-a",
              trackKey: "track-a",
            },
            {
              confidence: "HIGH",
              spotifyUrl: "https://open.spotify.com/track/track-b",
              trackKey: "track-b",
            },
            {
              confidence: "HIGH",
              spotifyUrl: "https://open.spotify.com/track/track-a",
              trackKey: "track-a",
            },
          ],
          name: "Arpiar",
        } as never),
        getArtistGlobal: async () => null,
        getSet: async () => null,
        refreshAccessTokenForUser: async () => ({
          accessToken: "spotify-access-token",
          expiresIn: 3600,
          scopes: ["playlist-modify-private"],
          spotifyUserId: "spotify-user-123",
        }),
      },
    );

    expect(result).toEqual({
      confidenceFilter: "HIGH",
      playlistId: "playlist-123",
      playlistName: "Arpiar",
      playlistUrl: "https://open.spotify.com/playlist/playlist-123",
      tracksAdded: 2,
    });

    expect(fetchFn).toHaveBeenCalledTimes(2);
    expect(fetchFn.mock.calls[0]?.[0]).toBe("https://api.spotify.com/v1/users/spotify-user-123/playlists");
    expect(JSON.parse(String(fetchFn.mock.calls[0]?.[1]?.body))).toEqual({
      description:
        "Built from Set Signal Archive - https://dj-setlist-generator.vercel.app/artists/arpiar",
      name: "Arpiar",
      public: false,
    });
    expect(JSON.parse(String(fetchFn.mock.calls[1]?.[1]?.body))).toEqual({
      uris: ["spotify:track:track-b", "spotify:track:track-a"],
    });
  });

  it("fails when no exportable tracks are available", async () => {
    await expect(
      executeSpotifyExport(
        "user-123",
        {
          confidenceFilter: "all",
          entityType: "set",
          slug: "no-tracks",
        },
        {
          getArtistForUser: async () => null,
          getArtistGlobal: async () => null,
          getSet: async () =>
            ({
              title: "No Tracks",
              tracks: [
                {
                  idx: 1,
                  spotifyUrl: "https://open.spotify.com/search/no-track-id",
                  title: "Unknown Track",
                },
              ],
            } as never),
          refreshAccessTokenForUser: async () => {
            throw new Error("should not run");
          },
        },
      ),
    ).rejects.toBeInstanceOf(SpotifyExportNoTracksError);
  });

  it("fails when the Spotify connection is missing private playlist scope", async () => {
    await expect(
      executeSpotifyExport(
        "user-123",
        {
          confidenceFilter: "all",
          entityType: "set",
          slug: "scope-test",
        },
        {
          getArtistForUser: async () => null,
          getArtistGlobal: async () => null,
          getSet: async () =>
            ({
              title: "Scope Test",
              tracks: [
                {
                  conf: "HIGH",
                  idx: 1,
                  spotifyUrl: "https://open.spotify.com/track/track-a",
                  title: "Alpha",
                },
              ],
            } as never),
          refreshAccessTokenForUser: async () => ({
            accessToken: "spotify-access-token",
            expiresIn: 3600,
            scopes: [],
            spotifyUserId: "spotify-user-123",
          }),
        },
      ),
    ).rejects.toBeInstanceOf(SpotifyExportScopeError);
  });

  it("surfaces Spotify API failures as remote export errors", async () => {
    await expect(
      executeSpotifyExport(
        "user-123",
        {
          confidenceFilter: "all",
          entityType: "set",
          slug: "remote-error",
        },
        {
          fetchFn: vi.fn().mockResolvedValue({
            ok: false,
            text: async () => "bad request",
          }) as never,
          getArtistForUser: async () => null,
          getArtistGlobal: async () => null,
          getSet: async () =>
            ({
              title: "Remote Error",
              tracks: [
                {
                  conf: "HIGH",
                  idx: 1,
                  spotifyUrl: "https://open.spotify.com/track/track-a",
                  title: "Alpha",
                },
              ],
            } as never),
          refreshAccessTokenForUser: async () => ({
            accessToken: "spotify-access-token",
            expiresIn: 3600,
            scopes: ["playlist-modify-private"],
            spotifyUserId: "spotify-user-123",
          }),
        },
      ),
    ).rejects.toBeInstanceOf(SpotifyExportRemoteError);
  });
});
