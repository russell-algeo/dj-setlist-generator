import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const pkg=process.env.PGLITE_PACKAGE_ROOT;
const {PGlite}=await import(pkg?pathToFileURL(resolve(pkg,'dist/index.js')).href:'@electric-sql/pglite');
const {pgcrypto}=await import(pkg?pathToFileURL(resolve(pkg,'dist/contrib/pgcrypto.js')).href:'@electric-sql/pglite/contrib/pgcrypto');
import {readFileSync,readdirSync} from 'node:fs';
import {randomUUID} from 'node:crypto';
import assert from 'node:assert/strict';
import {spawnSync,spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
const calls=[]; const onNotice=n=>{if(n.message.startsWith('test_busy '))calls.push(n.message.slice(10));}; const db=new PGlite({extensions:{pgcrypto}}), q=(s,p=[])=>db.query(s,p,{onNotice});
await db.exec('CREATE ROLE set_list_worker');
for(const f of readdirSync('drizzle/migrations').filter(f=>/^\d.*\.sql$/.test(f)).sort()) await db.exec(readFileSync('drizzle/migrations/'+f,'utf8'));
let checks=0; const reject=async(s,p=[],pattern)=>{await assert.rejects(q(s,p),pattern);checks++};
const col=randomUUID();
await q("INSERT INTO authn.users(id,email) VALUES('owner','owner@example.invalid'),('viewer','viewer@example.invalid')");
await q("INSERT INTO app.archive_collections(id,slug,title) VALUES($1,'yoon-fest','Synthetic')",[col]);
await q("INSERT INTO app.archive_collection_members(collection_id,user_id,role) VALUES($1,'owner','manager'),($1,'viewer','viewer')",[col]);
const reserved=(await q('SELECT * FROM ops.yoon_reserved_versions ORDER BY source_id LIMIT 1')).rows[0];
// Names/metadata in unrelated archives must not activate Yoon-only policy.
const otherCol=randomUUID();await q("INSERT INTO app.archive_collections(id,slug,title) VALUES($1,'unrelated','Unrelated')",[otherCol]);
for(const visibility of ['public','private']) for(const title of ['mean gaps v2','yoon_version']){
 const id=randomUUID(),sub=randomUUID(),run=randomUUID(),scope=visibility==='private'?otherCol:null;
 await q('INSERT INTO app.sets(id,slug,title,normalized_title,visibility,collection_id) VALUES($1,$2,$3,$3,$4,$5)',[id,id,title,visibility,scope]);
 await q("UPDATE app.sets SET metadata='{\"timingModelVersion\":\"unrelated\"}' WHERE id=$1",[id]);
 assert.equal((await q('SELECT app.yoon_version_readable($1,false) ok',[id])).rows[0].ok,true);checks++;
 await q('INSERT INTO ops.submissions(id,requested_by,mode,status,visibility,collection_id,artist_name) VALUES($1,\'owner\',\'set\',\'queued\',$2,$3,$4)',[sub,visibility,scope,title]);
 await q('INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,publication_visibility,target_set_id,collection_id,source_metadata) VALUES($1,$2,\'owner\',\'queued\',\'local:synthetic\',$3,$4,$5,$6)',[run,sub,visibility,visibility==='private'?id:null,scope,{timingModelVersion:'unrelated'}]);
 assert.equal((await q('SELECT app.yoon_submission_version_readable($1) ok',[sub])).rows[0].ok,true);checks++;
 await q('SELECT ops.assert_yoon_version_execution($1,\'admit\')',[run]);checks++;
}
await reject("INSERT INTO app.sets(id,slug,title,normalized_title,visibility,collection_id,metadata) VALUES($1,'unknown-yoon-corrected','x','x','private',$2,'{\"timingModelVersion\":\"v2\"}')",[randomUUID(),col],/unregistered/);
await reject("INSERT INTO app.sets(id,slug,title,normalized_title,visibility,collection_id) VALUES($1,'fixed-wrong-collection','x','x','private',$2)",[reserved.set_id,otherCol],/unregistered/);
const revision=reserved.media_revision;
const ids=Array.from({length:27},(_,i)=>({set:i===0?reserved.logical_set_id:randomUUID(),run:randomUUID(),sub:randomUUID(),media:randomUUID(),source:'legacy'+i,slug:'legacy'+i}));
const descriptor={...reserved.descriptor,source_url:'https://www.dropbox.com/scl/fi/SYNTHETIC/source.wav?dl=1'}; const legacyDescriptor={source_sha256:'a'.repeat(64),source_bytes:100,source_start_seconds:0,source_end_seconds:30};
async function insertRows(x){
 await q("INSERT INTO app.sets(id,slug,title,normalized_title,visibility,collection_id,source_id) VALUES($1,$2,'Synthetic','synthetic','private',$3,$4)",[x.set,x.slug,col,x.source]);
 await q("INSERT INTO ops.submissions(id,requested_by,mode,status,visibility,collection_id) VALUES($1,'owner','set','private_analysis_pending','private',$2)",[x.sub,col]);
 await q("INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,publication_visibility,target_set_id,collection_id,source_metadata) VALUES($1,$2,'owner','private_resume_pending','local:synthetic','private',$3,$4,$5)",[x.run,x.sub,x.set,col,{yoon_fixed_input:x.set===reserved.set_id?descriptor:legacyDescriptor}]);
 await q(`INSERT INTO app.set_media(id,set_id,revision,content_type,duration_seconds,recording_sources,source_spans) VALUES($1,$2,'${x.set===reserved.set_id?revision:'legacy'}','audio/wav',30,'[]','[]')`,[x.media,x.set]);
}
for(const x of ids)await insertRows(x);
const origin=randomUUID();
await q(`INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,publication_visibility,target_set_id,collection_id,source_metadata)
 SELECT $1,submission_id,requested_by,status,source_url,publication_visibility,target_set_id,collection_id,source_metadata FROM ops.set_runs WHERE id=$2`,[origin,ids[0].run]);
for(const r of [...ids.map(i=>i.run),origin]) await q(`INSERT INTO ops.segment_hits(set_run_id,segment_index,timestamp_seconds,recognized,raw_data)
 SELECT $1,i,i*15,false,jsonb_build_object('private_jackson_v2',jsonb_build_object('valid',true,'in_flight',false,'response',jsonb_build_object('padding',repeat('synthetic-json-evidence-',100)))) FROM generate_series(0,15) i`,[r]);

const readable=async(id,selected=false)=>(await q('SELECT app.yoon_version_readable($1,$2) ok',[id,selected])).rows[0].ok;
assert.equal(await readable(ids[0].set),true);checks++;
await reject("INSERT INTO app.sets(id,slug,title,normalized_title,visibility,collection_id) VALUES($1,'unknown-v2','x','x','private',$2)",[reserved.set_id,col],/unregistered/);
const snapshots=[];for(const x of ids)snapshots.push({set_id:x.set,snapshot_sha256:(await q('SELECT ops.yoon_sha(ops.yoon_version_snapshot($1)) sha',[x.set])).rows[0].sha});
const audience=(await q('SELECT ops.yoon_audience($1) sha',[col])).rows[0].sha;
async function register(x,pred=null){
 await q(`INSERT INTO ops.yoon_versions(set_id,logical_set_id,model_version,source_id,run_id,submission_id,media_id,slug,media_revision,collection_id,requested_by,predecessor_set_id,manifest_sha256,source_sha256,media_sha256,audience_sha256,processing_approved,released)
 VALUES($1,$2,$3,$4,$5,$6,$7,$8,'${pred?revision:'legacy'}',$9,'owner',$10,$11,$12,$13,$14,true,$15)`,[x.set,pred??x.set,pred?reserved.model_version:'v1',x.source,x.run,x.sub,x.media,x.slug,col,pred,'b'.repeat(64),x.sourceSha??(await q('SELECT ops.yoon_source_fingerprint($1) sha',[x.run])).rows[0].sha,x.mediaSha??(await q('SELECT ops.yoon_media_fingerprint($1) sha',[x.set])).rows[0].sha,audience,!pred]);
}
await db.exec('BEGIN');
await q('INSERT INTO ops.yoon_version_collections(collection_id,audience_sha256,bootstrap_manifest,bootstrap_sha256) VALUES($1,$2,$3,ops.yoon_sha($3::jsonb))',[col,audience,snapshots]);
for(const x of ids){await q('INSERT INTO ops.yoon_version_families(logical_set_id,collection_id,selected_set_id) VALUES($1,$2,$1)',[x.set,col]);await register(x)}
await db.exec('COMMIT');checks++;
assert.equal(await readable(ids[0].set,true),true);checks++;
await reject("UPDATE ops.yoon_versions SET source_id='tamper' WHERE set_id=$1",[ids[0].set],/immutable/);
await reject("DELETE FROM app.archive_collection_members WHERE collection_id=$1 AND user_id='viewer'",[col],/audience/);
await reject("INSERT INTO app.sets(id,slug,title,normalized_title,visibility,collection_id) VALUES($1,'unknown','x','x','private',$2)",[randomUUID(),col],/unregistered/);
const x={set:reserved.set_id,run:reserved.run_id,sub:reserved.submission_id,media:reserved.media_id,source:reserved.source_id,slug:'synthetic-v2'};
x.sourceSha=(await q("SELECT ops.yoon_sha(jsonb_build_object('source_url','local:synthetic','descriptor',$1::jsonb)) sha",[descriptor])).rows[0].sha;
x.mediaSha=(await q(`SELECT ops.yoon_sha(jsonb_build_object('id',$1::uuid,'set_id',$2::uuid,'revision','${revision}','content_type','audio/wav','duration_seconds',30.000000::numeric(12,6),'recording_sources','[]'::jsonb,'source_spans','[]'::jsonb)) sha`,[x.media,x.set])).rows[0].sha;
function compile(name,args){
 const p=spawnSync(process.env.PYTHON||'python3',['-c',`import json,sys; from scripts.yoon_version_registry import ${name}; print(${name}(*json.load(sys.stdin)))`],{input:JSON.stringify(args),encoding:'utf8'});
 assert.equal(p.status,0,p.stderr);return p.stdout;
}
const registry={set_id:x.set,logical_set_id:ids[0].set,model_version:reserved.model_version,source_id:x.source,run_id:x.run,submission_id:x.sub,media_id:x.media,slug:x.slug,media_revision:revision,collection_id:col,requested_by:'owner',predecessor_set_id:ids[0].set,manifest_sha256:'b'.repeat(64),source_sha256:x.sourceSha,media_sha256:x.mediaSha,audience_sha256:audience,staging_approved:true,processing_approved:false,released:false,frozen:false};
const initialRows={
 'app.sets':{id:x.set,slug:x.slug,title:'Synthetic',normalized_title:'synthetic',visibility:'private',collection_id:col,source_id:x.source},
 'ops.submissions':{id:x.sub,requested_by:'owner',mode:'set',status:'private_analysis_pending',visibility:'private',collection_id:col},
 'ops.set_runs':{id:x.run,submission_id:x.sub,requested_by:'owner',status:'private_resume_pending',source_url:'local:synthetic',publication_visibility:'private',target_set_id:x.set,collection_id:col,source_metadata:{yoon_fixed_input:descriptor}},
 'app.set_media':{id:x.media,set_id:x.set,revision,content_type:'audio/wav',duration_seconds:30,recording_sources:[],source_spans:[]}
};
await db.exec(compile('stage_sql',[registry,initialRows]));checks++;
await reject('SELECT ops.assert_yoon_version_execution($1,\'admit\')',[x.run],/approved/);
await reject("UPDATE app.sets SET title='Unapproved import' WHERE id=$1",[x.set],/unapproved/);
await db.exec(compile('approve_execution_sql',[x.set,registry]));checks++;

assert.equal(await readable(x.set),false);checks++;
assert.equal((await q('SELECT app.yoon_submission_version_readable($1) ok',[x.sub])).rows[0].ok,false);checks++;
await q('SELECT ops.assert_yoon_version_execution($1,\'admit\')',[x.run]);checks++;
await q("UPDATE ops.set_runs SET source_metadata=source_metadata || '{\"yoon_queue_v1\":{\"version\":1,\"status\":\"queued\"}}'::jsonb WHERE id=$1",[ids[0].run]);
await reject('SELECT ops.assert_yoon_version_execution($1,\'enqueue\')',[x.run],/enrolled/);
await reject('SELECT ops.initialize_yoon_version_execution($1)',[x.set],/enrolled/);
await q("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_queue_v1,status}','\"complete\"') WHERE id=$1",[ids[0].run]);
await q('SELECT ops.assert_yoon_version_execution($1,\'enqueue\')',[x.run]);checks++;
await db.exec(compile('initialize_execution_sql',[x.set]));checks++;
await reject('SELECT ops.initialize_yoon_version_execution($1)',[x.set],/fresh/);
const initial=(await q("SELECT source_metadata->'yoon_resume' s FROM ops.set_runs WHERE id=$1",[x.run])).rows[0].s;
assert.equal(initial.initialization_mode,'fresh');assert.equal(initial.requests,0);assert.equal(initial.members.length,2);checks+=3;
// Exercise real queue/store classes after compiled stage + approval + init.
await db.exec(`CREATE ROLE synthetic_private_worker;
 GRANT USAGE ON SCHEMA app,ops TO synthetic_private_worker;
 GRANT SELECT ON app.sets,app.archive_collections,app.archive_collection_members,app.set_media TO synthetic_private_worker;
 GRANT SELECT ON ops.yoon_versions,ops.yoon_version_families,ops.yoon_reserved_versions TO synthetic_private_worker;
 GRANT SELECT(collection_id,audience_sha256) ON ops.yoon_version_collections TO synthetic_private_worker;
 GRANT SELECT,INSERT,UPDATE,DELETE ON ops.set_runs,ops.submissions,ops.segment_hits,ops.set_run_leases TO synthetic_private_worker;
 -- Match the sealed runtime worker function dependencies; never owner helpers.
 GRANT EXECUTE ON FUNCTION app.yoon_version_readable(uuid,boolean),app.yoon_submission_version_readable(uuid),ops.yoon_collection_scope(uuid),ops.yoon_is_v2(jsonb),ops.yoon_sha(jsonb),ops.yoon_audience(uuid),ops.yoon_source_fingerprint(uuid),ops.yoon_media_fingerprint(uuid),ops.yoon_registry_lock(),ops.yoon_run_busy(uuid),ops.assert_yoon_version_identity(uuid),ops.assert_yoon_version_execution(uuid,text,text) TO synthetic_private_worker;`);
assert.equal((await q("SELECT has_function_privilege('synthetic_private_worker','ops.initialize_yoon_version_execution(uuid)','EXECUTE') ok")).rows[0].ok,false);checks++;
const beforeClaim=(await q('SELECT source_metadata FROM ops.set_runs WHERE id=$1',[x.run])).rows[0].source_metadata;
const originalBusy=(await q("SELECT pg_get_functiondef('ops.yoon_run_busy(uuid)'::regprocedure) body")).rows[0].body;
await db.exec(originalBusy.replace('FUNCTION ops.yoon_run_busy(', 'FUNCTION ops.test_original_busy('));
await db.exec(`GRANT EXECUTE ON FUNCTION ops.test_original_busy(uuid) TO synthetic_private_worker;
CREATE OR REPLACE FUNCTION ops.yoon_run_busy(p uuid) RETURNS boolean LANGUAGE plpgsql STABLE AS $$ BEGIN
 IF p NOT IN ('${ids[0].run}'::uuid,'${origin}'::uuid,'${x.run}'::uuid) THEN RAISE EXCEPTION 'test_unrelated_busy_invoked'; END IF;
 RAISE NOTICE 'test_busy %',p;
 RETURN ops.test_original_busy(p); END $$;`);
const callsBefore=calls.length;

const py=`from pathlib import Path
__file__=str(Path("scripts/test_yoon_resume_pg.py").resolve())
exec(Path('scripts/test_yoon_resume_pg.py').read_text().split("RUN='a0000000")[0])
import os
from worker.jobs.yoon_queue import PrivateQueue,identity
run='${x.run}'
queue=PrivateQueue(connect=connect)
with queue.store(run).locked(owner=False) as (_,row,state): manifest=identity(row,state)
check(queue.enqueue([manifest])['queued']==1)
reservation=queue.refresh_and_reserve(run)
check(bool(reservation))
os.environ['SET_LIST_DISPATCH_GENERATION']=reservation['generation']
s=ResumeStore(run,'9001','1',connect=connect)
check(s.finalize_ready() is False)
s.claim()
check(s.require_owner()['fresh_source_initialized'])
print(json.dumps({'done':True,'checks':checks}),file=sys.__stdout__,flush=True)
`;
const child=spawn(process.env.PYTHON||'python3',['-c',py],{stdio:['pipe','pipe','pipe']});let stderr='',done=false;child.stderr.on('data',d=>stderr+=d);
for await(const line of createInterface({input:child.stdout})){
 const request=JSON.parse(line);if(request.done){checks+=request.checks;done=true;continue;}
 let n=0;try{const result=await q(request.sql.replace(/%s/g,()=>`$${++n}`),request.params);for(const row of result.rows)for(const f of result.fields??[])if(f.dataTypeID===20&&row[f.name]!==null)row[f.name]=Number(row[f.name]);child.stdin.write(JSON.stringify({rows:result.rows,fields:result.fields})+'\n');}catch(e){child.stdin.write(JSON.stringify({error:e.message})+'\n');}
}
assert.equal(await new Promise(resolve=>child.on('close',resolve)),0,stderr);assert(done,stderr);

assert(calls.length>callsBefore);checks++;
assert(!calls.slice(callsBefore).includes(x.run));checks++;
console.log('BOUNDED_CALLS '+JSON.stringify({freshClaimBusyCalls:calls.length-callsBefore,expectedWindows:reserved.expected_windows,legacyOriginIncluded:calls.includes(origin),unrelatedCalls:0}));
await q("UPDATE ops.set_runs SET status='private_resume_pending',source_metadata=$2 WHERE id=$1",[x.run,beforeClaim]);
await q('DELETE FROM ops.set_run_leases WHERE set_run_id=$1',[x.run]);


await reject("UPDATE ops.set_runs SET source_url='local:changed' WHERE id=$1",[x.run],/identity/);

await db.exec('ALTER TABLE ops.set_runs DISABLE TRIGGER yoon_version_write_guard');
await q("UPDATE ops.set_runs SET status='private_resume_running' WHERE id=$1",[origin]);
await db.exec('ALTER TABLE ops.set_runs ENABLE TRIGGER yoon_version_write_guard');
await reject('SELECT ops.assert_yoon_version_execution($1,\'admit\')',[x.run],/occupied/);
await reject("INSERT INTO ops.set_run_leases(set_run_id,slot_index,segment_start_index,segment_end_index,status) VALUES($1,0,0,0,'pending')",[x.run],/occupied/);
await db.exec('ALTER TABLE ops.set_runs DISABLE TRIGGER yoon_version_write_guard');
await q("UPDATE ops.set_runs SET status='private_resume_pending' WHERE id=$1",[origin]);
await db.exec('ALTER TABLE ops.set_runs ENABLE TRIGGER yoon_version_write_guard');
await q('UPDATE ops.yoon_versions SET processing_approved=false WHERE set_id=$1',[x.set]);
await reject('SELECT ops.assert_yoon_version_execution($1,\'admit\')',[x.run],/approved/);
await reject("UPDATE app.sets SET title='bad' WHERE id=$1",[x.set],/unapproved/);
await q('UPDATE ops.yoon_versions SET processing_approved=true WHERE set_id=$1',[x.set]);
await q("UPDATE ops.set_runs SET status='private_resume_running' WHERE id=$1",[ids[0].run]);
await reject('SELECT ops.assert_yoon_version_execution($1,\'admit\')',[x.run],/occupied/);
await q("UPDATE ops.set_runs SET status='private_resume_pending' WHERE id=$1",[ids[0].run]);
await q("UPDATE ops.set_runs SET status='private_resume_complete',source_metadata=source_metadata || $2::jsonb WHERE id=$1",[x.run,{yoon_resume:{status:'complete',expected_audio_sha256:'c'.repeat(64),audio_sha256:'c'.repeat(64),source_id:x.source},yoon_metadata_publication_v1:{status:'complete',run_id:x.run,target_set_id:x.set}}]);
await q("INSERT INTO ops.segment_hits(set_run_id,segment_index,timestamp_seconds,recognized,raw_data) SELECT $1,i,i*15,false,jsonb_build_object('private_jackson_v2',jsonb_build_object('valid',true,'in_flight',false,'response',jsonb_build_object('segment_index',i,'timestamp',i*15))) FROM generate_series(0,$2::integer-1) i",[x.run,reserved.expected_windows]);
await q("INSERT INTO app.set_entries(set_id,position,display_artist,display_title,start_time_seconds,confidence) VALUES($1,1,'Test','Track',0,'HIGH')",[x.set]);
const hash=async id=>(await q('SELECT ops.yoon_sha(ops.yoon_version_snapshot($1)) sha',[id])).rows[0].sha;
async function review(oldSet,newSet,oldHash,newHash){
 const doc={old_set_id:oldSet,new_set_id:newSet,old_snapshot_sha256:oldHash,new_snapshot_sha256:newHash,reviewer:'synthetic-reviewer',checks:Object.fromEntries(['independent_review','source_matched','ordered_windows','stable_derivative','import_complete','metadata_complete','timestamps_and_spans','audience_unchanged'].map(k=>[k,true]))};
 const sha=(await q('SELECT ops.yoon_sha($1::jsonb) sha',[doc])).rows[0].sha;
 await q('INSERT INTO ops.yoon_release_reviews(review_sha256,review) VALUES($1,$2)',[sha,doc]); return sha;
}
const old=await hash(ids[0].set),next=await hash(x.set), args=[ids[0].set,ids[0].set,0,x.set,old,next,await review(ids[0].set,x.set,old,next)];
await reject('SELECT ops.select_yoon_version($1,$2,$3,$4,$5,$6,$7)',[...args.slice(0,4),'e'.repeat(64),...args.slice(5)],/review|snapshot/);
await q('SELECT ops.select_yoon_version($1,$2,$3,$4,$5,$6,$7)',args);checks++;
assert.equal(await readable(ids[0].set,true),false);assert.equal(await readable(ids[0].set),true);assert.equal(await readable(x.set,true),true);checks+=3;
await reject('SELECT ops.select_yoon_version($1,$2,$3,$4,$5,$6,$7)',args,/cas/);
await reject("UPDATE app.sets SET title='bad' WHERE id=$1",[ids[0].set],/frozen/);
assert.equal(await hash(ids[0].set),old);checks++;
await q('SELECT ops.select_yoon_version($1,$2,1,$3,$4,$5,$6,true)',[ids[0].set,x.set,ids[0].set,next,old,await review(x.set,ids[0].set,next,old)]);checks++;
assert.equal(await readable(ids[0].set,true),true);checks++;
await db.exec(originalBusy);
await q("UPDATE ops.set_runs SET status='private_resume_running' WHERE id=$1",[ids[1].run]);checks++;
await reject('SELECT ops.select_yoon_version($1,$2,NULL,$3,$4,$5,$6,true)',[ids[0].set,ids[0].set,x.set,old,next,args[6]],/cas/);
await reject('DELETE FROM ops.yoon_version_history',[],/append/);
console.log(`PASS ${checks} bounded-family synthetic PostgreSQL checks, full migrations; no network or live data.`);await db.close();
