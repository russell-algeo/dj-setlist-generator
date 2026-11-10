"""Actual credential-free enqueue compiler through the synthetic PGlite bridge."""
from pathlib import Path
exec((Path(__file__).with_name('test_yoon_resume_pg.py')).read_text().split("RUN='a0000000")[0])
import copy
from worker.jobs.yoon_queue_enqueue import snapshot_sql, compile_enqueue
from worker.jobs.yoon_queue import KEY
RUN='a0000000-0000-4000-8000-000000000010'
ids=[RUN]
for i in (11,12,13):
    run=f'a0000000-0000-4000-8000-{i:012d}';target=f'10000000-0000-4000-8000-{i:012d}'
    query("INSERT INTO app.sets(id,slug,title,normalized_title,visibility,collection_id) SELECT %s,%s,title,normalized_title,visibility,collection_id FROM app.sets WHERE id='10000000-0000-4000-8000-000000000001'",(target,'compiler-'+str(i)))
    query("""INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,publication_visibility,target_set_id,collection_id,source_metadata)
        SELECT %s,submission_id,requested_by,status,source_url,publication_visibility,%s,collection_id,source_metadata FROM ops.set_runs WHERE id=%s""",(run,target,RUN))
    ids.append(run)
def rows():
    with connect():return query(snapshot_sql(ids))
def queued_count():
    return query("SELECT count(*) AS n FROM ops.set_runs WHERE id=ANY(%s::uuid[]) AND source_metadata ? 'yoon_queue_v1'",(ids,))[0]['n']
def execute(sql):
    with connect():query(sql)
snapshot=rows();check(len(snapshot)==4)
compiled=compile_enqueue(snapshot,ids)
check('dropbox' not in compiled and 'https://' not in compiled)
check(compiled.index('pg_advisory_xact_lock')<compiled.index('FOR UPDATE OF r,u'))
check("current_setting('transaction_isolation')" in compiled)
denies(lambda:compile_enqueue(snapshot[:-1],ids))
denies(lambda:compile_enqueue(snapshot,[*ids,RUN]))
wrong=copy.deepcopy(snapshot);wrong[0]['current_members']=wrong[0]['current_members'][:1]
denies(lambda:compile_enqueue(wrong,ids))
wrong=copy.deepcopy(snapshot);wrong[1]['target_set_id']=wrong[0]['target_set_id']
denies(lambda:compile_enqueue(wrong,ids))
wrong=copy.deepcopy(snapshot);wrong[0]['source_metadata']['yoon_fixed_input']['source_bytes']=1
denies(lambda:compile_enqueue(wrong,ids))
# A later ineligible row aborts the whole one-statement transaction, not just
# itself. Earlier loop iterations must not leave a partially enqueued batch.
query("UPDATE ops.set_runs SET status='private_resume_running' WHERE id=%s",(ids[2],))
denies(lambda:execute(compiled));check(queued_count()==0)
query("UPDATE ops.set_runs SET status='private_resume_pending' WHERE id=%s",(ids[2],))
# Drift after reviewed snapshot: membership, cancellation, descriptor and state.
query("UPDATE app.archive_collection_members SET role='viewer' WHERE user_id='synthetic-owner'")
denies(lambda:execute(compiled));check(queued_count()==0)
query("UPDATE app.archive_collection_members SET role='manager' WHERE user_id='synthetic-owner'")
query('UPDATE ops.set_runs SET cancel_requested_at=now() WHERE id=%s',(ids[1],))
denies(lambda:execute(compiled));check(queued_count()==0)
query('UPDATE ops.set_runs SET cancel_requested_at=null WHERE id=%s',(ids[1],))
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_fixed_input,source_url}','\"https://www.dropbox.com/synthetic-changed\"') WHERE id=%s",(ids[1],))
denies(lambda:execute(compiled));check(queued_count()==0)
query('UPDATE ops.set_runs SET source_metadata=%s::jsonb WHERE id=%s',(json.dumps(snapshot[1]['source_metadata']),ids[1]))
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_resume,requests}','1') WHERE id=%s",(ids[1],))
denies(lambda:execute(compiled));check(queued_count()==0)
query('UPDATE ops.set_runs SET source_metadata=%s::jsonb WHERE id=%s',(json.dumps(snapshot[1]['source_metadata']),ids[1]))
execute(compiled);check(queued_count()==4)
# Exact retries are no-ops, including a later legitimate active owner. They
# cannot reset metadata, generation, ownership, statuses or updated_at.
query("UPDATE ops.set_runs SET status='private_resume_running',source_metadata=jsonb_set(source_metadata,'{yoon_resume,workflow_run_id}','\"9001\"') WHERE id=%s",(RUN,))
before=query('SELECT row_to_json(r)::text AS row FROM ops.set_runs r WHERE id=ANY(%s::uuid[]) ORDER BY id',(ids,))
execute(compiled)
check(query('SELECT row_to_json(r)::text AS row FROM ops.set_runs r WHERE id=ANY(%s::uuid[]) ORDER BY id',(ids,))==before)
execute(compile_enqueue(rows(),ids))
check(query('SELECT row_to_json(r)::text AS row FROM ops.set_runs r WHERE id=ANY(%s::uuid[]) ORDER BY id',(ids,))==before)
# A second run cannot enqueue a previously opted-in target under a new identity.
dup='a0000000-0000-4000-8000-000000000099'
query("""INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,publication_visibility,target_set_id,collection_id,source_metadata)
    SELECT %s,submission_id,requested_by,'private_resume_pending',source_url,publication_visibility,target_set_id,collection_id,source_metadata-'yoon_queue_v1'
    FROM ops.set_runs WHERE id=%s""",(dup,ids[1]))
with connect():duplicate_snapshot=query(snapshot_sql([dup]))
denies(lambda:execute(compile_enqueue(duplicate_snapshot,[dup])))
check(query("SELECT source_metadata ? 'yoon_queue_v1' AS queued FROM ops.set_runs WHERE id=%s",(dup,))[0]['queued'] is False)
# Existing same-id entries cannot be overwritten if their identity has drifted.
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_queue_v1,identity,requested_by}','\"changed\"') WHERE id=%s",(ids[3],))
malformed_before=query('SELECT row_to_json(r)::text AS row FROM ops.set_runs r WHERE id=%s',(ids[3],))[0]['row']
denies(lambda:execute(compiled))
check(query('SELECT row_to_json(r)::text AS row FROM ops.set_runs r WHERE id=%s',(ids[3],))[0]['row']==malformed_before)
check(query("SELECT status FROM ops.set_runs WHERE id='40000000-0000-4000-8000-000000000099'")[0]['status']=='completed')
print(json.dumps({'done':True,'checks':checks}),file=sys.__stdout__,flush=True)
