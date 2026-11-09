import "server-only";
import { and, eq } from "drizzle-orm";
import { unstable_noStore as noStore } from "next/cache";
import type { SessionActor } from "@/lib/auth/session";
import { getDb } from "@/lib/db/client";
import { archiveCollections, archiveCollectionMembers } from "@/lib/db/schema";

export class YoonAccessError extends Error {}

export async function hasYoonAccess(actor: SessionActor | null): Promise<boolean> {
  noStore();
  if (!actor || actor.authType !== "session") return false;
  const [member] = await getDb().select({ id: archiveCollections.id })
    .from(archiveCollections).innerJoin(archiveCollectionMembers,
      and(eq(archiveCollectionMembers.collectionId, archiveCollections.id),
        eq(archiveCollectionMembers.userId, actor.userId)))
    .where(eq(archiveCollections.slug, "yoon-fest")).limit(1);
  return Boolean(member);
}

export async function assertYoonAccess(actor: SessionActor | null): Promise<void> {
  if (!await hasYoonAccess(actor)) throw new YoonAccessError("Not found");
}

export async function getYoonActor(): Promise<SessionActor | null> {
  noStore();
  const { getSessionActor } = await import("@/lib/auth/session");
  const actor = await getSessionActor();
  return await hasYoonAccess(actor) ? actor : null;
}

export const YOON_PRIVATE_HEADERS = {
  "Cache-Control": "private, no-store, max-age=0, must-revalidate",
  "CDN-Cache-Control": "no-store",
  "Vercel-CDN-Cache-Control": "no-store",
  "X-Robots-Tag": "noindex, nofollow, noarchive",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
} as const;
