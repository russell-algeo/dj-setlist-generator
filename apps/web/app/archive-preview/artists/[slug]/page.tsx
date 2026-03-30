import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ArchiveArtistPage } from "@/components/archive/archive-pages";
import { getArchiveArtistSummaryBySlug } from "@/lib/archive/data";
import { buildArchiveMetadata } from "@/lib/archive/metadata";

type PreviewArtistPageProps = {
  params: Promise<{
    slug: string;
  }>;
  searchParams: Promise<{
    q?: string;
  }>;
};

export async function generateMetadata({
  params,
}: PreviewArtistPageProps): Promise<Metadata> {
  const { slug } = await params;
  const artist = await getArchiveArtistSummaryBySlug(slug);

  return buildArchiveMetadata({
    title: artist ? `${artist.name} Preview` : "Artist Preview",
    description:
      "Preview the React-native artist archive page driven by normalized set and track rows.",
    noindex: true,
  });
}

export default async function PreviewArtistPage({
  params,
  searchParams,
}: PreviewArtistPageProps) {
  const [{ slug }, queryParams] = await Promise.all([params, searchParams]);
  const artist = await getArchiveArtistSummaryBySlug(slug);

  if (!artist) {
    notFound();
  }

  return <ArchiveArtistPage artist={artist} preview query={queryParams.q?.trim() ?? ""} />;
}
