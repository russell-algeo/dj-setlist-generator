import "server-only";

import { createHash } from "node:crypto";

import { requireEnv } from "@/lib/env";

export const buildDatabaseCacheNamespace = (connectionString: string): string => {
  try {
    const url = new URL(connectionString);
    if (!["postgres:", "postgresql:"].includes(url.protocol) || !url.hostname || url.pathname.length < 2) {
      throw new Error("Invalid database connection URL");
    }
    const host = url.hostname.toLowerCase().replace(/-pooler(?=\.)/u, "");
    const identity = JSON.stringify([host, url.port || "5432", decodeURIComponent(url.pathname.slice(1))]);
    return `archive-db-${createHash("sha256").update(identity).digest("hex").slice(0, 20)}`;
  } catch {
    throw new Error("Invalid database connection URL for archive cache");
  }
};

export const getArchiveCacheNamespace = (): string =>
  buildDatabaseCacheNamespace(requireEnv("databaseUrl") as string);
