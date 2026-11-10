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
from worker.jobs.yoon_spotify_enrich import Store, RUN, KEY, digest
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
    yield Conn()
def query(sql,params=()):
    c=Cursor();c.execute(sql,params);return c.rows
sys.stdout=sys.stderr
checks=0
def check(value):
    global checks
    assert value;checks+=1
def denies(fn):
    global checks
    try:fn()
    except RuntimeError:checks+=1
    else:raise AssertionError('expected denial')

query("INSERT INTO authn.users(id,email) VALUES('owner','owner@example.invalid'),('viewer','viewer@example.invalid')")
col='20000000-0000-4000-8000-000000000001';sid='10000000-0000-4000-8000-000000000001';sub='30000000-0000-4000-8000-000000000001'
query("INSERT INTO app.archive_collections(id,slug,title) VALUES(%s,'synthetic','Synthetic')",(col,))
query("INSERT INTO app.archive_collection_members(collection_id,user_id,role) VALUES(%s,'owner','manager'),(%s,'viewer','viewer')",(col,col))
query("INSERT INTO app.sets(id,slug,title,normalized_title,visibility,collection_id) VALUES(%s,'synthetic','Synthetic','synthetic','private',%s)",(sid,col))
query("INSERT INTO ops.submissions(id,requested_by,mode,status,visibility,collection_id) VALUES(%s,'owner','set','completed','private',%s)",(sub,col))
tracks=[{'title':'Synthetic','artist':'Synthetic'} for _ in range(28)]
state={'used_owners':['1:1'],'status':'complete','valid_responses':479,'clustered_setlist':tracks,'members':[{'user_id':'owner','role':'manager'},{'user_id':'viewer','role':'viewer'}]}
metadata={'yoon_resume':state,'yoon_fixed_input':{}}
query("INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,publication_visibility,target_set_id,collection_id,source_metadata) VALUES(%s,%s,'owner','private_resume_complete','local:synthetic','private',%s,%s,%s::jsonb)",(RUN,sub,sid,col,json.dumps(metadata)))
for i in range(479):
    response=dict(timestamp=i*15,segment_index=i,track_title=None,artist=None,shazam_track_id=None,raw_data={'matches':[]},recognized=False,http_status=200)
    data={'private_jackson_v2':{'valid':True,'response':response,'attempts':[dict(state='finished',workflow_run_id='1',run_attempt='1',diagnostic=dict(http_status=200,outcome='no_match'))]}}
    query('INSERT INTO ops.segment_hits(set_run_id,segment_index,timestamp_seconds,recognized,raw_data) VALUES(%s,%s,%s,false,%s::jsonb)',(RUN,i,i*15,json.dumps(data)))
expected=dict(target_set_id=sid,collection_id=col,submission_id=sub,requested_by='owner',source_digest=digest({}),cluster_digest=digest(tracks))
s=object.__new__(Store);s.run_id=RUN;s.connect=connect;s.owner={'workflow_run_id':'1','run_attempt':'1'};s.expected=expected
before=query("SELECT row_to_json(s)::text AS data FROM app.sets s WHERE id=%s",(sid,))[0]['data']
ticket,got=s.reserve();check(got==tracks);denies(s.reserve)
denies(lambda:s.finish('wrong',[]))
check(query("SELECT source_metadata->%s->>'status' AS state FROM ops.set_runs WHERE id=%s",(KEY,RUN))[0]['state']=='reserved')
query("UPDATE ops.submissions SET cancel_requested_at=now() WHERE id=%s",(sub,))
denies(lambda:s.finish(ticket,[]))
query("UPDATE ops.submissions SET cancel_requested_at=NULL WHERE id=%s",(sub,))
s.finish(ticket,[]);check(s.reserve()==(None,tracks))
check(query("SELECT row_to_json(s)::text AS data FROM app.sets s WHERE id=%s",(sid,))[0]['data']==before)
check(query("SELECT source_metadata->'yoon_resume' AS state FROM ops.set_runs WHERE id=%s",(RUN,))[0]['state']==state)
# Exercise the separate recheck receipt through the actual SQL engine. Synthetic
# identity and result hash replace only the fixed finite-run pins in this test.
from worker.jobs import yoon_spotify_recheck as recheck
indices=sorted(list(recheck.INDICES)+[i for i in range(28) if i not in recheck.INDICES][:12])
results=[{'index':i,'spotify_url':None if i in recheck.INDICES else 'synthetic-verified'} for i in indices]
prior=dict(status='complete',input=expected,results=results,results_digest=digest(results))
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_spotify_enrichment}',%s::jsonb) WHERE id=%s",(json.dumps(prior),RUN))
r=object.__new__(recheck.RecheckStore);r.run_id=RUN;r.connect=connect;r.expected=expected;r.owner=s.owner
with patch.object(recheck,'DONALD_RUN',RUN),patch.object(recheck,'PRIOR_DIGEST',digest(results)):
    ticket,got=r.reserve();check(got==tracks);denies(r.reserve)
    denies(lambda:r.finish('wrong',[{'index':i} for i in recheck.INDICES]))
    check(query("SELECT source_metadata->%s AS state FROM ops.set_runs WHERE id=%s",(KEY,RUN))[0]['state']==prior)
    r.finish(ticket,[{'index':i,'diagnostic':{'status':'no_verified_candidate'}} for i in recheck.INDICES])
    check(r.reserve()==(None,tracks))
    check(query("SELECT source_metadata->%s AS state FROM ops.set_runs WHERE id=%s",(KEY,RUN))[0]['state']==prior)
    check(query("SELECT source_metadata->%s->>'status' AS state FROM ops.set_runs WHERE id=%s",(recheck.RECHECK_KEY,RUN))[0]['state']=='complete')
check(query("SELECT row_to_json(s)::text AS data FROM app.sets s WHERE id=%s",(sid,))[0]['data']==before)
check(query("SELECT source_metadata->'yoon_resume' AS state FROM ops.set_runs WHERE id=%s",(RUN,))[0]['state']==state)
denies(lambda:query("UPDATE app.sets SET visibility='public' WHERE id=%s",(sid,)))
print(json.dumps({'done':True,'checks':checks}),file=sys.__stdout__,flush=True)
