import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ArchiveSetPage } from "@/components/archive/archive-pages";
import { getArchiveSetDetailBySlug } from "@/lib/archive/data";
import { buildArchiveMetadata } from "@/lib/archive/metadata";

type PreviewSetPageProps = {
  params: Promise<{
    slug: string;
  }>;
  searchParams: Promise<{
    q?: string;
  }>;
};

export async function generateMetadata({
  params,
}: PreviewSetPageProps): Promise<Metadata> {
  const { slug } = await params;
  const detail = await getArchiveSetDetailBySlug(slug);

  return buildArchiveMetadata({
    title: detail ? detail.title : "Set Preview",
    description:
      "Preview the React-native set archive page driven by normalized set, track, and artist rows.",
    noindex: true,
  });
}

export default async function PreviewSetPage({
  params,
  searchParams,
}: PreviewSetPageProps) {
  const [{ slug }, queryParams] = await Promise.all([params, searchParams]);
  const detail = await getArchiveSetDetailBySlug(slug);

  if (!detail) {
    notFound();
  }

  return <ArchiveSetPage detail={detail} preview query={queryParams.q?.trim() ?? ""} />;
}
