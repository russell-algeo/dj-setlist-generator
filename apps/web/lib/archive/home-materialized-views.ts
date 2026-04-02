import { sql } from "drizzle-orm";

import { getWorkerDb } from "@/lib/db/client";

const REFRESH_STATEMENTS = [
  sql`REFRESH MATERIALIZED VIEW CONCURRENTLY "app"."archive_home_artist_atlas_mv"`,
  sql`REFRESH MATERIALIZED VIEW CONCURRENTLY "app"."archive_home_pair_summaries_mv"`,
  sql`REFRESH MATERIALIZED VIEW CONCURRENTLY "app"."archive_home_set_library_index_mv"`,
] as const;

export const refreshArchiveHomeMaterializedViews = async () => {
  // The public app role cannot refresh these archive-home MVs. Use the
  // internal worker connection, which is granted MAINTAIN on them.
  const db = getWorkerDb();

  for (const statement of REFRESH_STATEMENTS) {
    await db.execute(statement);
  }
};
