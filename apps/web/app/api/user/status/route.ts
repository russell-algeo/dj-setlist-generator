import { NextResponse } from "next/server";

import { getSessionActor, getSpotifyConnectionForUser } from "@/lib/auth/session";

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

  return NextResponse.json({ spotifyConnected });
}
