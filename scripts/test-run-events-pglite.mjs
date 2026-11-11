// Synthetic actual application reader + PostgreSQL engine. No network or live DSN.
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const root=resolve(dirname(fileURLToPath(import.meta.url)), '..');
const variant=readFileSync(resolve(root,'apps/web/lib/jobs/public.server.ts'),'utf8').includes('readableSubmissionPredicate')?'preview':'production';
const evidenceDir=process.env.RUN_EVENTS_EVIDENCE_DIR;
const record=(name,value)=>{ if(evidenceDir)writeFileSync(resolve(evidenceDir,name),JSON.stringify(value,null,2)+'\n'); };
const require=createRequire(resolve(root,'apps/web/package.json'));
process.env.TSX_TSCONFIG_PATH=resolve(root,'apps/web/tsconfig.json');require('tsx/cjs/api').register();
const pgRoot=process.env.PGLITE_PACKAGE_ROOT;
const {PGlite}=await import(pgRoot?pathToFileURL(resolve(pgRoot,'dist/index.js')).href:'@electric-sql/pglite');
const {pgcrypto}=await import(pgRoot?pathToFileURL(resolve(pgRoot,'dist/contrib/pgcrypto.js')).href:'@electric-sql/pglite/contrib/pgcrypto');
const {drizzle}=require('drizzle-orm/pg-proxy');const pg=new PGlite({extensions:{pgcrypto}});
const q=(text,params=[])=>pg.query(text,params);
const deny=()=>{throw new Error('Network forbidden in bounded-events tests');};globalThis.fetch=deny;
for(const name of ['node:http','node:https']){const m=require(name);m.get=deny;m.request=deny;}
require('node:net').Socket.prototype.connect=deny;require('node:tls').connect=deny;
let reads=[];let tieReference=false;
const db=drizzle(async(text,params,method)=>{
 // The only intentional visible refinement is stable UUID ordering for ties.
 // Untied cases compare with exact legacy; tied cases compare with this explicit
 // reference refinement, never silently claim exact legacy tied order.
 if(tieReference && text.startsWith('select') && text.includes('from "ops"."worker_events"'))text=text.replace(/order by "ops"\."worker_events"\."created_at" desc$/,'order by "ops"."worker_events"."created_at" desc, "ops"."worker_events"."id" desc');
 const result=await pg.query(text,params,method==='execute'?{}:{rowMode:'array'});
 reads.push({text,params,rows:result.rows.length,bytes:Buffer.byteLength(JSON.stringify(result.rows))});
 return {rows:method==='get'?result.rows[0]:result.rows};
});
// pg-proxy raw execute returns rows directly; match the actual Neon-HTTP result
// envelope used by AppDb without changing either application's implementation.
const execute=db.execute.bind(db);db.execute=async(...args)=>({rows:await execute(...args)});
const mock=(path,exports)=>{const id=require.resolve(path);require.cache[id]={id,filename:id,loaded:true,exports};};
mock('server-only',{});mock(resolve(root,'apps/web/lib/db/client.ts'),{getDb:()=>db});
mock(resolve(root,'apps/web/lib/jobs/submissions.ts'),{getSubmissionDetail:()=>{throw new Error('unexpected detail reader');}});
const current=require(resolve(root,'apps/web/lib/jobs/public.server.ts')).getPublicSubmissionRunEventsPage;
const oldpath=resolve(root,'apps/web/test/fixtures/run-events-legacy.ts');
const legacy=require(oldpath).getPublicSubmissionRunEventsPage;
let checks=0,cases=0;const equal=(a,b,label)=>{assert.deepEqual(a,b,label);checks++;};
const id=n=>`10000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const actor=(userId,isAdmin=false)=>({userId,isAdmin,authType:'session',email:`${userId}@example.invalid`,displayName:null,isAllowlisted:true});
const owner=actor('owner');const base={actor:owner,submissionId:id(1),setRunId:id(101),page:1,pageSize:6};
const read=async(fn,args={},ties=false)=>{reads=[];tieReference=ties;const result=await fn({...base,...args});return {result,reads:[...reads]};};
const parity=async(args={},ties=false)=>{const a=await read(legacy,args,ties),b=await read(current,args);equal(b.result,a.result,'DTO parity'+JSON.stringify(args));const query=b.reads.find(r=>r.text.includes('WITH ordered'));if(query){assert.ok(query.rows<=21,'bounded page + possible header');checks++;}cases++;return {before:a,after:b};};
const addEvent=(n,type,stamp,{run=101,sub=1,message=`fixture-${n}`,details={}}={})=>q('INSERT INTO ops.worker_events(id,submission_id,set_run_id,event_type,message,created_at,details) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)',[id(n),id(sub),id(run),type,message,stamp,JSON.stringify(details)]);
const clear=()=>q('DELETE FROM ops.worker_events');
let dense;
try{
 await pg.exec('CREATE ROLE set_list_worker');
 for(const file of readdirSync(resolve(root,'drizzle/migrations')).filter(f=>/^\d.*\.sql$/.test(f)).sort())await pg.exec(readFileSync(resolve(root,'drizzle/migrations',file),'utf8'));
 await q("INSERT INTO authn.users(id,email) VALUES('owner','owner@example.invalid'),('other','other@example.invalid'),('viewer','viewer@example.invalid'),('admin','admin@example.invalid')");
 const addSub=async(n,privateScope=false)=>q(`INSERT INTO ops.submissions(id,requested_by,mode,status${variant==='preview'?',visibility,collection_id':''}) VALUES($1,'owner','set','completed'${variant==='preview'?', $2,$3':''})`,variant==='preview'?[id(n),privateScope?'private':'public',privateScope?id(500):null]:[id(n)]);
 const addRun=async(n,sub,privateScope=false)=>q(`INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url${variant==='preview'?',publication_visibility,collection_id,target_set_id':''}) VALUES($1,$2,'owner','completed','https://example.invalid/synthetic'${variant==='preview'?', $3,$4,$5':''})`,variant==='preview'?[id(n),id(sub),privateScope?'private':'public',privateScope?id(500):null,privateScope?id(501):null]:[id(n),id(sub)]);
 await addSub(1);await addSub(2);await addRun(101,1);await addRun(102,1);await addRun(103,2);
 await parity();equal((await read(current)).result,{events:[],page:1,pageSize:6,totalCount:0,totalPages:1},'empty header');
 for(const args of [{setRunId:id(999)},{submissionId:id(2)}, {setRunId:id(103)}]){await parity(args);equal((await read(current,args)).result,null,'unmatched scope rejected');equal(reads.length,1,'no event query after failed run check');}
 for(let i=0;i<47;i++)await addEvent(1000+i,'set_run.failed',new Date(1700000000000+i*1000).toISOString(),{message:i===0?'':i===1?'Beyoncé ☃':`event-${i}`});
 await addEvent(1100,'custom.event','2030-01-01T00:00:00Z');
 await addEvent(1101,'set_run.dispatch','2030-01-01T00:00:00Z',{run:102});
 await addEvent(1102,'set_run.dispatch','2030-01-01T00:00:00Z',{run:103,sub:2});
 for(const pageSize of [0,-1,1,1.5,6,20,100,Infinity,NaN])for(const page of [-1,0,1,1.5,2,9,999,Infinity,-Infinity,NaN])await parity({page,pageSize});
 const boundaries=['set_run.retried','set_run.requeued','set_run.dispatch','set_run.publish_retry_dispatched','set_run.bootstrap.started'];
 for(const type of boundaries){
  await clear();await addEvent(2000,type,'2026-01-01T00:00:00.123900Z');
  await addEvent(2001,'set_run.failed','2026-01-01T00:00:00.123100Z'); // legacy JS Date includes this
  await addEvent(2002,'set_run.failed','2026-01-01T00:00:00.122999Z'); // excluded
  await addEvent(2003,'set_run.completed','2026-01-01T00:00:00.124000Z');
  await addEvent(2004,'set_run.retried','2026-01-01T00:00:00.123500Z'); // same-ms earlier boundary
  await addEvent(2005,'custom.event','2030-01-01T00:00:00Z');
  await addEvent(2006,'set_run.dispatch','2030-01-01T00:00:00Z',{run:102});
  const result=await parity();equal(result.after.result.events.map(e=>e.id),[2003,2000,2004,2001].map(id),'millisecond floor matches JS, newest boundary correct');
  await parity({page:2,pageSize:2});await parity({page:999,pageSize:2});
 }
 await clear();for(let i=0;i<49;i++)await addEvent(3000+i,i===20?'set_run.dispatch':'set_run.failed','2026-01-01T00:00:00.999999Z');
 const all=[];
 for(let page=1;page<=9;page++){const result=await parity({page,pageSize:6},true);all.push(...result.after.result.events.map(e=>e.id));}
 equal(all,Array.from({length:49},(_,n)=>id(3048-n)),'all static tied events exactly once across nine pages');
 equal(new Set(all).size,49,'no tied duplicates');
 const repeated=await read(current,{page:3});equal(repeated.result,(await read(current,{page:3})).result,'repeated tied page stable');
 await clear();
 await q(`INSERT INTO ops.worker_events(id,submission_id,set_run_id,event_type,message,created_at,details)
  SELECT ('20000000-0000-4000-8000-'||lpad(g::text,12,'0'))::uuid,$1,$2,
   CASE WHEN g=4000 THEN 'set_run.dispatch' ELSE 'set_run.failed' END,
   'synthetic message '||g, '2026-01-01'::timestamptz+g*interval '1 second',
   jsonb_build_object('synthetic_unused_details',repeat(md5(g::text),128)) FROM generate_series(1,5000) g`,[id(1),id(101)]);
 const result=await parity();const a=result.before.reads.filter(r=>r.text.includes('worker_events'));const b=result.after.reads.filter(r=>r.text.includes('WITH ordered'));
 dense={baselineReturnedRows:a.reduce((n,r)=>n+r.rows,0),candidateReturnedRows:b.reduce((n,r)=>n+r.rows,0),baselineJsonBytes:a.reduce((n,r)=>n+r.bytes,0),candidateJsonBytes:b.reduce((n,r)=>n+r.bytes,0),currentAttemptCount:result.after.result.totalCount};
 equal(dense.baselineReturnedRows,5000,'legacy reads entire matching history');equal(dense.candidateReturnedRows,6,'candidate transfers six page rows');equal(dense.currentAttemptCount,1001,'count includes boundary');
 assert.ok(!b[0].text.includes('details'),'unused details never selected');checks++;
 record(`captured-query-${variant}.json`,{text:b[0].text,params:b[0].params,baseline:{text:a[0].text,params:a[0].params}});
 if(variant==='preview'){
  await q("INSERT INTO app.archive_collections(id,slug,title) VALUES($1,'bounded-event-private','Synthetic')",[id(500)]);
  await q("INSERT INTO app.archive_collection_members(collection_id,user_id,role) VALUES($1,'owner','manager'),($1,'viewer','viewer')",[id(500)]);
  await q("INSERT INTO app.sets(id,slug,title,normalized_title,visibility,collection_id) VALUES($1,'synthetic-events','Synthetic','synthetic','private',$2)",[id(501),id(500)]);
  await addSub(50,true);await addRun(150,50,true);await addEvent(6000,'set_run.failed','2026-01-01T00:00:00Z',{run:150,sub:50});
  const scope={submissionId:id(50),setRunId:id(150)};await parity({...scope,actor:actor('viewer')});
  for(const who of [actor('other'),actor('admin',true)]){await parity({...scope,actor:who});equal((await read(current,{...scope,actor:who})).result,null,'private nonmember denied');equal(reads.length,1,'no private event payload query');}
  await q("DELETE FROM app.archive_collection_members WHERE user_id='viewer'");await parity({...scope,actor:actor('viewer')});equal((await read(current,{...scope,actor:actor('viewer')})).result,null,'revocation effective');
 }
 const receipt={variant,checks,parityCases:cases,dense,networkBlocked:true,source:variant==='preview'?'291eab5':'c07f5b46',tiePolicy:'timestamp desc then uuid desc; intentional documented refinement',billingMeasurement:false};
 record(`results-${variant}.json`,receipt);console.log(JSON.stringify(receipt));
}finally{await pg.close();}
