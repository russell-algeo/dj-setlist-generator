import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ArchiveArtistPage } from "@/components/archive/archive-pages";
import { getArchiveArtistSummaryBySlug } from "@/lib/archive/data";
import { buildArchiveMetadata } from "@/lib/archive/metadata";

type ArtistDetailPageProps = {
  params: Promise<{
    slug: string;
  }>;
  searchParams: Promise<{
    q?: string;
  }>;
};

export async function generateMetadata({
  params,
}: ArtistDetailPageProps): Promise<Metadata> {
  const { slug } = await params;
  const artist = await getArchiveArtistSummaryBySlug(slug);

  return buildArchiveMetadata({
    title: artist ? `${artist.name} | Set Signal Archive` : "Artist Archive",
    description:
      "React-rendered artist archive page driven by normalized sets and tracks.",
    canonicalPath: `/artists/${slug}`,
  });
}

export default async function ArtistDetailPage({
  params,
  searchParams,
}: ArtistDetailPageProps) {
  const [{ slug }, queryParams] = await Promise.all([params, searchParams]);
  const artist = await getArchiveArtistSummaryBySlug(slug);

  if (!artist) {
    notFound();
  }

  return <ArchiveArtistPage artist={artist} preview={false} query={queryParams.q?.trim() ?? ""} />;
}
