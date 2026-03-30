import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ArchiveArtistPage, ArchiveSetPage } from "@/components/archive/archive-pages";
import { buildArchiveMetadata } from "@/lib/archive/metadata";
import { normalizeLegacyPath } from "@/lib/archive/utils";

type LegacyArchivePageProps = {
  params: Promise<{
    legacy: string[];
  }>;
  searchParams: Promise<{
    q?: string;
  }>;
};

const getPagePath = async (paramsPromise: LegacyArchivePageProps["params"]) => {
  const params = await paramsPromise;
  return normalizeLegacyPath(params.legacy.join("/"));
};

const loadArchiveData = async () => import("@/lib/archive/data");

export async function generateMetadata({
  params,
}: LegacyArchivePageProps): Promise<Metadata> {
  const legacyPath = await getPagePath(params);
  const { resolveLegacyArchivePath, getArchiveArtistSummaryBySlug, getArchiveSetDetailBySlug } =
    await loadArchiveData();
  const resolution = await resolveLegacyArchivePath(legacyPath);

  if (!resolution) {
    return buildArchiveMetadata({
      title: "Archive Page",
      description: "Structured archive page rendered from normalized archive rows.",
    });
  }

  if (resolution.entityType === "artist") {
    const artist = await getArchiveArtistSummaryBySlug(resolution.slug);
    return buildArchiveMetadata({
      title: artist ? `${artist.name} | Set Signal Archive` : "Artist Archive",
      description:
        "React-rendered artist archive page driven by normalized sets and tracks.",
      canonicalPath: resolution.legacyPath,
    });
  }

  const detail = await getArchiveSetDetailBySlug(resolution.slug);
  return buildArchiveMetadata({
    title: detail ? `${detail.title} | Set Signal Archive` : "Set Archive",
    description:
      "React-rendered set archive page driven by normalized set and track rows.",
    canonicalPath: resolution.legacyPath,
  });
}

export default async function LegacyArchivePage({
  params,
  searchParams,
}: LegacyArchivePageProps) {
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

    return <ArchiveArtistPage artist={artist} preview={false} query={queryParams.q?.trim() ?? ""} />;
  }

  const detail = await getArchiveSetDetailBySlug(resolution.slug);
  if (!detail) {
    notFound();
  }

  return <ArchiveSetPage detail={detail} preview={false} query={queryParams.q?.trim() ?? ""} />;
}
