// Execute the real public jobs-list reader against synthetic, in-memory PostgreSQL.
// No application credentials, live database, provider calls or production writes.
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(resolve(root, 'apps/web/package.json'));
process.env.TSX_TSCONFIG_PATH = resolve(root, 'apps/web/tsconfig.json');
require('tsx/cjs/api').register();
const packageRoot = process.env.PGLITE_PACKAGE_ROOT;
const { PGlite } = await import(packageRoot
  ? pathToFileURL(resolve(packageRoot, 'dist/index.js')).href : '@electric-sql/pglite');
const { pgcrypto } = await import(packageRoot
  ? pathToFileURL(resolve(packageRoot, 'dist/contrib/pgcrypto.js')).href : '@electric-sql/pglite/contrib/pgcrypto');
const { drizzle } = require('drizzle-orm/pg-proxy');
const pg = new PGlite({ extensions: { pgcrypto } });
const q = (text, params = []) => pg.query(text, params);

// A fail-closed network guard is installed before loading any application module.
const denyNetwork = () => { throw new Error('Network access forbidden in jobs-list fixtures'); };
globalThis.fetch = denyNetwork;
for (const name of ['node:http', 'node:https']) {
  const module = require(name);
  module.request = denyNetwork;
  module.get = denyNetwork;
}
require('node:net').Socket.prototype.connect = denyNetwork;
require('node:tls').connect = denyNetwork;

let legacyMode = false;
let eventReads = [];
let allReads = [];
const db = drizzle(async (text, params, method) => {
  // Reference the exact old event SELECT, retaining every other query and DTO path.
  if (legacyMode && text.startsWith('select distinct on')) {
    text = text.replace(/^select distinct on \("ops"\."worker_events"\."submission_id"\)/, 'select')
      .replace(/order by "ops"."worker_events"\."submission_id", "ops"."worker_events"\."created_at" desc, "ops"."worker_events"\."id" desc$/, 'order by "ops"."worker_events"."created_at" desc');
    assert.ok(!text.startsWith('select distinct on'), 'legacy reference query must be unbounded');
  }
  const result = await pg.query(text, params, { rowMode: 'array' });
  const rows = result.rows;
  const record = { text, params, count: rows.length, bytes: Buffer.byteLength(JSON.stringify(rows)) };
  allReads.push(record);
  if (text.includes('from "ops"."worker_events"')) eventReads.push(record);
  return { rows: method === 'get' ? rows[0] : rows };
});
const mock = (path, exports) => {
  const id = require.resolve(path);
  require.cache[id] = { id, filename: id, loaded: true, exports };
};
mock('server-only', {});
mock(resolve(root, 'apps/web/lib/db/client.ts'), { getDb: () => db });
mock(resolve(root, 'apps/web/lib/jobs/submissions.ts'), {
  getSubmissionDetail: () => { throw new Error('Unexpected detail reader'); },
});
const { listPublicSubmissionsForActor: list } = require(resolve(root, 'apps/web/lib/jobs/public.server.ts'));

let checks = 0;
const equal = (actual, expected, message) => { assert.deepEqual(actual, expected, message); checks += 1; };
const id = n => `10000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const actor = (userId, isAdmin = false) => ({ userId, isAdmin, authType: 'session', email: `${userId}@example.invalid`, displayName: null, isAllowlisted: true });
const owner = actor('owner');
const preview = readFileSync(resolve(root, 'apps/web/lib/jobs/public.server.ts'), 'utf8').includes('readableSubmissionPredicate');

try {
  await pg.exec('CREATE ROLE set_list_worker');
  for (const file of readdirSync(resolve(root, 'drizzle/migrations')).filter(f => /^\d.*\.sql$/.test(f)).sort()) {
    await pg.exec(readFileSync(resolve(root, 'drizzle/migrations', file), 'utf8'));
  }
  await q("INSERT INTO authn.users(id,email) VALUES('owner','owner@example.invalid'),('other','other@example.invalid'),('viewer','viewer@example.invalid'),('admin','admin@example.invalid')");
  const addSubmission = async (n, { user = 'owner', status = 'completed', created = n, visibility = 'public', collection = null } = {}) => {
    const columns = preview ? ',visibility,collection_id' : '';
    const values = preview ? ',$6,$7' : '';
    const params = [id(n), user, status, new Date(1700000000000 + created * 1000).toISOString(), new Date(1700000000000 + created * 1000 + 500).toISOString()];
    if (preview) params.push(visibility, collection);
    await q(`INSERT INTO ops.submissions(id,requested_by,mode,status,created_at,updated_at${columns}) VALUES($1,$2,'set',$3,$4,$5${values})`, params);
  };
  const addEvent = (n, submission, timestamp, message = `event-${n}`) => q(
    'INSERT INTO ops.worker_events(id,submission_id,event_type,message,created_at) VALUES($1,$2,\'arbitrary.event\',$3,$4)',
    [id(n), submission === null ? null : id(submission), message, timestamp],
  );
  const read = async (who = owner, filter = 'all', legacy = false) => {
    eventReads = [];
    allReads = [];
    legacyMode = legacy;
    const result = await list(who, filter);
    return { result, events: [...eventReads], queries: [...allReads] };
  };

  equal((await read()).result, [], 'empty list');
  equal(allReads.length, 1, 'empty list does not read counts or events');
  for (let n = 1; n <= 6; n += 1) await addSubmission(n, { status: n === 1 ? 'running' : 'completed' });
  await addSubmission(7, { user: 'other' });
  await addSubmission(8); // No events: updatedAt fallback must survive.
  // A realistic large history and very small latest-event output. Timestamps are unique per submission.
  await q(`INSERT INTO ops.worker_events(id,submission_id,event_type,message,created_at)
    SELECT ('20000000-0000-4000-8000-' || lpad(g::text,12,'0'))::uuid,
      ('10000000-0000-4000-8000-' || lpad(((g % 6)+1)::text,12,'0'))::uuid,
      'synthetic.history',repeat('old event payload ',10), timestamptz '2024-01-01' + g * interval '1 second'
    FROM generate_series(1,15433) g`);
  for (let n = 1; n <= 6; n += 1) await addEvent(100 + n, n, `2025-01-0${n}T00:00:00Z`, `latest-${n}`);
  await addEvent(200, 7, '2026-01-01T00:00:00Z', 'other actor event');
  await addEvent(201, null, '2026-02-01T00:00:00Z', 'unscoped event');
  const statuses = ['queued', 'recognizing', 'completed', 'failed', 'failed', 'cancelled'];
  for (let n = 0; n < statuses.length; n += 1) {
    const columns = preview ? ',publication_visibility' : '';
    const values = preview ? ",'public'" : '';
    await q(`INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,attempt_count${columns}) VALUES($1,$2,'owner',$3,'local:synthetic',$4${values})`, [id(300 + n), id(1), statuses[n], n === 4 ? 3 : 1]);
  }
  const legacy = await read(owner, 'all', true);
  const current = await read();
  equal(current.result, legacy.result, 'full DTO equivalent to legacy query for non-tied events');
  equal(current.events.length, 1, 'one batched event query, not N+1');
  equal(current.events[0].count, 6, 'one event per visible submission that has events');
  equal(current.events[0].params.length, 7, 'event query bound only to selected submissions');
  equal(current.result.map(row => row.id), [8, 6, 5, 4, 3, 2, 1].map(id), 'submission order remains creation-descending');
  equal(current.result[0].lastActivityMessage, null, 'missing event has null message');
  equal(current.result[0].lastActivityAt, new Date(1700000000000 + 8500).toISOString(), 'missing event uses updatedAt');
  equal(current.result.at(-1).counts, { totalCount: 6, queuedCount: 1, inFlightCount: 1, activeCount: 2, completedCount: 1, failedCount: 2, cancelledCount: 1, terminalCount: 4 }, 'run counts unchanged');
  equal(current.result.at(-1).actions, { retryableCount: 2, exhaustedRetryCount: 1, cancellableCount: 2, canRetry: true, canCancel: true }, 'retry/cancel counts unchanged');
  equal((await read(owner, 'active')).result.map(row => row.id), [id(1)], 'active filter');
  equal((await read(owner, 'completed')).result.map(row => row.id), [8, 6, 5, 4, 3, 2].map(id), 'terminal filter');
  equal((await read(owner, 'garbage')).result, (await read(owner, 'all')).result, 'invalid status keeps normalized all default');
  equal((await read(actor('other'))).result.map(row => row.id), [id(7)], 'non-admin cannot read other owner events');
  equal((await read(actor('admin', true))).result.length, 8, 'admin reads public submissions');
  const bytes = { before: legacy.events[0].bytes, after: current.events[0].bytes };
  assert.ok(bytes.after < bytes.before / 1000, 'history egress reduced by >1000x'); checks += 1;

  // Timestamp wins over UUID; equal timestamps choose maximum UUID consistently.
  await addEvent(999, 1, '2024-01-01T00:00:00Z', 'larger UUID but older');
  await addEvent(901, 1, '2026-03-01T00:00:00.123456Z', 'tie winner');
  await addEvent(900, 1, '2026-03-01T00:00:00.123456Z', 'tie loser inserted later');
  equal((await read(owner, 'active')).result[0].lastActivityMessage, 'tie winner', 'stable UUID tie-break is not insertion order');
  equal((await read(owner, 'active')).result[0].lastActivityMessage, 'tie winner', 'repeat tie result is stable');
  await addEvent(899, 1, '2026-03-01T00:00:00.123457Z', 'newer by one microsecond');
  equal((await read(owner, 'active')).result[0].lastActivityMessage, 'newer by one microsecond', 'SQL preserves timestamp microseconds before JS date conversion');
  await addEvent(898, 1, '2026-03-02T00:00:00Z', '');
  equal((await read(owner, 'active')).result[0].lastActivityMessage, '', 'empty messages are retained');

  if (preview) {
    await q("INSERT INTO app.archive_collections(id,slug,title) VALUES($1,'synthetic-jobs-private','Synthetic')", [id(500)]);
    await q("INSERT INTO app.archive_collection_members(collection_id,user_id,role) VALUES($1,'owner','manager'),($1,'viewer','viewer')", [id(500)]);
    await addSubmission(50, { user: 'other', visibility: 'private', collection: id(500) });
    await addEvent(550, 50, '2026-01-01T00:00:00Z', 'private member-only event');
    equal((await read(actor('viewer'))).result.map(row => row.id), [id(50)], 'private collection viewer may read');
    equal((await read(actor('admin', true))).result.some(row => row.id === id(50)), false, 'general admin does not grant private collection access');
    equal((await read(actor('other'))).result.some(row => row.id === id(50)), false, 'private submission ownership alone does not grant membership');
    await q("DELETE FROM app.archive_collection_members WHERE user_id='viewer'");
    equal((await read(actor('viewer'))).result, [], 'membership revocation takes effect on next read');
    equal(eventReads.length, 0, 'revoked actor transfers no event payload');
  }

  // The pre-existing 100-row list window is applied before event selection.
  for (let n = 1000; n < 1105; n += 1) {
    await addSubmission(n);
    await addEvent(2000 + n, n, '2026-01-01T00:00:00Z');
  }
  const window = await read();
  equal(window.result.length, 100, 'list limit remains 100');
  equal(window.result.map(row => row.id), Array.from({ length: 100 }, (_, n) => id(1104 - n)), 'same newest-100 list window');
  equal(window.events[0].count, 100, 'at most 100 events returned');
  equal(new Set(window.events[0].params), new Set(window.result.map(row => row.id)), 'event scope exactly matches visible window');
  equal(window.result, (await read(owner, 'all', true)).result, 'window DTO equivalence including counts and events');
  console.log(JSON.stringify({ suite: 'jobs-list-postgres', branch: preview ? 'preview' : 'production', checks, fixtureEventBytes: bytes, reductionFactor: bytes.before / bytes.after }));
} finally {
  await pg.close();
}
