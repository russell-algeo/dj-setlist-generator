// Standalone synthetic role/default-ACL regression. No credentials or network calls.
import assert from 'node:assert/strict';
import {readFileSync,readdirSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {randomUUID} from 'node:crypto';
const pkg=process.env.PGLITE_PACKAGE_ROOT;
const {PGlite}=await import(pkg?pathToFileURL(resolve(pkg,'dist/index.js')).href:'@electric-sql/pglite');
const {pgcrypto}=await import(pkg?pathToFileURL(resolve(pkg,'dist/contrib/pgcrypto.js')).href:'@electric-sql/pglite/contrib/pgcrypto');
const migrations=new URL('../drizzle/migrations/',import.meta.url);
const migration=readFileSync(new URL('0024_yoon_version_registry.sql',migrations),'utf8');
const marker='-- Finite new-object ACL seal';
assert.equal(migration.split(marker).length,2);
const base=migration.slice(0,migration.indexOf(marker)),seal=migration.slice(migration.indexOf(marker));
const scope={"originalSha256": "2a2e380515d2b930fa90e8be5b7252bbbea3c675ff231686539991707fc56c67", "tables": ["ops.yoon_reserved_versions", "ops.yoon_version_collections", "ops.yoon_version_families", "ops.yoon_versions", "ops.yoon_release_reviews", "ops.yoon_version_history"], "functions": ["ops.yoon_sha(jsonb)", "ops.yoon_audience(uuid)", "ops.yoon_source_fingerprint(uuid)", "ops.yoon_media_fingerprint(uuid)", "ops.yoon_collection_scope(uuid)", "ops.yoon_is_v2(jsonb)", "app.yoon_version_readable(uuid,boolean)", "app.yoon_submission_version_readable(uuid)", "ops.yoon_registry_lock()", "ops.yoon_run_busy(uuid)", "ops.assert_yoon_version_identity(uuid)", "ops.assert_yoon_version_execution(uuid,text,text)", "ops.yoon_version_snapshot(uuid)", "ops.yoon_immutable_registry()", "ops.yoon_registration_check()", "ops.yoon_mutation_guard()", "ops.yoon_bootstrap_check()", "ops.yoon_audience_guard()", "ops.select_yoon_version(uuid,uuid,bigint,uuid,text,text,text,boolean)", "ops.initialize_yoon_version_execution(uuid)", "ops.yoon_selection_receipt_check()", "ops.yoon_release_receipt_check()"], "readFunctions": ["app.yoon_version_readable(uuid,boolean)", "app.yoon_submission_version_readable(uuid)", "ops.yoon_collection_scope(uuid)", "ops.yoon_is_v2(jsonb)"], "workerFunctions": ["ops.yoon_sha(jsonb)", "ops.yoon_audience(uuid)", "ops.yoon_source_fingerprint(uuid)", "ops.yoon_media_fingerprint(uuid)", "ops.yoon_registry_lock()", "ops.yoon_run_busy(uuid)", "ops.assert_yoon_version_identity(uuid)", "ops.assert_yoon_version_execution(uuid,text,text)"], "roles": ["set_list_worker", "set_list_dev_worker", "set_list_dev_app"], "existingObjectsChanged": false, "defaultAclsChanged": false};
let checks=0;const eq=(a,b)=>{assert.deepEqual(a,b);checks++};
for(const devRoles of [false,true]){
 const db=new PGlite({extensions:{pgcrypto}}),q=(sql,p=[])=>db.query(sql,p);
 try{
 await db.exec('CREATE ROLE set_list_worker; CREATE ROLE neondb_owner');
 for(const f of readdirSync(migrations).filter(f=>/^\d.*\.sql$/.test(f)&&!f.startsWith('0024_')).sort())await db.exec(readFileSync(new URL(f,migrations),'utf8'));
 await db.exec(`GRANT ALL ON SCHEMA ops,app,authn TO neondb_owner;
 GRANT ALL ON ALL TABLES IN SCHEMA ops,app,authn TO neondb_owner;
 GRANT ALL ON ALL SEQUENCES IN SCHEMA ops,app,authn TO neondb_owner;
 GRANT USAGE ON SCHEMA ops,app,authn TO set_list_worker;
 GRANT SELECT,REFERENCES ON ALL TABLES IN SCHEMA app TO set_list_worker;
 GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA ops TO set_list_worker`);
 if(devRoles){await db.exec(`CREATE ROLE set_list_dev_worker; CREATE ROLE set_list_dev_app;
 GRANT USAGE ON SCHEMA ops,app,authn TO set_list_dev_worker,set_list_dev_app;
 GRANT SELECT,REFERENCES ON ALL TABLES IN SCHEMA app TO set_list_dev_worker;
 GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA ops TO set_list_dev_worker;
 GRANT SELECT ON ALL TABLES IN SCHEMA app,ops TO set_list_dev_app;
 ALTER DEFAULT PRIVILEGES FOR ROLE neondb_owner IN SCHEMA ops GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO set_list_dev_worker,set_list_dev_app;
 ALTER DEFAULT PRIVILEGES FOR ROLE neondb_owner IN SCHEMA ops GRANT EXECUTE ON FUNCTIONS TO set_list_dev_worker,set_list_dev_app;
 ALTER DEFAULT PRIVILEGES FOR ROLE neondb_owner IN SCHEMA app GRANT EXECUTE ON FUNCTIONS TO set_list_dev_worker,set_list_dev_app;`);
 for(const role of ['set_list_dev_worker','set_list_dev_app'])eq((await q("SELECT pg_has_role($1,'set_list_worker','MEMBER') x",[role])).rows[0].x,false);
 }
 const acl=async()=>({tables:(await q("SELECT c.oid,c.relacl::text FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('app','ops','authn') ORDER BY c.oid")).rows,functions:(await q("SELECT p.oid,p.proacl::text FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN ('app','ops','authn') ORDER BY p.oid")).rows,defaults:(await q('SELECT oid,defaclacl::text FROM pg_default_acl ORDER BY oid')).rows});
 const before=await acl();
 await db.exec('BEGIN; SET LOCAL ROLE neondb_owner');
 await db.exec(base);
 if(devRoles)for(const role of ['set_list_dev_worker','set_list_dev_app']){
 eq((await q("SELECT has_table_privilege($1,'ops.yoon_versions','UPDATE') x",[role])).rows[0].x,true);
 eq((await q("SELECT has_function_privilege($1,'ops.initialize_yoon_version_execution(uuid)','EXECUTE') x",[role])).rows[0].x,true);
 }
 await db.exec(seal);await db.exec('COMMIT');
 const after=await acl();eq(after.defaults,before.defaults);
 for(const kind of ['tables','functions'])for(const row of before[kind])eq(after[kind].find(x=>x.oid===row.oid),row);
 const roles=devRoles?scope.roles:['set_list_worker'];
 for(const role of roles){
 for(const table of scope.tables)for(const privilege of ['INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER'])eq((await q('SELECT has_table_privilege($1,$2,$3) x',[role,table,privilege])).rows[0].x,false);
 for(const table of ['ops.yoon_version_history','ops.yoon_release_reviews'])eq((await q("SELECT has_table_privilege($1,$2,'SELECT') x",[role,table])).rows[0].x,false);
 for(const column of ['bootstrap_manifest','bootstrap_sha256'])eq((await q("SELECT has_column_privilege($1,'ops.yoon_version_collections',$2,'SELECT') x",[role,column])).rows[0].x,false);
 const appColumns={'ops.yoon_reserved_versions':['set_id','submission_id'],'ops.yoon_versions':['set_id','submission_id','logical_set_id','collection_id','released'],'ops.yoon_version_families':['logical_set_id','selected_set_id'],'ops.yoon_version_collections':['collection_id']};
 for(const table of scope.tables){
  const columns=(await q('SELECT attname FROM pg_attribute WHERE attrelid=$1::regclass AND attnum>0 AND NOT attisdropped',[table])).rows.map(x=>x.attname);
  for(const column of columns){const allowed=role==='set_list_dev_app'?(appColumns[table]??[]).includes(column):(['ops.yoon_reserved_versions','ops.yoon_versions','ops.yoon_version_families'].includes(table)||(table==='ops.yoon_version_collections'&&['collection_id','audience_sha256'].includes(column)));eq((await q("SELECT has_column_privilege($1,$2,$3,'SELECT') x",[role,table,column])).rows[0].x,allowed);}
 }
 const allow=scope.readFunctions.concat(role==='set_list_dev_app'?[]:scope.workerFunctions);
 for(const fn of scope.functions)eq((await q("SELECT has_function_privilege($1,$2,'EXECUTE') x",[role,fn])).rows[0].x,allow.includes(fn));
 for(const privilege of ['INSERT','UPDATE','DELETE'])eq((await q("SELECT has_table_privilege($1,'app.set_entries',$2) x",[role,privilege])).rows[0].x,false);
 }
 eq((await q("SELECT rolname FROM pg_roles WHERE rolname IN ('set_list_dev_worker','set_list_dev_app') ORDER BY rolname")).rows.map(r=>r.rolname),devRoles?['set_list_dev_app','set_list_dev_worker']:[]);
 // Reapplication does not change any permissions or defaults.
 const sealed=await acl();await db.exec('BEGIN; SET LOCAL ROLE neondb_owner');await db.exec(seal);await db.exec('COMMIT');eq(await acl(),sealed);
 // Entirely synthetic private archive: gate supplements existing membership.
 const collection=randomUUID(),set=randomUUID(),sub=randomUUID(),run=randomUUID();
 await q("INSERT INTO authn.users(id,email) VALUES('synthetic-owner','owner@example.invalid'),('synthetic-viewer','viewer@example.invalid')");
 await q("INSERT INTO app.archive_collections(id,slug,title) VALUES($1,'synthetic-archive','Synthetic')",[collection]);
 await q("INSERT INTO app.archive_collection_members(collection_id,user_id,role) VALUES($1,'synthetic-owner','manager'),($1,'synthetic-viewer','viewer')",[collection]);
 await q("INSERT INTO app.sets(id,slug,title,normalized_title,visibility,collection_id) VALUES($1,'synthetic-only','Synthetic','synthetic','private',$2)",[set,collection]);
 await q("INSERT INTO ops.submissions(id,requested_by,mode,status,visibility,collection_id) VALUES($1,'synthetic-owner','set','private_resume_pending','private',$2)",[sub,collection]);
 await q("INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,publication_visibility,target_set_id,collection_id) VALUES($1,$2,'synthetic-owner','private_resume_pending','synthetic:fixture','private',$3,$4)",[run,sub,set,collection]);
 for(const role of roles){
 await db.exec('SET ROLE '+role);
 for(const [user,allowed] of [['synthetic-owner',true],['synthetic-viewer',true],['synthetic-outsider',false]])eq((await q('SELECT app.yoon_version_readable(s.id,false) AND EXISTS(SELECT 1 FROM app.archive_collection_members m WHERE m.collection_id=s.collection_id AND m.user_id=$2) x FROM app.sets s WHERE s.id=$1',[set,user])).rows[0].x,allowed);
 eq((await q('SELECT app.yoon_submission_version_readable($1) x',[sub])).rows[0].x,true);
 if(role!=='set_list_dev_app'){await q("SELECT ops.assert_yoon_version_execution($1,'metadata',NULL)",[run]);checks++;}
 for(const statement of ['SELECT * FROM ops.yoon_version_history','DELETE FROM ops.yoon_versions WHERE false',"SELECT ops.initialize_yoon_version_execution('11111111-1111-4111-8111-111111111111')","UPDATE app.set_entries SET metadata=metadata WHERE false"]){await assert.rejects(()=>q(statement),e=>e.code==='42501');checks++;}
 await db.exec('RESET ROLE');
 }
 console.log(JSON.stringify({status:'PASS',configuration:devRoles?'noninheriting-development-defaults':'generic-worker-only',cumulativeChecks:checks}));
 }finally{await db.close();}
}
console.log(`PASS ${checks} synthetic ACL/default-role checks. No live actions.`);
