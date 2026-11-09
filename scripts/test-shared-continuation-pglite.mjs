// Synthetic actual migration/admission/retention SQL, never a connected database.
import { readFileSync, readdirSync } from 'node:fs';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
const pkg=process.env.PGLITE_PACKAGE_ROOT || '/tmp/dj-cancellation-pglite/node_modules/@electric-sql/pglite';
const {PGlite}=await import(pathToFileURL(resolve(pkg,'dist/index.js')).href);
const {pgcrypto}=await import(pathToFileURL(resolve(pkg,'dist/contrib/pgcrypto.js')).href);
const require=createRequire(resolve('apps/web/package.json'));

const db=new PGlite({extensions:{pgcrypto}});
await db.exec('CREATE ROLE set_list_worker');
for(const f of readdirSync('drizzle/migrations').filter(f=>/^\d.*\.sql$/.test(f)).sort()) await db.exec(readFileSync('drizzle/migrations/'+f,'utf8'));
await db.exec("INSERT INTO authn.users(id,email) VALUES('synthetic','synthetic@example.invalid'); INSERT INTO ops.submissions(id,requested_by,mode,status,visibility) VALUES('10000000-0000-4000-8000-000000000001','synthetic','set','queued','public')");
const id='20000000-0000-4000-8000-000000000001',now=Date.now()/1000;
const state={version:1,created_at:now,deadline:now+604800,continuations:1,requests:1,request_limit:16,geometry:{segment_count:2,segment_duration:30,segment_overlap:15},review_required:false,in_flight:false,paused:true,next_allowed_at:now-1};
const metadata=s=>({segment_count:2,shared_recognition:s});
const queries=JSON.parse(execFileSync(process.execPath,['--import',require.resolve('tsx'),'scripts/shared-continuation-queries.ts'],{encoding:'utf8',env:{...process.env,TSX_TSCONFIG_PATH:'apps/web/tsconfig.json',SHARED_FIXTURE_METADATA:JSON.stringify(metadata(state))}}));
await db.query("INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,publication_visibility,source_metadata) VALUES($1,'10000000-0000-4000-8000-000000000001','synthetic','queued','local:synthetic','public',$2)",[id,metadata(state)]);
let checks=0;
const blocker='20000000-0000-4000-8000-000000000002';
await db.query("INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,publication_visibility,source_metadata) VALUES($1,'10000000-0000-4000-8000-000000000001','synthetic','cancelled','local:blocker','public',$2)",[blocker,metadata({...state,in_flight:true})]);
assert.equal((await db.query('SELECT * FROM ops.claim_next_dispatchable_set_run(10)')).rows.length,0);checks++;
assert.equal((await db.query("SELECT ops.shared_recognition_dispatchable($1,'{}'::jsonb) AS ok",[id])).rows[0].ok,false);checks++;
await db.query("UPDATE ops.set_runs SET source_metadata=$2 WHERE id=$1",[blocker,metadata({...state,in_flight:true,in_flight_until:now-1})]);
assert.equal((await db.query('SELECT ops.shared_recognition_dispatchable($1,$2::jsonb) AS ok',[id,metadata(state)])).rows[0].ok,true);checks++;
assert.equal((await db.query('SELECT ops.shared_recognition_dispatchable($1,$2::jsonb) AS ok',[blocker,metadata({...state,in_flight:true,in_flight_until:now-1})])).rows[0].ok,false);checks++;
await db.query("INSERT INTO ops.segment_hits(set_run_id,segment_index,timestamp_seconds,raw_data) VALUES($1,0,0,$2)",[blocker,{shared_recognition:{version:1,valid:false,in_flight:true,attempts:[{expires_at:now-1}]}}]);
assert.equal((await db.query('SELECT ops.shared_recognition_dispatchable($1,$2::jsonb) AS ok',[id,metadata(state)])).rows[0].ok,true);checks++;
await db.query("UPDATE ops.segment_hits SET raw_data=$2 WHERE set_run_id=$1",[blocker,{shared_recognition:{version:1,valid:false,in_flight:true,attempts:[{expires_at:now+1000}]}}]);
assert.equal((await db.query('SELECT ops.shared_recognition_dispatchable($1,$2::jsonb) AS ok',[id,metadata(state)])).rows[0].ok,false);checks++;
// Synthetic operator reconciliation only, not an automatic application action.
await db.query("UPDATE ops.segment_hits SET raw_data=$2 WHERE set_run_id=$1",[blocker,{shared_recognition:{version:1,valid:false,in_flight:false,attempts:[{expires_at:now-1}]}}]);
await db.query("UPDATE ops.set_runs SET source_metadata=$2 WHERE id=$1",[blocker,metadata({...state,created_at:now-700000,deadline:now-1})]);
await db.query('DELETE FROM ops.segment_hits WHERE set_run_id=$1',[blocker]);
await db.query("UPDATE ops.set_runs SET source_metadata=$2 WHERE id=$1",[blocker,metadata(state)]);

const eligible=async s=>(await db.query('SELECT ops.shared_recognition_dispatchable($1,$2::jsonb) AS ok',[id,metadata(s)])).rows[0].ok;
assert.equal(await eligible(state),true);checks++;
for(const [requests,expected] of [[0,true],[1,false]]) {
  assert.equal((await db.query('SELECT ops.shared_recognition_dispatchable($1,$2::jsonb) AS ok',[id,{shared_recognition:{...state,requests,geometry:undefined,request_limit:8192}}])).rows[0].ok,expected);checks++;
}
for(const patch of [{next_allowed_at:now+1000},{review_required:true},{in_flight:true},{continuations:256},{requests:16},{deadline:now-1},{deadline:now+604801},{requests:'1'},{version:2},{continuations:-1},{reason:'window_attempt_budget'}]){assert.equal(await eligible({...state,...patch}),false,JSON.stringify(patch));checks++;}
await db.query("UPDATE ops.set_runs SET source_metadata=$2 WHERE id=$1",[id,metadata({...state,next_allowed_at:now+1000})]);
assert.equal((await db.query('SELECT * FROM ops.claim_next_dispatchable_set_run(10)')).rows.length,0);checks++;
await db.query("UPDATE ops.set_runs SET source_metadata=$2 WHERE id=$1",[id,metadata(state)]);
assert.equal((await db.query('SELECT * FROM ops.claim_next_dispatchable_set_run(10)')).rows.length,1);checks++;
// Admission has committed. Another run reserves before generation assignment.
await db.query("UPDATE ops.set_runs SET source_metadata=$2 WHERE id=$1",[blocker,metadata({...state,in_flight:true,in_flight_until:now+3665})]);
assert.equal((await db.query('SELECT ops.shared_recognition_dispatchable($1,$2::jsonb) AS ok',[id,metadata(state)])).rows[0].ok,false);checks++;
assert.equal((await db.query(queries.generationClaim.sql,queries.generationClaim.params)).rows.length,1);checks++;
assert.equal((await db.query('SELECT source_metadata FROM ops.set_runs WHERE id=$1',[id])).rows[0].source_metadata.dispatch_generation,'synthetic-generation');checks++;
await db.query("UPDATE ops.set_runs SET source_metadata=$2 WHERE id=$1",[blocker,metadata(state)]);
await db.query("INSERT INTO ops.set_run_leases(id,set_run_id,segment_start_index,segment_end_index,status) VALUES('30000000-0000-4000-8000-000000000001',$1,0,0,'completed')",[id]);
await db.query("INSERT INTO ops.segment_hits(set_run_id,segment_index,timestamp_seconds,raw_data,created_at) VALUES($1,0,0,$2,now()-interval '8 days')",[id,{shared_recognition:{version:1,valid:true,in_flight:false,response:{segment_index:0,timestamp:0,http_status:200,error_type:null,was_rate_limited:false,raw_data:{matches:[]}}}}]);
await db.query("INSERT INTO ops.segment_hits(set_run_id,segment_index,timestamp_seconds,raw_data) VALUES($1,1,15,$2)",[id,{shared_recognition:{version:1,valid:false,in_flight:false}}]);
assert.equal((await db.query(queries.validCount.sql,queries.validCount.params)).rows[0].n,1);checks++;
await db.query("UPDATE ops.segment_hits SET raw_data=$2 WHERE set_run_id=$1 AND segment_index=1",[id,{shared_recognition:{version:1,valid:true,in_flight:false,response:{segment_index:1,timestamp:15,http_status:200,error_type:null,was_rate_limited:false,raw_data:{matches:[]}}}}]);
assert.equal((await db.query(queries.validCount.sql,queries.validCount.params)).rows[0].n,2);checks++;
const malformed='20000000-0000-4000-8000-000000000003';
await db.query("INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,publication_visibility) VALUES($1,'10000000-0000-4000-8000-000000000001','synthetic','completed','local:malformed','public')",[malformed]);
await db.query("INSERT INTO ops.segment_hits(set_run_id,segment_index,timestamp_seconds,raw_data) VALUES($1,0,0,'{}')",[malformed]);
const goodResponse={segment_index:0,timestamp:0,http_status:200,error_type:null,was_rate_limited:false,raw_data:{matches:[]}};
for(const patch of [{timestamp:15},{http_status:500},{error_type:'transport'},{was_rate_limited:true},{segment_index:1},{raw_data:{}},{raw_data:{matches:[{}]}},{raw_data:{matches:[],track:null}}]) {
  await db.query('UPDATE ops.segment_hits SET raw_data=$2 WHERE set_run_id=$1',[malformed,{shared_recognition:{version:1,valid:true,in_flight:false,response:{...goodResponse,...patch}}}]);
  assert.equal((await db.query(queries.validCount.sql,queries.validCount.params)).rows[0].n,2,JSON.stringify(patch));checks++;
}
for(const [raw,expected] of [[{},0],[{matches:[]},1],[{matches:[{}]},0],[{matches:[],track:null},0],[{matches:[{}],track:{}},1]]) {
  await db.query('UPDATE ops.segment_hits SET raw_data=$2 WHERE set_run_id=$1',[malformed,raw]);
  assert.equal((await db.query(queries.legacyCount.sql,queries.legacyCount.params)).rows[0].n,expected);checks++;
}
await db.query('DELETE FROM ops.segment_hits WHERE set_run_id=$1',[malformed]);
for(const query of ['DELETE FROM ops.segment_hits','DELETE FROM ops.set_run_leases',"UPDATE ops.segment_hits SET raw_data='{}'"]){await assert.rejects(db.exec(query),/Shared recognition/);checks++;}
await db.query("UPDATE ops.set_runs SET heartbeat_at=now()-interval '2 hours',updated_at=now()-interval '2 hours' WHERE id=$1",[id]);
for(const name of ['staleLeases','staleRuns']) await db.query(queries[name].sql,queries[name].params);
assert.equal((await db.query('SELECT status FROM ops.set_runs WHERE id=$1',[id])).rows[0].status,'dispatched');checks++;
const requeued=await db.query(queries.requeue.sql,queries.requeue.params);assert.equal(requeued.rows.length,1);checks++;
assert.equal((await db.query('SELECT count(*)::integer AS n FROM ops.segment_hits')).rows[0].n,2);checks++;
assert.equal((await db.query('SELECT status FROM ops.set_run_leases')).rows[0].status,'completed');checks++;
assert.equal((await db.query('SELECT source_metadata FROM ops.set_runs WHERE id=$1',[id])).rows[0].source_metadata.active_workflow_run_id,'awaiting_dispatch');checks++;
await db.exec('SELECT ops.cleanup_expired_ops_data()');assert.equal((await db.query('SELECT count(*)::integer AS n FROM ops.segment_hits')).rows[0].n,2);checks++;
await db.query("UPDATE ops.set_runs SET source_metadata=$2 WHERE id=$1",[id,metadata({...state,created_at:now-700000,deadline:now-1})]);
await db.query(queries.staleRuns.sql,queries.staleRuns.params);
assert.equal((await db.query('SELECT status FROM ops.set_runs WHERE id=$1',[id])).rows[0].status,'failed');checks++;
await db.query("UPDATE ops.set_runs SET status='completed',source_metadata=$2 WHERE id=$1",[id,metadata({...state,created_at:now-700000,deadline:now-1})]);
await db.exec('SELECT ops.cleanup_expired_ops_data()');assert.equal((await db.query('SELECT count(*)::integer AS n FROM ops.segment_hits')).rows[0].n,1);checks++;
console.log(`PASS ${checks} shared continuation actual PostgreSQL checks`);await db.close();
