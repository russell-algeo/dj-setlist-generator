import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ArchiveArtistPage, ArchiveSetPage } from "@/components/archive/archive-pages";
import { buildArchiveMetadata } from "@/lib/archive/metadata";
import { normalizeLegacyPath } from "@/lib/archive/utils";

type PreviewLegacyArchivePageProps = {
  params: Promise<{
    legacy: string[];
  }>;
  searchParams: Promise<{
    q?: string;
  }>;
};

const getPagePath = async (paramsPromise: PreviewLegacyArchivePageProps["params"]) => {
  const params = await paramsPromise;
  return normalizeLegacyPath(params.legacy.join("/"));
};

const loadArchiveData = async () => import("@/lib/archive/data");

export async function generateMetadata({
  params,
}: PreviewLegacyArchivePageProps): Promise<Metadata> {
  const legacyPath = await getPagePath(params);
  const { resolveLegacyArchivePath, getArchiveArtistSummaryBySlug, getArchiveSetDetailBySlug } =
    await loadArchiveData();
  const resolution = await resolveLegacyArchivePath(legacyPath);

  if (!resolution) {
    return buildArchiveMetadata({
      title: "Archive Preview",
      description: "Preview the React-native archive page rendered from normalized archive rows.",
      noindex: true,
    });
  }

  if (resolution.entityType === "artist") {
    const artist = await getArchiveArtistSummaryBySlug(resolution.slug);
    return buildArchiveMetadata({
      title: artist ? `${artist.name} | Set Signal Archive` : "Artist Archive Preview",
      description: "Preview the React-rendered artist archive page.",
      noindex: true,
    });
  }

  const detail = await getArchiveSetDetailBySlug(resolution.slug);
  return buildArchiveMetadata({
    title: detail ? `${detail.title} | Set Signal Archive` : "Set Archive Preview",
    description: "Preview the React-rendered set archive page.",
    noindex: true,
  });
}

export default async function PreviewLegacyArchivePage({
  params,
  searchParams,
}: PreviewLegacyArchivePageProps) {
  const [legacyPath, queryParams] = await Promise.all([getPagePath(params), searchParams]);
  const { resolveLegacyArchivePath, getArchiveArtistSummaryBySlug, getArchiveSetDetailBySlug } =
    await loadArchiveData();
  const resolution = await resolveLegacyArchivePath(legacyPath);

  if (!resolution) {
    notFound();
  }

  if (resolution.entityType === "artist") {
    const artist = await getArchiveArtistSummaryBySlug(resolution.slug);
    if (!artist) {
      notFound();
    }

    return <ArchiveArtistPage artist={artist} preview query={queryParams.q?.trim() ?? ""} />;
  }

  const detail = await getArchiveSetDetailBySlug(resolution.slug);
  if (!detail) {
    notFound();
  }

  return <ArchiveSetPage detail={detail} preview query={queryParams.q?.trim() ?? ""} />;
}
