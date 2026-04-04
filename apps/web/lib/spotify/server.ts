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

export const refreshSpotifyAccessTokenForUser = async (
  targetUserId: string,
): Promise<RefreshedSpotifyAccessToken> => {
  const db = getDb();

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

  const tokenResponse = await fetch("https://accounts.spotify.com/api/token", {
    method: "POST",
    headers: {
      authorization: `Basic ${Buffer.from(
        `${env.spotifyClientId}:${env.spotifyClientSecret}`,
      ).toString("base64")}`,
      "content-type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: decryptSecret(connection.refreshTokenCiphertext),
    }),
  });

  if (!tokenResponse.ok) {
    const errorText = await tokenResponse.text().catch(() => "unknown error");
    await db
      .update(spotifyConnections)
      .set({ lastError: `${tokenResponse.status}: ${errorText}`, updatedAt: new Date() })
      .where(eq(spotifyConnections.userId, targetUserId));
    throw new SpotifyTokenRefreshError("Spotify token refresh failed");
  }

  const tokenPayload = (await tokenResponse.json()) as {
    access_token: string;
    expires_in: number;
  };

  await db
    .update(spotifyConnections)
    .set({
      lastRefreshAt: new Date(),
      lastError: null,
      updatedAt: new Date(),
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
