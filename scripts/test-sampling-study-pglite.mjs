import {resolve} from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {readFileSync,readdirSync} from 'node:fs';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import assert from 'node:assert/strict';
const pkg=process.env.PGLITE_PACKAGE_ROOT;
const {PGlite}=await import(pathToFileURL(resolve(pkg,'dist/index.js')).href);
const {pgcrypto}=await import(pathToFileURL(resolve(pkg,'dist/contrib/pgcrypto.js')).href);
const root=fileURLToPath(new URL('../',import.meta.url));const db=new PGlite({extensions:{pgcrypto}});
await db.exec('CREATE ROLE set_list_worker');
for(const f of readdirSync(root+'drizzle/migrations').filter(f=>/^\d.*\.sql$/.test(f)).sort())await db.exec(readFileSync(root+'drizzle/migrations/'+f,'utf8'));
await db.exec('GRANT USAGE ON SCHEMA ops TO set_list_worker; GRANT SELECT ON ops.set_runs,ops.segment_hits,ops.set_run_leases TO set_list_worker');
await db.exec(readFileSync(root+'scripts/sampling-study-schema.sql','utf8'));
const child=spawn(process.env.PYTHON||'python3',[root+'scripts/test_sampling_study_pg.py'],{cwd:root,env:{PATH:process.env.PATH,HOME:'/tmp',PYTHONDONTWRITEBYTECODE:'1'},stdio:['pipe','pipe','pipe']});
let done=false,checks=0,stderr='';child.stderr.on('data',x=>stderr+=x);
for await(const line of createInterface({input:child.stdout})){
 const q=JSON.parse(line);if(q.done){done=true;checks=q.checks;continue}let i=0;
 try{const r=await db.query(q.sql.replace(/%s/g,()=>`$${++i}`),q.params);for(const row of r.rows)for(const f of r.fields??[])if(f.dataTypeID===20&&row[f.name]!==null)row[f.name]=Number(row[f.name]);child.stdin.write(JSON.stringify({rows:r.rows,fields:r.fields})+'\n')}
 catch(e){child.stdin.write(JSON.stringify({error:e.message})+'\n')}
}
const code=await new Promise(r=>child.on('close',r));assert.equal(code,0,stderr);assert(done,stderr);
console.log(`PASS ${checks} actual StudyStore/PGlite checks; full migrations, isolated synthetic data; NOT multi-session contention/lock-loss proof.`);await db.close();
