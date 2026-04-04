import { NextResponse } from "next/server";

import { getSessionActor, getSpotifyConnectionForUser } from "@/lib/auth/session";
import { env } from "@/lib/env";

export async function GET() {
  const actor = await getSessionActor();

  if (!actor) {
    return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  }

  const connection = await getSpotifyConnectionForUser(actor.userId) as {
    refreshTokenCiphertext: string | null;
    revokedAt: Date | null;
  } | null;
  const spotifyConnected = Boolean(
    connection && connection.refreshTokenCiphertext && !connection.revokedAt,
  );
  const spotifyConfigured = Boolean(env.spotifyClientId && env.spotifyClientSecret);

  return NextResponse.json({ spotifyConfigured, spotifyConnected });
}
