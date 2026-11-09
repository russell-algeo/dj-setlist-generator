import { spanDuration } from "@/lib/yoon-fest/playback";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ArchiveSetExplorer } from "@/components/archive/archive-set-explorer";
import { YoonAccessBoundary } from "@/components/yoon-fest/yoon-access-boundary";
import { getYoonActor } from "@/lib/yoon-fest/access.server";
import { getYoonSet, toYoonSetDetail } from "@/lib/yoon-fest/data.server";
export const dynamic = "force-dynamic";
export const revalidate = 0;
export const metadata: Metadata = { title: "Private recording", robots: { index: false, follow: false, noarchive: true }, referrer: "no-referrer" };
export default async function YoonSetPage({ params }: { params: Promise<{ slug: string }> }) {
  const actor = await getYoonActor();
  if (!actor) notFound();
  const set = await getYoonSet(actor, (await params).slug);
  if (!set) notFound();
  return <YoonAccessBoundary viewerId={actor.userId}><ArchiveSetExplorer
    detail={toYoonSetDetail(set)} initialListened={null} initialQuery=""
    management={{ canDeleteSet: false, deleteImpact: null, setWillBeRemoved: false, submittedByViewer: false }}
    privateContext={{ collectionHref: "/collections/yoon-fest", boundaryNote: `${set.boundaryStatus}: ${set.boundaryNote}`,
      audio: { src: `/api/yoon-fest/media/${set.audio.assetId}?part=0`, revision: set.audio.revision,
        segments: set.spans.map((span, index) => ({ src: `/api/yoon-fest/media/${set.audio.assetId}?part=${index}`,
          startSeconds: span.startSample / span.sampleRate, durationSeconds: spanDuration(span) })) } }}
  /></YoonAccessBoundary>;
}
