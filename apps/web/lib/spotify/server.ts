import "server-only";

import { eq } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { spotifyConnections } from "@/lib/db/schema";
import { env } from "@/lib/env";
import { decryptSecret } from "@/lib/security/encryption";

export class SpotifyConnectionError extends Error {}
export class SpotifyConfigurationError extends Error {}
export class SpotifyTokenRefreshError extends Error {}

export type RefreshedSpotifyAccessToken = {
  accessToken: string;
  expiresIn: number;
  scopes: string[];
  spotifyUserId: string;
};

type SpotifyTokenRefreshDeps = {
  db?: ReturnType<typeof getDb>;
  decrypt?: (cipherText: string) => string;
  fetchFn?: typeof fetch;
  now?: () => Date;
};

const SPOTIFY_RECONNECT_REQUIRED_MESSAGE =
  "Spotify connection needs to be reconnected. Connect Spotify again and retry the export.";

export const refreshSpotifyAccessTokenForUser = async (
  targetUserId: string,
  deps: SpotifyTokenRefreshDeps = {},
): Promise<RefreshedSpotifyAccessToken> => {
  const db = deps.db ?? getDb();
  const decrypt = deps.decrypt ?? decryptSecret;
  const fetchFn = deps.fetchFn ?? fetch;
  const now = deps.now ?? (() => new Date());

  if (!env.spotifyClientId || !env.spotifyClientSecret) {
    throw new SpotifyConfigurationError("Spotify OAuth is not configured");
  }

  const [connection] = await db
    .select()
    .from(spotifyConnections)
    .where(eq(spotifyConnections.userId, targetUserId))
    .limit(1);

  if (!connection?.refreshTokenCiphertext || connection.revokedAt) {
    throw new SpotifyConnectionError("No Spotify connection found");
  }

  let refreshToken: string;

  try {
    refreshToken = decrypt(connection.refreshTokenCiphertext);
  } catch {
    const timestamp = now();

    await db
      .update(spotifyConnections)
      .set({
        lastError: "Stored Spotify refresh token could not be decrypted. Reconnect Spotify.",
        revokedAt: timestamp,
        updatedAt: timestamp,
      })
      .where(eq(spotifyConnections.userId, targetUserId));

    throw new SpotifyConnectionError(SPOTIFY_RECONNECT_REQUIRED_MESSAGE);
  }

  const tokenResponse = await fetchFn("https://accounts.spotify.com/api/token", {
    method: "POST",
    headers: {
      authorization: `Basic ${Buffer.from(
        `${env.spotifyClientId}:${env.spotifyClientSecret}`,
      ).toString("base64")}`,
      "content-type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: refreshToken,
    }),
  });

  if (!tokenResponse.ok) {
    const errorText = await tokenResponse.text().catch(() => "unknown error");
    const timestamp = now();

    await db
      .update(spotifyConnections)
      .set({ lastError: `${tokenResponse.status}: ${errorText}`, updatedAt: timestamp })
      .where(eq(spotifyConnections.userId, targetUserId));
    throw new SpotifyTokenRefreshError("Spotify token refresh failed");
  }

  const tokenPayload = (await tokenResponse.json()) as {
    access_token: string;
    expires_in: number;
  };

  const refreshedAt = now();

  await db
    .update(spotifyConnections)
    .set({
      lastRefreshAt: refreshedAt,
      lastError: null,
      updatedAt: refreshedAt,
    })
    .where(eq(spotifyConnections.userId, targetUserId));

  return {
    accessToken: tokenPayload.access_token,
    expiresIn: tokenPayload.expires_in,
    scopes: Array.isArray(connection.scopes)
      ? connection.scopes.flatMap((scope) => (typeof scope === "string" ? [scope] : []))
      : [],
    spotifyUserId: connection.spotifyUserId,
  };
};
