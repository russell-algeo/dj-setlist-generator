import { NextRequest, NextResponse } from "next/server";

import {
  getArchiveHomeSetLibraryPayload,
  getWorkspaceSetLibraryPayload,
} from "@/lib/archive/home-explorer-data";
import type { ArchiveHomeSetSort } from "@/lib/archive/home-explorer-types";
import { getSessionActor } from "@/lib/auth/session";

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const page = Number(searchParams.get("page") ?? "1");
  const query = searchParams.get("query") ?? "";
  const artistFilter = searchParams.get("artist") ?? "ALL";
  const scope = searchParams.get("scope");
  const sort = searchParams.get("sort");
  const resolvedSort: ArchiveHomeSetSort =
    sort === "default" || sort === "duration" || sort === "rate" || sort === "tracks"
      ? (sort as ArchiveHomeSetSort)
      : "default";
  const safePage = Number.isFinite(page) ? page : 1;

  if (scope === "mine") {
    const actor = await getSessionActor();
    if (actor) {
      const payload = await getWorkspaceSetLibraryPayload({
        artistFilter,
        page: safePage,
        query,
        sort: resolvedSort,
        userId: actor.userId,
      });
      return NextResponse.json(payload);
    }
  }

  const payload = await getArchiveHomeSetLibraryPayload({
    artistFilter,
    page: safePage,
    query,
    sort: resolvedSort,
  });

  return NextResponse.json(payload);
}
