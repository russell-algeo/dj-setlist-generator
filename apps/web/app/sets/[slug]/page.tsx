import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ArchiveSetPage } from "@/components/archive/archive-pages";
import { getArchiveSetManagementBySlug } from "@/lib/archive/deletions";
import { buildArchiveMetadata } from "@/lib/archive/metadata";
import { getSessionActor } from "@/lib/auth/session";

type SetDetailPageProps = {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ q?: string }>;
};

const loadArchiveData = async () => import("@/lib/archive/data");

export async function generateMetadata({ params }: SetDetailPageProps): Promise<Metadata> {
  const { slug } = await params;
  const { getArchiveSetDetailBySlug } = await loadArchiveData();
  const detail = await getArchiveSetDetailBySlug(slug);
  return buildArchiveMetadata({
    title: detail ? `${detail.title} | Set Signal Archive` : "Set Archive",
    description: "React-rendered set archive page driven by normalized set and track rows.",
    canonicalPath: `/sets/${slug}`,
  });
}

export default async function SetDetailPage({ params, searchParams }: SetDetailPageProps) {
  const [{ slug }, queryParams] = await Promise.all([params, searchParams]);
  const [{ getArchiveSetDetailBySlug }, actor] = await Promise.all([
    loadArchiveData(),
    getSessionActor(),
  ]);
  const [detail, management] = await Promise.all([
    getArchiveSetDetailBySlug(slug),
    getArchiveSetManagementBySlug(slug, actor),
  ]);
  if (!detail) notFound();
  return <ArchiveSetPage detail={detail} management={management} query={queryParams.q?.trim() ?? ""} />;
}
