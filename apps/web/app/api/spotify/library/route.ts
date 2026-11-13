import { NextResponse } from "next/server";
import { z } from "zod";

import { getSessionActor } from "@/lib/auth/session";
import {
  ensureSpotifyLibraryScope,
  isSpotifyTrackId,
  setSpotifyTrackSaved,
  SpotifyLibraryRemoteError,
  SpotifyLibraryScopeError,
} from "@/lib/spotify/library.server";
import {
  refreshSpotifyAccessTokenForUser,
  SpotifyConfigurationError,
  SpotifyConnectionError,
  SpotifyTokenRefreshError,
} from "@/lib/spotify/server";

const librarySchema = z.object({
  saved: z.boolean(),
  trackId: z.string().refine(isSpotifyTrackId, "Invalid Spotify track id"),
});

// Browser-session only: a cross-site page cannot send a JSON body without a
// CORS preflight, which this route never approves.
export async function POST(request: Request) {
  if (!(request.headers.get("content-type") ?? "").includes("application/json")) {
    return NextResponse.json({ error: "JSON body required" }, { status: 415 });
  }

  const actor = await getSessionActor();
  if (!actor) {
    return NextResponse.json({ error: "Sign in to save tracks", reason: "signin" }, { status: 401 });
  }

  const parsed = librarySchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.issues[0]?.message ?? "Invalid request" }, { status: 400 });
  }

  try {
    const token = await refreshSpotifyAccessTokenForUser(actor.userId);
    ensureSpotifyLibraryScope(token.scopes);
    await setSpotifyTrackSaved({
      accessToken: token.accessToken,
      saved: parsed.data.saved,
      trackId: parsed.data.trackId,
    });
    return NextResponse.json({ saved: parsed.data.saved });
  } catch (error) {
    if (error instanceof SpotifyConnectionError || error instanceof SpotifyLibraryScopeError) {
      return NextResponse.json({ error: error.message, reason: "connect" }, { status: 409 });
    }
    if (error instanceof SpotifyConfigurationError) {
      return NextResponse.json({ error: error.message }, { status: 503 });
    }
    if (error instanceof SpotifyTokenRefreshError || error instanceof SpotifyLibraryRemoteError) {
      return NextResponse.json({ error: error.message }, { status: 502 });
    }
    throw error;
  }
}
