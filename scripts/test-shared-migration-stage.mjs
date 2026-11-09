// Upgrade an existing 0020 database with the actual Drizzle migrator; no network.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {preparePrivateMigrationStage} from './private-migration-stage.mjs';
const require=createRequire(import.meta.url);
const {PGlite}=require('@electric-sql/pglite');
const {pgcrypto}=require('@electric-sql/pglite/contrib/pgcrypto');
const {drizzle}=require('drizzle-orm/pglite');
const {migrate}=require('drizzle-orm/pglite/migrator');
const root=fileURLToPath(new URL('../',import.meta.url));
const db=new PGlite({extensions:{pgcrypto}});
await db.exec('CREATE ROLE set_list_worker');
const orm=drizzle(db),baseline=preparePrivateMigrationStage(root,'recognition');
const options=folder=>({migrationsFolder:folder,migrationsSchema:'public',migrationsTable:'__drizzle_migrations'});
// Historical baseline includes legacy multi-command fragments unsupported by
// PGlite's prepared-query adapter; execute unchanged historical SQL and record
// its real hashes, matching the existing staged migration regression harness.
await db.exec('CREATE TABLE public.__drizzle_migrations(id serial PRIMARY KEY, hash text NOT NULL, created_at bigint)');
for(const entry of JSON.parse(readFileSync(baseline+'/meta/_journal.json','utf8')).entries){
  const sql=readFileSync(`${baseline}/${entry.tag}.sql`,'utf8');
  await db.exec(sql);
  await db.query('INSERT INTO public.__drizzle_migrations(hash,created_at) VALUES($1,$2)',[createHash('sha256').update(sql).digest('hex'),entry.when]);
}
const rows=async()=>(await db.query('SELECT hash,created_at FROM public.__drizzle_migrations ORDER BY created_at')).rows;
const before=await rows();
await migrate(orm,options(root+'drizzle/migrations'));
const after=await rows();
assert.equal(after.length,before.length+1);
assert.equal(after.at(-1).hash,createHash('sha256').update(readFileSync(root+'drizzle/migrations/0021_shared_recognition_continuation.sql')).digest('hex'));
assert.equal((await db.query("SELECT obj_description('ops.claim_next_dispatchable_set_run(integer)'::regprocedure,'pg_proc') AS marker")).rows[0].marker,'shared-recognition-continuation-v1');
assert.equal((await db.query("SELECT obj_description('ops.cleanup_expired_ops_data()'::regprocedure,'pg_proc') AS marker")).rows[0].marker,'private-recognition-retention-v1');
await migrate(orm,options(root+'drizzle/migrations'));
assert.deepEqual(await rows(),after);
console.log('PASS actual Drizzle 0020-to-0021 upgrade, exact migration hash, private marker preservation and idempotence.');
await db.close();
