import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { requireSessionActor } from "@/lib/auth/session";
import { getDb } from "@/lib/db/client";
import { spotifyConnections } from "@/lib/db/schema";
import { env } from "@/lib/env";
import { encryptSecret } from "@/lib/security/encryption";

const db = getDb();

export async function GET(request: Request) {
  const actor = await requireSessionActor("/");
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const error = url.searchParams.get("error");
  const cookieStore = await cookies();
  const expectedState = cookieStore.get("spotify_oauth_state")?.value;

  if (error) {
    return NextResponse.redirect(new URL("/?spotify=error", request.url));
  }

  if (!code || !state || !expectedState || state !== expectedState) {
    return NextResponse.redirect(new URL("/?spotify=invalid_state", request.url));
  }

  if (!env.spotifyClientId || !env.spotifyClientSecret || !env.spotifyRedirectUri) {
    return NextResponse.redirect(new URL("/?spotify=missing_config", request.url));
  }

  const tokenResponse = await fetch("https://accounts.spotify.com/api/token", {
    method: "POST",
    headers: {
      authorization: `Basic ${Buffer.from(`${env.spotifyClientId}:${env.spotifyClientSecret}`).toString("base64")}`,
      "content-type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code,
      redirect_uri: env.spotifyRedirectUri,
    }),
  });

  if (!tokenResponse.ok) {
    return NextResponse.redirect(new URL("/?spotify=token_error", request.url));
  }

  const tokenPayload = (await tokenResponse.json()) as {
    access_token: string;
    refresh_token?: string;
    scope?: string;
  };

  const profileResponse = await fetch("https://api.spotify.com/v1/me", {
    headers: {
      authorization: `Bearer ${tokenPayload.access_token}`,
    },
  });

  if (!profileResponse.ok) {
    return NextResponse.redirect(new URL("/?spotify=profile_error", request.url));
  }

  const profile = (await profileResponse.json()) as {
    id: string;
  };

  await db
    .insert(spotifyConnections)
    .values({
      userId: actor.userId,
      spotifyUserId: profile.id,
      refreshTokenCiphertext: tokenPayload.refresh_token
        ? encryptSecret(tokenPayload.refresh_token)
        : null,
      scopes: tokenPayload.scope?.split(" ") ?? [],
      connectedAt: new Date(),
      updatedAt: new Date(),
      lastRefreshAt: new Date(),
      revokedAt: null,
      lastError: null,
    })
    .onConflictDoUpdate({
      target: spotifyConnections.userId,
      set: {
        spotifyUserId: profile.id,
        refreshTokenCiphertext: tokenPayload.refresh_token
          ? encryptSecret(tokenPayload.refresh_token)
          : spotifyConnections.refreshTokenCiphertext,
        scopes: tokenPayload.scope?.split(" ") ?? [],
        updatedAt: new Date(),
        lastRefreshAt: new Date(),
        revokedAt: null,
        lastError: null,
      },
    });

  cookieStore.delete("spotify_oauth_state");

  return NextResponse.redirect(new URL("/?spotify=connected", request.url));
}
