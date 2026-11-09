import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { YoonCollection } from "@/components/yoon-fest/yoon-collection";
import { YoonAccessBoundary } from "@/components/yoon-fest/yoon-access-boundary";
import { getYoonActor } from "@/lib/yoon-fest/access.server";
import { getYoonSets, toYoonSetDetail } from "@/lib/yoon-fest/data.server";
export const dynamic = "force-dynamic";
export const revalidate = 0;
// Generic even for authorized users: no private title in previews/metadata.
export const metadata: Metadata = { title: "Private collection", robots: { index: false, follow: false, noarchive: true }, referrer: "no-referrer" };
export default async function YoonCollectionPage() {
  const actor = await getYoonActor();
  if (!actor) notFound();
  const sets = (await getYoonSets(actor)).map((set) => ({ detail: toYoonSetDetail(set), boundaryNote: `${set.boundaryStatus}: ${set.boundaryNote}` }));
  return <YoonAccessBoundary viewerId={actor.userId}><YoonCollection sets={sets} /></YoonAccessBoundary>;
}
