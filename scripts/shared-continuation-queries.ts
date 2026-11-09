import { eq, sql } from 'drizzle-orm';
import { PgDialect } from 'drizzle-orm/pg-core';
import { setRuns } from '../drizzle/schema';
import { buildRequeueWithCleanupQuery } from '../apps/web/lib/jobs/requeue';
import { recoverStaleLeasesQuery, recoverStaleRunsQuery } from '../apps/web/lib/jobs/recovery-sql';
import { validRecognitionHit } from '../apps/web/lib/jobs/shared-recognition';
import { recoveryEligibility } from '../apps/web/lib/jobs/recovery-eligibility';
import { prepareDispatchMetadata } from '../apps/web/lib/jobs/publication';
const snapshot = {id:'20000000-0000-4000-8000-000000000001',status:'dispatched',stage:'dispatching',attemptCount:0,sourceMetadata:JSON.parse(process.env.SHARED_FIXTURE_METADATA || '{}')} as typeof setRuns.$inferSelect;
const dialect = new PgDialect();
console.log(JSON.stringify({
  generationClaim: dialect.sqlToQuery(sql`update ${setRuns} set source_metadata=${prepareDispatchMetadata('synthetic-generation')} where ${recoveryEligibility(snapshot)} returning id`),
  legacyCount: dialect.sqlToQuery(sql`select count(*)::integer as n from ops.segment_hits where ${validRecognitionHit(false, 2)}`),
  validCount: dialect.sqlToQuery(sql`select count(*)::integer as n from ops.segment_hits where ${validRecognitionHit(true, 2, 15)}`),
  requeue: dialect.sqlToQuery(buildRequeueWithCleanupQuery({ predicate: eq(setRuns.id, '20000000-0000-4000-8000-000000000001'), stage: 'queued' })),
  staleLeases: dialect.sqlToQuery(recoverStaleLeasesQuery),
  staleRuns: dialect.sqlToQuery(recoverStaleRunsQuery),
}));
