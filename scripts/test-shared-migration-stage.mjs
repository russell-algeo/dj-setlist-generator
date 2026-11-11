// Upgrade an existing 0021 database with the actual Drizzle migrator; no network.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
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
// Reproduce the already-applied 0021 journal exactly before the additive patch.
const priorEntry=JSON.parse(readFileSync(root+'drizzle/migrations/meta/_journal.json','utf8')).entries.find(e=>e.tag==='0021_shared_recognition_continuation');
const priorSql=readFileSync(root+'drizzle/migrations/'+priorEntry.tag+'.sql','utf8');
await db.exec(priorSql);
await db.query('INSERT INTO public.__drizzle_migrations(hash,created_at) VALUES($1,$2)',[createHash('sha256').update(priorSql).digest('hex'),priorEntry.when]);
const before=await rows();
const journal=JSON.parse(readFileSync(root+'drizzle/migrations/meta/_journal.json','utf8'));
const cutoff=journal.entries.findIndex(e=>e.tag==='0022_shared_recognition_parallel');
assert.notEqual(cutoff,-1);
const stage=mkdtempSync(join(tmpdir(),'shared-migration-v2-'));
try {
mkdirSync(join(stage,'meta'));
for(const entry of journal.entries.slice(0,cutoff+1)) {
  copyFileSync(root+'drizzle/migrations/'+entry.tag+'.sql',join(stage,entry.tag+'.sql'));
}
writeFileSync(join(stage,'meta/_journal.json'),JSON.stringify({...journal,entries:journal.entries.slice(0,cutoff+1)}));
await migrate(orm,options(stage));
const after=await rows();
assert.equal(after.length,before.length+1);
assert.equal(after.at(-2).hash,createHash('sha256').update(readFileSync(root+'drizzle/migrations/0021_shared_recognition_continuation.sql')).digest('hex'));
assert.equal((await db.query("SELECT obj_description('ops.claim_next_dispatchable_set_run(integer)'::regprocedure,'pg_proc') AS marker")).rows[0].marker,'shared-recognition-parallel-v2');
assert.equal((await db.query("SELECT obj_description('ops.cleanup_expired_ops_data()'::regprocedure,'pg_proc') AS marker")).rows[0].marker,'private-recognition-retention-v1');
assert.equal(after.at(-1).hash,createHash('sha256').update(readFileSync(root+'drizzle/migrations/0022_shared_recognition_parallel.sql')).digest('hex'));
assert.deepEqual(after.slice(0,-1),before);
assert.equal(Number(after.at(-1).created_at),journal.entries[cutoff].when);
await migrate(orm,options(stage));
assert.deepEqual(await rows(),after);
// Upgrade the already-applied v2 stage, without rewriting its journal or SQL.
const claimBody=(await db.query("SELECT pg_get_functiondef('ops.claim_next_dispatchable_set_run(integer)'::regprocedure) AS body")).rows[0].body;
const finalEntry=journal.entries[cutoff+1];
assert.equal(finalEntry.tag,'0023_shared_recognition_throttle');
assert.ok(journal.entries.length>=cutoff+2);
// This regression owns only 0021 through 0023, independent of later migrations.
copyFileSync(root+'drizzle/migrations/'+finalEntry.tag+'.sql',join(stage,finalEntry.tag+'.sql'));
writeFileSync(join(stage,'meta/_journal.json'),JSON.stringify({...journal,entries:journal.entries.slice(0,cutoff+2)}));
await migrate(orm,options(stage));
const final=await rows();
assert.equal(final.length,after.length+1);
assert.deepEqual(final.slice(0,-1),after);
assert.equal(final.at(-1).hash,createHash('sha256').update(readFileSync(root+'drizzle/migrations/'+finalEntry.tag+'.sql')).digest('hex'));
assert.equal(Number(final.at(-1).created_at),finalEntry.when);
assert.equal((await db.query("SELECT obj_description('ops.claim_next_dispatchable_set_run(integer)'::regprocedure,'pg_proc') AS marker")).rows[0].marker,'shared-recognition-throttle-v3');
assert.equal((await db.query("SELECT pg_get_functiondef('ops.claim_next_dispatchable_set_run(integer)'::regprocedure) AS body")).rows[0].body,claimBody);
assert.equal((await db.query("SELECT obj_description('ops.cleanup_expired_ops_data()'::regprocedure,'pg_proc') AS marker")).rows[0].marker,'private-recognition-retention-v1');
await migrate(orm,options(stage));
assert.deepEqual(await rows(),final);
console.log('PASS actual Drizzle 0021-to-0022-to-0023 upgrades, exact journal hashes/timestamps, v2/v3 markers, claim-body/private-marker preservation and per-stage idempotence.');
} finally {
  await db.close();
  rmSync(stage,{recursive:true,force:true});
}
