import "server-only";

import {
  and,
  asc,
  count,
  countDistinct,
  desc,
  eq,
  ilike,
  inArray,
  isNotNull,
  isNull,
  like,
  or,
  sql,
} from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { normalizeText } from "@/lib/archive/import-helpers";
import { artists, setArtists, setRuns, sets, sitePages } from "@/lib/db/schema";

const clampPage = (page: number) => (Number.isFinite(page) && page > 0 ? Math.floor(page) : 1);

export const getArtistBySlug = async (slug: string) => {
  const db = getDb();
  const [artist] = await db.select().from(artists).where(eq(artists.slug, slug)).limit(1);
  return artist ?? null;
};

export const getSetBySlug = async (slug: string) => {
  const db = getDb();
  const [setRecord] = await db.select().from(sets).where(eq(sets.slug, slug)).limit(1);
  return setRecord ?? null;
};

export const getArchiveStats = async () => {
  const db = getDb();
  const [[artistStats], [setStats]] = await Promise.all([
    db
      .select({ count: countDistinct(artists.id) })
      .from(artists)
      .leftJoin(setArtists, eq(setArtists.artistId, artists.id))
      .where(isNotNull(setArtists.setId)),
    db.select({ count: count(sets.id) }).from(sets),
  ]);

  return {
    artistCount: Number(artistStats?.count ?? 0),
    setCount: Number(setStats?.count ?? 0),
  };
};

export const listArtists = async (search?: string, userId?: string) => {
  const db = getDb();
  const query = search?.trim();

  const searchFilter = query
    ? or(
        ilike(artists.name, `%${query}%`),
        ilike(artists.normalizedName, `%${query.toLowerCase()}%`),
      )
    : undefined;

  if (userId) {
    const rows = await db
      .select({
        id: artists.id,
        slug: artists.slug,
        name: artists.name,
        imageUrl: artists.imageUrl,
        updatedAt: artists.updatedAt,
        setCount: sql<number>`count(distinct ${sets.id})`,
      })
      .from(artists)
      .innerJoin(setArtists, eq(setArtists.artistId, artists.id))
      .innerJoin(sets, eq(sets.id, setArtists.setId))
      .innerJoin(
        setRuns,
        and(
          eq(setRuns.sourceUrl, sets.sourceUrl),
          eq(setRuns.requestedBy, userId),
          isNull(setRuns.archiveRemovedAt),
        ),
      )
      .where(searchFilter)
      .groupBy(artists.id)
      .orderBy(desc(sql`count(distinct ${sets.id})`), asc(artists.name))
      .limit(200);

    return rows;
  }

  // Global branch (unchanged behaviour)
  const visibilityFilter = isNotNull(setArtists.setId);

  const rows = await db
    .select({
      id: artists.id,
      slug: artists.slug,
      name: artists.name,
      imageUrl: artists.imageUrl,
      updatedAt: artists.updatedAt,
      setCount: sql<number>`count(${setArtists.setId})`,
    })
    .from(artists)
    .leftJoin(setArtists, eq(setArtists.artistId, artists.id))
    .where(
      query
        ? and(visibilityFilter, searchFilter)
        : visibilityFilter,
    )
    .groupBy(artists.id)
    .orderBy(desc(sql`count(${setArtists.setId})`), asc(artists.name))
    .limit(200);

  return rows;
};

export const suggestArtistsByPrefix = async (query: string, limit = 5) => {
  const db = getDb();
  const normalizedQuery = normalizeText(query);

  if (!normalizedQuery) {
    return [];
  }

  const rows = await db
    .select({
      id: artists.id,
      slug: artists.slug,
      name: artists.name,
      setCount: sql<number>`count(distinct ${setArtists.setId})`,
    })
    .from(artists)
    .innerJoin(setArtists, eq(setArtists.artistId, artists.id))
    .where(and(like(artists.normalizedName, `${normalizedQuery}%`), eq(setArtists.role, "primary")))
    .groupBy(artists.id)
    .orderBy(desc(sql`count(distinct ${setArtists.setId})`), asc(artists.name))
    .limit(limit);

  return rows;
};

export const listSets = async ({
  page,
  pageSize = 30,
  search,
  userId,
}: {
  page: number;
  pageSize?: number;
  search?: string;
  userId?: string;
}) => {
  const db = getDb();
  const safePage = clampPage(page);
  const query = search?.trim();

  const searchFilter = query
    ? or(
        ilike(sets.title, `%${query}%`),
        ilike(sets.normalizedTitle, `%${query.toLowerCase()}%`),
        ilike(sets.uploader, `%${query}%`),
      )
    : undefined;

  const userFilter = userId
    ? inArray(
        sets.sourceUrl,
        db
          .select({ sourceUrl: setRuns.sourceUrl })
          .from(setRuns)
          .where(and(eq(setRuns.requestedBy, userId), isNull(setRuns.archiveRemovedAt))),
      )
    : undefined;

  const filters = and(searchFilter, userFilter);

  const [countRow] = await db
    .select({ value: count(sets.id) })
    .from(sets)
    .where(filters);

  const items = await db
    .select({
      id: sets.id,
      slug: sets.slug,
      title: sets.title,
      sourceUrl: sets.sourceUrl,
      sourcePlatform: sets.sourcePlatform,
      durationSeconds: sets.durationSeconds,
      uploader: sets.uploader,
      imageUrl: sets.imageUrl,
      recognitionRate: sets.recognitionRate,
      updatedAt: sets.updatedAt,
    })
    .from(sets)
    .where(filters)
    .orderBy(desc(sets.updatedAt), asc(sets.title))
    .limit(pageSize)
    .offset((safePage - 1) * pageSize);

  return {
    items,
    page: safePage,
    pageSize,
    totalItems: Number(countRow?.value ?? 0),
  };
};

export const getLatestImportedPages = async () => {
  const db = getDb();

  const pages = await db
    .select({
      path: sitePages.path,
      pageType: sitePages.pageType,
      slug: sitePages.slug,
      updatedAt: sitePages.updatedAt,
    })
    .from(sitePages)
    .where(and(isNotNull(sitePages.slug), isNotNull(sitePages.updatedAt)))
    .orderBy(desc(sitePages.updatedAt))
    .limit(12);

  return pages;
};
