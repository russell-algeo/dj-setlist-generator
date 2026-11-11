"""Actual private queue + admission + ResumeStore over the synthetic PGlite bridge."""
# Reuse the bridge definitions only, without executing the resume test scenarios.
from pathlib import Path
exec((Path(__file__).with_name('test_yoon_resume_pg.py')).read_text().split("RUN='a0000000")[0])
import copy, os, io, contextlib
from worker.jobs.yoon_queue import PrivateQueue, identity, KEY
from worker.jobs import yoon_admission as admission
RUN='a0000000-0000-4000-8000-000000000010'
queue=PrivateQueue(connect=connect)
def manifest(run=RUN):
    with queue.store(run).locked(owner=False) as (_,row,state):return identity(row,state)
def saved(run=RUN):
    return query('SELECT status,source_metadata FROM ops.set_runs WHERE id=%s',(run,))[0]
def state_patch(values):
    query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_resume}',source_metadata->'yoon_resume'||%s::jsonb) WHERE id=%s",(json.dumps(values),RUN))
original=copy.deepcopy(saved()['source_metadata'])
manifest1=manifest()
bad=copy.deepcopy(manifest1);bad['members'][0]['role']='viewer'
denies(lambda:queue.enqueue([bad]));check(KEY not in saved()['source_metadata'])
duplicate=copy.deepcopy(manifest1);duplicate['id']='a0000000-0000-4000-8000-000000000099'
denies(lambda:queue.enqueue([manifest1,duplicate]))
check(KEY not in saved()['source_metadata'])
check(queue.enqueue([manifest1])['queued']==1)
# An opted-in target cannot later enter under another run identity.
query('''INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,publication_visibility,target_set_id,collection_id,source_metadata)
    SELECT %s,submission_id,requested_by,status,source_url,publication_visibility,target_set_id,collection_id,source_metadata-'yoon_queue_v1'
    FROM ops.set_runs WHERE id=%s''',(duplicate['id'],RUN))
denies(lambda:queue.enqueue([duplicate]))
check(queue.enqueue([manifest1])['existing']==1)
# Every opted-in malformed record must block startup instead of disappearing
# from the status-filtered work list and falsely completing an empty queue.
queued_snapshot=copy.deepcopy(saved()['source_metadata'])
valid_queue=queued_snapshot[KEY]
malformed=[None, [], 'invalid', {**valid_queue,'version':2}, {**valid_queue,'version':True},
           {**valid_queue,'status':'garbage'}, {**valid_queue,'status':None},
           {k:v for k,v in valid_queue.items() if k!='status'},
           {**valid_queue,'status':'complete'},
           {**valid_queue,'status':'reserved','generation':None},
           {**valid_queue,'status':'running','generation':str(uuid.uuid4()),'owner':None}]
for broken in malformed:
    metadata=copy.deepcopy(queued_snapshot);metadata[KEY]=broken
    query('UPDATE ops.set_runs SET source_metadata=%s::jsonb WHERE id=%s',(json.dumps(metadata),RUN))
    before=saved();called=[]
    check(RUN in queue.blocked_ids())
    report=PrivateQueue(connect=connect).tick(lambda payload:called.append(payload))
    check(report['blocked']==1 and report['reserved']==0)
    check(called==[] and saved()==before)
query('UPDATE ops.set_runs SET source_metadata=%s::jsonb WHERE id=%s',(json.dumps(queued_snapshot),RUN))
# Known budget pauses are eligible only for coverage-only completion. With
# incomplete evidence they cannot get a reservation or fall into worker claim.
for reason in ('lifetime_time_budget','lifetime_request_budget','continuation_budget','window_attempt_budget'):
    metadata=copy.deepcopy(queued_snapshot);metadata['yoon_resume'].update(reason=reason,review_required=False)
    query("UPDATE ops.set_runs SET status='private_resume_paused',source_metadata=%s::jsonb WHERE id=%s",(json.dumps(metadata),RUN))
    called=[];report=queue.tick(lambda payload:called.append(payload))
    check(report['blocked']==1 and report['reserved']==0 and called==[])
    check(saved()['status']=='private_resume_paused' and saved()['source_metadata'][KEY]['status']=='blocked')
    check(saved()['source_metadata']['yoon_resume']==metadata['yoon_resume'])
    generation=str(uuid.uuid4());metadata[KEY].update(status='reserved',generation=generation,owner=None)
    query('UPDATE ops.set_runs SET source_metadata=%s::jsonb WHERE id=%s',(json.dumps(metadata),RUN))
    os.environ['SET_LIST_DISPATCH_GENERATION']=generation
    before=saved();denies(lambda:ResumeStore(RUN,'9088','1',connect=connect).finalize_ready())
    check(saved()==before and RUN in queue.blocked_ids())
query("UPDATE ops.set_runs SET status='private_resume_pending',source_metadata=%s::jsonb WHERE id=%s",(json.dumps(queued_snapshot),RUN))
os.environ.pop('SET_LIST_DISPATCH_GENERATION',None)
# Membership/source/cancellation changes are fenced before reserve.
query("UPDATE app.archive_collection_members SET role='viewer' WHERE user_id='synthetic-owner'")
denies(lambda:queue.refresh_and_reserve(RUN))
query("UPDATE app.archive_collection_members SET role='manager' WHERE user_id='synthetic-owner'")
query('UPDATE ops.set_runs SET cancel_requested_at=now() WHERE id=%s',(RUN,))
denies(lambda:queue.refresh_and_reserve(RUN));check(queue.ids()==[])
query('UPDATE ops.set_runs SET cancel_requested_at=null WHERE id=%s',(RUN,))
state_patch({'next_allowed_at':9999999999})
check(queue.refresh_and_reserve(RUN) is None)
check(saved()['source_metadata'][KEY]['status']=='queued')
state_patch({'next_allowed_at':0})
reservation=queue.refresh_and_reserve(RUN);check(bool(reservation['generation']))
check(queue.refresh_and_reserve(RUN) is None)
# Two additional target identities. No network or source files are involved.
other=[]
for i in (11,12):
    run=f'a0000000-0000-4000-8000-{i:012d}';target=f'10000000-0000-4000-8000-{i:012d}'
    query("INSERT INTO app.sets(id,slug,title,normalized_title,visibility,collection_id) SELECT %s,%s,title,normalized_title,visibility,collection_id FROM app.sets WHERE id=%s",(target,'synthetic-'+str(i),manifest1['target_set_id']))
    query("""INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,publication_visibility,target_set_id,collection_id,source_metadata)
        SELECT %s,submission_id,requested_by,'private_resume_pending',source_url,publication_visibility,%s,collection_id,source_metadata-'yoon_queue_v1'
        FROM ops.set_runs WHERE id=%s""",(run,target,RUN))
    queue.enqueue([manifest(run)]);other.append(run)
res2=queue.refresh_and_reserve(other[0]);check(bool(res2))
denies(lambda:queue.refresh_and_reserve(other[1]))
# Reservation counts immediately, and cannot be stolen by direct/manual workers.
s=ResumeStore(RUN,'9001','1',connect=connect)
denies(s.claim)
os.environ['SET_LIST_DISPATCH_GENERATION']=str(uuid.uuid4());denies(s.claim)
os.environ['SET_LIST_DISPATCH_GENERATION']=reservation['generation']
s.claim();check(saved()['source_metadata'][KEY]['owner']==s.owner)
check(saved()['source_metadata'][KEY]['status']=='running')
denies(s.claim)
other_owner=ResumeStore(RUN,'9002','1',connect=connect);denies(other_owner.claim)
check(query("SELECT count(*) AS n FROM ops.segment_hits WHERE set_run_id=%s",(RUN,))[0]['n']==4)
# Existing successful windows survive all queue transitions. Clean throttle
# pause cannot be picked up until both run and individual windows are due.
plan=s.prepare_scheduler();ticket=s.reserve(4)
check(RUN not in queue.blocked_ids())  # genuinely running owned work may hold requests
# A real running receipt has many progress fields beyond its two-field owner.
# It must occupy one slot, not block all future admissions as an uncertain owner.
active_before=copy.deepcopy(saved())
others_before={run:copy.deepcopy(saved(run)) for run in other}
evidence_before=query('SELECT row_to_json(h)::text AS row FROM ops.segment_hits h WHERE set_run_id=%s ORDER BY segment_index',(RUN,))
leases_before=query('SELECT row_to_json(l)::text AS row FROM ops.set_run_leases l WHERE set_run_id=%s ORDER BY segment_start_index',(RUN,))
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_queue_v1,status}','\"queued\"') WHERE id=%s",(other[0],))
sent=[];report=queue.tick(lambda payload:sent.append(payload))
check(report=={'pending':3,'reserved':1,'blocked':0} and len(sent)==1)
check(saved()==active_before)
check(query('SELECT row_to_json(h)::text AS row FROM ops.segment_hits h WHERE set_run_id=%s ORDER BY segment_index',(RUN,))==evidence_before)
check(query('SELECT row_to_json(l)::text AS row FROM ops.set_run_leases l WHERE set_run_id=%s ORDER BY segment_start_index',(RUN,))==leases_before)
check(queue.tick(lambda payload:sent.append(payload))=={'pending':3,'reserved':0,'blocked':0})
check(len(sent)==1)  # one active worker + one reservation fills cap two
remaining=next(run for run in other if saved(run)['source_metadata'][KEY]['status']=='queued')
try:queue.refresh_and_reserve(remaining)
except RuntimeError as exc:check(str(exc)=='private_admission_capacity')
else:raise AssertionError('expected capacity, not uncertainty or another reservation')
# Malformed or mismatched queue identities remain fail-closed even when the
# worker's actual resume receipt and per-window evidence still look valid.
for owner in (None,{},[],{'workflow_run_id':'9999','run_attempt':'1'},
              {'workflow_run_id':'9001','run_attempt':'2'},
              {'workflow_run_id':9001,'run_attempt':'1'}):
    metadata=copy.deepcopy(active_before['source_metadata']);metadata[KEY]['owner']=owner
    query('UPDATE ops.set_runs SET source_metadata=%s::jsonb WHERE id=%s',(json.dumps(metadata),RUN))
    before_bad=saved();called=[]
    check(queue.tick(lambda payload:called.append(payload))=={'pending':3,'reserved':0,'blocked':1})
    check(called==[] and saved()==before_bad)
    denies(lambda:queue.refresh_and_reserve(remaining))
    check(saved()==before_bad)
query('UPDATE ops.set_runs SET source_metadata=%s::jsonb WHERE id=%s',(json.dumps(active_before['source_metadata']),RUN))
for run,before in others_before.items():
    query('UPDATE ops.set_runs SET source_metadata=%s::jsonb WHERE id=%s',(json.dumps(before['source_metadata']),run))
check(saved()==active_before)
r=Recognition(60,None,None,None,None,False,4,was_rate_limited=True,error_type='RateLimited',http_status=429)
s.finish(r,ticket,60);s.release('workflow_interrupted')
check(queue.refresh_and_reserve(RUN) is None)
check(saved()['source_metadata'][KEY]['status']=='queued')
state_patch({'next_allowed_at':0})
check(queue.refresh_and_reserve(RUN) is None)  # individual window due survives
query("UPDATE ops.segment_hits SET raw_data=jsonb_set(raw_data,'{private_jackson_v2,next_allowed_at}','0') WHERE set_run_id=%s",(RUN,))
res3=queue.refresh_and_reserve(RUN);check(res3['generation']!=reservation['generation'])
os.environ['SET_LIST_DISPATCH_GENERATION']=reservation['generation'];denies(other_owner.claim)
os.environ['SET_LIST_DISPATCH_GENERATION']=res3['generation'];other_owner.claim()
check(query("SELECT count(*) AS n FROM ops.segment_hits WHERE set_run_id=%s AND raw_data->'private_jackson_v2'->>'valid'='true'",(RUN,))[0]['n']==4)
# Hard-killed in-flight request is retained and blocks automatic continuation.
other_owner.prepare_scheduler();other_owner.reserve(5);other_owner.release('workflow_interrupted')
check(queue.refresh_and_reserve(RUN) is None)
check(saved()['source_metadata'][KEY]['status']=='blocked')
denies(lambda:queue.refresh_and_reserve(other[1]))
# An uncertain HTTP outcome never reissues the reservation, even across ticks.
sends=[]
queue.tick(lambda payload:sends.append(payload))
queue.tick(lambda payload:sends.append(payload))
check(sends==[])
# Completion-only path bypasses provider budget without creating a new owner,
# even when another run is uncertain. All window evidence still must validate.
run4='a0000000-0000-4000-8000-000000000014';target4='10000000-0000-4000-8000-000000000014'
query("INSERT INTO app.sets(id,slug,title,normalized_title,visibility,collection_id) SELECT %s,'synthetic-14',title,normalized_title,visibility,collection_id FROM app.sets WHERE id=%s",(target4,manifest1['target_set_id']))
query("""INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,publication_visibility,target_set_id,collection_id,source_metadata)
    SELECT %s,submission_id,requested_by,'private_resume_pending',source_url,publication_visibility,%s,collection_id,%s::jsonb FROM ops.set_runs WHERE id=%s""",(run4,target4,json.dumps(original),RUN))
queue.enqueue([manifest(run4)])
query("""INSERT INTO ops.segment_hits(set_run_id,segment_index,timestamp_seconds,recognized,raw_data)
    SELECT %s,i,i*15,false,jsonb_build_object('private_jackson_v2',jsonb_build_object('valid',true,'in_flight',false,'attempts','[]'::jsonb,
      'response',jsonb_build_object('track_title',null,'artist',null,'shazam_track_id',null,'segment_index',i,'timestamp',i*15,'recognized',false,'raw_data',jsonb_build_object('matches','[]'::jsonb)))) FROM generate_series(0,478) i""",(run4,))
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_resume,requests}','999999') WHERE id=%s",(run4,))
# Explicit review and unsafe pause survive full coverage. Test both controller
# completion and the already-dispatched worker fast path, with no state loss.
completion_snapshot=copy.deepcopy(saved(run4)['source_metadata'])
for review in (True,False):
    blocked=copy.deepcopy(completion_snapshot)
    blocked['yoon_resume'].update(review_required=review,reason='operator_review_required')
    query("UPDATE ops.set_runs SET status='private_resume_paused',source_metadata=%s::jsonb WHERE id=%s",(json.dumps(blocked),run4))
    check(queue.refresh_and_reserve(run4) is None)
    after=saved(run4)
    check(after['status']=='private_resume_paused' and after['source_metadata'][KEY]['status']=='blocked')
    check(after['source_metadata']['yoon_resume']==blocked['yoon_resume'])
    reserved=copy.deepcopy(blocked)
    generation=str(uuid.uuid4())
    reserved[KEY].update(status='reserved',generation=generation,owner=None)
    query("UPDATE ops.set_runs SET source_metadata=%s::jsonb WHERE id=%s",(json.dumps(reserved),run4))
    os.environ['SET_LIST_DISPATCH_GENERATION']=generation
    before=saved(run4)
    denies(lambda:ResumeStore(run4,'9014','1',connect=connect).finalize_ready())
    check(saved(run4)==before)
query("UPDATE ops.set_runs SET status='private_resume_pending',source_metadata=%s::jsonb WHERE id=%s",(json.dumps(completion_snapshot),run4))
out,err=io.StringIO(),io.StringIO()
with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
    check(queue.refresh_and_reserve(run4) is None)
check(out.getvalue()=='' and err.getvalue()=='')
check(saved(run4)['status']=='private_resume_complete')
check(saved(run4)['source_metadata'][KEY]['status']=='complete')
check(saved(run4)['source_metadata']['yoon_resume']['requests']==999999)
check(run4 not in queue.ids())
# Full valid hit coverage cannot conceal a contradictory claimed lease or
# retained run-level in-flight marker. Neither path clears their evidence.
for uncertain in ('claimed_lease','in_flight'):
    metadata=copy.deepcopy(completion_snapshot)
    if uncertain=='in_flight':metadata['yoon_resume']['in_flight']=True
    query("UPDATE ops.set_runs SET status='private_resume_pending',source_metadata=%s::jsonb WHERE id=%s",(json.dumps(metadata),run4))
    if uncertain=='claimed_lease':
        query("INSERT INTO ops.set_run_leases(set_run_id,slot_index,segment_start_index,segment_end_index,status,claimed_by) VALUES(%s,0,0,0,'claimed','999')",(run4,))
    hits_before=query('SELECT row_to_json(h)::text AS row FROM ops.segment_hits h WHERE set_run_id=%s ORDER BY segment_index',(run4,))
    leases_before=query('SELECT row_to_json(l)::text AS row FROM ops.set_run_leases l WHERE set_run_id=%s ORDER BY id',(run4,))
    check(run4 in queue.blocked_ids())
    if uncertain=='claimed_lease':denies(lambda:queue.refresh_and_reserve(run4))
    else:check(queue.refresh_and_reserve(run4) is None)
    check(saved(run4)['status']=='private_resume_pending')
    reserved=copy.deepcopy(metadata);generation=str(uuid.uuid4())
    reserved[KEY].update(status='reserved',generation=generation,owner=None)
    query('UPDATE ops.set_runs SET source_metadata=%s::jsonb WHERE id=%s',(json.dumps(reserved),run4))
    os.environ['SET_LIST_DISPATCH_GENERATION']=generation
    before=saved(run4);denies(lambda:ResumeStore(run4,'9014','1',connect=connect).finalize_ready())
    check(saved(run4)==before)
    check(query('SELECT row_to_json(h)::text AS row FROM ops.segment_hits h WHERE set_run_id=%s ORDER BY segment_index',(run4,))==hits_before)
    check(query('SELECT row_to_json(l)::text AS row FROM ops.set_run_leases l WHERE set_run_id=%s ORDER BY id',(run4,))==leases_before)
    if uncertain=='claimed_lease':query('DELETE FROM ops.set_run_leases WHERE set_run_id=%s',(run4,))
# Each known settled budget pause can still complete fully validated durable
# coverage. The original request count remains exhausted, with no provider call.
for reason in ('lifetime_time_budget','lifetime_request_budget','continuation_budget','window_attempt_budget'):
    ready=copy.deepcopy(completion_snapshot);ready['yoon_resume'].update(reason=reason,review_required=False)
    query("UPDATE ops.set_runs SET status='private_resume_paused',source_metadata=%s::jsonb WHERE id=%s",(json.dumps(ready),run4))
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
        check(queue.refresh_and_reserve(run4) is None)
    check(saved(run4)['status']=='private_resume_complete' and saved(run4)['source_metadata'][KEY]['status']=='complete')
    check(saved(run4)['source_metadata']['yoon_resume']['requests']==999999)
# Queue-complete and row-complete cannot hide a retained explicit review flag.
completed_snapshot=copy.deepcopy(saved(run4)['source_metadata'])
reviewed=copy.deepcopy(completed_snapshot);reviewed['yoon_resume']['review_required']=True
query('UPDATE ops.set_runs SET source_metadata=%s::jsonb WHERE id=%s',(json.dumps(reviewed),run4))
before=saved(run4)
check(run4 in queue.blocked_ids())
denies(lambda:ResumeStore(run4,'9014','1',connect=connect).finalize_ready())
check(saved(run4)==before)
# A real queued worker fast-finalizer may complete without a retained resume
# owner. Its terminal receipt still validates, and does not claim live work.
reserved=copy.deepcopy(completion_snapshot);generation=str(uuid.uuid4())
reserved[KEY].update(status='reserved',generation=generation,owner=None)
query("UPDATE ops.set_runs SET status='private_resume_pending',source_metadata=%s::jsonb WHERE id=%s",(json.dumps(reserved),run4))
os.environ['SET_LIST_DISPATCH_GENERATION']=generation
with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
    check(ResumeStore(run4,'9014','1',connect=connect).finalize_ready())
terminal=saved(run4)
check(terminal['status']=='private_resume_complete' and terminal['source_metadata'][KEY]['status']=='complete')
check(terminal['source_metadata'][KEY]['owner']=={'workflow_run_id':'9014','run_attempt':'1'})
check(terminal['source_metadata']['yoon_resume'].get('workflow_run_id') is None)
check(run4 not in queue.blocked_ids())
# A terminal record with a retained per-hit request is uncertain too, even
# when no lease remains claimed. Startup and worker fast paths preserve it.
query("UPDATE ops.segment_hits SET raw_data=jsonb_set(raw_data,'{private_jackson_v2,in_flight}','true') WHERE set_run_id=%s AND segment_index=0",(run4,))
before=saved(run4)
check(run4 in queue.blocked_ids())
denies(lambda:ResumeStore(run4,'9014','1',connect=connect).finalize_ready())
check(saved(run4)==before)
check(query("SELECT raw_data->'private_jackson_v2'->>'in_flight' AS inflight FROM ops.segment_hits WHERE set_run_id=%s AND segment_index=0",(run4,))[0]['inflight']=='true')
query("UPDATE ops.segment_hits SET raw_data=jsonb_set(raw_data,'{private_jackson_v2,in_flight}','false') WHERE set_run_id=%s AND segment_index=0",(run4,))
# Restarted controllers report retained uncertain sends, without touching the
# reservation or attempting any external dispatch. All three send phases count.
for status in ('reserved','sending','dispatched'):
    query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_queue_v1,status}',%s::jsonb) WHERE id=%s",(json.dumps(status),other[0]))
    queue.uncertain(res2)
    before=saved(other[0])
    restarted=PrivateQueue(connect=connect)
    report=restarted.tick(lambda payload:sends.append(payload))
    check(report['blocked']>=2)  # uncertainty plus retained recognition blocker
    check(saved(other[0])==before)
    check(sends==[])
# A quiet queue with only a cleanly paused blocked run must not look complete.
# Temporarily exclude other synthetic pending rows to test the zero-active path.
query("UPDATE ops.set_runs SET cancel_requested_at=now() WHERE id=ANY(%s::uuid[])",(other,))
report=PrivateQueue(connect=connect).tick(lambda payload:sends.append(payload))
check(report['pending']==0 and report['blocked']>=1)
check(saved()['status']=='private_resume_paused')
check(saved()['source_metadata'][KEY]['status']=='blocked')
check(sends==[])
# No public run, archive row or origin is ever modified by this test's queue.
check(query("SELECT status FROM ops.set_runs WHERE id='40000000-0000-4000-8000-000000000099'")[0]['status']=='completed')
print(json.dumps({'done':True,'checks':checks}),file=sys.__stdout__,flush=True)
