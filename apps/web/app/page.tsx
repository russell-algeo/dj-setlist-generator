import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { ArchiveHomeExplorer } from "@/components/archive/archive-home-explorer";
import { getArchiveHomeExplorerInitial } from "@/lib/archive/home-explorer-data";
import { buildArchiveMetadata } from "@/lib/archive/metadata";
import { getSessionActor } from "@/lib/auth/session";

type HomePageProps = {
  searchParams: Promise<Record<string, string | undefined>>;
};

export async function generateMetadata({
  searchParams,
}: HomePageProps): Promise<Metadata> {
  await searchParams;

  return buildArchiveMetadata({
    title: "Set Signal Explorer",
    description:
      "React-native archive homepage with the current archive explorer design and behavior.",
    canonicalPath: "/",
  });
}

export default async function HomePage({ searchParams }: HomePageProps) {
  const resolvedSearchParams = await searchParams;
  const scope = resolvedSearchParams.scope === "mine" ? "mine" : "global";
  const isPersonal = scope === "mine";

  const actor = await getSessionActor();

  if (isPersonal && !actor) {
    redirect(`/?callbackUrl=${encodeURIComponent("/?scope=mine")}`);
  }

  const payload = await getArchiveHomeExplorerInitial({
    artistFilter: resolvedSearchParams.artist,
    compareMode:
      resolvedSearchParams.mode === "intersection" ||
      resolvedSearchParams.mode === "union"
        ? resolvedSearchParams.mode
        : "union",
    page: Number(resolvedSearchParams.page ?? "1"),
    query: resolvedSearchParams.query ?? "",
    scope,
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
    userId: actor?.userId,
    viewerUserId: actor?.userId,
  });

  return <ArchiveHomeExplorer initial={payload} />;
}
