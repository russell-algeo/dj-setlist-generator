import {resolve} from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {readFileSync,readdirSync} from 'node:fs';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import assert from 'node:assert/strict';
const pkg=process.env.PGLITE_PACKAGE_ROOT;
const {PGlite}=await import(pkg?pathToFileURL(resolve(pkg,'dist/index.js')).href:'@electric-sql/pglite');
const {pgcrypto}=await import(pkg?pathToFileURL(resolve(pkg,'dist/contrib/pgcrypto.js')).href:'@electric-sql/pglite/contrib/pgcrypto');
const root=fileURLToPath(new URL('../',import.meta.url));
const db=new PGlite({extensions:{pgcrypto}});
await db.exec('CREATE ROLE set_list_worker');
for(const f of readdirSync(root+'drizzle/migrations').filter(f=>/^\d.*\.sql$/.test(f)).sort()) await db.exec(readFileSync(root+'drizzle/migrations/'+f,'utf8'));
await db.exec("INSERT INTO authn.users(id,email) VALUES('synthetic-owner','owner@example.invalid'); INSERT INTO ops.submissions(id,requested_by,mode,status,visibility) VALUES('30000000-0000-4000-8000-000000000001','synthetic-owner','set','running','public')");
for(const id of ['a0000000-0000-4000-8000-000000000010','a0000000-0000-4000-8000-000000000011'])
 await db.query("INSERT INTO ops.set_runs(id,submission_id,requested_by,status,stage,source_url,publication_visibility,source_metadata) VALUES($1,'30000000-0000-4000-8000-000000000001','synthetic-owner','recognizing','recognizing','local:synthetic','public',$2)",[id,{active_workflow_run_id:'9001',dispatch_generation:'g',segment_count:3}]);
await db.exec('CREATE ROLE synthetic_shared_worker; GRANT USAGE ON SCHEMA app,ops TO synthetic_shared_worker; GRANT SELECT ON ALL TABLES IN SCHEMA app TO synthetic_shared_worker; GRANT SELECT,INSERT,UPDATE ON ALL TABLES IN SCHEMA ops TO synthetic_shared_worker; GRANT USAGE ON ALL SEQUENCES IN SCHEMA ops TO synthetic_shared_worker');
const child=spawn(process.env.PYTHON||'python3',[root+'scripts/test_shared_recognition_pg.py'],{cwd:root,env:{PATH:'/usr/bin:/bin',HOME:'/tmp',PYTHONDONTWRITEBYTECODE:'1',...(process.env.LD_LIBRARY_PATH?{LD_LIBRARY_PATH:process.env.LD_LIBRARY_PATH}:{})},stdio:['pipe','pipe','pipe']});
let done=false,checks=0,stderr='';child.stderr.on('data',d=>stderr+=d);
const closed=new Promise(r=>child.on('close',r));
for await(const line of createInterface({input:child.stdout})){
 const req=JSON.parse(line);if(req.done){done=true;checks=req.checks;continue;}
 let index=0;const sql=req.sql.replace(/%s/g,()=>`$${++index}`);
 try{const r=await db.query(sql,req.params);for(const row of r.rows)for(const f of r.fields??[])if(f.dataTypeID===20&&row[f.name]!==null)row[f.name]=Number(row[f.name]);child.stdin.write(JSON.stringify({rows:r.rows,fields:r.fields})+'\n');}
 catch(e){child.stdin.write(JSON.stringify({error:e.message})+'\n');}
}
assert.equal(await closed,0,stderr);assert(done,stderr);
console.log(`PASS ${checks} actual Python RecognitionStore/PGlite checks; full migrations, worker-like privileges, synthetic data only.`);
await db.close();
