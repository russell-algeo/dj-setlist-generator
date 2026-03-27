import { NextResponse } from "next/server";

import { eq } from "drizzle-orm";

import { assertInternalRequest } from "@/lib/auth/session";
import { getDb } from "@/lib/db/client";
import { setRuns, spotifyConnections } from "@/lib/db/schema";
import { env } from "@/lib/env";
import { readRequestBody } from "@/lib/http/request-body";
import { decryptSecret } from "@/lib/security/encryption";

const db = getDb();

export async function POST(request: Request) {
  const denial = assertInternalRequest(request);
  if (denial) {
    return denial;
  }

  if (!env.spotifyClientId || !env.spotifyClientSecret) {
    return NextResponse.json({ error: "Spotify OAuth is not configured" }, { status: 503 });
  }

  const body = await readRequestBody(request);
  const setRunId = body.setRunId ? String(body.setRunId) : undefined;
  const userId = body.userId ? String(body.userId) : undefined;

  let targetUserId = userId;

  if (!targetUserId && setRunId) {
    const [run] = await db.select().from(setRuns).where(eq(setRuns.id, setRunId)).limit(1);
    targetUserId = run?.requestedBy;
  }

  if (!targetUserId) {
    return NextResponse.json({ error: "userId or setRunId is required" }, { status: 400 });
  }

  const [connection] = await db
    .select()
    .from(spotifyConnections)
    .where(eq(spotifyConnections.userId, targetUserId))
    .limit(1);

  if (!connection?.refreshTokenCiphertext) {
    return NextResponse.json({ error: "No Spotify connection found" }, { status: 404 });
  }

  const tokenResponse = await fetch("https://accounts.spotify.com/api/token", {
    method: "POST",
    headers: {
      authorization: `Basic ${Buffer.from(`${env.spotifyClientId}:${env.spotifyClientSecret}`).toString("base64")}`,
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
    return NextResponse.json({ error: "Spotify token refresh failed" }, { status: 502 });
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

  return NextResponse.json({
    access_token: tokenPayload.access_token,
    expires_in: tokenPayload.expires_in,
    spotify_user_id: connection.spotifyUserId,
  });
}
