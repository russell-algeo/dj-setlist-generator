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
from worker.jobs.yoon_spotify_enrich import RUN, digest
from worker.jobs.yoon_metadata_enrich import MetadataStore, KEY
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
                if value is not None and field['dataTypeID'] in (114,3802):row[key]=json.loads(value)
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

# Every additional finite registration exercises real role-limited staging and owner apply.
from tests.test_yoon_enrichment_registrations import fixture
from worker.jobs.yoon_sources import CATALOG
from worker.jobs.yoon_enrichment_registrations import ADDITIONAL_ENRICHMENT_RUNS
from worker.jobs.yoon_spotify_enrich import DONALD_SCOPE, DONALD_MEMBERS
from worker.pipeline.enrich import build_set_payload
from setlist_builder import Track
from scripts.yoon_metadata_pins import snapshot_sql, prepare_pins
from scripts.yoon_metadata_apply import snapshot_sql as apply_snapshot_sql, prepare_apply, PUBLICATION_KEY
query('CREATE ROLE synthetic_metadata_worker')
query('GRANT USAGE ON SCHEMA app,ops TO synthetic_metadata_worker')
query('GRANT SELECT ON ALL TABLES IN SCHEMA app,ops TO synthetic_metadata_worker')
query('GRANT UPDATE ON ops.set_runs,ops.submissions,ops.segment_hits TO synthetic_metadata_worker')
col=DONALD_SCOPE['collection_id'];owner=DONALD_SCOPE['requested_by']
for i,member in enumerate(DONALD_MEMBERS):
    query('INSERT INTO authn.users(id,email) VALUES(%s,%s)',(member['user_id'],f'finite-{i}@example.invalid'))
query("INSERT INTO app.archive_collections(id,slug,title) VALUES(%s,'finite','Synthetic finite')",(col,))
for member in DONALD_MEMBERS:
    query('INSERT INTO app.archive_collection_members(collection_id,user_id,role) VALUES(%s,%s,%s)',(col,member['user_id'],member['role']))
for index,run in enumerate(ADDITIONAL_ENRICHMENT_RUNS):
    row,state,hits,expected=fixture(run);sid=row['target_set_id'];sub=row['submission_id']
    mix=dict(title='Synthetic',artist_name='Synthetic DJ',duration=CATALOG[state['source_id']].duration)
    query("INSERT INTO app.sets(id,slug,title,normalized_title,visibility,collection_id,metadata) VALUES(%s,%s,'Synthetic','synthetic','private',%s,%s::jsonb)",(sid,f'finite-{index}',col,json.dumps(dict(mixInfo=mix,boundaryNote='preserve'))))
    query("INSERT INTO ops.submissions(id,requested_by,mode,status,visibility,collection_id) VALUES(%s,%s,'set','completed','private',%s)",(sub,owner,col))
    metadata=dict(row['source_metadata'],yoon_resume=state)
    query("INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,publication_visibility,target_set_id,published_set_id,collection_id,source_metadata) VALUES(%s,%s,%s,'private_resume_complete','local:synthetic','private',%s,%s,%s,%s::jsonb)",(run,sub,owner,sid,sid,col,json.dumps(metadata)))
    query("INSERT INTO ops.segment_hits(set_run_id,segment_index,timestamp_seconds,recognized,raw_data) SELECT %s::uuid,segment_index,segment_index*15,false,raw_data FROM jsonb_to_recordset(%s::jsonb) AS h(segment_index int,raw_data jsonb)",(run,json.dumps(hits)))
    track=state['clustered_setlist'][0];eid=str(uuid.uuid4());meta=dict(track,position=1,privateRecognitionProvenance={'runId':run})
    query("INSERT INTO app.set_entries(id,set_id,position,display_artist,display_title,start_time_seconds,end_time_seconds,confidence,detection_count,cluster_density,cluster_span,metadata) VALUES(%s,%s,1,%s,%s,0,60,%s,3,1,3,%s::jsonb)",(eid,sid,track['artist'],track['title'],track['confidence'],json.dumps(meta)))
    pin_snapshot=query(snapshot_sql(run))[0]['value'];pins=prepare_pins(run,pin_snapshot)
    s=MetadataStore(pins,'1','1',run);s.connect=connect
    with s.locked() as(cur,r,tracks):before=s.snapshot(cur,r)
    payload=build_set_payload(enriched_tracks=[dict(track=Track(**track),metadata={'bpm':122,'discogs_url':'https://www.discogs.com/release/123','platform_matches':{'spotify':{'status':'unverified'},'youtube':{'status':'unverified'}}})],mix_info=dict(mix,artist_profile_image='https://example.invalid/profile.jpg'))
    query('SET ROLE synthetic_metadata_worker')
    ticket,got,got_mix=s.reserve();check(got==state['clustered_setlist']);check(got_mix==mix)
    denies(s.reserve)
    s.finish(ticket,payload);check(s.reserve()==(None,None,None))
    with s.locked() as(cur,r,tracks):
        check(s.snapshot(cur,r)==before)
        receipt=r['source_metadata'][KEY];check(receipt['applied'] is False and receipt['status']=='complete')
    query('RESET ROLE')
    snap=json.loads(query(apply_snapshot_sql(run))[0]['snapshot_json']);plan=prepare_apply(run,snap)
    def apply():
        with connect() as conn,conn.transaction(),conn.cursor() as cur:
            for sql in plan['sql_statements']:cur.execute(sql)
    query('SET ROLE synthetic_metadata_worker');denies(apply);query('RESET ROLE')
    apply();apply()
    entry=query('SELECT id,metadata FROM app.set_entries WHERE set_id=%s',(sid,))[0]
    check(str(entry['id'])==eid);check(entry['metadata']['bpm']==122)
    check(entry['metadata']['privateRecognitionProvenance']==meta['privateRecognitionProvenance'])
    check(query("SELECT source_metadata->'yoon_resume' AS state FROM ops.set_runs WHERE id=%s",(run,))[0]['state']==state)
    check(query("SELECT source_metadata->%s->>'status' AS status FROM ops.set_runs WHERE id=%s",(PUBLICATION_KEY,run))[0]['status']=='complete')
    check(query('SELECT visibility FROM app.sets WHERE id=%s',(sid,))[0]['visibility']=='private')
check(query('SELECT count(*) AS n FROM app.public_sets')[0]['n']==0)
check(query('SELECT count(*) AS n FROM app.tracks')[0]['n']==0)
check(query('SELECT count(*) AS n FROM app.artists')[0]['n']==0)
print(json.dumps({'done':True,'checks':checks}),file=sys.__stdout__,flush=True)
