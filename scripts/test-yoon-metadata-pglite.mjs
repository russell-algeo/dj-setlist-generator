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
const child=spawn(process.env.PYTHON||'python3',[root+'scripts/test_yoon_metadata_pg.py'],{cwd:root,env:{PATH:'/usr/bin:/bin',HOME:'/tmp',PYTHONDONTWRITEBYTECODE:'1',...(process.env.LD_LIBRARY_PATH?{LD_LIBRARY_PATH:process.env.LD_LIBRARY_PATH}:{})},stdio:['pipe','pipe','pipe']});
let done=false,checks=0,stderr='';child.stderr.on('data',d=>stderr+=d);
const closed=new Promise(r=>child.on('close',r));
for await(const line of createInterface({input:child.stdout})){
 const req=JSON.parse(line);if(req.done){done=true;checks=req.checks;continue;}
 let index=0;const sql=req.sql.replace(/%s/g,()=>`$${++index}`);
 try{const r=await db.query(sql,req.params,{parsers:{114:v=>v,3802:v=>v}});for(const row of r.rows)for(const f of r.fields??[])if(f.dataTypeID===20&&row[f.name]!==null)row[f.name]=Number(row[f.name]);child.stdin.write(JSON.stringify({rows:r.rows,fields:r.fields})+'\n');}
 catch(e){child.stdin.write(JSON.stringify({error:e.message})+'\n');}
}
assert.equal(await closed,0,stderr);assert(done,stderr);
console.log(`PASS ${checks} actual Python private full-metadata/PGlite checks; full migrations, transaction rollback, synthetic data only.`);
await db.close();
