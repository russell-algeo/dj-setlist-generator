import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "drizzle-kit";

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
  out: path.join(rootDir, "drizzle", "migrations"),
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
