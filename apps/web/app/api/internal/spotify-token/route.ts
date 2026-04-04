import { NextResponse } from "next/server";

import { eq } from "drizzle-orm";

import { assertInternalRequest } from "@/lib/auth/session";
import { getDb } from "@/lib/db/client";
import { setRuns } from "@/lib/db/schema";
import { readRequestBody } from "@/lib/http/request-body";
import {
  refreshSpotifyAccessTokenForUser,
  SpotifyConfigurationError,
  SpotifyConnectionError,
  SpotifyTokenRefreshError,
} from "@/lib/spotify/server";

const db = getDb();

export async function POST(request: Request) {
  const denial = assertInternalRequest(request);
  if (denial) {
    return denial;
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

  try {
    const token = await refreshSpotifyAccessTokenForUser(targetUserId);

    return NextResponse.json({
      access_token: token.accessToken,
      expires_in: token.expiresIn,
      spotify_user_id: token.spotifyUserId,
    });
  } catch (error) {
    if (error instanceof SpotifyConnectionError) {
      return NextResponse.json({ error: error.message }, { status: 404 });
    }

    if (error instanceof SpotifyConfigurationError) {
      return NextResponse.json({ error: error.message }, { status: 503 });
    }

    if (error instanceof SpotifyTokenRefreshError) {
      return NextResponse.json({ error: error.message }, { status: 502 });
    }

    throw error;
  }
}
