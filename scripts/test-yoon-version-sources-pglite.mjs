// Finite SQL/runtime identities and descriptor pins must agree byte-for-byte in
// their parsed JSON representation. No private rows, provider or network access.
import {resolve} from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {readFileSync,readdirSync} from 'node:fs';
import assert from 'node:assert/strict';
const pkg=process.env.PGLITE_PACKAGE_ROOT;
const {PGlite}=await import(pkg?pathToFileURL(resolve(pkg,'dist/index.js')).href:'@electric-sql/pglite');
const {pgcrypto}=await import(pkg?pathToFileURL(resolve(pkg,'dist/contrib/pgcrypto.js')).href:'@electric-sql/pglite/contrib/pgcrypto');
const root=fileURLToPath(new URL('../',import.meta.url));
const fixture=JSON.parse(readFileSync(root+'tests/data/yoon_version_reviewed_sources.json','utf8'));
const db=new PGlite({extensions:{pgcrypto}});
await db.exec('CREATE ROLE set_list_worker');
for(const file of readdirSync(root+'drizzle/migrations').filter(f=>/^\d.*\.sql$/.test(f)).sort()) await db.exec(readFileSync(root+'drizzle/migrations/'+file,'utf8'));
const rows=(await db.query('SELECT * FROM ops.yoon_reserved_versions ORDER BY source_id')).rows;
assert.equal(rows.length,10);
let checks=1;
for(const row of rows){
 const p=fixture.plans.find(p=>p.source_id===row.source_id);assert(p);checks++;
 for(const key of ['set_id','run_id','submission_id','media_id']){assert.equal(row[key],p.proposed_ids[key]);checks++;}
 for(const key of ['logical_set_id','model_version','media_revision','expected_windows']){assert.equal(row[key],p[key]);checks++;}
 assert.deepEqual(row.descriptor,p.descriptor_without_private_locator);checks++;
 assert(!JSON.stringify(row).includes('https://'));checks++;
}
for(const table of ['yoon_versions','yoon_version_collections','yoon_version_families','yoon_version_history']){
 assert.equal((await db.query('SELECT count(*)::int AS n FROM ops.'+table)).rows[0].n,0);checks++;
}
// Existing worker deployment already has schema usage; this empty role fixture does not.
await db.exec('GRANT USAGE ON SCHEMA ops TO set_list_worker; SET ROLE set_list_worker');
assert.equal((await db.query('SELECT count(*)::int AS n FROM ops.yoon_reserved_versions')).rows[0].n,10);checks++;
for(const table of ['yoon_version_history','yoon_release_reviews']){
 await assert.rejects(db.query('SELECT * FROM ops.'+table),/permission denied/);checks++;
}
console.log(`PASS ${checks} finite version SQL/catalog/privacy checks; full migrations, no staged rows, synthetic database only.`);
await db.close();
