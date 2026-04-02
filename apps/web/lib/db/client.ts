import { neon, neonConfig } from "@neondatabase/serverless";
import { drizzle } from "drizzle-orm/neon-http";

import { env, requireEnv } from "@/lib/env";
import * as schema from "@/lib/db/schema";

neonConfig.poolQueryViaFetch = true;

const createDb = (connectionString: string) => {
  const client = neon(connectionString);

  return drizzle(client, { schema });
};

export const getDb = () => createDb((env.databaseUrl ?? requireEnv("databaseUrl")) as string);

export const getWorkerDb = () =>
  createDb((env.databaseUrlDirect ?? requireEnv("databaseUrlDirect")) as string);

export const getMigrationsDb = () =>
  createDb((env.databaseUrlMigrations ?? requireEnv("databaseUrlMigrations")) as string);

export type AppDb = ReturnType<typeof createDb>;
