"""Execute real durable-store SQL over local stdio PGlite, never a live database."""
import json
import sys
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from worker.jobs.shared_recognition import RecognitionStore, RecognitionPause, RecognitionFence, valid_coverage
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
    c=Cursor();c.execute('SET ROLE synthetic_shared_worker')
    try: yield Conn()
    finally: c.execute('RESET ROLE')
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
    except (RuntimeError,RecognitionPause,RecognitionFence): checks+=1
    else: raise AssertionError('expected refusal')
RUN='a0000000-0000-4000-8000-000000000010'
OTHER='a0000000-0000-4000-8000-000000000011'
def store(run=RUN,workflow='9001',attempt='1'):
    return RecognitionStore(run,workflow_id=workflow,attempt=attempt,generation='g',connect=connect)
def reset_clock():
    query("""UPDATE ops.set_runs SET source_metadata=jsonb_set(jsonb_set(source_metadata,
      '{shared_recognition,next_allowed_at}','0'),'{shared_recognition,provider_next_allowed_at}','0')
      WHERE source_metadata->'shared_recognition'->>'version'='1'""")
def result(index,**kwargs):
    return Recognition(index*15,None,None,None,{'matches':[]},False,index,http_status=200,**kwargs)
with patch('socket.socket.connect',side_effect=AssertionError('network forbidden')), \
     patch('socket.getaddrinfo',side_effect=AssertionError('network forbidden')), \
     TemporaryDirectory() as tmp:
    p=Path(tmp)/'synthetic-audio';p.write_bytes(b'synthetic fixture; never provider audio')
    context=SimpleNamespace(audio_file=p,total_segments=3,source_url='local:synthetic')
    a,b=store(),store(OTHER)
    check(a.begin()['continuations']==1)
    check(a.prepared(context)==3)
    b.begin();b.prepared(context)
    check(a.state()[1]['request_limit']==24)
    check(query('SELECT count(*) AS n FROM ops.set_run_leases WHERE set_run_id=%s',(RUN,))[0]['n']==3)
    denies(a.begin)
    denies(lambda:store(workflow='9002').state())
    first,wait,reason=a.reserve()
    check(first['index']==0 and wait==0 and reason is None)
    check(a.state()[1]['requests']==1)
    a.authorize(first);check(True)
    check(b.reserve()[2]=='provider_busy')
    check(b.state()[1]['requests']==0)
    # Outstanding reservation cannot be overwritten, even by same owner.
    check(a.reserve()[0] is None)
    limited=Recognition(0,None,None,None,None,False,0,was_rate_limited=True,
                        error_type='RateLimited',http_status=429,retry_after_seconds=600,
                        retry_after_format='delta_seconds')
    a.finish(first,limited)
    _,state=a.state()
    check(not state['in_flight'] and state['spacing_seconds']==60 and state['requests']==1)
    check(a.reserve()[1]>595)
    check(b.reserve()[1]>595) # Cross-run cooldown, not merely same-process sleeps.
    a.pause('cooldown_pending')
    reset_clock()
    query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{active_workflow_run_id}','\"9002\"') WHERE id=%s",(RUN,))
    a2=store(workflow='9002');saved=a2.begin()
    check(saved['continuations']==2 and saved['requests']==1 and saved['spacing_seconds']==60)
    a2.prepared(context)
    check(query('SELECT count(*) AS n FROM ops.segment_hits WHERE set_run_id=%s',(RUN,))[0]['n']==1)
    denies(a.state)
    request,_,_=a2.reserve();check(request['index']==0)
    a2.finish(request,result(0))
    hit=query('SELECT * FROM ops.segment_hits WHERE set_run_id=%s AND segment_index=0',(RUN,))[0]
    evidence=hit['raw_data']['shared_recognition']
    check(evidence['valid'] and len(evidence['attempts'])==2)
    check([x['diagnostic']['http_status'] for x in evidence['attempts']]==[429,200])
    denies(lambda:a2.finish(request,result(0)))
    denies(lambda:query("UPDATE ops.segment_hits SET recognized=true WHERE set_run_id=%s AND segment_index=0",(RUN,)))
    denies(lambda:query("DELETE FROM ops.segment_hits WHERE set_run_id=%s",(RUN,)))
    denies(lambda:query("SELECT ops.initialize_set_run_leases(%s,3,1,1)",(RUN,)))
    reset_clock();request,_,_=a2.reserve();check(request['index']==1)
    a2.finish(request,result(1))
    reset_clock();request,_,_=a2.reserve();check(request['index']==2)
    a2.finish(request,result(2))
    query("UPDATE ops.set_runs SET source_metadata=jsonb_set(jsonb_set(source_metadata,'{shared_recognition,requests}','24'),'{shared_recognition,session_requests}','24') WHERE id=%s",(RUN,))
    check(a2.reserve()[2]=='complete') # All-valid finalization precedes caps.
    hits=query('SELECT * FROM ops.segment_hits WHERE set_run_id=%s ORDER BY segment_index',(RUN,))
    check(valid_coverage(hits,3,versioned=True))
    check(not valid_coverage(hits[:2],3,versioned=True))
    damaged=dict(hits[0]);damaged['raw_data']={'shared_recognition':dict(evidence,response={'bad':True})}
    check(not valid_coverage([damaged,*hits[1:]],3,versioned=True))
    check(not valid_coverage([dict(segment_index=0,raw_data={'error':'bad'})],1,versioned=False))
    # Provenance mismatch survives a fresh workflow instead of deleting valid rows.
    a2.pause('complete')
    query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{active_workflow_run_id}','\"9003\"') WHERE id=%s",(RUN,))
    a3=store(workflow='9003');check(a3.begin()['requests']==24)
    p.write_bytes(b'changed synthetic derivative')
    denies(lambda:a3.prepared(context))
    check(a3.state()[1]['review_required'])
    check(query('SELECT count(*) AS n FROM ops.segment_hits WHERE set_run_id=%s',(RUN,))[0]['n']==3)
    # Capture an uncertain hardkill. Other runs cannot issue a duplicate/overlap.
    reset_clock();request,_,_=b.reserve();check(request['index']==0)
    b.pause('worker_or_storage_error')
    check(b.state()[1]['in_flight'] and b.state()[1]['review_required'])
    query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{active_workflow_run_id}','\"9002\"') WHERE id=%s",(OTHER,))
    denies(lambda:store(OTHER,'9002').begin())
    # Cancellation/owner changes reject response writes atomically.
    query('UPDATE ops.set_runs SET cancel_requested_at=now() WHERE id=%s',(OTHER,))
    denies(lambda:b.finish(request,result(0)))
    check(query("SELECT raw_data->'shared_recognition'->>'in_flight' AS v FROM ops.segment_hits WHERE set_run_id=%s",(OTHER,))[0]['v']=='true')
    # Quarantine expires only for OTHER new work. The unknown window remains blocked.
    query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{shared_recognition,in_flight_until}','0') WHERE id=%s",(OTHER,))
    query("UPDATE ops.segment_hits SET raw_data=jsonb_set(raw_data,'{shared_recognition,attempts,0,expires_at}','0') WHERE set_run_id=%s",(OTHER,))
    reset_clock()
    fresh='a0000000-0000-4000-8000-000000000012'
    query("""INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,publication_visibility,source_metadata)
      SELECT %s,submission_id,requested_by,'recognizing','local:synthetic','public',
      '{"active_workflow_run_id":"9001","dispatch_generation":"g","segment_count":3}'::jsonb
      FROM ops.set_runs WHERE id=%s""",(fresh,RUN))
    c=store(fresh);c.begin();c.prepared(context)
    next_request,_,_=c.reserve();check(next_request['index']==0)
    c.authorize(next_request);check(True)
    query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{shared_recognition,request_deadline}','0') WHERE id=%s",(fresh,))
    denies(lambda:c.authorize(next_request))
    check(query("SELECT raw_data->'shared_recognition'->>'in_flight' AS v FROM ops.segment_hits WHERE set_run_id=%s",(OTHER,))[0]['v']=='true')
    # Cancellation remains permanent even after provider quarantine expires.
    denies(lambda:store(OTHER,'9002').begin())
    # Known response may settle an expired reservation without ever sending again.
    c.finish(next_request,result(0));reset_clock()
    query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{shared_recognition,session_requests}','24') WHERE id=%s",(fresh,))
    check(c.reserve()[2]=='workflow_request_budget')
    query("UPDATE ops.set_runs SET source_metadata=jsonb_set(jsonb_set(source_metadata,'{shared_recognition,session_requests}','1'),'{shared_recognition,requests}','24') WHERE id=%s",(fresh,))
    check(c.reserve()[2]=='lifetime_request_budget')
    query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{shared_recognition,requests}','1') WHERE id=%s",(fresh,))
    exhausted={'shared_recognition':{'version':1,'valid':False,'in_flight':False,'attempts':[{'outcome':'failed'}]*8}}
    query("""INSERT INTO ops.segment_hits(set_run_id,lease_id,segment_index,timestamp_seconds,recognized,raw_data)
      SELECT %s,id,1,15,false,%s::jsonb FROM ops.set_run_leases WHERE set_run_id=%s AND segment_start_index=1""",
      (fresh,json.dumps(exhausted),fresh))
    check(c.reserve()[2]=='window_attempt_budget')
    check(c.state()[1]['requests']==1)
    # App UPDATE is not needed by the worker; full actual SQL succeeds with SELECT only.
    with connect():
        denies(lambda:query('SELECT * FROM app.sets FOR UPDATE'))
print(json.dumps({'done':True,'checks':checks}),file=sys.__stdout__,flush=True)
