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
from recognition_transport import RequestAuthorizationError

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
    except (RuntimeError,RecognitionPause,RecognitionFence,RequestAuthorizationError): checks+=1
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
    check(a.begin()['policy_version']==3)
    check(a.prepared(context,slot_count=2,lease_size=2)==2)
    b.begin();b.prepared(context,slot_count=2,lease_size=2)
    check(a.state()[1]['request_limit']==24)
    denies(a.begin)
    denies(lambda:store(workflow='9002').state())
    lease=a.claim_lease('worker0');second=a.claim_lease('worker1')
    check(lease['segment_start_index']==0 and lease['segment_end_index']==1)
    check(second['segment_start_index']==2)
    a.pause('recognition_retry_pending')
    check(a.state()[1]['reason']=='recognition_no_progress')
    first=a.reserve(0,lease['id'],'worker0')
    check(a.state()[1]['reason'] is None)
    concurrent=a.reserve(1,lease['id'],'worker0')
    across_slot=a.reserve(2,second['id'],'worker1')
    check(a.state()[1]['requests']==3 and a.state()[1]['in_flight'])
    other=b.claim_lease('other-worker')
    cross_run=b.reserve(0,other['id'],'other-worker');check(cross_run['index']==0)
    denies(lambda:a.reserve(0,lease['id'],'worker0'))
    denies(lambda:a.reserve(1,lease['id'],'wrong-worker'))
    denies(lambda:a.reserve(8,lease['id'],'worker0'))
    limited=Recognition(0,None,None,None,None,False,0,was_rate_limited=True,
                        error_type='RateLimited',http_status=429,retry_after_seconds=600,
                        retry_after_format='delta_seconds')
    # A concurrent reservation may temporarily occupy the last non429 slot.
    query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{shared_recognition,request_limit}','3') WHERE id=%s",(RUN,))
    from worker.jobs.shared_recognition import budget_reason
    now,temporary=a.state()
    check(budget_reason(temporary,now)=='recognition_requests_in_flight')
    a.pause('lifetime_request_budget')
    a.finish(first,limited,600)
    a.pause('lifetime_request_budget')
    check(a.state()[1]['reason']=='recognition_retry_pending')
    query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{shared_recognition,request_limit}','24') WHERE id=%s",(RUN,))
    a.finish(across_slot,result(2))
    check(a.state()[1]['in_flight'])
    a.finish(concurrent,result(1))
    check(not a.state()[1]['in_flight'])
    check(a.missing_indices(lease)==[0])
    denies(lambda:a.reserve(0,lease['id'],'worker0'))
    denies(lambda:a.finish(concurrent,result(1)))
    check(a.settle_lease(second,'worker1'))
    check(not a.settle_lease(lease,'worker0'))
    a.pause('recognition_retry_pending')
    state_a=a.state()[1]
    check(state_a['next_allowed_at']>0 and state_a['paused'])
    check('spacing_seconds' not in state_a)
    # New v2 runs are not blocked by another run's active HTTP request.
    check(query("SELECT ops.shared_recognition_dispatchable(%s,'{}'::jsonb) AS ok",(str(uuid.uuid4()),))[0]['ok'])
    # An owner with unknown outcomes never redispatches, even after expiry.
    check(not query('SELECT ops.shared_recognition_dispatchable(id,source_metadata) AS ok FROM ops.set_runs WHERE id=%s',(OTHER,))[0]['ok'])
    denies(lambda:store(OTHER,attempt='2').begin())
    b.finish(cross_run,result(0))
    before=query('SELECT raw_data FROM ops.segment_hits WHERE set_run_id=%s AND segment_index=1',(RUN,))[0]['raw_data']
    # Simulate clean app-finalizer requeue (no deletion of completed rows).
    query("UPDATE ops.set_run_leases SET status='pending' WHERE set_run_id=%s AND status='failed'",(RUN,))
    query("UPDATE ops.set_runs SET source_metadata=jsonb_set(jsonb_set(source_metadata,'{active_workflow_run_id}','\"9002\"'),'{shared_recognition,next_allowed_at}','0') WHERE id=%s",(RUN,))
    query("UPDATE ops.segment_hits SET raw_data=jsonb_set(raw_data,'{shared_recognition,next_allowed_at}','0') WHERE set_run_id=%s AND segment_index=0",(RUN,))
    reset_clock()
    a2=store(workflow='9002');check(a2.begin()['continuations']==2)
    check(a2.prepared(context,slot_count=2,lease_size=2)==2)
    lease2=a2.claim_lease('worker2');check(a2.missing_indices(lease2)==[0])
    for i in range(12):
        reset_clock()
        query("UPDATE ops.segment_hits SET raw_data=jsonb_set(raw_data,'{shared_recognition,next_allowed_at}','0') WHERE set_run_id=%s AND segment_index=0",(RUN,))
        ticket=a2.reserve(0,lease2['id'],'worker2')
        directive=a2.finish(ticket,limited)
        check(directive.delay_seconds >= 600)
        check(a2.state()[1]['throttle_requests']==i+2)
        check(a2.state()[1]['requests']-a2.state()[1]['throttle_requests']==2)
        denies(lambda:a2.reserve(0,lease2['id'],'worker2'))
    # Restart workflow without resetting exponential streak or completed windows.
    a2.settle_lease(lease2,'worker2');a2.pause('cooldown_pending')
    query("UPDATE ops.set_run_leases SET status='pending' WHERE set_run_id=%s AND status='failed'",(RUN,))
    query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{active_workflow_run_id}',to_jsonb('9003'::text)) WHERE id=%s",(RUN,))
    reset_clock()
    query("UPDATE ops.segment_hits SET raw_data=jsonb_set(raw_data,'{shared_recognition,next_allowed_at}','0') WHERE set_run_id=%s AND segment_index=0",(RUN,))
    a2=store(workflow='9003');check(a2.begin()['throttle_requests']==13)
    lease2=a2.claim_lease('worker2')
    again=a2.reserve(0,lease2['id'],'worker2');a2.finish(again,result(0))
    check(a2.settle_lease(lease2,'worker2'))
    check(a2.claim_lease('worker2') is None)
    a2.pause('done');check(not a2.state()[1]['paused'])
    after=query('SELECT raw_data FROM ops.segment_hits WHERE set_run_id=%s AND segment_index=1',(RUN,))[0]['raw_data']
    check(before==after)
    hits=query('SELECT * FROM ops.segment_hits WHERE set_run_id=%s ORDER BY segment_index',(RUN,))
    check(valid_coverage(hits,3,versioned=True,step=15))
    evidence=hits[0]['raw_data']['shared_recognition']
    check(len(evidence['attempts'])==14 and evidence['attempts'][0]['outcome']=='failed')
    check(evidence['attempts'][-1]['outcome']=='valid')
    denies(lambda:query('UPDATE ops.segment_hits SET raw_data=%s::jsonb WHERE set_run_id=%s AND segment_index=1',('{}',RUN)))
    denies(lambda:query('DELETE FROM ops.segment_hits WHERE set_run_id=%s',(RUN,)))
    # A clean legacy v1 policy can upgrade without modifying valid evidence.
    old_result=query('SELECT raw_data FROM ops.segment_hits WHERE set_run_id=%s AND segment_index=0',(OTHER,))[0]['raw_data']
    query("UPDATE ops.set_runs SET source_metadata=jsonb_set(jsonb_set(jsonb_set(source_metadata,'{active_workflow_run_id}','\"9002\"'),'{shared_recognition,policy_version}','1'),'{shared_recognition,spacing_seconds}','30') WHERE id=%s",(OTHER,))
    query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{shared_recognition,next_allowed_at}',to_jsonb(extract(epoch FROM now())+600)) WHERE id=%s",(OTHER,))
    upgraded=store(OTHER,workflow='9002')
    denies(upgraded.begin)
    check(query("SELECT (source_metadata->'shared_recognition'->>'next_allowed_at')::float8 > extract(epoch FROM now())+590 AS kept FROM ops.set_runs WHERE id=%s",(OTHER,))[0]['kept'])
    query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{shared_recognition,next_allowed_at}','0') WHERE id=%s",(OTHER,))
    check(upgraded.begin()['policy_version']==3)
    check(old_result==query('SELECT raw_data FROM ops.segment_hits WHERE set_run_id=%s AND segment_index=0',(OTHER,))[0]['raw_data'])
    b=upgraded
    b.pause('recognition_retry_pending')
    check(b.state()[1]['reason']=='recognition_no_progress')
    # A cancelled owner cannot reserve or settle more provider work.
    pending=b.claim_lease('other2')
    query("UPDATE ops.set_runs SET cancel_requested_at=now() WHERE id=%s",(OTHER,))
    denies(lambda:b.reserve(2,pending['id'],'other2'))
print(json.dumps({'done':True,'checks':checks}),file=sys.__stdout__,flush=True)
