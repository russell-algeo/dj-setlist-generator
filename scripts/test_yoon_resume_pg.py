"""Actual ResumeStore methods over a local stdin/stdout PGlite adapter, no sockets."""
import json,sys,uuid
from decimal import Decimal
from contextlib import contextmanager
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from worker.jobs.yoon_resume_store import ResumeStore,QueuePause
from worker.pipeline.models import Recognition

class Cursor:
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def execute(self,sql,params=()):
        print(json.dumps({'sql':sql,'params':params},default=str),file=sys.__stdout__,flush=True)
        result=json.loads(sys.stdin.readline())
        if 'error' in result: raise RuntimeError(result['error'])
        self.rows=result['rows']
        for row in self.rows:
            for field in result.get('fields',[]):
                key=field['name'];value=row.get(key)
                if value is not None and field['dataTypeID']==2950:row[key]=uuid.UUID(value)
                if value is not None and field['dataTypeID']==1700:row[key]=Decimal(str(value))
    def fetchone(self): return self.rows[0] if self.rows else None
    def fetchall(self): return self.rows
class Conn:
    def cursor(self): return Cursor()
    @contextmanager
    def transaction(self):
        c=Cursor();c.execute('BEGIN')
        try: yield
        except BaseException:
            c.execute('ROLLBACK');raise
        else: c.execute('COMMIT')
@contextmanager
def connect():
    c=Cursor();c.execute('SET ROLE synthetic_private_worker')
    try:yield Conn()
    finally:c.execute('RESET ROLE')
def query(sql,params=()):
    c=Cursor();c.execute(sql,params);return c.rows
sys.stdout=sys.stderr
checks=0
def check(value):
    global checks
    assert value;checks+=1
def denies(fn):
    global checks
    try: fn()
    except (RuntimeError,QueuePause): checks+=1
    else: raise AssertionError('expected denial')
RUN='a0000000-0000-4000-8000-000000000010'
with connect():
    for table in ('app.sets','app.archive_collections','app.archive_collection_members'):
        denies(lambda table=table:query('SELECT * FROM '+table+' FOR UPDATE'))
s=ResumeStore(RUN,'9001','1',connect=connect)
source=s.claim();check(source.startswith('https://www.dropbox.com/'))
state=s.require_owner();check(state['continuations']==1 and state['provenance_seeded'])
plan=s.prepare_scheduler();check(plan.slot_count==12)
check(s.require_owner()['scheduler_plan']['lease_size']==plan.lease_size)
check(s.next_windows(1,2)[0][0]['segment_index']==plan.lease_size)
check(query('SELECT count(*)::int AS n FROM ops.set_run_leases WHERE set_run_id=%s',(RUN,))[0]['n']==479)
check(query("SELECT count(*)::int AS n FROM ops.set_run_leases WHERE set_run_id=%s AND status='completed'",(RUN,))[0]['n']==4)
candidate,wait=s.next_window();check(candidate['segment_index']==4 and wait==0)
denies(s.claim)
denies(lambda:s.reserve(0))
wrong=ResumeStore(RUN,'9002','1',connect=connect);denies(wrong.require_owner)
from recognition_lock_faults import run_checks
checks += run_checks(s,query,index=4)
ticket=s.reserve(4);denies(lambda:s.reserve(4))
check(s.require_owner()['requests']==1)
r=Recognition(60,None,None,None,None,False,4,was_rate_limited=True,error_type='RateLimited')
r.http_status=429
check(s.finish(r,ticket,60).delay_seconds == 60)
candidate,wait=s.next_window();check(candidate['segment_index']==4 and wait>55)
denies(lambda:s.reserve(4))
s.release('cooldown_pending');denies(s.claim);check(query('SELECT status FROM ops.set_runs WHERE id=%s',(RUN,))[0]['status']=='private_resume_paused')
# Another workflow may claim, but pending window due is still enforced at reserve.
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_resume,next_allowed_at}','0'::jsonb) WHERE id=%s",(RUN,))
query("UPDATE ops.segment_hits SET raw_data=jsonb_set(raw_data,'{private_jackson_v2,next_allowed_at}','0') WHERE set_run_id=%s",(RUN,))
wrong.claim();check(wrong.require_owner()['continuations']==2)
denies(s.require_owner)
for i in range(12):
    query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_resume,next_allowed_at}','0') WHERE id=%s",(RUN,))
    query("UPDATE ops.segment_hits SET raw_data=jsonb_set(raw_data,'{private_jackson_v2,next_allowed_at}','0') WHERE set_run_id=%s AND segment_index=4",(RUN,))
    t=wrong.reserve(4)
    directive=wrong.finish(r,t,0)
    check(directive.delay_seconds==min(3600,60*2**(i+1)))
    check(wrong.require_owner()['throttle_requests']==i+2)
    check(wrong.require_owner()['requests']-wrong.require_owner()['throttle_requests']==0)
    denies(lambda:wrong.reserve(4))
# Model a pre-upgrade exhausted window and old lifetime/continuation counters.
wrong.release('cooldown_pending')
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_resume}',(source_metadata->'yoon_resume')-'throttle_policy_version'-'throttle_requests') WHERE id=%s",(RUN,))
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(jsonb_set(source_metadata,'{yoon_resume,created_at}','1'),'{yoon_resume,continuations}','300') WHERE id=%s",(RUN,))
query("UPDATE ops.set_run_leases SET status='exhausted' WHERE set_run_id=%s AND segment_start_index=4",(RUN,))
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_resume,next_allowed_at}','0') WHERE id=%s",(RUN,))
query("UPDATE ops.segment_hits SET raw_data=jsonb_set(raw_data,'{private_jackson_v2,next_allowed_at}','0') WHERE set_run_id=%s AND segment_index=4",(RUN,))
wrong=ResumeStore(RUN,'9011','1',connect=connect);wrong.claim()
check(wrong.require_owner()['throttle_requests']==13)
check(wrong.require_owner()['continuations']==301)
check(wrong.next_window()[0]['segment_index']==4)
ticket=wrong.reserve(4)
r=Recognition(60,None,None,None,{'matches':[]},False,4)
r.http_status=200
wrong.finish(r,ticket,0)
# A completed effective non429 cap is an intentional pause, never an
# unexpected authorization failure, and must not append/reopen anything.
for _ in range(8):
    cap_ticket=wrong.reserve(9)
    cap_response=Recognition(135,None,None,None,None,False,9,
        error_type='ProviderServerError',http_status=503,retry_after_format='absent')
    wrong.finish(cap_response,cap_ticket,0)
cap_before=query('SELECT row_to_json(h)::text AS row FROM ops.segment_hits h WHERE set_run_id=%s AND segment_index=9',(RUN,))[0]['row']
try:
    wrong.reserve(9)
except QueuePause as exc:
    check(str(exc)=='window_attempt_budget')
else:raise AssertionError('expected intentional exhausted-window pause')
check(cap_before==query('SELECT row_to_json(h)::text AS row FROM ops.segment_hits h WHERE set_run_id=%s AND segment_index=9',(RUN,))[0]['row'])
check(query("SELECT status FROM ops.set_run_leases WHERE set_run_id=%s AND segment_start_index=9",(RUN,))[0]['status']=='exhausted')
check(wrong.summary()[0]['valid']==5)
check(wrong.next_window()[0]['segment_index']==5)
hit=query('SELECT raw_data FROM ops.segment_hits WHERE set_run_id=%s AND segment_index=4',(RUN,))[0]['raw_data']['private_jackson_v2']
check(hit['valid'] and len(hit['attempts'])==14)
check([a['diagnostic']['http_status'] for a in hit['attempts']]==[429]*13+[200])
# Distinct pending windows may be in flight together; completed rows cannot be replayed.
denies(lambda:wrong.reserve(4))
ticket5=wrong.reserve(5);ticket6=wrong.reserve(6)
for index,ticket in [(5,ticket5),(6,ticket6)]:
    response=Recognition(index*15,None,None,None,{'matches':[]},False,index,http_status=200)
    denies(lambda:wrong.finish(response,'wrong-ticket',0))
    wrong.finish(response,ticket,0)
check(wrong.summary()[0]['valid']==7)
# Preserve per-window provider waits; one success must not erase another window's wait.
ticket7=wrong.reserve(7)
limited=Recognition(105,None,None,None,None,False,7,was_rate_limited=True,error_type='RateLimited',http_status=429)
wrong.finish(limited,ticket7,9000)
denies(lambda:wrong.reserve(7))
# A slot can only admit its assigned partition, even though workflow owner is shared.
denies(lambda:wrong.reserve(plan.lease_size,0))
denies(lambda:wrong.reserve(plan.lease_size,1))
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_resume,next_allowed_at}','0'::jsonb) WHERE id=%s",(RUN,))
slot_ticket=wrong.reserve(plan.lease_size,1)
slot_result=Recognition(plan.lease_size*15,None,None,None,{'matches':[]},False,plan.lease_size,http_status=200)
wrong.finish(slot_result,slot_ticket,0)
check(wrong.summary()[0]['valid']==8)
# An interrupted reservation is not rewritten as a valid response or blindly retried.
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_resume,next_allowed_at}','0'::jsonb) WHERE id=%s",(RUN,))
wrong.reserve(8);wrong.release('worker_interrupted')
check(query('SELECT raw_data FROM ops.segment_hits WHERE set_run_id=%s AND segment_index=8',(RUN,))[0]['raw_data']['private_jackson_v2']['in_flight'])
denies(ResumeStore(RUN,'9003','1',connect=connect).claim)
# Reconcile only in this synthetic DB to test cancellation/audience/public fences.
query("UPDATE ops.set_runs SET status='private_resume_running' WHERE id=%s",(RUN,))
query("UPDATE ops.set_runs SET cancel_requested_at=now() WHERE id=%s",(RUN,));denies(wrong.require_owner)
query("UPDATE ops.set_runs SET cancel_requested_at=null WHERE id=%s",(RUN,))
query("INSERT INTO app.archive_collection_members(collection_id,user_id,role) VALUES('20000000-0000-4000-8000-000000000001','synthetic-other','viewer')")
denies(wrong.require_owner)
query("DELETE FROM app.archive_collection_members WHERE user_id='synthetic-other'")
query("UPDATE ops.set_runs SET create_playlist=true WHERE id=%s",(RUN,));denies(wrong.require_owner)
query("UPDATE ops.set_runs SET create_playlist=false WHERE id=%s",(RUN,))
denies(wrong.complete)
# Existing public retention still applies, while old private attempts survive.
query("UPDATE ops.segment_hits SET created_at=now()-interval '8 days'")
query('SELECT ops.cleanup_expired_ops_data()')
check(query('SELECT count(*)::int AS n FROM ops.segment_hits WHERE set_run_id=%s',(RUN,))[0]['n']==11)
check(query("SELECT count(*)::int AS n FROM ops.segment_hits WHERE set_run_id='40000000-0000-4000-8000-000000000099'")[0]['n']==0)
# Complete durable coverage remains finalizable after all provider budgets expire.
query("DELETE FROM ops.segment_hits WHERE set_run_id=%s",(RUN,))
query("""INSERT INTO ops.segment_hits(set_run_id,lease_id,segment_index,timestamp_seconds,recognized,raw_data)
 SELECT %s,l.id,l.segment_start_index,l.segment_start_index*15,false,
 jsonb_build_object('private_jackson_v2',jsonb_build_object('valid',true,'in_flight',false,'attempts','[]'::jsonb,
 'response',jsonb_build_object('timestamp',l.segment_start_index*15,'segment_index',l.segment_start_index,
 'track_title',null,'artist',null,'shazam_track_id',null,'raw_data',jsonb_build_object('matches','[]'::jsonb),
 'recognized',false,'error_type',null,'was_rate_limited',false,'error_details',null)))
 FROM ops.set_run_leases l WHERE l.set_run_id=%s""",(RUN,RUN))
query("UPDATE ops.set_runs SET status='private_resume_paused',source_metadata=jsonb_set(jsonb_set(source_metadata,'{yoon_resume,requests}','768'),'{yoon_resume,continuations}','32') WHERE id=%s",(RUN,))
finalizer=ResumeStore(RUN,'9003','1',connect=connect)
check(finalizer.finalize_ready())
check(query('SELECT status FROM ops.set_runs WHERE id=%s',(RUN,))[0]['status']=='private_resume_complete')
check(query("SELECT (source_metadata->'yoon_resume'->>'requests')::int AS n FROM ops.set_runs WHERE id=%s",(RUN,))[0]['n']==768)
check(finalizer.finalize_ready())
# Prepared sample drift is a durable review pause, not silently accepted.
query("UPDATE ops.set_runs SET status='private_resume_running' WHERE id=%s",(RUN,))
denies(lambda:wrong.write({'status':'prepared','audio_sha256':'b'*64,'recognition_mode':'resumable'}))
check(query("SELECT source_metadata->'yoon_resume'->>'reason' AS reason FROM ops.set_runs WHERE id=%s",(RUN,))[0]['reason']=='prepared_audio_changed')
check(query("SELECT source_metadata->'yoon_resume'->>'review_required' AS review FROM ops.set_runs WHERE id=%s",(RUN,))[0]['review']=='true')
# Synthetic reconciliation between deliberately corrupted fixtures. Production
# admission must reject these states; never use this as a recovery procedure.
def reconcile_fixture(run):
    query("UPDATE ops.set_runs SET status='private_resume_paused',source_metadata=jsonb_set(source_metadata,'{yoon_resume,review_required}','false') WHERE id=%s",(run,))
    query("UPDATE ops.set_run_leases SET status='pending' WHERE set_run_id=%s AND status='claimed'",(run,))
reconcile_fixture(RUN)
# New catalog source: empty fresh run, one-time derivative pin, normal queue.
from worker.jobs.yoon_sources import DONALD
from worker.jobs.yoon_resume_policy import initial_state
DONALD_RUN='a0000000-0000-4000-8000-000000000020'
fresh_state=initial_state(float(query("SELECT extract(epoch from clock_timestamp()) AS n")[0]['n']))
fresh_state.update(source_id=DONALD.id,source_pins=DONALD.pins(),initialization_mode='fresh',
    members=[{'user_id':'synthetic-owner','role':'manager'},{'user_id':'synthetic-viewer','role':'viewer'}])
descriptor=dict(DONALD.pins(),source_id=DONALD.id,recognition_mode='resumable',
    source_url='https://dropbox.com/SYNTHETIC_DONALD')
query("""INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,
 publication_visibility,target_set_id,collection_id,source_metadata)
 SELECT %s,submission_id,requested_by,'private_resume_pending','local:synthetic',
 publication_visibility,target_set_id,collection_id,%s::jsonb FROM ops.set_runs WHERE id=%s""",
 (DONALD_RUN,json.dumps({'yoon_fixed_input':descriptor,'yoon_resume':fresh_state}),RUN))
d=ResumeStore(DONALD_RUN,'9100','1',connect=connect)
# The catalog's four exact pins are enforced before any lease is created.
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_fixed_input,source_end_seconds}','10570') WHERE id=%s",(DONALD_RUN,))
denies(d.claim)
check(query('SELECT count(*)::int AS n FROM ops.set_run_leases WHERE set_run_id=%s',(DONALD_RUN,))[0]['n']==0)
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_fixed_input,source_end_seconds}','10571') WHERE id=%s",(DONALD_RUN,))
check(d.claim()=='https://dropbox.com/SYNTHETIC_DONALD')
state=d.require_owner()
check(state['fresh_source_initialized'] and not state.get('provenance_seeded') and not state.get('origin'))
check(state['expected_windows']==479 and 'provisional' in state['bounds'])
check(query('SELECT count(*)::int AS n FROM ops.set_run_leases WHERE set_run_id=%s',(DONALD_RUN,))[0]['n']==479)
check(query('SELECT count(*)::int AS n FROM ops.segment_hits WHERE set_run_id=%s',(DONALD_RUN,))[0]['n']==0)
d.write({'status':'prepared','audio_sha256':'c'*64,'recognition_mode':'resumable'})
check(d.require_owner()['expected_audio_sha256']=='c'*64)
d.prepare_scheduler()
ticket=d.reserve(0)
d.finish(Recognition(0,None,None,None,{'matches':[]},False,0,http_status=200),ticket,0)
check(d.summary()[0]['valid']==1)
d.release('bounded_pause')
d2=ResumeStore(DONALD_RUN,'9101','1',connect=connect)
d2.claim();d2.write({'status':'prepared','audio_sha256':'c'*64,'recognition_mode':'resumable'})
check(d2.require_owner()['continuations']==2)
check(d2.summary()[0]['valid']==1)
denies(lambda:d2.reserve(0))
denies(lambda:d2.write({'status':'prepared','audio_sha256':'d'*64,'recognition_mode':'resumable'}))
check(query("SELECT source_metadata->'yoon_resume'->>'reason' AS reason FROM ops.set_runs WHERE id=%s",(DONALD_RUN,))[0]['reason']=='prepared_audio_changed')
check(query("SELECT source_metadata->'yoon_resume'->>'expected_audio_sha256' AS digest FROM ops.set_runs WHERE id=%s",(DONALD_RUN,))[0]['digest']=='c'*64)
# New catalog source: empty fresh run, one-time derivative pin, normal queue.
reconcile_fixture(DONALD_RUN)
from worker.jobs.yoon_sources import HALO
from worker.jobs.yoon_resume_policy import initial_state
HALO_RUN='a0000000-0000-4000-8000-000000000030'
fresh_state=initial_state(float(query("SELECT extract(epoch from clock_timestamp()) AS n")[0]['n']))
fresh_state.update(source_id=HALO.id,source_pins=HALO.pins(),initialization_mode='fresh',
    members=[{'user_id':'synthetic-owner','role':'manager'},{'user_id':'synthetic-viewer','role':'viewer'}])
descriptor=dict(HALO.pins(),source_id=HALO.id,recognition_mode='resumable',
    source_url='https://dropbox.com/SYNTHETIC_HALO')
query("""INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,
 publication_visibility,target_set_id,collection_id,source_metadata)
 SELECT %s,submission_id,requested_by,'private_resume_pending','local:synthetic',
 publication_visibility,target_set_id,collection_id,%s::jsonb FROM ops.set_runs WHERE id=%s""",
 (HALO_RUN,json.dumps({'yoon_fixed_input':descriptor,'yoon_resume':fresh_state}),RUN))
d=ResumeStore(HALO_RUN,'9200','1',connect=connect)
# The catalog's four exact pins are enforced before any lease is created.
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_fixed_input,source_end_seconds}','15721') WHERE id=%s",(HALO_RUN,))
denies(d.claim)
check(query('SELECT count(*)::int AS n FROM ops.set_run_leases WHERE set_run_id=%s',(HALO_RUN,))[0]['n']==0)
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_fixed_input,source_end_seconds}','15720') WHERE id=%s",(HALO_RUN,))
check(d.claim()=='https://dropbox.com/SYNTHETIC_HALO')
state=d.require_owner()
check(state['fresh_source_initialized'] and not state.get('provenance_seeded') and not state.get('origin'))
check(state['expected_windows']==359 and 'provisional' in state['bounds'])
check(query('SELECT count(*)::int AS n FROM ops.set_run_leases WHERE set_run_id=%s',(HALO_RUN,))[0]['n']==359)
check(query('SELECT count(*)::int AS n FROM ops.segment_hits WHERE set_run_id=%s',(HALO_RUN,))[0]['n']==0)
d.write({'status':'prepared','audio_sha256':'c'*64,'recognition_mode':'resumable'})
check(d.require_owner()['expected_audio_sha256']=='c'*64)
d.prepare_scheduler()
ticket=d.reserve(0)
d.finish(Recognition(0,None,None,None,{'matches':[]},False,0,http_status=200),ticket,0)
check(d.summary()[0]['valid']==1)
d.release('bounded_pause')
d2=ResumeStore(HALO_RUN,'9201','1',connect=connect)
d2.claim();d2.write({'status':'prepared','audio_sha256':'c'*64,'recognition_mode':'resumable'})
check(d2.require_owner()['continuations']==2)
check(d2.summary()[0]['valid']==1)
denies(lambda:d2.reserve(0))
denies(lambda:d2.write({'status':'prepared','audio_sha256':'d'*64,'recognition_mode':'resumable'}))
check(query("SELECT source_metadata->'yoon_resume'->>'reason' AS reason FROM ops.set_runs WHERE id=%s",(HALO_RUN,))[0]['reason']=='prepared_audio_changed')
check(query("SELECT source_metadata->'yoon_resume'->>'expected_audio_sha256' AS digest FROM ops.set_runs WHERE id=%s",(HALO_RUN,))[0]['digest']=='c'*64)
query("DELETE FROM ops.segment_hits WHERE set_run_id=%s",(HALO_RUN,))
query("""INSERT INTO ops.segment_hits(set_run_id,lease_id,segment_index,timestamp_seconds,recognized,raw_data)
 SELECT %s,l.id,l.segment_start_index,l.segment_start_index*15,false,
 jsonb_build_object('private_jackson_v2',jsonb_build_object('valid',true,'in_flight',false,'attempts','[]'::jsonb,
 'response',jsonb_build_object('timestamp',l.segment_start_index*15,'segment_index',l.segment_start_index,
 'track_title',null,'artist',null,'shazam_track_id',null,'raw_data',jsonb_build_object('matches','[]'::jsonb),
 'recognized',false,'error_type',null,'was_rate_limited',false,'error_details',null)))
 FROM ops.set_run_leases l WHERE l.set_run_id=%s""",(HALO_RUN,HALO_RUN))
# Synthetic reconciliation after the deliberate digest-drift test, not live recovery.
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_resume,review_required}','false') WHERE id=%s",(HALO_RUN,))
check(d2.finalize_ready())
check(query("SELECT (source_metadata->'yoon_resume'->>'valid_responses')::int AS n FROM ops.set_runs WHERE id=%s",(HALO_RUN,))[0]['n']==359)
check(query('SELECT status FROM ops.set_runs WHERE id=%s',(HALO_RUN,))[0]['status']=='private_resume_complete')
# New catalog source: empty fresh run, one-time derivative pin, normal queue.
reconcile_fixture(HALO_RUN)
from worker.jobs.yoon_sources import GRISHA
from worker.jobs.yoon_resume_policy import initial_state
GRISHA_RUN='a0000000-0000-4000-8000-000000000040'
fresh_state=initial_state(float(query("SELECT extract(epoch from clock_timestamp()) AS n")[0]['n']))
fresh_state.update(source_id=GRISHA.id,source_pins=GRISHA.pins(),initialization_mode='fresh',
    members=[{'user_id':'synthetic-owner','role':'manager'},{'user_id':'synthetic-viewer','role':'viewer'}])
descriptor=dict(GRISHA.pins(),source_id=GRISHA.id,recognition_mode='resumable',
    source_url='https://dropbox.com/SYNTHETIC_GRISHA')
query("""INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,
 publication_visibility,target_set_id,collection_id,source_metadata)
 SELECT %s,submission_id,requested_by,'private_resume_pending','local:synthetic',
 publication_visibility,target_set_id,collection_id,%s::jsonb FROM ops.set_runs WHERE id=%s""",
 (GRISHA_RUN,json.dumps({'yoon_fixed_input':descriptor,'yoon_resume':fresh_state}),RUN))
d=ResumeStore(GRISHA_RUN,'9300','1',connect=connect)
# The catalog's four exact pins are enforced before any lease is created.
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_fixed_input,source_end_seconds}','12135') WHERE id=%s",(GRISHA_RUN,))
denies(d.claim)
check(query('SELECT count(*)::int AS n FROM ops.set_run_leases WHERE set_run_id=%s',(GRISHA_RUN,))[0]['n']==0)
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_fixed_input,source_end_seconds}','12134.883265306122') WHERE id=%s",(GRISHA_RUN,))
check(d.claim()=='https://dropbox.com/SYNTHETIC_GRISHA')
state=d.require_owner()
check(state['fresh_source_initialized'] and not state.get('provenance_seeded') and not state.get('origin'))
check(state['expected_windows']==479 and 'provisional' in state['bounds'])
check(query('SELECT count(*)::int AS n FROM ops.set_run_leases WHERE set_run_id=%s',(GRISHA_RUN,))[0]['n']==479)
check(query('SELECT count(*)::int AS n FROM ops.segment_hits WHERE set_run_id=%s',(GRISHA_RUN,))[0]['n']==0)
d.write({'status':'prepared','audio_sha256':'c'*64,'recognition_mode':'resumable'})
check(d.require_owner()['expected_audio_sha256']=='c'*64)
d.prepare_scheduler()
ticket=d.reserve(0)
d.finish(Recognition(0,None,None,None,{'matches':[]},False,0,http_status=200),ticket,0)
check(d.summary()[0]['valid']==1)
d.release('bounded_pause')
d2=ResumeStore(GRISHA_RUN,'9301','1',connect=connect)
d2.claim();d2.write({'status':'prepared','audio_sha256':'c'*64,'recognition_mode':'resumable'})
check(d2.require_owner()['continuations']==2)
check(d2.summary()[0]['valid']==1)
denies(lambda:d2.reserve(0))
denies(lambda:d2.write({'status':'prepared','audio_sha256':'d'*64,'recognition_mode':'resumable'}))
check(query("SELECT source_metadata->'yoon_resume'->>'reason' AS reason FROM ops.set_runs WHERE id=%s",(GRISHA_RUN,))[0]['reason']=='prepared_audio_changed')
check(query("SELECT source_metadata->'yoon_resume'->>'expected_audio_sha256' AS digest FROM ops.set_runs WHERE id=%s",(GRISHA_RUN,))[0]['digest']=='c'*64)
# Actual admission SQL over the migrated database. PGlite has one backend;
# contention/interleavings are separately modeled in test_yoon_admission.
from worker.jobs import yoon_admission as admission
reconcile_fixture(GRISHA_RUN)
def admitted(run,target):
    with connect() as conn, conn.transaction(), conn.cursor() as cur:
        admission.lock(cur)
        admission.check(cur,run,target)
        return True
for i,r in enumerate((DONALD_RUN,HALO_RUN,GRISHA_RUN),2):
    target=f'10000000-0000-4000-8000-{i:012d}'
    query("INSERT INTO app.sets(id,slug,title,normalized_title,visibility,collection_id) SELECT %s,%s,'Synthetic','synthetic','private',collection_id FROM app.sets LIMIT 1",(target,'capacity-'+str(i)))
    new_run=f'b0000000-0000-4000-8000-{i:012d}'
    query("""INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,
      publication_visibility,target_set_id,collection_id,source_metadata)
      SELECT %s,submission_id,requested_by,'private_resume_paused','local:synthetic-capacity',
      publication_visibility,%s,collection_id,source_metadata FROM ops.set_runs WHERE id=%s""",(new_run,target,r))
DONALD_RUN='b0000000-0000-4000-8000-000000000002'
HALO_RUN='b0000000-0000-4000-8000-000000000003'
GRISHA_RUN='b0000000-0000-4000-8000-000000000004'
check(admitted(DONALD_RUN,'10000000-0000-4000-8000-000000000002'))
query("UPDATE ops.set_runs SET status='private_resume_running' WHERE id=%s",(DONALD_RUN,))
check(admitted(HALO_RUN,'10000000-0000-4000-8000-000000000003'))
query("UPDATE ops.set_runs SET status='private_resume_running' WHERE id=%s",(HALO_RUN,))
denies(lambda:admitted(GRISHA_RUN,'10000000-0000-4000-8000-000000000004'))
denies(lambda:admitted(DONALD_RUN,'different-target'))
denies(lambda:admitted(GRISHA_RUN,'10000000-0000-4000-8000-000000000002'))
query("UPDATE ops.set_runs SET status='private_resume_complete',source_metadata=jsonb_set(source_metadata,'{yoon_spotify_enrichment}',%s::jsonb) WHERE id=%s",(json.dumps({'status':'reserved','owner':{'workflow_run_id':'9900','run_attempt':'1'}}),DONALD_RUN))
denies(lambda:admitted(GRISHA_RUN,'10000000-0000-4000-8000-000000000004'))
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_spotify_enrichment,status}','\"complete\"') WHERE id=%s",(DONALD_RUN,))
check(admitted(GRISHA_RUN,'10000000-0000-4000-8000-000000000004'))
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_resume,review_required}','true') WHERE id=%s",(DONALD_RUN,))
denies(lambda:admitted(GRISHA_RUN,'10000000-0000-4000-8000-000000000004'))
print(json.dumps({'done':True,'checks':checks}),file=sys.__stdout__,flush=True)
