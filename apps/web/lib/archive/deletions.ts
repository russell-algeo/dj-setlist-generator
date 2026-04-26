import "server-only";

import { randomUUID } from "node:crypto";

import { neon } from "@neondatabase/serverless";
import { revalidatePath, revalidateTag } from "next/cache";
import { eq, sql } from "drizzle-orm";

import { archiveCacheTags } from "@/lib/archive/data";
import { archiveHomeTags } from "@/lib/archive/home-explorer-data";
import { refreshArchiveHomeMaterializedViews } from "@/lib/archive/home-materialized-views";
import { getDb } from "@/lib/db/client";
import { artists, setArtists, sets } from "@/lib/db/schema";
import { env, requireEnv } from "@/lib/env";
import type { SessionActor } from "@/lib/auth/session";

export class ArchiveDeletionError extends Error {
  constructor(
    message: string,
    public readonly code: "not_found" | "forbidden" | "invalid_request",
    public readonly status: number,
  ) {
    super(message);
    this.name = "ArchiveDeletionError";
  }
}

type SetRecord = {
  id: string;
  slug: string;
  sourceUrl: string | null;
  title: string;
};

type ArtistRecord = {
  id: string;
  name: string;
  slug: string;
};

type ActiveRunRow = {
  id: string;
  requestedBy: string;
  setId: string;
};

type SetOwnerRow = {
  count: number | string;
  requestedBy: string;
};

type ArtistSetRow = {
  id: string;
  owners: unknown;
  slug: string;
  sourceUrl: string | null;
  title: string;
};

export type ArchiveSetManagement = {
  canDeleteSet: boolean;
  deleteImpact: string | null;
  setWillBeRemoved: boolean;
  submittedByViewer: boolean;
};

export type ArchiveArtistManagement = {
  artistWillBeRemoved: boolean;
  canDeleteArtist: boolean;
  deletableSetIds: string[];
  deleteImpact: string | null;
  setDeleteImpacts: Record<string, string>;
  submittedByViewer: boolean;
  submittedSetIds: string[];
};

type DeleteResult = {
  deletionId: string;
  entityRemoved: boolean;
  message: string;
  mode: "removed_submission" | "deleted_record";
};

const asRows = <T>(rows: unknown[]): T[] => rows as T[];

const numberOrZero = (value: number | string | null | undefined) =>
  Number.isFinite(Number(value ?? 0)) ? Number(value ?? 0) : 0;

const asStringArray = (value: unknown): string[] => {
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === "string" && item.length > 0);
  }

  if (typeof value === "string" && value.trim().length > 0) {
    try {
      const parsed = JSON.parse(value) as unknown;
      return asStringArray(parsed);
    } catch {
      return [];
    }
  }

  return [];
};

const getMutationConnectionString = () => {
  if (env.databaseUrlDirect) {
    return env.databaseUrlDirect;
  }

  if (env.databaseUrl) {
    return env.databaseUrl;
  }

  return requireEnv("databaseUrlDirect") as string;
};

const getMutationSql = () => neon(getMutationConnectionString());

const cleanReason = (reason?: string | null) => {
  const trimmed = reason?.trim();
  return trimmed ? trimmed.slice(0, 1000) : null;
};

const buildRunDeletionMetadata = ({
  actor,
  deletionId,
  entityType,
  reason,
}: {
  actor: SessionActor;
  deletionId: string;
  entityType: "artist" | "set";
  reason: string | null;
}) => ({
  actorEmail: actor.email,
  actorRole: actor.isAdmin ? "admin" : "submitter",
  actorUserId: actor.userId,
  deletionId,
  entityType,
  reason,
  removedAt: new Date().toISOString(),
});

const loadSetRecord = async (slug: string): Promise<SetRecord | null> => {
  const db = getDb();
  const [setRecord] = await db
    .select({
      id: sets.id,
      slug: sets.slug,
      sourceUrl: sets.sourceUrl,
      title: sets.title,
    })
    .from(sets)
    .where(eq(sets.slug, slug))
    .limit(1);

  return setRecord ?? null;
};

const loadArtistRecord = async (slug: string): Promise<ArtistRecord | null> => {
  const db = getDb();
  const [artistRecord] = await db
    .select({
      id: artists.id,
      name: artists.name,
      slug: artists.slug,
    })
    .from(artists)
    .where(eq(artists.slug, slug))
    .limit(1);

  return artistRecord ?? null;
};

const loadSetArtistSlugs = async (setId: string): Promise<string[]> => {
  const db = getDb();
  const rows = await db
    .select({ slug: artists.slug })
    .from(setArtists)
    .innerJoin(artists, eq(artists.id, setArtists.artistId))
    .where(eq(setArtists.setId, setId));

  return rows.map((row) => row.slug);
};

const loadActiveSetRuns = async (setRecord: SetRecord): Promise<ActiveRunRow[]> => {
  const db = getDb();
  const result = await db.execute(sql<ActiveRunRow>`
    SELECT DISTINCT
      sr.id::text AS id,
      sr.requested_by AS "requestedBy",
      ${setRecord.id}::text AS "setId"
    FROM "ops"."set_runs" sr
    WHERE sr.archive_removed_at IS NULL
      AND sr.status = 'completed'
      AND (
        sr.published_set_id = ${setRecord.id}::uuid
        OR (${setRecord.sourceUrl}::text IS NOT NULL AND sr.source_url = ${setRecord.sourceUrl})
      )
  `);

  return asRows<ActiveRunRow>(result.rows);
};

const loadSetOwners = async (setRecord: SetRecord): Promise<SetOwnerRow[]> => {
  const db = getDb();
  const result = await db.execute(sql<SetOwnerRow>`
    SELECT
      sr.requested_by AS "requestedBy",
      count(*)::int AS count
    FROM "ops"."set_runs" sr
    WHERE sr.archive_removed_at IS NULL
      AND sr.status = 'completed'
      AND (
        sr.published_set_id = ${setRecord.id}::uuid
        OR (${setRecord.sourceUrl}::text IS NOT NULL AND sr.source_url = ${setRecord.sourceUrl})
      )
    GROUP BY sr.requested_by
  `);

  return asRows<SetOwnerRow>(result.rows);
};

const loadArtistSets = async (artistRecord: ArtistRecord): Promise<ArtistSetRow[]> => {
  const db = getDb();
  const result = await db.execute(sql<ArtistSetRow>`
    SELECT
      s.id::text AS id,
      s.slug,
      s.title,
      s.source_url AS "sourceUrl",
      COALESCE(
        jsonb_agg(DISTINCT sr.requested_by) FILTER (WHERE sr.requested_by IS NOT NULL),
        '[]'::jsonb
      ) AS owners
    FROM "app"."set_artists" sa
    INNER JOIN "app"."sets" s
      ON s.id = sa.set_id
    LEFT JOIN "ops"."set_runs" sr
      ON sr.archive_removed_at IS NULL
     AND sr.status = 'completed'
     AND (
       sr.published_set_id = s.id
       OR (s.source_url IS NOT NULL AND sr.source_url = s.source_url)
     )
    WHERE sa.artist_id = ${artistRecord.id}::uuid
    GROUP BY s.id, s.slug, s.title, s.source_url
    ORDER BY s.title ASC
  `);

  return asRows<ArtistSetRow>(result.rows);
};

const loadActiveArtistRuns = async (
  artistRecord: ArtistRecord,
): Promise<ActiveRunRow[]> => {
  const db = getDb();
  const result = await db.execute(sql<ActiveRunRow>`
    SELECT DISTINCT
      sr.id::text AS id,
      sr.requested_by AS "requestedBy",
      s.id::text AS "setId"
    FROM "app"."set_artists" sa
    INNER JOIN "app"."sets" s
      ON s.id = sa.set_id
    INNER JOIN "ops"."set_runs" sr
      ON sr.archive_removed_at IS NULL
     AND sr.status = 'completed'
     AND (
       sr.published_set_id = s.id
       OR (s.source_url IS NOT NULL AND sr.source_url = s.source_url)
     )
    WHERE sa.artist_id = ${artistRecord.id}::uuid
  `);

  return asRows<ActiveRunRow>(result.rows);
};

const getSetOwnershipSummary = async (setRecord: SetRecord, actor: SessionActor | null) => {
  const ownerRows = await loadSetOwners(setRecord);
  const ownerIds = ownerRows.map((row) => row.requestedBy);
  const ownerCount = ownerRows.reduce((sum, row) => sum + numberOrZero(row.count), 0);
  const submittedByViewer = Boolean(actor && ownerIds.includes(actor.userId));
  const otherOwnerIds = actor ? ownerIds.filter((ownerId) => ownerId !== actor.userId) : ownerIds;

  return {
    otherOwnerIds,
    ownerCount,
    ownerIds,
    submittedByViewer,
  };
};

export const getArchiveSetManagementBySlug = async (
  slug: string,
  actor: SessionActor | null,
): Promise<ArchiveSetManagement> => {
  if (!actor) {
    return {
      canDeleteSet: false,
      deleteImpact: null,
      setWillBeRemoved: false,
      submittedByViewer: false,
    };
  }

  const setRecord = await loadSetRecord(slug);
  if (!setRecord) {
    return {
      canDeleteSet: false,
      deleteImpact: null,
      setWillBeRemoved: false,
      submittedByViewer: false,
    };
  }

  const ownership = await getSetOwnershipSummary(setRecord, actor);
  const canDeleteSet = actor.isAdmin || ownership.submittedByViewer;
  const setWillBeRemoved = actor.isAdmin || ownership.otherOwnerIds.length === 0;
  const deleteImpact = canDeleteSet
    ? actor.isAdmin
      ? "This removes the set from the archive for everyone."
      : setWillBeRemoved
        ? "This removes your submitted set from the public archive."
        : "This removes the set from your submissions and workspace. The public set stays visible because someone else also submitted it."
    : null;

  return {
    canDeleteSet,
    deleteImpact,
    setWillBeRemoved,
    submittedByViewer: ownership.submittedByViewer,
  };
};

export const getArchiveArtistManagementBySlug = async (
  slug: string,
  actor: SessionActor | null,
): Promise<ArchiveArtistManagement> => {
  if (!actor) {
    return {
      artistWillBeRemoved: false,
      canDeleteArtist: false,
      deletableSetIds: [],
      deleteImpact: null,
      setDeleteImpacts: {},
      submittedByViewer: false,
      submittedSetIds: [],
    };
  }

  const artistRecord = await loadArtistRecord(slug);
  if (!artistRecord) {
    return {
      artistWillBeRemoved: false,
      canDeleteArtist: false,
      deletableSetIds: [],
      deleteImpact: null,
      setDeleteImpacts: {},
      submittedByViewer: false,
      submittedSetIds: [],
    };
  }

  const artistSets = await loadArtistSets(artistRecord);
  const submittedSetIds = artistSets
    .filter((setItem) => asStringArray(setItem.owners).includes(actor.userId))
    .map((setItem) => setItem.id);
  const submittedSetIdSet = new Set(submittedSetIds);
  const deletableSetIds = actor.isAdmin
    ? artistSets.map((setItem) => setItem.id)
    : submittedSetIds;
  const submittedByViewer = submittedSetIds.length > 0;
  const canDeleteArtist = actor.isAdmin || submittedByViewer;
  const hardDeleteSetIds = actor.isAdmin
    ? artistSets.map((setItem) => setItem.id)
    : artistSets
        .filter((setItem) => {
          if (!submittedSetIdSet.has(setItem.id)) {
            return false;
          }
          const otherOwners = asStringArray(setItem.owners).filter((ownerId) => ownerId !== actor.userId);
          return otherOwners.length === 0;
        })
        .map((setItem) => setItem.id);
  const artistWillBeRemoved = artistSets.length > 0 && hardDeleteSetIds.length === artistSets.length;
  const hardDeleteSetIdSet = new Set(hardDeleteSetIds);
  const setDeleteImpacts = Object.fromEntries(
    artistSets
      .filter((setItem) => deletableSetIds.includes(setItem.id))
      .map((setItem) => [
        setItem.id,
        actor.isAdmin
          ? "This removes the set from the archive for everyone."
          : hardDeleteSetIdSet.has(setItem.id)
            ? "This removes your submitted set from the public archive."
            : "This removes the set from your submissions and workspace. The public set stays visible because someone else also submitted it.",
      ]),
  );
  const deleteImpact = canDeleteArtist
    ? actor.isAdmin
      ? `This removes ${artistRecord.name}, their artist page, and all associated sets from the archive.`
      : artistWillBeRemoved
        ? `This removes ${artistRecord.name} and all sets you submitted for this artist.`
        : `This removes the sets you submitted for ${artistRecord.name}. The artist page stays visible if other submitted sets remain.`
    : null;

  return {
    artistWillBeRemoved,
    canDeleteArtist,
    deletableSetIds,
    deleteImpact,
    setDeleteImpacts,
    submittedByViewer,
    submittedSetIds,
  };
};

const revalidateArchiveDeletion = async ({
  artistSlugs,
  refreshMaterializedViews,
  setSlugs,
}: {
  artistSlugs: string[];
  refreshMaterializedViews: boolean;
  setSlugs: string[];
}) => {
  if (refreshMaterializedViews) {
    await refreshArchiveHomeMaterializedViews();
  }

  for (const tag of [
    archiveCacheTags.home,
    archiveCacheTags.lists,
    archiveCacheTags.connections,
    archiveHomeTags.home,
    archiveHomeTags.atlas,
    archiveHomeTags.lists,
    archiveHomeTags.network,
    archiveHomeTags.pair,
  ]) {
    revalidateTag(tag);
  }

  for (const slug of artistSlugs) {
    revalidateTag(archiveCacheTags.artist(slug));
    revalidatePath(`/artists/${slug}`);
  }

  for (const slug of setSlugs) {
    revalidateTag(archiveCacheTags.set(slug));
    revalidateTag(archiveHomeTags.setTracklist(slug));
    revalidatePath(`/sets/${slug}`);
  }

  revalidatePath("/");
};

export const deleteArchiveSetBySlug = async ({
  actor,
  reason,
  slug,
}: {
  actor: SessionActor;
  reason?: string | null;
  slug: string;
}): Promise<DeleteResult> => {
  const setRecord = await loadSetRecord(slug);
  if (!setRecord) {
    throw new ArchiveDeletionError("Set not found.", "not_found", 404);
  }

  const [ownership, activeRuns, artistSlugs] = await Promise.all([
    getSetOwnershipSummary(setRecord, actor),
    loadActiveSetRuns(setRecord),
    loadSetArtistSlugs(setRecord.id),
  ]);

  if (!actor.isAdmin && !ownership.submittedByViewer) {
    throw new ArchiveDeletionError(
      "Only the submitter or an admin can delete this set.",
      "forbidden",
      403,
    );
  }

  const deletionId = randomUUID();
  const now = new Date().toISOString();
  const sanitizedReason = cleanReason(reason);
  const hardDelete = actor.isAdmin || ownership.otherOwnerIds.length === 0;
  const action = hardDelete ? "delete_set" : "remove_set_submission";
  const runDeletionMetadata = buildRunDeletionMetadata({
    actor,
    deletionId,
    entityType: "set",
    reason: sanitizedReason,
  });
  const sourceUrls = setRecord.sourceUrl ? [setRecord.sourceUrl] : [];
  const runActorClause = actor.isAdmin || hardDelete ? "" : "AND sr.requested_by = $6";
  const runActorParams = actor.isAdmin || hardDelete ? [] : [actor.userId];
  const sqlClient = getMutationSql();

  const queries = [
    {
      params: [
        deletionId,
        "set",
        setRecord.id,
        setRecord.slug,
        setRecord.title,
        action,
        actor.isAdmin ? "admin" : "submitter",
        actor.userId,
        actor.email,
        sanitizedReason,
        JSON.stringify([setRecord.id]),
        JSON.stringify(artistSlugs),
        JSON.stringify({
          expectedSetRunsMarked: actor.isAdmin
            ? activeRuns.length
            : activeRuns.filter((run) => run.requestedBy === actor.userId).length,
          expectedSetsDeleted: hardDelete ? 1 : 0,
        }),
        JSON.stringify({
          otherOwnerIds: ownership.otherOwnerIds,
          ownerCount: ownership.ownerCount,
        }),
      ],
      text: `
        INSERT INTO "ops"."archive_deletions" (
          "id",
          "entity_type",
          "entity_id",
          "slug",
          "title",
          "action",
          "actor_role",
          "requested_by",
          "requested_by_email",
          "reason",
          "affected_set_ids",
          "affected_artist_slugs",
          "row_counts",
          "metadata"
        )
        VALUES (
          $1::uuid,
          $2,
          $3::uuid,
          $4,
          $5,
          $6,
          $7,
          $8,
          $9,
          $10,
          $11::jsonb,
          $12::jsonb,
          $13::jsonb,
          $14::jsonb
        )
      `,
    },
    {
      params: [
        now,
        deletionId,
        [setRecord.id],
        JSON.stringify(runDeletionMetadata),
        sourceUrls,
        ...runActorParams,
      ],
      text: `
        UPDATE "ops"."set_runs" sr
        SET
          archive_removed_at = $1::timestamptz,
          archive_removal_id = $2::uuid,
          published_set_id = CASE
            WHEN sr.published_set_id = ANY($3::uuid[]) THEN NULL
            ELSE sr.published_set_id
          END,
          source_metadata = jsonb_set(
            COALESCE(sr.source_metadata, '{}'::jsonb),
            '{archiveDeletion}',
            $4::jsonb,
            true
          ),
          updated_at = $1::timestamptz
        WHERE sr.archive_removed_at IS NULL
          AND sr.status = 'completed'
          AND (
            sr.published_set_id = ANY($3::uuid[])
            OR sr.source_url = ANY($5::text[])
          )
          ${runActorClause}
      `,
    },
  ];

  if (hardDelete) {
    queries.push(
      {
        params: [[setRecord.id]],
        text: `DELETE FROM "app"."sets" WHERE id = ANY($1::uuid[])`,
      },
      {
        params: [],
        text: `
          DELETE FROM "app"."tracks" t
          WHERE NOT EXISTS (
            SELECT 1 FROM "app"."set_entries" se WHERE se.track_id = t.id
          )
        `,
      },
      {
        params: [],
        text: `
          DELETE FROM "app"."artists" a
          WHERE NOT EXISTS (
            SELECT 1 FROM "app"."set_artists" sa WHERE sa.artist_id = a.id
          )
          AND NOT EXISTS (
            SELECT 1 FROM "app"."track_artists" ta WHERE ta.artist_id = a.id
          )
        `,
      },
    );
  }

  await sqlClient.transaction((tx) =>
    queries.map((query) => tx.query(query.text, query.params)),
  );

  await revalidateArchiveDeletion({
    artistSlugs,
    refreshMaterializedViews: hardDelete,
    setSlugs: [setRecord.slug],
  });

  return {
    deletionId,
    entityRemoved: hardDelete,
    message: hardDelete
      ? "Set deleted from the archive."
      : "Set removed from your submissions and workspace.",
    mode: hardDelete ? "deleted_record" : "removed_submission",
  };
};

export const deleteArchiveArtistBySlug = async ({
  actor,
  reason,
  slug,
}: {
  actor: SessionActor;
  reason?: string | null;
  slug: string;
}): Promise<DeleteResult> => {
  const artistRecord = await loadArtistRecord(slug);
  if (!artistRecord) {
    throw new ArchiveDeletionError("Artist not found.", "not_found", 404);
  }

  const [artistSets, activeRuns] = await Promise.all([
    loadArtistSets(artistRecord),
    loadActiveArtistRuns(artistRecord),
  ]);
  const submittedSetIds = artistSets
    .filter((setItem) => asStringArray(setItem.owners).includes(actor.userId))
    .map((setItem) => setItem.id);

  if (!actor.isAdmin && submittedSetIds.length === 0) {
    throw new ArchiveDeletionError(
      "Only a submitter or an admin can delete this artist.",
      "forbidden",
      403,
    );
  }

  const submittedSetIdSet = new Set(submittedSetIds);
  const hardDeleteSetIds = actor.isAdmin
    ? artistSets.map((setItem) => setItem.id)
    : artistSets
        .filter((setItem) => {
          if (!submittedSetIdSet.has(setItem.id)) {
            return false;
          }
          const otherOwners = asStringArray(setItem.owners).filter((ownerId) => ownerId !== actor.userId);
          return otherOwners.length === 0;
        })
        .map((setItem) => setItem.id);
  const hardDeleteSetIdSet = new Set(hardDeleteSetIds);
  const touchedSetIds = actor.isAdmin ? artistSets.map((setItem) => setItem.id) : submittedSetIds;
  const touchedSetSlugs = artistSets
    .filter((setItem) => touchedSetIds.includes(setItem.id))
    .map((setItem) => setItem.slug);
  const touchedSourceUrls = artistSets
    .filter((setItem) => touchedSetIds.includes(setItem.id) && setItem.sourceUrl)
    .map((setItem) => setItem.sourceUrl as string);
  const artistWillBeRemoved = artistSets.length > 0 && hardDeleteSetIds.length === artistSets.length;
  const deletionId = randomUUID();
  const now = new Date().toISOString();
  const sanitizedReason = cleanReason(reason);
  const action = actor.isAdmin ? "delete_artist" : "remove_artist_submissions";
  const runDeletionMetadata = buildRunDeletionMetadata({
    actor,
    deletionId,
    entityType: "artist",
    reason: sanitizedReason,
  });
  const runActorClause = actor.isAdmin ? "" : "AND sr.requested_by = $6";
  const runActorParams = actor.isAdmin ? [] : [actor.userId];
  const sqlClient = getMutationSql();

  const queries = [
    {
      params: [
        deletionId,
        "artist",
        artistRecord.id,
        artistRecord.slug,
        artistRecord.name,
        action,
        actor.isAdmin ? "admin" : "submitter",
        actor.userId,
        actor.email,
        sanitizedReason,
        JSON.stringify(touchedSetIds),
        JSON.stringify([artistRecord.slug]),
        JSON.stringify({
          expectedSetRunsMarked: actor.isAdmin
            ? activeRuns.length
            : activeRuns.filter((run) => run.requestedBy === actor.userId).length,
          expectedSetsDeleted: hardDeleteSetIds.length,
        }),
        JSON.stringify({
          hardDeleteSetIds,
          keptSetIds: artistSets
            .filter((setItem) => touchedSetIds.includes(setItem.id) && !hardDeleteSetIdSet.has(setItem.id))
            .map((setItem) => setItem.id),
        }),
      ],
      text: `
        INSERT INTO "ops"."archive_deletions" (
          "id",
          "entity_type",
          "entity_id",
          "slug",
          "title",
          "action",
          "actor_role",
          "requested_by",
          "requested_by_email",
          "reason",
          "affected_set_ids",
          "affected_artist_slugs",
          "row_counts",
          "metadata"
        )
        VALUES (
          $1::uuid,
          $2,
          $3::uuid,
          $4,
          $5,
          $6,
          $7,
          $8,
          $9,
          $10,
          $11::jsonb,
          $12::jsonb,
          $13::jsonb,
          $14::jsonb
        )
      `,
    },
    {
      params: [
        now,
        deletionId,
        touchedSetIds,
        JSON.stringify(runDeletionMetadata),
        touchedSourceUrls,
        ...runActorParams,
      ],
      text: `
        UPDATE "ops"."set_runs" sr
        SET
          archive_removed_at = $1::timestamptz,
          archive_removal_id = $2::uuid,
          published_set_id = CASE
            WHEN sr.published_set_id = ANY($3::uuid[]) THEN NULL
            ELSE sr.published_set_id
          END,
          source_metadata = jsonb_set(
            COALESCE(sr.source_metadata, '{}'::jsonb),
            '{archiveDeletion}',
            $4::jsonb,
            true
          ),
          updated_at = $1::timestamptz
        WHERE sr.archive_removed_at IS NULL
          AND sr.status = 'completed'
          AND (
            sr.published_set_id = ANY($3::uuid[])
            OR sr.source_url = ANY($5::text[])
          )
          ${runActorClause}
      `,
    },
  ];

  if (hardDeleteSetIds.length > 0) {
    queries.push({
      params: [hardDeleteSetIds],
      text: `DELETE FROM "app"."sets" WHERE id = ANY($1::uuid[])`,
    });
  }

  if (actor.isAdmin || artistWillBeRemoved) {
    queries.push({
      params: [artistRecord.id],
      text: `DELETE FROM "app"."artists" WHERE id = $1::uuid`,
    });
  } else {
    queries.push({
      params: [artistRecord.id],
      text: `
        DELETE FROM "app"."artists" a
        WHERE a.id = $1::uuid
          AND NOT EXISTS (
            SELECT 1 FROM "app"."set_artists" sa WHERE sa.artist_id = a.id
          )
      `,
    });
  }

  queries.push(
    {
      params: [],
      text: `
        DELETE FROM "app"."tracks" t
        WHERE NOT EXISTS (
          SELECT 1 FROM "app"."set_entries" se WHERE se.track_id = t.id
        )
      `,
    },
    {
      params: [],
      text: `
        DELETE FROM "app"."artists" a
        WHERE NOT EXISTS (
          SELECT 1 FROM "app"."set_artists" sa WHERE sa.artist_id = a.id
        )
        AND NOT EXISTS (
          SELECT 1 FROM "app"."track_artists" ta WHERE ta.artist_id = a.id
        )
      `,
    },
  );

  await sqlClient.transaction((tx) =>
    queries.map((query) => tx.query(query.text, query.params)),
  );

  await revalidateArchiveDeletion({
    artistSlugs: [artistRecord.slug],
    refreshMaterializedViews: hardDeleteSetIds.length > 0 || actor.isAdmin,
    setSlugs: touchedSetSlugs,
  });

  return {
    deletionId,
    entityRemoved: actor.isAdmin || artistWillBeRemoved,
    message: actor.isAdmin || artistWillBeRemoved
      ? "Artist deleted from the archive."
      : "Your submitted sets were removed from this artist.",
    mode: actor.isAdmin || artistWillBeRemoved ? "deleted_record" : "removed_submission",
  };
};
