import "server-only";
import { z } from "zod";
import type { SessionActor } from "@/lib/auth/session";
import { buildSetSpotifyExportCandidates } from "@/lib/archive/spotify-export";
import { addPlaylistTracks, createPlaylist, ensureSpotifyPlaylistScope } from "@/lib/spotify/playlist.server";
import { refreshSpotifyAccessTokenForUser } from "@/lib/spotify/server";
import { hasYoonAccess, getYoonActor, YOON_PRIVATE_HEADERS } from "./access.server";
import type { YoonCollection } from "./collection-model.server";
import { loadYoonCollection } from "./data.server";
import { toYoonSetDetail } from "./data.server";

export const yoonExportSchema = z.object({
  entityType: z.enum(["set", "festival"]), slug: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/),
  confidenceFilter: z.enum(["all", "HIGH", "MEDIUM", "LOW"]),
}).strict();
export type YoonExportRequest = z.infer<typeof yoonExportSchema>;
export type YoonExportDeps = {
  actor: () => Promise<SessionActor | null>; authorize: (actor: SessionActor | null) => Promise<boolean>;
  collection: (actor: SessionActor) => YoonCollection | Promise<YoonCollection>;
  refresh: typeof refreshSpotifyAccessTokenForUser; fetch: typeof fetch;
};
const defaults: YoonExportDeps = {
  actor: getYoonActor, authorize: hasYoonAccess, collection: loadYoonCollection,
  refresh: refreshSpotifyAccessTokenForUser, fetch,
};
const json = (body: unknown, status: number) => Response.json(body, { status, headers: YOON_PRIVATE_HEADERS });

export function buildYoonExportPlan(collection: YoonCollection, input: YoonExportRequest) {
  const sets = input.entityType === "festival"
    ? input.slug === "yoon-fest" ? collection.sets : []
    : collection.sets.filter((set) => set.slug === input.slug);
  if (!sets.length) return null;
  const candidates = sets.flatMap((set) => buildSetSpotifyExportCandidates(toYoonSetDetail(set), input.confidenceFilter));
  const ids = candidates.map((candidate) => candidate.spotifyTrackId);
  return {
    name: input.entityType === "festival" ? "Yoon Fest" : sets[0]!.title,
    // The permitted playlist contains music IDs and its display title, not private source links/provenance.
    description: "Selected tracks from Yoon Fest. Audio links are not included.",
    spotifyTrackIds: input.entityType === "festival" ? [...new Set(ids)] : ids,
  };
}

export async function exportYoonPlaylist(request: Request, deps: YoonExportDeps = defaults): Promise<Response> {
  const actor = await deps.actor();
  if (!actor || !await deps.authorize(actor)) return json({ error: "Not found" }, 404);
  // Session-only POST: reject cross-site or originless writes before parsing or looking up tracks.
  if (request.headers.get("origin") !== new URL(request.url).origin) return json({ error: "Invalid request origin" }, 403);
  if (!request.headers.get("content-type")?.startsWith("application/json")) return json({ error: "JSON required" }, 415);
  let input: YoonExportRequest;
  try {
    const body = await request.text();
    if (body.length > 4096) return json({ error: "Request too large" }, 413);
    input = yoonExportSchema.parse(JSON.parse(body));
  } catch { return json({ error: "Invalid export request" }, 400); }
  const plan = buildYoonExportPlan(await deps.collection(actor), input);
  if (!plan) return json({ error: "Not found" }, 404);
  if (!plan.spotifyTrackIds.length) return json({ error: "No Spotify-resolved tracks are available for export" }, 422);
  let playlist: Awaited<ReturnType<typeof createPlaylist>> | null = null;
  try {
    const connection = await deps.refresh(actor.userId);
    ensureSpotifyPlaylistScope(connection.scopes);
    playlist = await createPlaylist({ accessToken: connection.accessToken, description: plan.description,
      fetchFn: deps.fetch, name: plan.name, spotifyUserId: connection.spotifyUserId });
    await addPlaylistTracks({ accessToken: connection.accessToken, fetchFn: deps.fetch,
      playlistId: playlist.playlistId, spotifyTrackIds: plan.spotifyTrackIds });
    return json({ ...playlist, tracksAdded: plan.spotifyTrackIds.length, confidenceFilter: input.confidenceFilter }, 201);
  } catch {
    // Do not expose raw Spotify errors/tokens and do not retry playlist creation automatically.
    return json({ error: playlist
      ? "The playlist was created, but adding tracks did not finish. Check it in Spotify before starting another export."
      : "Spotify export could not finish. Check your Spotify connection and account before trying again.",
      ...(playlist ? { playlistUrl: playlist.playlistUrl } : {}) }, 502);
  }
}
