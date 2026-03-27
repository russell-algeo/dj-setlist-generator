import "server-only";

import { sql } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { createWorkerEvent } from "@/lib/jobs/internal";
import { dispatchPendingWork } from "@/lib/jobs/dispatch";

const db = getDb();

export const runSchedulerRecovery = async () => {
  // Recover leases before runs: a run reset to queued must not have stale claimed
  // leases still attached when the dispatcher picks it up again.
  const leaseRecovery = await db.execute(
    sql`select ops.recover_stale_leases(interval '15 minutes') as recovered`,
  );
  const runRecovery = await db.execute(
    sql`select ops.recover_stale_set_runs(interval '30 minutes') as recovered`,
  );
  const cleanup = await db.execute(sql`select ops.cleanup_expired_ops_data() as counts`);

  const recoveredLeases = Number(leaseRecovery.rows[0]?.recovered ?? 0);
  const recoveredRuns = Number(runRecovery.rows[0]?.recovered ?? 0);
  const cleanupCounts = (cleanup.rows[0]?.counts ?? {}) as Record<string, number>;

  if (recoveredLeases > 0 || recoveredRuns > 0) {
    await createWorkerEvent({
      eventType: "scheduler.stale_recovery",
      message: `Recovered ${recoveredLeases} stale lease(s) and ${recoveredRuns} stale run(s)`,
      details: { recoveredLeases, recoveredRuns },
    });
  }

  const { artistDispatch, setDispatch } = await dispatchPendingWork();

  return {
    recoveredLeases,
    recoveredRuns,
    cleanup: cleanupCounts,
    artistDispatch,
    setDispatch,
  };
};
