"""Old/new exact locked-path parity using the disposable PGlite bridge only."""
import copy, importlib.util, json, sys, uuid
from contextlib import contextmanager
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worker.jobs.yoon_resume_store import ResumeStore
from worker.jobs.yoon_sources import JACKSON
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
        if 'FROM ops.set_runs r, app.sets s,' in sql:
            global locked_bytes
            rows=copy.deepcopy(self.rows)
            for row in rows: row['db_now']=0
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
RUN='a0000000-0000-4000-8000-000000000010'
checks=0
members=[dict(user_id='synthetic-owner',role='manager'),dict(user_id='synthetic-viewer',role='viewer')]
state=dict(version=1,members=members,workflow_run_id='9001',run_attempt='1',unknown={'keep':[None,False,{'x':1}]})
descriptor=dict(JACKSON.pins(),recognition_mode='resumable',source_url='https://www.dropbox.com/synthetic')
metadata=dict(yoon_fixed_input=descriptor,yoon_resume=state,unrelated={'raw_evidence':'x'*10000})
variants=[None,False,0,'',1,'bad',[],[{}],{}]
fixtures=[('valid',metadata)]
for v in variants: fixtures.append(('root:'+repr(v),v))
for key in ['yoon_fixed_input','yoon_resume','yoon_queue_v1']:
    m=copy.deepcopy(metadata);m.pop(key,None);fixtures.append((key+':missing',m))
    for v in variants:
        m=copy.deepcopy(metadata);m[key]=v;fixtures.append((key+':'+repr(v),m))
for key in ['members','source_pins','workflow_run_id','run_attempt','version','source_id']:
    for v in variants:
        m=copy.deepcopy(metadata);m['yoon_resume'][key]=v;fixtures.append(('state:'+key+repr(v),m))
for v in [members[::-1],members[:1],members+[members[0]],[members[0],dict(user_id='synthetic-viewer',role='manager')]]:
    m=copy.deepcopy(metadata);m['yoon_resume']['members']=v;fixtures.append(('members-exact',m))
# Query text itself must be identical after the projection, so guards and locks
# cannot accidentally pass merely because our valid fixture does not exercise them.
import inspect
old_body=inspect.getsource(old.ResumeStore.locked)
new_body=inspect.getsource(ResumeStore.locked)
assert old_body[old_body.index('FROM ops.set_runs r,'):]==new_body[new_body.index('FROM ops.set_runs r,'):]
checks+=1
for label,m in fixtures:
    query('UPDATE ops.set_runs SET status=%s,source_metadata=%s::jsonb WHERE id=%s',('private_resume_running',json.dumps(m),RUN))
    outcomes=[]
    for cls in [old.ResumeStore,ResumeStore]:
        s=cls(RUN,'9001','1',connect=connect)
        try:
            with s.locked() as (cur,row,st):
                selected={k:row[k] for k in ['id','submission_id','target_set_id','collection_id','requested_by','status']}
                relevant=row['source_metadata']
                selected['source_metadata']={k:v for k,v in relevant.items() if k in ['yoon_fixed_input','yoon_resume','yoon_queue_v1']}
                outcomes.append(('ok',selected,st))
        except Exception as e: outcomes.append((type(e).__name__,str(e)))
    assert outcomes[0]==outcomes[1],(label,outcomes)
    checks+=1
# A write through the compact row must preserve unrelated metadata and unknown state.
query('UPDATE ops.set_runs SET source_metadata=%s::jsonb WHERE id=%s',(json.dumps(metadata),RUN))
s=ResumeStore(RUN,'9001','1',connect=connect)
with s.locked() as (cur,row,st):
    st['test_mutation']='saved';s.save_state(cur,st)
saved=query('SELECT source_metadata FROM ops.set_runs WHERE id=%s',(RUN,))[0]['source_metadata']
assert saved=={**metadata,'yoon_resume':{**state,'test_mutation':'saved'}}; checks+=1
try:
    with s.locked() as (cur,row,st):
        st['unknown']='should rollback';s.save_state(cur,st);raise ValueError('rollback')
except ValueError:pass
assert saved==query('SELECT source_metadata FROM ops.set_runs WHERE id=%s',(RUN,))[0]['source_metadata'];checks+=1
# Exact queued identity remains available, including unknown descriptor fields.
with s.locked() as (_,row,st): expected=identity(row,st)
for generation in ['00000000-0000-4000-8000-000000000001',None,False,{},'malformed']:
    queue=dict(version=1,identity=expected,status='running',generation=generation,unknown={'keep':True})
    m={**metadata,'yoon_queue_v1':queue}
    query('UPDATE ops.set_runs SET source_metadata=%s::jsonb WHERE id=%s',(json.dumps(m),RUN))
    with s.locked() as (_,row,st):
        assert row['source_metadata']['yoon_queue_v1']==queue
        validate_identity(row,st,queue)
    checks+=1
# Application-visible UTF-8 JSON row bytes, not PostgreSQL wire/Neon billing.
for label,padding in [('synthetic_typical_4KiB',4096),('synthetic_padded_1MiB',1048576)]:
    m={**metadata,'unrelated':{'synthetic_evidence':'x'*padding}}
    query('UPDATE ops.set_runs SET source_metadata=%s::jsonb WHERE id=%s',(json.dumps(m),RUN))
    sizes=[]
    for cls in [old.ResumeStore,ResumeStore]:
        with cls(RUN,'9001','1',connect=connect).locked(): pass
        sizes.append(locked_bytes)
    assert sizes[1]<sizes[0];checks+=1
    print(json.dumps({'fixture':label,'old_json_bytes':sizes[0],'new_json_bytes':sizes[1],
                      'reduction_percent':round(100*(1-sizes[1]/sizes[0]),2)}),file=sys.stderr)
print(json.dumps({'done':True,'checks':checks}),file=sys.__stdout__,flush=True)
