import "server-only";

import { sql } from "drizzle-orm";
import type { AppDb } from "@/lib/db/client";

type EventRow = {
  id: string;
  eventType: string;
  message: string;
  createdAt: Date;
  setRunId: string | null;
};
type ResultRow = {
  totalCount: number | string;
  id: string | null;
  eventType: string | null;
  message: string | null;
  createdAt: Date | string | null;
  setRunId: string | null;
};

/** One statement/snapshot; bound returned history without dropping stored events.
 * Caller must retain its existing run/submission authorization check.
 */
export const readRunEventsPage = async ({
  db, submissionId, setRunId, page, pageSize, eventTypes, boundaryTypes,
}: {
  db: Pick<AppDb, "execute">;
  submissionId: string;
  setRunId: string;
  page: number;
  pageSize: number;
  eventTypes: readonly string[];
  boundaryTypes: readonly string[];
}) => {
  const safePageSize = Math.max(1, Math.min(pageSize, 20));
  // The HTTP route supplies finite positive integers. Preserve the old helper's
  // fractional/NaN/infinite direct-call arithmetic too, without invalid SQL.
  const invalidSlice = Number.isNaN(page) || Number.isNaN(safePageSize);
  const queryPage = Number.isFinite(page) ? page : page === Infinity ? Number.MAX_SAFE_INTEGER : 1;
  const querySize = Number.isNaN(safePageSize) ? 1 : safePageSize;
  const allowed = sql.join(eventTypes.map((value) => sql`${value}`), sql`, `);
  const boundaries = sql.join(boundaryTypes.map((value) => sql`${value}`), sql`, `);
  // UUID only resolves equal timestamps; it is not insertion order. This
  // intentionally stabilizes tied pages. Rank/count compact keys server-side;
  // load message payloads only for the chosen page, never unused details.
  const result = await db.execute(sql<ResultRow>`
    WITH ordered AS MATERIALIZED (
      SELECT id, created_at,
        row_number() OVER (ORDER BY created_at DESC, id DESC) AS ordinal,
        max(date_trunc('milliseconds', created_at)) FILTER (
          WHERE event_type IN (${boundaries})
        ) OVER () AS attempt_boundary
      FROM ops.worker_events
      WHERE submission_id = ${submissionId}::uuid AND set_run_id = ${setRunId}::uuid
        AND event_type IN (${allowed})
    ), current_events AS MATERIALIZED (
      SELECT * FROM ordered
      WHERE attempt_boundary IS NULL OR created_at >= attempt_boundary
    ), counts AS (
      SELECT count(*)::float8 AS total_count FROM current_events
    ), page_info AS (
      SELECT total_count,
        greatest(1::float8, least(${queryPage}::float8,
          greatest(1::float8, ceil(total_count / ${querySize}::float8)))) AS current_page
      FROM counts
    ), page_events AS MATERIALIZED (
      SELECT e.id, e.ordinal FROM current_events e CROSS JOIN page_info p
      WHERE NOT ${invalidSlice}::boolean
        AND e.ordinal > trunc((p.current_page - 1) * ${querySize}::float8)
        AND e.ordinal <= trunc(p.current_page * ${querySize}::float8)
    )
    SELECT p.total_count AS "totalCount", e.id, e.event_type AS "eventType",
      e.message, e.created_at AS "createdAt", e.set_run_id AS "setRunId"
    FROM page_info p
    LEFT JOIN page_events chosen ON true
    LEFT JOIN ops.worker_events e ON e.id = chosen.id
    ORDER BY chosen.ordinal
  `);
  const rows = result.rows as unknown as ResultRow[];
  if (rows.length === 0) throw new Error("Run event count row missing");
  const totalCount = Number(rows[0].totalCount);
  const totalPages = Math.max(1, Math.ceil(totalCount / safePageSize));
  const currentPage = Math.max(1, Math.min(page, totalPages));
  const events: EventRow[] = rows.filter((row) => row.id !== null).map((row) => {
    if (row.eventType === null || row.message === null || row.createdAt === null) {
      throw new Error("Run event row incomplete");
    }
    return {
      id: row.id!, eventType: row.eventType, message: row.message,
      createdAt: row.createdAt instanceof Date ? row.createdAt : new Date(row.createdAt),
      setRunId: row.setRunId,
    };
  });
  return { events, totalCount, totalPages, page: currentPage, pageSize: safePageSize };
};
