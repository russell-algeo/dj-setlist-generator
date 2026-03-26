import { neon, neonConfig } from "@neondatabase/serverless";
import { drizzle } from "drizzle-orm/neon-http";

import { env, requireEnv } from "@/lib/env";
import * as schema from "@/lib/db/schema";

neonConfig.fetchConnectionCache = true;

export const getDb = () => {
  const connectionString = env.databaseUrl ?? requireEnv("databaseUrl");
  const client = neon(connectionString);

  return drizzle(client, { schema });
};

export type AppDb = ReturnType<typeof getDb>;
