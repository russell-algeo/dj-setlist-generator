import type { Account } from "next-auth";
import { describe, expect, it, vi } from "vitest";

import { spotifyConnections } from "@/lib/db/schema";

import {
  SPOTIFY_AUTH_SCOPES,
  buildSpotifyConnectionSyncPayload,
  buildSpotifyConnectionUpdateSet,
  syncSpotifyConnectionFromAccount,
} from "./spotify-connection";

const spotifyAccount = (overrides: Partial<Account> = {}): Account =>
  ({
    provider: "spotify",
    providerAccountId: "spotify-user-123",
    type: "oauth",
    ...overrides,
  }) as Account;

describe("buildSpotifyConnectionSyncPayload", () => {
  it("encrypts refresh tokens and stores returned scopes", () => {
    const now = new Date("2026-04-24T12:00:00.000Z");
    const payload = buildSpotifyConnectionSyncPayload({
      account: spotifyAccount({
        refresh_token: "refresh-token",
        scope: "user-read-email playlist-modify-private playlist-modify-public",
      }),
      encrypt: (value) => `encrypted:${value}`,
      now: () => now,
      userId: "user-123",
    });

    expect(payload).toEqual({
      userId: "user-123",
      spotifyUserId: "spotify-user-123",
      refreshTokenCiphertext: "encrypted:refresh-token",
      scopes: ["user-read-email", "playlist-modify-private", "playlist-modify-public"],
      now,
    });

    expect(buildSpotifyConnectionUpdateSet(payload!)).toMatchObject({
      refreshTokenCiphertext: "encrypted:refresh-token",
      revokedAt: null,
      lastError: null,
    });
  });

  it("preserves an existing refresh token when Spotify omits a new one", () => {
    const payload = buildSpotifyConnectionSyncPayload({
      account: spotifyAccount(),
      encrypt: (value) => `encrypted:${value}`,
      now: () => new Date("2026-04-24T12:00:00.000Z"),
      userId: "user-123",
    });

    expect(payload?.refreshTokenCiphertext).toBeNull();
    expect(payload?.scopes).toEqual([...SPOTIFY_AUTH_SCOPES]);
    expect(buildSpotifyConnectionUpdateSet(payload!)).not.toHaveProperty(
      "refreshTokenCiphertext",
    );
  });

  it("ignores non-Spotify accounts", () => {
    expect(
      buildSpotifyConnectionSyncPayload({
        account: {
          provider: "google",
          providerAccountId: "google-user-123",
          type: "oauth",
        } as Account,
        userId: "user-123",
      }),
    ).toBeNull();
  });
});

describe("syncSpotifyConnectionFromAccount", () => {
  it("upserts the encrypted Spotify connection", async () => {
    const now = new Date("2026-04-24T12:00:00.000Z");
    const onConflictDoUpdate = vi.fn();
    const values = vi.fn(() => ({ onConflictDoUpdate }));
    const insert = vi.fn(() => ({ values }));

    const result = await syncSpotifyConnectionFromAccount({
      account: spotifyAccount({
        refresh_token: "refresh-token",
        scope: "playlist-modify-private",
      }),
      deps: {
        db: { insert } as never,
        encrypt: (value) => `encrypted:${value}`,
        now: () => now,
      },
      userId: "user-123",
    });

    expect(result).toBe(true);
    expect(insert).toHaveBeenCalledWith(spotifyConnections);
    expect(values).toHaveBeenCalledWith({
      userId: "user-123",
      spotifyUserId: "spotify-user-123",
      refreshTokenCiphertext: "encrypted:refresh-token",
      scopes: ["playlist-modify-private"],
      connectedAt: now,
      updatedAt: now,
      lastRefreshAt: now,
      revokedAt: null,
      lastError: null,
    });
    expect(onConflictDoUpdate).toHaveBeenCalledWith({
      target: spotifyConnections.userId,
      set: expect.objectContaining({
        spotifyUserId: "spotify-user-123",
        refreshTokenCiphertext: "encrypted:refresh-token",
        scopes: ["playlist-modify-private"],
        updatedAt: now,
        lastRefreshAt: now,
        revokedAt: null,
        lastError: null,
      }),
    });
  });
});
