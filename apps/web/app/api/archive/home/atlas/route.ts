import { NextRequest, NextResponse } from "next/server";

import { getArchiveHomeAtlasPayload } from "@/lib/archive/home-explorer-data";
import type { ArchiveHomeCompareMode } from "@/lib/archive/home-explorer-types";

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const compareMode = searchParams.get("mode");
  const selectedArtistSlugs = searchParams
    .getAll("artist")
    .flatMap((value) => value.split(","))
    .map((value) => value.trim())
    .filter(Boolean);

  const payload = await getArchiveHomeAtlasPayload({
    compareMode:
      compareMode === "intersection" || compareMode === "union"
        ? (compareMode as ArchiveHomeCompareMode)
        : "union",
    selectedArtistSlugs,
  });

  return NextResponse.json(payload);
}
