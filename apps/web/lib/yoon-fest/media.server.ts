import "server-only";
import type { SessionActor } from "@/lib/auth/session";
import { hasYoonAccess, getYoonActor, YOON_PRIVATE_HEADERS } from "./access.server";
import { loadYoonCollection } from "./data.server";
import type { YoonCollection } from "./collection-model.server";
import { dropboxPlaybackUrl } from "./dropbox-source.server";

export type YoonMediaDeps = {
  actor: () => Promise<SessionActor | null>;
  authorize: (actor: SessionActor | null) => Promise<boolean>;
  collection: (actor: SessionActor) => YoonCollection | Promise<YoonCollection>;
};
const defaults: YoonMediaDeps = { actor: getYoonActor, authorize: hasYoonAccess, collection: loadYoonCollection };

// Release the reviewed bearer URL only to a member's browser. The actual audio
// and Range requests go directly to Dropbox: this endpoint never relays bytes.
export async function serveYoonMedia(request: Request, assetId: string, deps: YoonMediaDeps = defaults): Promise<Response> {
  const denied = () => new Response(null, { status: 404, headers: YOON_PRIVATE_HEADERS });
  const actor = await deps.actor();
  if (!actor || !await deps.authorize(actor)) return denied();
  const part = new URL(request.url).searchParams.get("part") ?? "0";
  if (!/^(0|[1-9]\d*)$/.test(part) || !Number.isSafeInteger(Number(part))) return denied();
  const set = (await deps.collection(actor)).sets.find((item) => item.audio.assetId === assetId);
  const span = set?.spans[Number(part)];
  const source = span && set?.audio.sources.find((item) => item.recordingId === span.recordingId);
  const location = source && dropboxPlaybackUrl(source.url);
  if (!location) return denied();
  // No public cache, logs, export payload, or unauthenticated URL response.
  return new Response(null, { status: 307, headers: { ...YOON_PRIVATE_HEADERS, Location: location } });
}
