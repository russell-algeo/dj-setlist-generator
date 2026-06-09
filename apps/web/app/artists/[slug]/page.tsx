import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ArchiveArtistPage } from "@/components/archive/archive-pages";
import { getArchiveArtistManagementBySlug } from "@/lib/archive/deletions";
import { listUserSetListenProgress } from "@/lib/archive/listen-progress.server";
import { buildArchiveMetadata } from "@/lib/archive/metadata";
import type { ArchiveArtistSummary } from "@/lib/archive/types";
import { getSessionActor } from "@/lib/auth/session";

type ArtistDetailPageProps = {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ q?: string; scope?: string }>;
};

const loadArchiveData = async () => import("@/lib/archive/data");

const attachListenProgress = async (
  artist: ArchiveArtistSummary,
  userId: string | null,
): Promise<ArchiveArtistSummary> => {
  if (!userId || artist.sets.length === 0) {
    return artist;
  }

  const progressRows = await listUserSetListenProgress(
    userId,
    artist.sets.map((setItem) => setItem.id),
  );
  const progressBySetId = new Map(progressRows.map((row) => [row.setId, row]));

  return {
    ...artist,
    sets: artist.sets.map((setItem) => {
      const progress = progressBySetId.get(setItem.id);
      return {
        ...setItem,
        listenProgress: progress
          ? {
              coverageRatio: progress.coverageRatio,
              listened: progress.listened,
              listenedAt: progress.listenedAt,
            }
          : null,
      };
    }),
  };
};

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
  const actor = await getSessionActor();

  const { getArchiveArtistSummaryBySlug, getArchiveArtistSummaryBySlugForUser } =
    await loadArchiveData();

  let artist;
  if (scope === "mine") {
    if (actor) {
      artist = await getArchiveArtistSummaryBySlugForUser(slug, actor.userId);
    } else {
      artist = await getArchiveArtistSummaryBySlug(slug);
    }
  } else {
    artist = await getArchiveArtistSummaryBySlug(slug);
  }

  if (!artist) notFound();
  const artistWithListenProgress = await attachListenProgress(artist, actor?.userId ?? null);
  const management = await getArchiveArtistManagementBySlug(slug, actor);
  return (
    <ArchiveArtistPage
      artist={artistWithListenProgress}
      management={management}
      query={queryParams.q?.trim() ?? ""}
      scope={scope}
    />
  );
}
