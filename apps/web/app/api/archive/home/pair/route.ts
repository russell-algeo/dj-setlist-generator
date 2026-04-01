import { NextRequest, NextResponse } from "next/server";

import { getArchiveHomePairPayload } from "@/lib/archive/home-explorer-data";
import { getSessionActor } from "@/lib/auth/session";

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const artistASlug = searchParams.get("a");
  const artistBSlug = searchParams.get("b");
  const scope = searchParams.get("scope");

  if (!artistASlug || !artistBSlug) {
    return NextResponse.json(
      {
        error: "Both `a` and `b` artist slugs are required.",
      },
      { status: 400 },
    );
  }

  let userId: string | undefined;
  if (scope === "mine") {
    const actor = await getSessionActor();
    if (actor) {
      userId = actor.userId;
    }
  }

  const payload = await getArchiveHomePairPayload({
    artistASlug,
    artistBSlug,
    userId,
  });

  if (!payload) {
    return NextResponse.json(
      {
        error: "Pair not found.",
      },
      { status: 404 },
    );
  }

  return NextResponse.json(payload);
}
