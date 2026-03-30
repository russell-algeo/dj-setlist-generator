import { NextResponse } from "next/server";

import { getArchiveArtistSummaryBySlug } from "@/lib/archive/data";

type ArchiveArtistSummaryRouteProps = {
  params: Promise<{
    slug: string;
  }>;
};

export async function GET(_request: Request, { params }: ArchiveArtistSummaryRouteProps) {
  const { slug } = await params;
  const artist = await getArchiveArtistSummaryBySlug(slug);

  if (!artist) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  return NextResponse.json(artist);
}
