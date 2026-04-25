import type { Metadata } from "next";
import Link from "next/link";

import { ArchiveHomeExplorer } from "@/components/archive/archive-home-explorer";
import { AppShell } from "@/components/app-shell";
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

  // Unauthenticated workspace request — show sign-in prompt
  if (isPersonal && !actor) {
    return (
      <AppShell
        title="Set Signal Explorer"
        eyebrow="Public archive"
        description="React-native archive homepage with the current archive explorer design and behavior."
      >
        <div className="inline-actions" style={{ marginBottom: 18 }}>
          <Link className="pill-link pill-link--active" href="/?scope=mine">
            My workspace
          </Link>
          <Link className="pill-link" href="/">
            Global
          </Link>
        </div>
        <section className="panel">
          <div className="empty-state">
            <p>
              <strong>Sign in to see your workspace.</strong>
            </p>
            <p style={{ marginTop: 8 }}>
              Your personal workspace shows only the artists and sets from runs you submitted.
            </p>
            <div style={{ marginTop: 14 }}>
              <Link
                className="pill-link"
                href={`/signin?callbackUrl=${encodeURIComponent("/?scope=mine")}`}
              >
                Sign in →
              </Link>
            </div>
          </div>
        </section>
      </AppShell>
    );
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
