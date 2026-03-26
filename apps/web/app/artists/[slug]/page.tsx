import { notFound, redirect } from "next/navigation";

import { getArtistBySlug } from "@/lib/archive/repository";

type ArtistDetailPageProps = {
  params: Promise<{
    slug: string;
  }>;
};

export default async function ArtistDetailPage({ params }: ArtistDetailPageProps) {
  const { slug } = await params;
  const artist = await getArtistBySlug(slug);

  if (!artist) {
    notFound();
  }

  if (!artist.legacyPath) {
    notFound();
  }

  redirect(artist.legacyPath);
}
