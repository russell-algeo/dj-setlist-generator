import { NextRequest, NextResponse } from "next/server";

import { getArchiveHomePairPayload } from "@/lib/archive/home-explorer-data";

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const artistASlug = searchParams.get("a");
  const artistBSlug = searchParams.get("b");

  if (!artistASlug || !artistBSlug) {
    return NextResponse.json(
      {
        error: "Both `a` and `b` artist slugs are required.",
      },
      { status: 400 },
    );
  }

  const payload = await getArchiveHomePairPayload({
    artistASlug,
    artistBSlug,
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
