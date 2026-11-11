import "server-only";
import type { SessionActor } from "@/lib/auth/session";
import { hasYoonAccess, getYoonActor, YOON_PRIVATE_HEADERS } from "./access.server";
import { getYoonSetByAsset } from "./data.server";
import type { YoonSet } from "./collection-model.server";
import { dropboxPlaybackUrl } from "./dropbox-source.server";

export type YoonMediaDeps = {
  actor: () => Promise<SessionActor | null>;
  authorize: (actor: SessionActor | null) => Promise<boolean>;
  releasedAsset: (actor: SessionActor, assetId: string) => YoonSet | null | Promise<YoonSet | null>;
};
const defaults: YoonMediaDeps = { actor: getYoonActor, authorize: hasYoonAccess, releasedAsset: getYoonSetByAsset };

// Release the reviewed bearer URL only to a member's browser. The actual audio
// and Range requests go directly to Dropbox: this endpoint never relays bytes.
export async function serveYoonMedia(request: Request, assetId: string, deps: YoonMediaDeps = defaults): Promise<Response> {
  const denied = () => new Response(null, { status: 404, headers: YOON_PRIVATE_HEADERS });
  const actor = await deps.actor();
  if (!actor || !await deps.authorize(actor)) return denied();
  const part = new URL(request.url).searchParams.get("part") ?? "0";
  if (!/^(0|[1-9]\d*)$/.test(part) || !Number.isSafeInteger(Number(part))) return denied();
  const set = await deps.releasedAsset(actor, assetId);
  const span = set?.spans[Number(part)];
  const source = span && set?.audio.sources.find((item) => item.recordingId === span.recordingId);
  const location = source && dropboxPlaybackUrl(source.url);
  if (!location) return denied();
  // No public cache, logs, export payload, or unauthenticated URL response.
  return new Response(null, { status: 307, headers: { ...YOON_PRIVATE_HEADERS, Location: location } });
}
