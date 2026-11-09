import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "drizzle-kit";
import { preparePrivateMigrationStage } from "./scripts/private-migration-stage.mjs";

const rootDir = path.dirname(fileURLToPath(import.meta.url));

const url =
  process.env.DATABASE_URL_MIGRATIONS ??
  process.env.DATABASE_URL_DIRECT ??
  process.env.DEVELOPMENT_DATABASE_URL_MIGRATIONS ??
  process.env.DATABASE_URL ??
  process.env.DEVELOPMENT_DATABASE_URL_DIRECT ??
  "";

if (!url) {
  console.warn(
    "drizzle.config.ts: DATABASE_URL_MIGRATIONS / DATABASE_URL_DIRECT / DATABASE_URL is not set. Drizzle commands that need a database connection will fail.",
  );
}

export default defineConfig({
  dialect: "postgresql",
  schema: path.join(rootDir, "drizzle", "schema.ts"),
  // During the two-phase rollout, ordinary migrate stops safely at expand.
  // Sealing is a separate explicit operator step after guarded code is verified.
  // Build/deploy never invokes this. Keep generation on the canonical journal.
  out: process.argv.includes("migrate")
    ? preparePrivateMigrationStage(rootDir, process.env.PRIVATE_ARCHIVE_MIGRATION_PHASE ?? "expand")
    : path.join(rootDir, "drizzle", "migrations"),
  migrations: {
    schema: "public",
    table: "__drizzle_migrations",
  },
  dbCredentials: {
    url,
  },
  verbose: true,
  strict: true,
});
