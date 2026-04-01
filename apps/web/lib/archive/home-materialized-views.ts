import { sql } from "drizzle-orm";

import { getDb } from "@/lib/db/client";

const REFRESH_STATEMENTS = [
  sql`REFRESH MATERIALIZED VIEW CONCURRENTLY "app"."archive_home_artist_atlas_mv"`,
  sql`REFRESH MATERIALIZED VIEW CONCURRENTLY "app"."archive_home_pair_summaries_mv"`,
  sql`REFRESH MATERIALIZED VIEW CONCURRENTLY "app"."archive_home_set_library_index_mv"`,
] as const;

export const refreshArchiveHomeMaterializedViews = async () => {
  const db = getDb();

  for (const statement of REFRESH_STATEMENTS) {
    await db.execute(statement);
  }
};
