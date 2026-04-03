import { NextResponse } from "next/server";

import { suggestArtistsByPrefix } from "@/lib/archive/repository";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const query = searchParams.get("q")?.trim() ?? "";

  if (!query) {
    return NextResponse.json({ artists: [] });
  }

  const artists = await suggestArtistsByPrefix(query, 5);
  return NextResponse.json({ artists });
}
