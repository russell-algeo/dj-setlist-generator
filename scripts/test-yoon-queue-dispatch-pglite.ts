import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { readFileSync, readdirSync } from "node:fs";
import assert from "node:assert/strict";
import { PgDialect } from "drizzle-orm/pg-core";
import { buildPrivateYoonDispatchClaim } from "../apps/web/lib/jobs/private-yoon-dispatch-query";

async function main() {
  const pkg = process.env.PGLITE_PACKAGE_ROOT;
  const { PGlite } = await import(pkg ? pathToFileURL(resolve(pkg, "dist/index.js")).href : "@electric-sql/pglite");
  const { pgcrypto } = await import(pkg ? pathToFileURL(resolve(pkg, "dist/contrib/pgcrypto.js")).href : "@electric-sql/pglite/contrib/pgcrypto");
  const db = new PGlite({ extensions: { pgcrypto } });
  await db.exec("CREATE ROLE set_list_worker");
  for (const file of readdirSync("drizzle/migrations").filter(f => /^\d.*\.sql$/.test(f)).sort()) await db.exec(readFileSync("drizzle/migrations/" + file, "utf8"));
  const collection = "20000000-0000-4000-8000-000000000001", target = "10000000-0000-4000-8000-000000000001", submission = "30000000-0000-4000-8000-000000000001", setRunId = "a0000000-0000-4000-8000-000000000010", generation = "a0000000-0000-4000-8000-000000000020";
  await db.exec("INSERT INTO authn.users(id,email) VALUES('synthetic-owner','owner@example.invalid'),('synthetic-viewer','viewer@example.invalid')");
  await db.query("INSERT INTO app.archive_collections(id,slug,title) VALUES($1,'yoon-fest','Synthetic')", [collection]);
  await db.query("INSERT INTO app.archive_collection_members(collection_id,user_id,role) VALUES($1,'synthetic-owner','manager'),($1,'synthetic-viewer','viewer')", [collection]);
  await db.query("INSERT INTO app.sets(id,slug,title,normalized_title,visibility,collection_id) VALUES($1,'synthetic','Synthetic','synthetic','private',$2)", [target, collection]);
  await db.query("INSERT INTO ops.submissions(id,requested_by,mode,status,visibility,collection_id) VALUES($1,'synthetic-owner','set','private_analysis_pending','private',$2)", [submission, collection]);
  const identity = { id: setRunId, submission_id: submission, target_set_id: target, collection_id: collection, requested_by: "synthetic-owner", descriptor: { synthetic: true }, members: [{ user_id: "synthetic-owner", role: "manager" }, { user_id: "synthetic-viewer", role: "viewer" }] };
  const metadata = { yoon_fixed_input: identity.descriptor, yoon_resume: {}, yoon_queue_v1: { version: 1, status: "reserved", generation, identity } };
  await db.query("INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,publication_visibility,target_set_id,collection_id,source_metadata) VALUES($1,$2,'synthetic-owner','private_resume_pending','local:synthetic','private',$3,$4,$5)", [setRunId, submission, target, collection, metadata]);
  const dialect = new PgDialect();
  const claim = async (input = { setRunId, generation }) => { const q = dialect.sqlToQuery(buildPrivateYoonDispatchClaim(input)); return (await db.query(q.sql, q.params)).rows.length; };
  const reset = () => db.query("UPDATE ops.set_runs SET source_metadata=$2,publication_visibility='private',cancel_requested_at=null,status='private_resume_pending' WHERE id=$1", [setRunId, metadata]);
  let checks = 0;
  const check = (value: boolean) => { assert(value); checks++; };
  check(await claim({ setRunId, generation: target }) === 0);
  check(await claim() === 1); check(await claim() === 0);
  await reset();
  await assert.rejects(db.query("UPDATE ops.set_runs SET publication_visibility='public' WHERE id=$1", [setRunId])); checks++;
  for (const change of ["cancel_requested_at=now()", "status='private_resume_running'", "source_metadata=jsonb_set(source_metadata,'{yoon_fixed_input}','{}')", "source_metadata=jsonb_set(source_metadata,'{yoon_resume,review_required}','true')"]) {
    await db.query("UPDATE ops.set_runs SET " + change + " WHERE id=$1", [setRunId]);
    check(await claim() === 0); await reset();
  }
  await db.exec("UPDATE app.archive_collection_members SET role='viewer' WHERE user_id='synthetic-owner'"); check(await claim() === 0);
  await db.exec("UPDATE app.archive_collection_members SET role='manager' WHERE user_id='synthetic-owner'");
  await db.query("UPDATE ops.submissions SET cancel_requested_at=now() WHERE id=$1", [submission]); check(await claim() === 0);
  await db.query("UPDATE ops.submissions SET cancel_requested_at=null WHERE id=$1", [submission]);
  await db.query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_queue_v1,status}','\"queued\"') WHERE id=$1", [setRunId]);
  const rollover = async (workflowRunId: string, runAttempt = "1") => { const q = dialect.sqlToQuery(buildPrivateYoonDispatchClaim({ setRunId, controller: true, workflowRunId, runAttempt })); return (await db.query(q.sql, q.params)).rows.length; };
  check(await rollover("9001") === 1); check(await rollover("9001") === 0); check(await rollover("9000") === 0); check(await rollover("9001", "2") === 1); check(await rollover("9002") === 1);
  console.log(`PASS ${checks} actual TypeScript private dispatch PostgreSQL fences; synthetic data, no network.`);
  await db.close();
}
main().catch(error => { console.error(error); process.exitCode = 1; });
