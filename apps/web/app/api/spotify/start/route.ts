import { NextResponse } from "next/server";

import { env } from "@/lib/env";

export async function GET(request: Request) {
  if (!env.spotifyClientId || !env.spotifyClientSecret) {
    return NextResponse.json({ error: "Spotify OAuth is not configured yet" }, { status: 503 });
  }

  const requestUrl = new URL(request.url);
  const callbackUrl =
    requestUrl.searchParams.get("callbackUrl") ??
    new URL("/?spotify=connected", request.url).toString();
  const signInUrl = new URL("/api/auth/signin/spotify", request.url);
  signInUrl.searchParams.set("callbackUrl", callbackUrl);

  return NextResponse.redirect(signInUrl, { status: 302 });
}
