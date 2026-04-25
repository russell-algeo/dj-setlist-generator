import "server-only";

import type { Account } from "next-auth";

import { getDb } from "@/lib/db/client";
import { spotifyConnections } from "@/lib/db/schema";
import { encryptSecret } from "@/lib/security/encryption";

export const SPOTIFY_AUTH_SCOPES = [
  "user-read-email",
  "playlist-modify-private",
  "playlist-modify-public",
] as const;

export const SPOTIFY_AUTH_SCOPE = SPOTIFY_AUTH_SCOPES.join(" ");

type SpotifyConnectionSyncPayload = {
  userId: string;
  spotifyUserId: string;
  refreshTokenCiphertext: string | null;
  scopes: string[];
  now: Date;
};

type SpotifyConnectionUpdateSet = {
  spotifyUserId: string;
  refreshTokenCiphertext?: string;
  scopes: string[];
  updatedAt: Date;
  lastRefreshAt: Date;
  revokedAt: null;
  lastError: null;
};

type SpotifyConnectionSyncDeps = {
  db?: ReturnType<typeof getDb>;
  encrypt?: (plainText: string) => string;
  now?: () => Date;
};

const parseScope = (scope: string | null | undefined) => {
  const parsed = scope
    ?.split(" ")
    .map((value) => value.trim())
    .filter(Boolean);

  return parsed && parsed.length > 0 ? parsed : [...SPOTIFY_AUTH_SCOPES];
};

export const buildSpotifyConnectionSyncPayload = ({
  account,
  encrypt = encryptSecret,
  now = () => new Date(),
  userId,
}: {
  account: Account;
  encrypt?: (plainText: string) => string;
  now?: () => Date;
  userId: string;
}): SpotifyConnectionSyncPayload | null => {
  if (account.provider !== "spotify" || !account.providerAccountId) {
    return null;
  }

  return {
    userId,
    spotifyUserId: account.providerAccountId,
    refreshTokenCiphertext: account.refresh_token ? encrypt(account.refresh_token) : null,
    scopes: parseScope(account.scope),
    now: now(),
  };
};

export const buildSpotifyConnectionUpdateSet = (
  payload: SpotifyConnectionSyncPayload,
): SpotifyConnectionUpdateSet => ({
  spotifyUserId: payload.spotifyUserId,
  ...(payload.refreshTokenCiphertext
    ? { refreshTokenCiphertext: payload.refreshTokenCiphertext }
    : {}),
  scopes: payload.scopes,
  updatedAt: payload.now,
  lastRefreshAt: payload.now,
  revokedAt: null,
  lastError: null,
});

export const syncSpotifyConnectionFromAccount = async ({
  account,
  deps = {},
  userId,
}: {
  account: Account | null | undefined;
  deps?: SpotifyConnectionSyncDeps;
  userId: string | null | undefined;
}) => {
  if (!account || !userId) {
    return false;
  }

  const payload = buildSpotifyConnectionSyncPayload({
    account,
    encrypt: deps.encrypt ?? encryptSecret,
    now: deps.now,
    userId,
  });

  if (!payload) {
    return false;
  }

  const db = deps.db ?? getDb();

  await db
    .insert(spotifyConnections)
    .values({
      userId: payload.userId,
      spotifyUserId: payload.spotifyUserId,
      refreshTokenCiphertext: payload.refreshTokenCiphertext,
      scopes: payload.scopes,
      connectedAt: payload.now,
      updatedAt: payload.now,
      lastRefreshAt: payload.now,
      revokedAt: null,
      lastError: null,
    })
    .onConflictDoUpdate({
      target: spotifyConnections.userId,
      set: buildSpotifyConnectionUpdateSet(payload),
    });

  return true;
};
