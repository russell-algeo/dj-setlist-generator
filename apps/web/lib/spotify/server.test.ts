import { describe, expect, it, vi } from "vitest";

import { spotifyConnections } from "@/lib/db/schema";

import { refreshSpotifyAccessTokenForUser, SpotifyConnectionError } from "./server";

vi.mock("server-only", () => ({}));

vi.mock("@/lib/env", () => ({
  env: {
    spotifyClientId: "spotify-client-id",
    spotifyClientSecret: "spotify-client-secret",
  },
}));

const buildDb = (connection: unknown) => {
  const limit = vi.fn().mockResolvedValue(connection ? [connection] : []);
  const selectWhere = vi.fn(() => ({ limit }));
  const from = vi.fn(() => ({ where: selectWhere }));
  const select = vi.fn(() => ({ from }));

  const updateWhere = vi.fn().mockResolvedValue(undefined);
  const set = vi.fn(() => ({ where: updateWhere }));
  const update = vi.fn(() => ({ set }));

  return {
    db: { select, update },
    limit,
    set,
    update,
    updateWhere,
  };
};

describe("refreshSpotifyAccessTokenForUser", () => {
  it("revokes the Spotify connection when the stored refresh token cannot be decrypted", async () => {
    const now = new Date("2026-05-27T13:29:53.054Z");
    const connection = {
      refreshTokenCiphertext: "stored-ciphertext",
      revokedAt: null,
      scopes: ["playlist-modify-private"],
      spotifyUserId: "spotify-user-123",
    };
    const { db, set, update, updateWhere } = buildDb(connection);
    const decrypt = vi.fn(() => {
      throw new Error("Unsupported state or unable to authenticate data");
    });
    const fetchFn = vi.fn();

    await expect(
      refreshSpotifyAccessTokenForUser("user-123", {
        db: db as never,
        decrypt,
        fetchFn: fetchFn as never,
        now: () => now,
      }),
    ).rejects.toBeInstanceOf(SpotifyConnectionError);

    expect(decrypt).toHaveBeenCalledWith("stored-ciphertext");
    expect(fetchFn).not.toHaveBeenCalled();
    expect(update).toHaveBeenCalledWith(spotifyConnections);
    expect(set).toHaveBeenCalledWith({
      lastError: "Stored Spotify refresh token could not be decrypted. Reconnect Spotify.",
      revokedAt: now,
      updatedAt: now,
    });
    expect(updateWhere).toHaveBeenCalledTimes(1);
  });
});
