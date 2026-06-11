import { NextRequest, NextResponse } from "next/server";
import { sql } from "drizzle-orm";

import { listArtists } from "@/lib/archive/repository";
import { formatCompactDuration } from "@/lib/archive/utils";
import { getSessionActor } from "@/lib/auth/session";
import { getDb } from "@/lib/db/client";

const RESULT_LIMIT = 6;

type SearchType = "all" | "artists" | "sets";

const resolveType = (value: string | null): SearchType =>
  value === "artists" || value === "sets" ? value : "all";

type SetSearchRow = {
  artistName: string | null;
  duration: number | string | null;
  id: string;
  recognitionRate: number | string | null;
  slug: string;
  thumbnailUrl: string | null;
  title: string;
  totalTracks: number | string;
};

const numberOrZero = (value: number | string | null | undefined) => {
  const next = Number(value ?? 0);
  return Number.isFinite(next) ? next : 0;
};

const searchSets = async ({
  query,
  scope,
  userId,
}: {
  query: string;
  scope: "global" | "mine";
  userId?: string;
}) => {
  const db = getDb();
  const likeQuery = `%${query}%`;
  const prefixQuery = `${query}%`;
  const workspaceClause =
    scope === "mine" && userId
      ? sql`AND EXISTS (
          SELECT 1
          FROM "ops"."set_runs" runs
          WHERE runs.source_url = library.source_url
            AND runs.requested_by = ${userId}
            AND runs.archive_removed_at IS NULL
        )`
      : sql``;

  const result = await db.execute(sql<SetSearchRow>`
    SELECT
      library.set_id::text AS id,
      library.set_slug AS slug,
      library.set_title AS title,
      library.artist_name AS "artistName",
      library.duration_seconds AS duration,
      library.recognition_rate AS "recognitionRate",
      library.thumbnail_url AS "thumbnailUrl",
      library.total_tracks AS "totalTracks"
    FROM "app"."archive_home_set_library_index_mv" library
    WHERE (
      library.set_title ILIKE ${likeQuery}
      OR COALESCE(library.artist_name, '') ILIKE ${likeQuery}
      OR COALESCE(library.track_search_text, '') ILIKE ${likeQuery}
    )
    ${workspaceClause}
    ORDER BY
      CASE
        WHEN lower(library.set_title) = lower(${query}) THEN 0
        WHEN lower(library.set_title) LIKE lower(${prefixQuery}) THEN 1
        WHEN library.set_title ILIKE ${likeQuery} THEN 2
        WHEN lower(COALESCE(library.artist_name, '')) = lower(${query}) THEN 3
        WHEN lower(COALESCE(library.artist_name, '')) LIKE lower(${prefixQuery}) THEN 4
        WHEN COALESCE(library.artist_name, '') ILIKE ${likeQuery} THEN 5
        ELSE 6
      END ASC,
      library.sort_recognition_rate DESC,
      library.set_title ASC,
      library.set_slug ASC
    LIMIT ${RESULT_LIMIT}
  `);

  return result.rows as SetSearchRow[];
};

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const query = searchParams.get("q")?.trim() ?? "";
  const scope = searchParams.get("scope") === "mine" ? "mine" : "global";
  const type = resolveType(searchParams.get("type"));

  if (query.length < 2) {
    return NextResponse.json({
      artists: [],
      authRequired: false,
      query,
      scope,
      sets: [],
      type,
    });
  }

  const actor = await getSessionActor();

  if (scope === "mine" && !actor) {
    return NextResponse.json({
      artists: [],
      authRequired: true,
      query,
      scope,
      sets: [],
      type,
    });
  }

  const userId = scope === "mine" ? actor?.userId : undefined;

  const [artists, sets] = await Promise.all([
    type === "sets" ? Promise.resolve([]) : listArtists(query, userId),
    type === "artists" ? Promise.resolve([]) : searchSets({ query, scope, userId }),
  ]);

  return NextResponse.json({
    artists: artists.slice(0, RESULT_LIMIT).map((artist) => ({
      id: artist.id,
      href: `/artists/${artist.slug}`,
      imageUrl: artist.imageUrl,
      kind: "artist" as const,
      meta:
        scope === "mine"
          ? `${Number(artist.setCount ?? 0)} workspace sets`
          : `${Number(artist.setCount ?? 0)} sets`,
      name: artist.name,
      slug: artist.slug,
    })),
    authRequired: false,
    query,
    scope,
    sets: sets.map((setItem) => {
      const metaParts = [
        setItem.artistName,
        `${numberOrZero(setItem.totalTracks)} tracks`,
        `${Math.round(numberOrZero(setItem.recognitionRate))}% match`,
        formatCompactDuration(numberOrZero(setItem.duration)),
      ].filter(Boolean);

      return {
        artistName: setItem.artistName,
        href: `/sets/${setItem.slug}`,
        id: setItem.id,
        imageUrl: setItem.thumbnailUrl,
        kind: "set" as const,
        meta: metaParts.join(" - "),
        name: setItem.title,
        recognitionRate: numberOrZero(setItem.recognitionRate),
        slug: setItem.slug,
        totalTracks: numberOrZero(setItem.totalTracks),
      };
    }),
    type,
  });
}
