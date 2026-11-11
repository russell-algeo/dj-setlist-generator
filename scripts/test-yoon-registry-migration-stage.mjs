// Actual Drizzle upgrade/replay of reviewed 0024. Synthetic local PostgreSQL only.
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
const entry=journal.entries.at(-1);
assert.equal(entry.tag,'0024_yoon_version_registry');
assert.equal(entry.idx,23);
assert.equal(entry.when,1794355200000);
const sql=readFileSync(join(folder,entry.tag+'.sql'),'utf8');
const hash=createHash('sha256').update(sql).digest('hex');
const db=new PGlite({extensions:{pgcrypto}}),orm=drizzle(db);
const options=f=>({migrationsFolder:f,migrationsSchema:'public',migrationsTable:'__drizzle_migrations'});
const temp=mkdtempSync(join(tmpdir(),'yoon-registry-stage-'));
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
 mkdirSync(join(temp,'meta'));
 for(const e of journal.entries)copyFileSync(join(folder,e.tag+'.sql'),join(temp,e.tag+'.sql'));
 writeFileSync(join(temp,'meta/_journal.json'),JSON.stringify(journal));
 writeFileSync(join(temp,entry.tag+'.sql'),sql+'\n--> statement-breakpoint\nSELECT yoon_forced_migration_failure();\n');
 await assert.rejects(migrate(orm,options(temp)),/yoon_forced_migration_failure/);checks++;
 assert.equal((await db.query("SELECT to_regclass('ops.yoon_versions') registry")).rows[0].registry,null);checks++;
 assert.deepEqual(await ledger(),original);checks++;
 await migrate(orm,options(folder));
 const after=await ledger();
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
 await migrate(orm,options(folder));assert.deepEqual(await ledger(),after);checks++;
 console.log(`PASS ${checks} actual Drizzle 0023-to-0024 upgrade, forced rollback, exact public ledger, independent ledger preservation, existing data, no bootstrap, read-only worker grants and replay checks; SHA256 ${hash}`);
} finally {await db.close();rmSync(temp,{recursive:true,force:true})}
