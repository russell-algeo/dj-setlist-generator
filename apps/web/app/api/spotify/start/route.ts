import { randomUUID } from "node:crypto";

import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { requireSessionActor } from "@/lib/auth/session";
import { env } from "@/lib/env";

export async function GET(request: Request) {
  await requireSessionActor("/api/spotify/start");

  if (!env.spotifyClientId || !env.spotifyRedirectUri) {
    return NextResponse.json({ error: "Spotify OAuth is not configured yet" }, { status: 503 });
  }

  const state = randomUUID();
  const cookieStore = await cookies();
  cookieStore.set("spotify_oauth_state", state, {
    httpOnly: true,
    sameSite: "lax",
    secure: request.url.startsWith("https://"),
    path: "/",
    maxAge: 60 * 10,
  });

  const url = new URL("https://accounts.spotify.com/authorize");
  url.searchParams.set("client_id", env.spotifyClientId);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("redirect_uri", env.spotifyRedirectUri);
  url.searchParams.set("scope", "playlist-modify-private playlist-modify-public");
  url.searchParams.set("state", state);

  return NextResponse.redirect(url, { status: 302 });
}
