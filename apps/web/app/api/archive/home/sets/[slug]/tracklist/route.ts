import { NextResponse } from "next/server";

import { getArchiveHomeSetTracklistPayload } from "@/lib/archive/home-explorer-data";

type ArchiveHomeSetTracklistRouteProps = {
  params: Promise<{
    slug: string;
  }>;
};

export async function GET(
  _request: Request,
  { params }: ArchiveHomeSetTracklistRouteProps,
) {
  const { slug } = await params;
  const payload = await getArchiveHomeSetTracklistPayload(slug);

  if (!payload) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  return NextResponse.json(payload);
}
