import { notFound, redirect } from "next/navigation";

import { getSetBySlug } from "@/lib/archive/repository";

type SetDetailPageProps = {
  params: Promise<{
    slug: string;
  }>;
};

export default async function SetDetailPage({ params }: SetDetailPageProps) {
  const { slug } = await params;
  const setRecord = await getSetBySlug(slug);

  if (!setRecord) {
    notFound();
  }

  if (!setRecord.legacyPath) {
    notFound();
  }

  redirect(setRecord.legacyPath);
}
