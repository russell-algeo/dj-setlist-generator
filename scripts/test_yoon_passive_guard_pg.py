"""Old/new exact locked-path parity using the disposable PGlite bridge only."""
import copy, importlib.util, json, sys, uuid
from contextlib import contextmanager
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worker.jobs.yoon_resume_store import ResumeStore
from worker.jobs.yoon_sources import JACKSON, VERSION_CATALOG
from worker.jobs.yoon_queue import identity, validate_identity
# Default oracle travels with the test; optional external checkout supplies an
# independently loaded full baseline and must match the embedded locked method.
import hashlib, inspect
from fixtures import yoon_resume_locked_0354 as embedded
from worker.jobs.yoon_once import PRIVATE_GUARD
assert PRIVATE_GUARD == embedded.FROZEN_PRIVATE_GUARD, 'private guard drift from frozen baseline'
frozen_body = inspect.getsource(embedded.ResumeStore.locked)
assert hashlib.sha256(frozen_body.encode()).hexdigest() == embedded.LOCKED_SHA256
old = embedded
if len(sys.argv) > 1:
    base = Path(sys.argv[1])
    spec = importlib.util.spec_from_file_location('frozen_resume_store', base)
    old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
    assert inspect.getsource(old.ResumeStore.locked) == frozen_body, 'external baseline mismatch'
class Cursor:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, sql, params=()):
        print(json.dumps({'sql':sql,'params':params}, default=str),file=sys.__stdout__,flush=True)
        result=json.loads(sys.stdin.readline())
        if 'error' in result: raise RuntimeError(result['error'])
        self.rows=result['rows']
        executed.append(sql)
        if 'FROM ops.set_runs r, app.sets s,' in sql:
            global locked_bytes
            rows=copy.deepcopy(self.rows)
            for row in rows:
                if 'db_now' in row: row['db_now']=0
            locked_bytes=len(json.dumps(rows,separators=(',',':'),ensure_ascii=False).encode())
    def fetchone(self): return self.rows[0] if self.rows else None
    def fetchall(self): return self.rows
class Conn:
    def cursor(self): return Cursor()
    @contextmanager
    def transaction(self):
        c=Cursor(); c.execute('BEGIN')
        try: yield
        except BaseException: c.execute('ROLLBACK'); raise
        else: c.execute('COMMIT')
@contextmanager
def connect(): yield Conn()
def query(sql,params=()):
    c=Cursor();c.execute(sql,params);return c.rows
sys.stdout=sys.stderr
executed=[]
RUN='a0000000-0000-4000-8000-000000000010'
checks=0
from worker.jobs.yoon_resume_policy import initial_state
from worker.jobs.yoon_db_accounting import session
from worker.scheduler import build_scheduler_plan
from worker.pipeline.models import Recognition
from recognition_retry_policy import POLICY_VERSION
from tests.test_yoon_version_sources import descriptor as make_descriptor
members=[dict(user_id='synthetic-owner',role='manager'),dict(user_id='synthetic-viewer',role='viewer')]
source=next(iter(VERSION_CATALOG.values()))
now=query('SELECT extract(epoch from clock_timestamp())::float8 AS n')[0]['n']
state=initial_state(now)|dict(source_id=source.id,source_pins=source.pins(),members=members,
    initialization_mode='fresh',fresh_source_initialized=True,workflow_run_id='9001',run_attempt='1',
    continuations=1,session_started=now,session_requests=0,used_owners=['9001:1'],reason=None,
    recognition_mode='resumable',status='prepared',pacing_policy='shared-production-v2',
    expected_windows=source.windows,source_duration_seconds=source.duration,bounds=source.bounds,
    throttle_policy_version=POLICY_VERSION,throttle_requests=0,
    audio_sha256='a'*64,expected_audio_sha256='a'*64,
    scheduler_plan=build_scheduler_plan(source.windows).as_metadata())
metadata=dict(yoon_fixed_input=make_descriptor(source),yoon_resume=state)
row=query('SELECT id,submission_id,target_set_id,collection_id,requested_by FROM ops.set_runs WHERE id=%s',(RUN,))[0]
expected={**row,'descriptor':metadata['yoon_fixed_input'],'members':members}
metadata['yoon_queue_v1']=dict(version=1,identity=expected,status='running',
    enqueued_at=now-300,last_dispatched_at=now-100,dispatch_count=1,
    generation='00000000-0000-4000-8000-000000000001',owner=dict(workflow_run_id='9001',run_attempt='1'))

def install(m):
    query('UPDATE ops.set_runs SET status=%s,source_metadata=%s::jsonb WHERE id=%s',('private_resume_running',json.dumps(m),RUN))

def compare(label,m):
    global checks
    install(m);outcomes=[]
    for cls,method in [(old.ResumeStore,'require_owner'),(ResumeStore,'check_owner')]:
        s=cls(RUN,'9001','1',connect=connect)
        try:
            result=getattr(s,method)()
            if method=='check_owner':assert result is None
            outcomes.append(('ok',s.source.id))
        except Exception as e: outcomes.append((type(e).__name__,str(e)))
    assert outcomes[0]==outcomes[1],(label,outcomes)
    # Full require_owner still returns every original unknown/malformed-but-
    # dict-convertible field, not the passive subset.
    if outcomes[0][0]=='ok':
        assert ResumeStore(RUN,'9001','1',connect=connect).require_owner()==dict(m.get('yoon_resume') or {})
    checks+=1

values=[None,False,True,0,1,0.0,'','bad',[],[{}],{},[[],[]]]
compare('representative fresh v2',metadata)
for value in values:compare('root',value)
for key in ('yoon_fixed_input','yoon_resume','yoon_queue_v1'):
    m=copy.deepcopy(metadata);m.pop(key);compare(key+':missing',m)
    for value in values:
        m=copy.deepcopy(metadata);m[key]=value;compare(key,m)
fields=('version','initialization_mode','origin','provenance_seeded','source_id','source_pins',
        'members','workflow_run_id','run_attempt','review_required')
for key in fields:
    m=copy.deepcopy(metadata);m['yoon_resume'].pop(key,None);compare(key+':missing',m)
    for value in values:
        m=copy.deepcopy(metadata);m['yoon_resume'][key]=value;compare(key,m)
for value in [members[::-1],members[:1],members+[members[0]],[members[0],dict(user_id='synthetic-viewer',role='manager')]]:
    m=copy.deepcopy(metadata);m['yoon_resume']['members']=value;compare('members',m)
# Python dict() accepts a list of key/value pairs, including duplicate keys.
# These must bypass SQL object projection and retain original conversion behavior.
for st in [list(state.items()),list(state.items())+[['workflow_run_id','wrong']],
           list(state.items())+[['unknown',[1,2]]],list(state.items())+[['review_required',[]]],
           list(state.items())+[['review_required',[False]]]]:
    m=copy.deepcopy(metadata);m['yoon_resume']=st;compare('pair-list',m)
for key in metadata['yoon_fixed_input']:
    m=copy.deepcopy(metadata);m['yoon_fixed_input'].pop(key);compare('descriptor-missing:'+key,m)
    m=copy.deepcopy(metadata);m['yoon_fixed_input'][key]=False;compare('descriptor-false:'+key,m)
# Legacy Jackson accepts omitted source_id and still uses original source logic.
legacy=copy.deepcopy(metadata);legacy['yoon_fixed_input']=dict(JACKSON.pins(),recognition_mode='resumable',source_url='https://dropbox.com/SYNTHETIC')
legacy['yoon_resume'].pop('source_id');legacy['yoon_resume'].pop('source_pins')
compare('legacy Jackson',legacy)
for v in values:
    m=copy.deepcopy(legacy);m['yoon_resume']['source_id']=v;compare('legacy source_id',m)
# Full guard path through actual SQL, including cancellation and membership drift.
for table,key,bad,good in [('ops.set_runs','cancel_requested_at','now()','NULL'),
                         ('ops.submissions','cancel_requested_at','now()','NULL'),
                         ('ops.set_runs','create_playlist','true','false'),
                         ('ops.submissions','create_playlist','true','false')]:
    ident=RUN if table=='ops.set_runs' else row['submission_id'] if table=='ops.submissions' else row['target_set_id']
    query(f'UPDATE {table} SET {key}={bad} WHERE id=%s',(ident,))
    compare(table+':'+key,metadata)
    query(f'UPDATE {table} SET {key}={good} WHERE id=%s',(ident,))
query("UPDATE app.archive_collection_members SET role='manager' WHERE collection_id=%s AND user_id='synthetic-viewer'",(row['collection_id'],))
compare('actual member role changed',metadata)
query("UPDATE app.archive_collection_members SET role='viewer' WHERE collection_id=%s AND user_id='synthetic-viewer'",(row['collection_id'],))
# Both projections preserve SQL clauses and synchronized database check count.
install(metadata);sqls=[];sizes=[]
for method in ['require_owner','check_owner']:
    executed.clear()
    with session() as meter:
        s=ResumeStore(RUN,'9001','1',connect=connect);getattr(s,method)()
    counts=meter.snapshot()
    assert counts['connections_opened']==1 and counts['execute_calls']==4,counts
    assert counts['unmeasured_results']==4 and counts['measurement_failures']==0,counts
    sizes.append(locked_bytes)
    sqls.append(next(q for q in executed if 'FROM ops.set_runs r, app.sets s,' in q))
    assert not any(q.strip().upper().startswith(('UPDATE','INSERT','DELETE')) for q in executed)
    checks+=1
assert sqls[0][sqls[0].index('FROM ops.set_runs r,'):]==sqls[1][sqls[1].index('FROM ops.set_runs r,'):];checks+=1
assert sizes[1]<sizes[0]*.7,(sizes,source.id)
print(json.dumps({'fixture':'complete_fresh_v2_with_queue','source_id':source.id,
    'stage1_json_bytes':sizes[0],'passive_json_bytes':sizes[1],
    'reduction_percent':round(100*(1-sizes[1]/sizes[0]),2)}),file=sys.stderr);checks+=1
# Unknown state and metadata survive actual reserve/finish and writes. The new
# check cannot expose a partial state; require_owner and clock_state remain full.
m=copy.deepcopy(metadata);m['yoon_resume']['unknown']={'keep':[None,False,{'x':1}]};m['unrelated']={'preserve':'raw'};install(m)
s=ResumeStore(RUN,'9001','1',connect=connect)
assert s.check_owner() is None
assert s.require_owner()==m['yoon_resume'];assert s.clock_state()[1]==m['yoon_resume'];checks+=3
query("INSERT INTO ops.set_run_leases(set_run_id,slot_index,segment_start_index,segment_end_index,status) VALUES(%s,0,0,0,'pending')",(RUN,))
ticket=s.reserve(0);s.finish(Recognition(0,None,None,None,{'matches':[]},False,0,http_status=200),ticket,0)
s.write({'status':'prepared','test_unknown_write':True})
saved=query('SELECT source_metadata FROM ops.set_runs WHERE id=%s',(RUN,))[0]['source_metadata']
assert saved['yoon_resume']['unknown']==m['yoon_resume']['unknown']
assert saved['unrelated']==m['unrelated'] and saved['yoon_queue_v1']==m['yoon_queue_v1']
assert saved['yoon_resume']['requests']==1 and saved['yoon_resume']['test_unknown_write'] is True;checks+=3
# New guard does not mutate state even after a completed real attempt.
before=json.dumps(saved,sort_keys=True);s.check_owner()
assert before==json.dumps(query('SELECT source_metadata FROM ops.set_runs WHERE id=%s',(RUN,))[0]['source_metadata'],sort_keys=True);checks+=1
print(json.dumps({'done':True,'checks':checks}),file=sys.__stdout__,flush=True)
