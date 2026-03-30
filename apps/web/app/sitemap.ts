import type { MetadataRoute } from "next";
import { asc, isNotNull } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { artists, sets } from "@/lib/db/schema";
import { env } from "@/lib/env";

const baseUrl = (() => {
  try {
    return new URL(
      env.appBaseUrl || (env.deploymentTarget === "development" ? "http://localhost:3000" : "http://localhost:3000"),
    );
  } catch {
    return new URL("http://localhost:3000");
  }
})();

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const db = getDb();
  const [artistRows, setRows] = await Promise.all([
    db
      .select({ path: artists.legacyPath, updatedAt: artists.updatedAt })
      .from(artists)
      .where(isNotNull(artists.legacyPath))
      .orderBy(asc(artists.legacyPath)),
    db
      .select({ path: sets.legacyPath, updatedAt: sets.updatedAt })
      .from(sets)
      .where(isNotNull(sets.legacyPath))
      .orderBy(asc(sets.legacyPath)),
  ]);

  return [
    {
      url: new URL("/", baseUrl).toString(),
      lastModified: new Date(),
    },
    ...artistRows.map((row) => ({
      url: new URL(row.path ?? "/", baseUrl).toString(),
      lastModified: row.updatedAt,
    })),
    ...setRows.map((row) => ({
      url: new URL(row.path ?? "/", baseUrl).toString(),
      lastModified: row.updatedAt,
    })),
  ];
}
