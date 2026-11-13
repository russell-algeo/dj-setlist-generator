import { describe, expect, it, vi } from "vitest";

import {
  ensureSpotifyLibraryScope,
  isSpotifyTrackId,
  setSpotifyTrackSaved,
  SpotifyLibraryRemoteError,
  SpotifyLibraryScopeError,
} from "./library.server";

const TRACK = "7crxOiKNyPIb2rkCkCWlH7";

describe("Spotify library save", () => {
  it("accepts only 22-character base62 track ids", () => {
    expect(isSpotifyTrackId(TRACK)).toBe(true);
    expect(isSpotifyTrackId("spotify:track:" + TRACK)).toBe(false);
    expect(isSpotifyTrackId("abc")).toBe(false);
    expect(isSpotifyTrackId(`${TRACK.slice(0, 21)}/`)).toBe(false);
    expect(isSpotifyTrackId(undefined)).toBe(false);
  });

  it("requires the user-library-modify scope", () => {
    expect(() => ensureSpotifyLibraryScope(["user-read-email", "playlist-modify-private"])).toThrow(
      SpotifyLibraryScopeError,
    );
    expect(() => ensureSpotifyLibraryScope(["user-library-modify"])).not.toThrow();
  });

  it("PUTs the track URI to /me/library to save, and DELETEs it to undo", async () => {
    const fetchFn = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));
    await setSpotifyTrackSaved({ accessToken: "tok", fetchFn, saved: true, trackId: TRACK });
    await setSpotifyTrackSaved({ accessToken: "tok", fetchFn, saved: false, trackId: TRACK });

    const [saveUrl, saveInit] = fetchFn.mock.calls[0];
    expect(String(saveUrl)).toBe(
      `https://api.spotify.com/v1/me/library?uris=spotify%3Atrack%3A${TRACK}`,
    );
    expect(saveInit).toMatchObject({ method: "PUT", headers: { authorization: "Bearer tok" } });
    expect(fetchFn.mock.calls[1][1]).toMatchObject({ method: "DELETE" });
  });

  it("asks to reconnect when Spotify refuses the token", async () => {
    const fetchFn = vi.fn().mockResolvedValue(new Response("Insufficient client scope", { status: 403 }));
    await expect(
      setSpotifyTrackSaved({ accessToken: "tok", fetchFn, saved: true, trackId: TRACK }),
    ).rejects.toBeInstanceOf(SpotifyLibraryScopeError);
  });

  it("reports other Spotify failures without calling with a bad id", async () => {
    const fetchFn = vi.fn().mockResolvedValue(new Response("boom", { status: 500 }));
    await expect(
      setSpotifyTrackSaved({ accessToken: "tok", fetchFn, saved: true, trackId: TRACK }),
    ).rejects.toBeInstanceOf(SpotifyLibraryRemoteError);
    await expect(
      setSpotifyTrackSaved({ accessToken: "tok", fetchFn, saved: true, trackId: "../me" }),
    ).rejects.toBeInstanceOf(SpotifyLibraryRemoteError);
    expect(fetchFn).toHaveBeenCalledTimes(1);
  });
});
