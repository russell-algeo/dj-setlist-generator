import type { Metadata } from "next";

import { ArchiveHomeExplorer } from "@/components/archive/archive-home-explorer";
import { getArchiveHomeExplorerInitialPreview } from "@/lib/archive/home-explorer-data";
import { buildArchiveMetadata } from "@/lib/archive/metadata";

type PreviewHomePageProps = {
  searchParams: Promise<Record<string, string | undefined>>;
};

export const metadata: Metadata = buildArchiveMetadata({
  title: "Set Signal Explorer",
  description:
    "Preview the React-native archive homepage with the current archive explorer design and behavior.",
  noindex: true,
});

export default async function ArchivePreviewPage({
  searchParams,
}: PreviewHomePageProps) {
  const resolvedSearchParams = await searchParams;
  const payload = await getArchiveHomeExplorerInitialPreview({
    artistFilter: resolvedSearchParams.artist,
    compareMode:
      resolvedSearchParams.mode === "intersection" ||
      resolvedSearchParams.mode === "union"
        ? resolvedSearchParams.mode
        : "union",
    page: Number(resolvedSearchParams.page ?? "1"),
    query: resolvedSearchParams.query ?? "",
    selectedArtistSlugs: resolvedSearchParams.artists
      ? resolvedSearchParams.artists.split(",").map((value) => value.trim()).filter(Boolean)
      : undefined,
    sort:
      resolvedSearchParams.sort === "duration" ||
      resolvedSearchParams.sort === "rate" ||
      resolvedSearchParams.sort === "tracks" ||
      resolvedSearchParams.sort === "default"
        ? resolvedSearchParams.sort
        : "default",
  });

  return <ArchiveHomeExplorer initial={payload} preview />;
}
