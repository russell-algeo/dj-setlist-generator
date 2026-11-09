// Offline synthetic PostgreSQL test. PGlite is an optional test tool, not a runtime dependency.
import { fileURLToPath, pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
const packageRoot = process.env.PGLITE_PACKAGE_ROOT;
const { PGlite } = await import(packageRoot ? pathToFileURL(resolve(packageRoot, 'dist/index.js')).href : '@electric-sql/pglite');
const { pgcrypto } = await import(packageRoot ? pathToFileURL(resolve(packageRoot, 'dist/contrib/pgcrypto.js')).href : '@electric-sql/pglite/contrib/pgcrypto');
import { readFileSync, readdirSync } from 'node:fs';
import assert from 'node:assert/strict';
const root = fileURLToPath(new URL('../', import.meta.url));
const aclPath = process.argv[2];
if (!aclPath) throw new Error('Pass the JSON output from apps/web/scripts/export-private-access-test-sql.ts');
const db = new PGlite({ extensions: { pgcrypto } });
let checks = 0;
const check = (actual, expected) => { assert.deepEqual(actual, expected); checks++; };
const reject = async (sql, params=[]) => { await assert.rejects(db.query(sql,params)); checks++; };
await db.exec('CREATE ROLE set_list_worker');
for (const file of readdirSync(`${root}/drizzle/migrations`).filter(f=>/^\d.*\.sql$/.test(f) && parseInt(f,10) < 18).sort()) {
  try { await db.exec(readFileSync(`${root}/drizzle/migrations/${file}`, 'utf8')); }
  catch(error) { console.error('Prior migration failed:',file,error.message); process.exit(1); }
}
const ids = { pub:'10000000-0000-4000-8000-000000000001', priv:'10000000-0000-4000-8000-000000000002', col:'20000000-0000-4000-8000-000000000001', othercol:'20000000-0000-4000-8000-000000000002', pubsub:'30000000-0000-4000-8000-000000000001', privsub:'30000000-0000-4000-8000-000000000002', pubrun:'40000000-0000-4000-8000-000000000001', privrun:'40000000-0000-4000-8000-000000000002', pubartist:'50000000-0000-4000-8000-000000000001', privartist:'50000000-0000-4000-8000-000000000002' };
for (const user of ['synthetic-russell','synthetic-hal','outsider','admin']) await db.query('INSERT INTO authn.users(id,email) VALUES ($1,$2)',[user,`${user}@example.invalid`]);
await db.query(`INSERT INTO app.sets (id,slug,title,normalized_title) VALUES ($1,'public-set','Public Set','public set')`,[ids.pub]);
await db.query(`INSERT INTO ops.submissions (id,requested_by,mode,status) VALUES ($1,'synthetic-russell','set','queued')`,[ids.pubsub]);
await db.query(`INSERT INTO ops.set_runs (id,submission_id,requested_by,status,source_url) VALUES ($1,$2,'synthetic-russell','queued','https://example.invalid/public')`,[ids.pubrun,ids.pubsub]);
try { await db.exec(readFileSync(`${root}/drizzle/migrations/0018_private_collection_access.sql`,'utf8')); }
catch(error) { console.error('New migration failed:',error.message); process.exit(1); }
// Expand phase keeps the still-serving legacy public writer functional.
await db.exec("INSERT INTO app.sets(slug,title,normalized_title) VALUES ('legacy-expansion-test','Legacy','legacy'); DELETE FROM app.sets WHERE slug='legacy-expansion-test'");
checks++;
await db.exec(readFileSync(`${root}/drizzle/migrations/0019_private_insert_defaults.sql`,'utf8'));
check((await db.query('SELECT visibility FROM app.sets')).rows,[{visibility:'public'}]);
check((await db.query('SELECT publication_visibility FROM ops.set_runs')).rows,[{publication_visibility:'public'}]);
await reject(`INSERT INTO app.sets (slug,title,normalized_title) VALUES ('no-scope','No scope','no scope')`);
await reject(`INSERT INTO ops.submissions(requested_by,mode,status) VALUES ('synthetic-russell','set','queued')`);
await reject(`INSERT INTO ops.set_runs(submission_id,requested_by,status,source_url) VALUES ($1,'synthetic-russell','queued','none')`,[ids.pubsub]);
await db.query(`INSERT INTO app.archive_collections(id,slug,title) VALUES ($1,'yoon-fest','Synthetic private collection'),($2,'other','Other')`,[ids.col,ids.othercol]);
await db.query(`INSERT INTO app.archive_collection_members(collection_id,user_id,role) VALUES ($1,'synthetic-russell','manager'),($1,'synthetic-hal','viewer')`,[ids.col]);
await db.query(`INSERT INTO app.sets(id,slug,title,normalized_title,collection_id) VALUES ($1,'private-set','SECRET TITLE','secret title',$2)`,[ids.priv,ids.col]);
await db.query(`INSERT INTO ops.submissions(id,requested_by,mode,status,collection_id) VALUES ($1,'synthetic-russell','set','private_analysis_pending',$2)`,[ids.privsub,ids.col]);
await db.query(`INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,target_set_id,collection_id) VALUES ($1,$2,'synthetic-russell','queued','private-local-placeholder',$3,$4)`,[ids.privrun,ids.privsub,ids.priv,ids.col]);
await reject(`UPDATE app.sets SET visibility='public',collection_id=NULL WHERE id=$1`,[ids.priv]);
await reject(`UPDATE ops.submissions SET visibility='public',collection_id=NULL WHERE id=$1`,[ids.privsub]);
await reject(`UPDATE ops.set_runs SET collection_id=$2 WHERE id=$1`,[ids.privrun,ids.othercol]);
await reject(`UPDATE ops.set_runs SET published_set_id=$2 WHERE id=$1`,[ids.pubrun,ids.priv]);
await reject(`UPDATE ops.set_runs SET published_set_id=$2 WHERE id=$1`,[ids.privrun,ids.pub]);
await reject(`INSERT INTO ops.set_runs(submission_id,requested_by,status,source_url,target_set_id,collection_id) VALUES ($1,'synthetic-russell','queued','none',$2,$3)`,[ids.pubsub,ids.priv,ids.col]);
await reject(`INSERT INTO ops.set_runs(submission_id,requested_by,status,source_url,target_set_id,collection_id) VALUES ($1,'synthetic-russell','queued','none',$2,$3)`,[ids.privsub,ids.pub,ids.col]);
await db.query(`UPDATE ops.set_runs SET published_set_id=$2,status='private_analysis_complete' WHERE id=$1`,[ids.privrun,ids.priv]);
await db.query(`UPDATE ops.set_runs SET status='queued' WHERE id=$1`,[ids.privrun]);
check((await db.query('SELECT id FROM ops.claim_next_dispatchable_set_run(10)')).rows.map(x=>x.id),[ids.pubrun]);
check((await db.query('SELECT id FROM ops.public_set_runs')).rows.map(x=>x.id),[ids.pubrun]);
check((await db.query('SELECT id FROM ops.public_submissions')).rows.map(x=>x.id),[ids.pubsub]);
await db.query(`INSERT INTO app.artists(id,slug,name,normalized_name) VALUES ($1,'public-artist','Public Artist','public artist'),($2,'private-artist','SECRET ARTIST','secret artist')`,[ids.pubartist,ids.privartist]);
await db.query(`INSERT INTO app.set_artists(set_id,artist_id) VALUES ($1,$3),($2,$3),($2,$4)`,[ids.pub,ids.priv,ids.pubartist,ids.privartist]);
await db.query(`INSERT INTO app.set_entries(set_id,position,display_artist,display_title,start_time_seconds,end_time_seconds,confidence) VALUES ($1,1,'Public Artist','Public Track',0,10,'HIGH'),($2,1,'SECRET ARTIST','SECRET TRACK',0,10,'HIGH')`,[ids.pub,ids.priv]);
for (const view of ['archive_home_artist_atlas_mv','archive_home_pair_summaries_mv','archive_home_set_library_index_mv']) {
 await db.exec(`REFRESH MATERIALIZED VIEW app.${view}`);
 const data=(await db.query(`SELECT * FROM app.${view}`)).rows;
 check(JSON.stringify(data).includes('SECRET'),false);
}
for (const view of ['public_sets','public_set_entries','public_set_artists','public_artists','public_tracks','public_set_source_links']) check(JSON.stringify((await db.query(`SELECT * FROM app.${view}`)).rows).includes('SECRET'),false);
const acl = JSON.parse(readFileSync(aclPath,'utf8'));
for (const [user,scope] of Object.entries(acl)) {
 const allowed = ['synthetic-russell','synthetic-hal'].includes(user);
 const q=scope.sets; const rows=(await db.query(`SELECT id FROM app.sets WHERE ${q.sql} ORDER BY id`,q.params)).rows.map(x=>x.id);
 check(rows,allowed?[ids.pub,ids.priv]:[ids.pub]);
 if (scope.submissions) { const q=scope.submissions; const rows=(await db.query(`SELECT id FROM ops.submissions WHERE ${q.sql} ORDER BY id`,q.params)).rows.map(x=>x.id); check(rows,user==='synthetic-russell'?[ids.pubsub,ids.privsub]:user==='synthetic-hal'?[ids.privsub]:user==='admin'?[ids.pubsub]:[]); }
 if (scope.manage) { const q=scope.manage; const rows=(await db.query(`SELECT id FROM ops.submissions WHERE ${q.sql} ORDER BY id`,q.params)).rows.map(x=>x.id); check(rows,user==='synthetic-russell'?[ids.pubsub,ids.privsub]:user==='admin'?[ids.pubsub]:[]); }
}
await db.query(`DELETE FROM app.archive_collection_members WHERE user_id='synthetic-hal'`);
const q=acl['synthetic-hal'].sets; check((await db.query(`SELECT id FROM app.sets WHERE ${q.sql} ORDER BY id`,q.params)).rows.map(x=>x.id),[ids.pub]);
check((await db.query('SELECT set_slug FROM app.archive_home_set_library_index_mv')).rows,[{set_slug:'public-set'}]);
console.log(`PASS: ${checks} actual PostgreSQL checks; full migration chain, legacy public preservation, private defaults, scope triggers, public views/MVs, compiled app ACL, admin exclusion, manager mutations, revocation, dispatcher exclusion. In-memory synthetic database only.`);
await db.close();
