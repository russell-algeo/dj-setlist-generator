import { NextRequest, NextResponse } from "next/server";

import {
  getArchiveHomeAtlasPayload,
  getWorkspaceArtistCards,
} from "@/lib/archive/home-explorer-data";
import type { ArchiveHomeCompareMode } from "@/lib/archive/home-explorer-types";
import { getSessionActor } from "@/lib/auth/session";

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const compareMode = searchParams.get("mode");
  const scope = searchParams.get("scope");
  const rawSlugs = searchParams
    .getAll("artist")
    .flatMap((value) => value.split(","))
    .map((value) => value.trim())
    .filter(Boolean);

  const resolvedMode: ArchiveHomeCompareMode =
    compareMode === "intersection" || compareMode === "union"
      ? (compareMode as ArchiveHomeCompareMode)
      : "union";

  // In workspace mode, resolve userId and optionally expand __ALL__
  let selectedArtistSlugs = rawSlugs;
  let userId: string | undefined;
  if (scope === "mine") {
    const actor = await getSessionActor();
    if (actor) {
      userId = actor.userId;
      if (rawSlugs.includes("__ALL__")) {
        const workspaceCards = await getWorkspaceArtistCards(actor.userId);
        selectedArtistSlugs = workspaceCards.map((a) => a.slug);
      }
    }
  }

  const payload = await getArchiveHomeAtlasPayload({
    compareMode: resolvedMode,
    selectedArtistSlugs,
    userId,
  });

  return NextResponse.json(payload);
}
