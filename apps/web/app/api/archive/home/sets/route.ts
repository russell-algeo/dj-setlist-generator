import { NextRequest, NextResponse } from "next/server";

import { getArchiveHomeSetLibraryPayload } from "@/lib/archive/home-explorer-data";
import type { ArchiveHomeSetSort } from "@/lib/archive/home-explorer-types";

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const page = Number(searchParams.get("page") ?? "1");
  const query = searchParams.get("query") ?? "";
  const artistFilter = searchParams.get("artist") ?? "ALL";
  const sort = searchParams.get("sort");

  const payload = await getArchiveHomeSetLibraryPayload({
    artistFilter,
    page: Number.isFinite(page) ? page : 1,
    query,
    sort:
      sort === "default" ||
      sort === "duration" ||
      sort === "rate" ||
      sort === "tracks"
        ? (sort as ArchiveHomeSetSort)
        : "default",
  });

  return NextResponse.json(payload);
}
