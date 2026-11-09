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
check(query('SELECT count(*)::int AS n FROM ops.set_run_leases WHERE set_run_id=%s',(RUN,))[0]['n']==479)
check(query("SELECT count(*)::int AS n FROM ops.set_run_leases WHERE set_run_id=%s AND status='completed'",(RUN,))[0]['n']==4)
candidate,wait=s.next_window();check(candidate['segment_index']==4 and wait==0)
denies(s.claim)
denies(lambda:s.reserve(0))
wrong=ResumeStore(RUN,'9002','1',connect=connect);denies(wrong.require_owner)
s.reserve(4);denies(lambda:s.reserve(4))
check(s.require_owner()['requests']==1)
r=Recognition(60,None,None,None,None,False,4,was_rate_limited=True,error_type='RateLimited')
check(s.finish(r,{'http_status':429,'retry_after_format':'absent','outcome':'RateLimited'}) is None)
candidate,wait=s.next_window();check(candidate['segment_index']==4 and wait>295)
denies(lambda:s.reserve(4))
s.release('cooldown_pending');denies(s.claim);check(query('SELECT status FROM ops.set_runs WHERE id=%s',(RUN,))[0]['status']=='private_resume_paused')
denies(wrong.claim)
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_resume,next_allowed_at}','0'::jsonb) WHERE id=%s",(RUN,))
wrong.claim();check(wrong.require_owner()['continuations']==2)
denies(s.require_owner)
wrong.reserve(4)
r=Recognition(60,None,None,None,{'matches':[]},False,4)
wrong.finish(r,{'http_status':200,'retry_after_format':'absent','outcome':'no_match'})
check(wrong.summary()[0]['valid']==5)
check(wrong.next_window()[0]['segment_index']==5)
hit=query('SELECT raw_data FROM ops.segment_hits WHERE set_run_id=%s AND segment_index=4',(RUN,))[0]['raw_data']['private_jackson_v2']
check(hit['valid'] and len(hit['attempts'])==2)
check([a['diagnostic']['http_status'] for a in hit['attempts']]==[429,200])
# An interrupted reservation is not rewritten as a valid response or blindly retried.
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_resume,next_allowed_at}','0'::jsonb) WHERE id=%s",(RUN,))
wrong.reserve(5);wrong.release('worker_interrupted')
check(query('SELECT raw_data FROM ops.segment_hits WHERE set_run_id=%s AND segment_index=5',(RUN,))[0]['raw_data']['private_jackson_v2']['in_flight'])
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
check(query('SELECT count(*)::int AS n FROM ops.segment_hits WHERE set_run_id=%s',(RUN,))[0]['n']==6)
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
print(json.dumps({'done':True,'checks':checks}),file=sys.__stdout__,flush=True)
