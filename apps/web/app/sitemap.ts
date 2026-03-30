import type { MetadataRoute } from "next";
import { asc } from "drizzle-orm";
import { getDb } from "@/lib/db/client";
import { artists, sets } from "@/lib/db/schema";
import { env } from "@/lib/env";

const baseUrl = (() => {
  try {
    return new URL(
      env.appBaseUrl ||
        (env.deploymentTarget === "development" ? "http://localhost:3000" : "http://localhost:3000"),
    );
  } catch {
    return new URL("http://localhost:3000");
  }
})();

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const db = getDb();
  const [artistRows, setRows] = await Promise.all([
    db.select({ slug: artists.slug, updatedAt: artists.updatedAt }).from(artists).orderBy(asc(artists.slug)),
    db.select({ slug: sets.slug, updatedAt: sets.updatedAt }).from(sets).orderBy(asc(sets.slug)),
  ]);

  return [
    {
      url: new URL("/", baseUrl).toString(),
      lastModified: new Date(),
    },
    ...artistRows.map((row) => ({
      url: new URL(`/artists/${row.slug}`, baseUrl).toString(),
      lastModified: row.updatedAt,
    })),
    ...setRows.map((row) => ({
      url: new URL(`/sets/${row.slug}`, baseUrl).toString(),
      lastModified: row.updatedAt,
    })),
  ];
}
