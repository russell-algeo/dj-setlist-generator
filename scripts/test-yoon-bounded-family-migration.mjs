// Actual Drizzle upgrade/replay of reviewed 0025. Synthetic local PostgreSQL only.
import assert from 'node:assert/strict';
import {createHash,randomUUID} from 'node:crypto';
import {createRequire} from 'node:module';
import {copyFileSync,mkdirSync,mkdtempSync,readFileSync,rmSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
const require=createRequire(import.meta.url);
const pkg=process.env.PGLITE_PACKAGE_ROOT;
const {PGlite}=await import(pkg?pathToFileURL(resolve(pkg,'dist/index.js')).href:'@electric-sql/pglite');
const {pgcrypto}=await import(pkg?pathToFileURL(resolve(pkg,'dist/contrib/pgcrypto.js')).href:'@electric-sql/pglite/contrib/pgcrypto');
const {drizzle}=require('drizzle-orm/pglite');
const {migrate}=require('drizzle-orm/pglite/migrator');
const root=fileURLToPath(new URL('../',import.meta.url));
const folder=join(root,'drizzle/migrations');
const journal=JSON.parse(readFileSync(join(folder,'meta/_journal.json'),'utf8'));
// Test the exact additive upgrade independently of the sealed 0024 test.
journal.entries=journal.entries.filter(e=>e.idx<=24);
const entry=journal.entries.at(-1);
assert.equal(entry.tag,'0025_yoon_bounded_family_checks');
assert.equal(entry.idx,24);
assert.equal(entry.when,1794355200001);
const sql=readFileSync(join(folder,entry.tag+'.sql'),'utf8');
const hash=createHash('sha256').update(sql).digest('hex');
const db=new PGlite({extensions:{pgcrypto}}),orm=drizzle(db);
const options=f=>({migrationsFolder:f,migrationsSchema:'public',migrationsTable:'__drizzle_migrations'});
const temp=mkdtempSync(join(tmpdir(),'yoon-family-stage-'));
let checks=0;
try {
 await db.exec('CREATE ROLE set_list_worker; CREATE TABLE public.__drizzle_migrations(id serial PRIMARY KEY,hash text NOT NULL,created_at bigint); CREATE SCHEMA drizzle; CREATE TABLE drizzle.__drizzle_migrations(id serial PRIMARY KEY,hash text NOT NULL,created_at bigint)');
 for(const prior of journal.entries.slice(0,-1)){
  const source=readFileSync(join(folder,prior.tag+'.sql'),'utf8');
  await db.exec(source);
  await db.query('INSERT INTO public.__drizzle_migrations(hash,created_at) VALUES($1,$2)',[createHash('sha256').update(source).digest('hex'),prior.when]);
 }
 // Preserve the independent historical ledger; the actual migrator targets public.
 await db.query("INSERT INTO drizzle.__drizzle_migrations(hash,created_at) VALUES('synthetic-historical-record',1)");
 const sid=randomUUID();
 await db.query("INSERT INTO app.sets(id,slug,title,normalized_title,visibility) VALUES($1,'synthetic-existing','Existing','existing','public')",[sid]);
 const ledger=async()=> (await db.query("SELECT 'public' origin,id,hash,created_at FROM public.__drizzle_migrations UNION ALL SELECT 'drizzle',id,hash,created_at FROM drizzle.__drizzle_migrations ORDER BY origin,id")).rows;
 const original=await ledger(),beforeSet=(await db.query('SELECT to_jsonb(s) row FROM app.sets s WHERE id=$1',[sid])).rows;
 const functions=async()=> (await db.query("SELECT oid::regprocedure::text name,proowner,proacl::text,pg_get_functiondef(oid) body FROM pg_proc WHERE oid IN ('ops.yoon_mutation_guard()'::regprocedure,'ops.assert_yoon_version_execution(uuid,text,text)'::regprocedure,'ops.select_yoon_version(uuid,uuid,bigint,uuid,text,text,text,boolean)'::regprocedure) ORDER BY 1")).rows;
 const beforeFunctions=await functions();
 mkdirSync(join(temp,'meta'));
 for(const e of journal.entries)copyFileSync(join(folder,e.tag+'.sql'),join(temp,e.tag+'.sql'));
 writeFileSync(join(temp,'meta/_journal.json'),JSON.stringify(journal));
 writeFileSync(join(temp,entry.tag+'.sql'),sql+'\n--> statement-breakpoint\nSELECT yoon_forced_migration_failure();\n');
 await assert.rejects(migrate(orm,options(temp)),/yoon_forced_migration_failure/);checks++;
 assert.deepEqual(await functions(),beforeFunctions);checks++;
 assert.deepEqual(await ledger(),original);checks++;
 writeFileSync(join(temp,entry.tag+'.sql'),sql);
 await migrate(orm,options(temp));
 const after=await ledger();
 const afterFunctions=await functions();
 assert.deepEqual(afterFunctions.map(({body,...rest})=>rest),beforeFunctions.map(({body,...rest})=>rest));checks++;
 assert(afterFunctions.every((f,i)=>f.body!==beforeFunctions[i].body && f.body.includes('FOR family_run_id')));checks++;
 assert.equal(after.length,original.length+1);checks++;
 assert.deepEqual(after.filter(r=>r.origin==='drizzle'),original.filter(r=>r.origin==='drizzle'));checks++;
 assert.deepEqual(after.filter(r=>r.origin==='public').slice(0,-1),original.filter(r=>r.origin==='public'));checks++;
 const last=after.filter(r=>r.origin==='public').at(-1);
 assert.equal(last.hash,hash);assert.equal(Number(last.created_at),entry.when);checks+=2;
 assert.deepEqual((await db.query('SELECT to_jsonb(s) row FROM app.sets s WHERE id=$1',[sid])).rows,beforeSet);checks++;
 assert.equal((await db.query('SELECT count(*)::int n FROM ops.yoon_reserved_versions')).rows[0].n,10);checks++;
 for(const table of ['yoon_versions','yoon_version_families','yoon_version_collections','yoon_release_reviews','yoon_version_history']){assert.equal((await db.query(`SELECT count(*)::int n FROM ops.${table}`)).rows[0].n,0);checks++}
 assert.equal((await db.query('SELECT app.yoon_version_readable($1,false) ok',[sid])).rows[0].ok,true);checks++;
 assert.equal((await db.query("SELECT has_table_privilege('set_list_worker','ops.yoon_versions','SELECT') ok")).rows[0].ok,true);checks++;
 assert.equal((await db.query("SELECT has_table_privilege('set_list_worker','ops.yoon_versions','UPDATE') ok")).rows[0].ok,false);checks++;
 writeFileSync(join(temp,entry.tag+'.sql'),sql);
 await migrate(orm,options(temp));assert.deepEqual(await ledger(),after);checks++;
 console.log(`PASS ${checks} actual Drizzle 0024-to-0025 upgrade, forced rollback, exact public ledger, independent ledger preservation, existing data, no bootstrap, read-only worker grants and replay checks; SHA256 ${hash}`);
} finally {await db.close();rmSync(temp,{recursive:true,force:true})}
