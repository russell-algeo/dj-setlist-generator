"""Real StudyStore SQL over a local PGlite bridge; synthetic data, no sockets."""
import json,sys,uuid
from contextlib import contextmanager
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from worker.jobs.sampling_study_store import StudyStore,StudyPause,StudyFence
from worker.jobs.sampling_study import ExclusiveSession
from worker.jobs.sampling_study_manifest import digest
from tests.test_sampling_study import fixture

class Cursor:
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def execute(self,sql,params=()):
        print(json.dumps({'sql':sql,'params':params},default=str),file=sys.__stdout__,flush=True)
        result=json.loads(sys.stdin.readline())
        if 'error' in result:raise RuntimeError(result['error'])
        self.rows=result['rows']
    def fetchone(self):return self.rows[0] if self.rows else None
    def fetchall(self):return self.rows
class Conn:
    autocommit=True
    info=type('Info',(),{'transaction_status':0})()
    def cursor(self):return Cursor()
    @contextmanager
    def transaction(self):
        query('BEGIN');query('SET LOCAL ROLE set_list_worker')
        try:yield
        except BaseException:query('ROLLBACK');raise
        else:query('COMMIT')
def query(sql,params=()):
    c=Cursor();c.execute(sql,params);return c.rows
sys.stdout=sys.stderr
checks=0
def check(x):
    global checks
    assert x;checks+=1
def denies(fn,reason=None):
    global checks
    try:fn()
    except (RuntimeError,StudyPause,ValueError) as e:
        if reason is not None:assert str(e)==reason,(str(e),reason)
        checks+=1
    else:raise AssertionError('expected denial')
ID='80000000-0000-4000-8000-000000000001';G='90000000-0000-4000-8000-000000000001';REF='f'*40
m,data=fixture();h=m['windows'][0]['input_sha256'];W=m['windows'][0]['id'];W2=m['windows'][1]['id']
query("INSERT INTO ops.sampling_exclusive_grants_v1 VALUES(%s,false,%s,%s,now()-interval '1 minute',now()+interval '1 hour')",(G,'a'*64,REF))
query("INSERT INTO ops.sampling_studies_v1(id,grant_id,manifest,manifest_sha256,reference_sha256,request_limit) VALUES(%s,%s,%s::jsonb,%s,%s,720)",(ID,G,json.dumps(m),digest(m),'a'*64))
conn=Conn();s=StudyStore(conn,ID,'1:1',REF)
denies(s.claim,'study_exclusive_session_lost')
with ExclusiveSession(conn):
    denies(s.claim,'study_exclusive_grant_inactive')
    query('UPDATE ops.sampling_exclusive_grants_v1 SET enabled=true WHERE id=%s',(G,))
    # Worker cannot activate, seed, change cap or immutable manifest.
    for sql in ["UPDATE ops.sampling_exclusive_grants_v1 SET enabled=false","UPDATE ops.sampling_studies_v1 SET request_limit=719","UPDATE ops.sampling_studies_v1 SET manifest='{}'","DELETE FROM ops.sampling_attempts_v1"]:
        def denied_sql(sql=sql):
            with conn.transaction():query(sql)
        denies(denied_sql)
    s.claim();check(s.manifest==m);denies(s.claim,'study_claim_not_released')
    denies(lambda:StudyStore(conn,ID,'2:1',REF).reserve(W,h),'study_owner_changed')
    denies(lambda:s.reserve(W,'c'*64),'study_consumed_input_changed')
    t=s.reserve(W,h);check(query('SELECT requests FROM ops.sampling_studies_v1')[0]['requests']==1)
    denies(lambda:s.reserve(W2,h),'study_unknown_outcome')
    throttled={'outcome':'throttled','http_status':429,'candidate':None,'response_sha256':None,'error_type':'RateLimited','retry_after_seconds':75,'retry_after_format':'delta_seconds','raw_response':None}
    check(s.finish(t,throttled).delay_seconds==75)
    check(s.finish(t,throttled).delay_seconds==75)
    denies(lambda:s.finish(t,dict(throttled,retry_after_seconds=76)),'study_receipt_changed')
    denies(lambda:s.reserve(W2,h),'study_cooldown')
    check(s.release('paused',transport_drained=True)=='paused')
    s2=StudyStore(conn,ID,'2:1',REF);denies(s2.claim,'study_cooldown')
    query('UPDATE ops.sampling_studies_v1 SET next_allowed_at=0')
    s2.claim();t=s2.reserve(W,h);check(query('SELECT requests FROM ops.sampling_studies_v1')[0]['requests']==2)
    # All-attempt cap includes actual throttles and survives restart.
    query('UPDATE ops.sampling_studies_v1 SET request_limit=2')
    good={'outcome':'no_match','http_status':200,'candidate':None,'response_sha256':digest({'matches':[]}),'error_type':None,'retry_after_seconds':None,'retry_after_format':None,'raw_response':{'matches':[]}}
    s2.finish(t,good);check(s2.completed_ids()=={W})
    check(query("SELECT receipt->'raw_response' AS raw FROM ops.sampling_attempts_v1 WHERE ticket=%s",(t,))[0]['raw']=={'matches':[]})
    denies(lambda:s2.reserve(W2,h),'study_all_attempt_cap')
    query('UPDATE ops.sampling_studies_v1 SET request_limit=720')
    denies(lambda:s2.reserve(W,h),'study_terminal_window_replay')
    denies(lambda:s2.release('complete',transport_drained=True),'study_incomplete')
    denies(lambda:s2.release('paused',transport_drained=False),'study_transport_not_drained')
    # Expiry/cancellation block reserve, but a settled receipt can still commit.
    t=s2.reserve(W2,h);query('UPDATE ops.sampling_studies_v1 SET cancelled=true')
    s2.finish(t,good);denies(lambda:s2.reserve(m['windows'][2]['id'],h),'study_cancelled')
    query('UPDATE ops.sampling_studies_v1 SET cancelled=false')
    query("UPDATE ops.sampling_exclusive_grants_v1 SET expires_at=now()+interval '10 seconds'")
    denies(lambda:s2.reserve(m['windows'][2]['id'],h),'study_exclusive_grant_inactive')
    query("UPDATE ops.sampling_exclusive_grants_v1 SET expires_at=now()+interval '1 hour'")
    # Real Yoon demand with finite private fixture, not a fake experiment marker.
    query("INSERT INTO authn.users(id,email) VALUES('sampling-fixture','sampling@example.invalid')")
    query("INSERT INTO ops.submissions(id,requested_by,mode,status,visibility) VALUES('10000000-0000-4000-8000-000000000001','sampling-fixture','set','completed','public')")
    query("INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,publication_visibility,source_metadata) VALUES('20000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000001','sampling-fixture','private_resume_pending','local:synthetic','public','{\"yoon_queue_v1\":{\"version\":1,\"status\":\"queued\"}}')")
    denies(lambda:s2.reserve(m['windows'][2]['id'],h),'study_yoon_priority')
    query("UPDATE ops.set_runs SET source_metadata='{}',status='recognizing'")
    denies(lambda:s2.reserve(m['windows'][2]['id'],h),'study_ordinary_work_active')
    query("UPDATE ops.set_runs SET status='completed',source_metadata=jsonb_build_object('shared_recognition',jsonb_build_object('next_allowed_at',extract(epoch FROM clock_timestamp())+600))")
    denies(lambda:s2.reserve(m['windows'][2]['id'],h),'study_cooldown')
    query("UPDATE ops.set_runs SET source_metadata='{}'")
    # Unknown remains charged/occupied, cannot auto-resume or release as complete.
    t=s2.reserve(m['windows'][2]['id'],h)
    unknown=dict(good,outcome='unknown',http_status=None,response_sha256=None,error_type='RequestTimeout',raw_response=None)
    s2.finish(t,unknown);check(s2.release('paused',transport_drained=True)=='uncertain')
    denies(StudyStore(conn,ID,'3:1',REF).claim,'study_claim_not_released')
    check(query('SELECT requests FROM ops.sampling_studies_v1')[0]['requests']==4)
    check(query("SELECT count(*)::int AS n FROM ops.sampling_attempts_v1 WHERE outcome='unknown'")[0]['n']==1)
    # Constraints enforce one in-flight and one terminal success per window.
    denies(lambda:query("INSERT INTO ops.sampling_attempts_v1(ticket,study_id,number,window_id,input_sha256,owner) VALUES(%s,%s,5,'other',%s,'3:1')",(str(uuid.uuid4()),ID,h)))
check(query("SELECT count(*)::int AS n FROM ops.worker_events")[0]['n']==0)
print(json.dumps({'done':True,'checks':checks}),file=sys.__stdout__,flush=True)
