import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ArchiveArtistPage } from "@/components/archive/archive-pages";
import { buildArchiveMetadata } from "@/lib/archive/metadata";
import { getSessionActor } from "@/lib/auth/session";

type ArtistDetailPageProps = {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ q?: string; scope?: string }>;
};

const loadArchiveData = async () => import("@/lib/archive/data");

export async function generateMetadata({ params }: ArtistDetailPageProps): Promise<Metadata> {
  const { slug } = await params;
  const { getArchiveArtistIdentityBySlug } = await loadArchiveData();
  const artist = await getArchiveArtistIdentityBySlug(slug);
  return buildArchiveMetadata({
    title: artist ? `${artist.name} | Set Signal Archive` : "Artist Archive",
    description: "React-rendered artist archive page driven by normalized sets and tracks.",
    canonicalPath: `/artists/${slug}`,
  });
}

export default async function ArtistDetailPage({ params, searchParams }: ArtistDetailPageProps) {
  const [{ slug }, queryParams] = await Promise.all([params, searchParams]);
  const scope = queryParams.scope === "mine" ? "mine" : "global";

  const { getArchiveArtistSummaryBySlug, getArchiveArtistSummaryBySlugForUser } =
    await loadArchiveData();

  let artist;
  if (scope === "mine") {
    const actor = await getSessionActor();
    if (actor) {
      artist = await getArchiveArtistSummaryBySlugForUser(slug, actor.userId);
    } else {
      artist = await getArchiveArtistSummaryBySlug(slug);
    }
  } else {
    artist = await getArchiveArtistSummaryBySlug(slug);
  }

  if (!artist) notFound();
  return <ArchiveArtistPage artist={artist} query={queryParams.q?.trim() ?? ""} />;
}
