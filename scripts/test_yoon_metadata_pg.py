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

# Full-metadata integration: real Store SQL, real migrations, synthetic records.
from setlist_builder import Track
from worker.pipeline.enrich import build_set_payload
query("INSERT INTO authn.users(id,email) VALUES('owner','owner@example.invalid'),('viewer','viewer@example.invalid')")
col='20000000-0000-4000-8000-000000000001';sid='10000000-0000-4000-8000-000000000001';sub='30000000-0000-4000-8000-000000000001'
query("INSERT INTO app.archive_collections(id,slug,title) VALUES(%s,'synthetic','Synthetic')",(col,))
query("INSERT INTO app.archive_collection_members(collection_id,user_id,role) VALUES(%s,'owner','manager'),(%s,'viewer','viewer')",(col,col))
mix=dict(title='Synthetic',artist_name='Synthetic DJ',duration=7200)
query("INSERT INTO app.sets(id,slug,title,normalized_title,visibility,collection_id,metadata) VALUES(%s,'synthetic','Synthetic','synthetic','private',%s,%s::jsonb)",(sid,col,json.dumps(dict(mixInfo=mix,boundaryNote='preserve'))))
query("INSERT INTO ops.submissions(id,requested_by,mode,status,visibility,collection_id) VALUES(%s,'owner','set','completed','private',%s)",(sub,col))
tracks=[]
for i in range(28):
    known=i in (0,2)
    tracks.append(dict(title='Synthetic '+str(i) if known else 'Unknown Track',
        artist='Synthetic' if known else 'Unknown',start_time=i*60,end_time=(i+1)*60,
        confidence='HIGH' if known else 'UNCERTAIN',detection_count=3 if known else 0,
        cluster_density=1 if known else 0,cluster_span=3 if known else 0,
        shazam_track_id=str(i) if known else None,isrc=None,segment_indices=[i*4] if known else []))
state={'used_owners':['1:1'],'status':'complete','valid_responses':479,'clustered_setlist':tracks,'members':[{'user_id':'owner','role':'manager'},{'user_id':'viewer','role':'viewer'}]}
metadata={'yoon_resume':state,'yoon_fixed_input':{}}
query("INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,publication_visibility,target_set_id,published_set_id,collection_id,source_metadata) VALUES(%s,%s,'owner','private_resume_complete','local:synthetic','private',%s,%s,%s,%s::jsonb)",(RUN,sub,sid,sid,col,json.dumps(metadata)))
for i in range(479):
    response=dict(timestamp=i*15,segment_index=i,track_title=None,artist=None,shazam_track_id=None,raw_data={'matches':[]},recognized=False,http_status=200)
    data={'private_jackson_v2':{'valid':True,'response':response,'attempts':[dict(state='finished',workflow_run_id='1',run_attempt='1',diagnostic=dict(http_status=200,outcome='no_match'))]}}
    query('INSERT INTO ops.segment_hits(set_run_id,segment_index,timestamp_seconds,recognized,raw_data) VALUES(%s,%s,%s,false,%s::jsonb)',(RUN,i,i*15,json.dumps(data)))
ids=[]
for position,index in enumerate((0,2),1):
    track=tracks[index];entry_id=str(uuid.uuid4());ids.append(entry_id)
    meta=dict(track,position=position,privateRecognitionProvenance={'sourceSpans':[{'start':1,'end':2}],'runId':RUN})
    query('''INSERT INTO app.set_entries(id,set_id,position,display_artist,display_title,start_time_seconds,
        end_time_seconds,confidence,detection_count,cluster_density,cluster_span,metadata)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)''',
        (entry_id,sid,position,track['artist'],track['title'],track['start_time'],track['end_time'],track['confidence'],track['detection_count'],track['cluster_density'],track['cluster_span'],json.dumps(meta)))
# Include one legitimately seeded legacy window so origin locking/fingerprints
# are exercised along with the fresh per-attempt evidence.
origin_id='40000000-0000-4000-8000-000000000001'
seed=query('SELECT raw_data FROM ops.segment_hits WHERE set_run_id=%s AND segment_index=0',(RUN,))[0]['raw_data']['private_jackson_v2']
origin_metadata={'yoon_analysis':{'workflow_run_id':'2','status':'partial',
    'raw_recognitions':[seed['response']],
    'recognition_diagnostics':{'attempts':[{'segment_index':0,'http_status':200}]}}}
query("INSERT INTO ops.set_runs(id,submission_id,requested_by,status,source_url,publication_visibility,target_set_id,collection_id,source_metadata) VALUES(%s,%s,'owner','private_analysis_partial','local:synthetic','private',%s,%s,%s::jsonb)",(origin_id,sub,sid,col,json.dumps(origin_metadata)))
origin_hash=query("SELECT encode(digest(source_metadata::text,'sha256'),'hex') AS hash FROM ops.set_runs WHERE id=%s",(origin_id,))[0]['hash']
pin=dict(run_id=origin_id,metadata_sha256=origin_hash,workflow_run_id='2',valid_windows=1)
state['origin']=pin
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_resume}',%s::jsonb) WHERE id=%s",(json.dumps(state),RUN))
seed.update(origin=dict(pin,segment_index=0),attempts=[])
query('UPDATE ops.segment_hits SET raw_data=%s::jsonb WHERE set_run_id=%s AND segment_index=0',(json.dumps({'private_jackson_v2':seed}),RUN))
expected=dict(target_set_id=sid,collection_id=col,submission_id=sub,requested_by='owner',source_digest=digest({}),cluster_digest=digest(tracks))
s=object.__new__(MetadataStore);s.stage_only=False;s.run_id=RUN;s.connect=connect;s.owner={'workflow_run_id':'1','run_attempt':'1'};s.expected=expected
with s.locked() as (cur,row,got):
    before=s.snapshot(cur,row)
s.publication_digest=digest(before)
from scripts.yoon_metadata_pins import snapshot_sql, prepare_pins
pin_snapshot=query(snapshot_sql(RUN))[0]['value']
check(prepare_pins(RUN,pin_snapshot)==dict(expected,rich_metadata=True,publication_digest=s.publication_digest))
# Model the exact race boundary after Store.locked validates the old membership.
# Independent-connection lock timing is not claimed by this single-engine test.
original_snapshot=s.snapshot
def changed_audience(cur,row):
    cur.execute("UPDATE app.archive_collection_members SET role='manager' WHERE collection_id=%s AND user_id='viewer'",(col,))
    return original_snapshot(cur,row)
s.snapshot=changed_audience
denies(s.reserve)
s.snapshot=original_snapshot
check(query("SELECT role FROM app.archive_collection_members WHERE collection_id=%s AND user_id='viewer'",(col,))[0]['role']=='viewer')
ticket,got,got_mix=s.reserve();check(got==tracks);check(got_mix==mix);denies(s.reserve)
payload=build_set_payload(enriched_tracks=[dict(track=Track(**track),metadata={
    'spotify_album_art':'https://example.invalid/art.jpg' if track['artist']!='Unknown' else None,
    'bpm':122 if track['artist']!='Unknown' else None,
    'discogs_url':'https://www.discogs.com/release/123' if track['artist']!='Unknown' else None,
    'platform_matches':{'spotify':{'status':'unverified'},'youtube':{'status':'unverified'}}}) for track in tracks],
    mix_info=dict(mix,artist_profile_image='https://example.invalid/profile.jpg',artist_profile_name='Literal $private_metadata_apply$ marker'))
denies(lambda:s.finish('wrong',payload))
s.snapshot=changed_audience
denies(lambda:s.finish(ticket,payload))
s.snapshot=original_snapshot
check(query("SELECT role FROM app.archive_collection_members WHERE collection_id=%s AND user_id='viewer'",(col,))[0]['role']=='viewer')
query("UPDATE ops.submissions SET cancel_requested_at=now() WHERE id=%s",(sub,))
denies(lambda:s.finish(ticket,payload))
query("UPDATE ops.submissions SET cancel_requested_at=NULL WHERE id=%s",(sub,))
query("UPDATE app.set_entries SET metadata=metadata||'{\"extra\":true}'::jsonb WHERE id=%s",(ids[0],))
denies(lambda:s.finish(ticket,payload))
query("UPDATE app.set_entries SET metadata=metadata-'extra' WHERE id=%s",(ids[0],))
saved_payload=json.loads(json.dumps(payload))
old_url='https://open.spotify.com/track/'+'A'*22
new_url='https://open.spotify.com/track/'+'B'*22
old_entry=query('SELECT metadata FROM app.set_entries WHERE id=%s',(ids[0],))[0]['metadata']
linked_entry=dict(old_entry,spotify_url=old_url,platform_matches={'spotify':{'status':'matched','url':old_url}})
query('UPDATE app.set_entries SET metadata=%s::jsonb WHERE id=%s',(json.dumps(linked_entry),ids[0]))
with s.locked() as (cur,row,got):conflict_before=s.snapshot(cur,row)
s.publication_digest=digest(conflict_before)
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,ARRAY[%s,'publication_digest'],to_jsonb(%s::text)) WHERE id=%s",(KEY,s.publication_digest,RUN))
payload['tracks'][0].update(spotify_url=new_url,platform_matches={'spotify':{'status':'matched','url':new_url}})
s.finish(ticket,payload)
with s.locked() as (cur,row,got):
    check(s.snapshot(cur,row)==conflict_before)
    receipt=row['source_metadata'][KEY]
check(receipt['applied'] is False and len(receipt['conflicts'])==1)
# Synthetic fixture reset, not an automatic production conflict retry.
query('UPDATE app.set_entries SET metadata=%s::jsonb WHERE id=%s',(json.dumps(old_entry),ids[0]))
s.publication_digest=digest(before)
query("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,ARRAY[%s],%s::jsonb) WHERE id=%s",(KEY,json.dumps(dict(version=1,status='reserved',ticket=ticket,owner=s.owner,input=expected,publication_digest=s.publication_digest)),RUN))
payload=saved_payload
# Reproduce the deployment privilege boundary: app SELECT, ops writes only.
query('CREATE ROLE synthetic_metadata_worker')
query('GRANT USAGE ON SCHEMA app,ops TO synthetic_metadata_worker')
query('GRANT SELECT ON ALL TABLES IN SCHEMA app,ops TO synthetic_metadata_worker')
query('GRANT UPDATE ON ops.set_runs,ops.submissions,ops.segment_hits TO synthetic_metadata_worker')
query('SET ROLE synthetic_metadata_worker')
s.stage_only=False
denies(lambda:s.finish(ticket,payload))  # original app FOR UPDATE was forbidden
s.stage_only=True
s.finish(ticket,payload)
check(s.reserve()==(None,None,None))
check(query('SELECT count(*) AS n FROM app.set_entries WHERE set_id=%s',(sid,))[0]['n']==2)
query('RESET ROLE')
from scripts.yoon_metadata_apply import snapshot_sql as apply_snapshot_sql, prepare_apply, PUBLICATION_KEY
query("UPDATE ops.submissions SET requested_by='viewer' WHERE id=%s",(sub,))
check(query(apply_snapshot_sql(RUN))==[])
query("UPDATE ops.submissions SET requested_by='owner' WHERE id=%s",(sub,))
query('UPDATE ops.set_runs SET published_set_id=NULL WHERE id=%s',(RUN,))
check(query(apply_snapshot_sql(RUN))==[])
query('UPDATE ops.set_runs SET published_set_id=%s WHERE id=%s',(sid,RUN))
operator_snapshot=json.loads(query(apply_snapshot_sql(RUN))[0]['snapshot_json'])
operator_plan=prepare_apply(RUN,operator_snapshot)
def owner_apply():
    with connect() as conn,conn.transaction(),conn.cursor() as cur:
        for sql in operator_plan['sql_statements']:cur.execute(sql)
query("UPDATE app.archive_collection_members SET role='manager' WHERE collection_id=%s AND user_id='viewer'",(col,))
denies(owner_apply)
query("UPDATE app.archive_collection_members SET role='viewer' WHERE collection_id=%s AND user_id='viewer'",(col,))
query("UPDATE ops.submissions SET requested_by='viewer' WHERE id=%s",(sub,))
denies(owner_apply)
query("UPDATE ops.submissions SET requested_by='owner' WHERE id=%s",(sub,))
query('UPDATE ops.set_runs SET published_set_id=NULL WHERE id=%s',(RUN,))
denies(owner_apply)
query('UPDATE ops.set_runs SET published_set_id=%s WHERE id=%s',(sid,RUN))
def stale_isolation():
    with connect() as conn,conn.transaction(),conn.cursor() as cur:
        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        for sql in operator_plan['sql_statements']:cur.execute(sql)
denies(stale_isolation)
query("UPDATE ops.set_runs SET source_metadata=source_metadata||'{\"unexpected\":true}'::jsonb WHERE id=%s",(origin_id,))
denies(owner_apply)
query("UPDATE ops.set_runs SET source_metadata=source_metadata-'unexpected' WHERE id=%s",(origin_id,))
owner_apply();owner_apply()  # original reviewed plan replay is a no-op
check(query("SELECT source_metadata->%s->>'status' AS state FROM ops.set_runs WHERE id=%s",(PUBLICATION_KEY,RUN))[0]['state']=='complete')
with s.locked() as (cur,row,got):after=s.snapshot(cur,row);receipt=row['source_metadata'][KEY]
check(len(after['entries'])==28);check(receipt['applied'] is False)
check(after['entries'][0]['id']==ids[0]);check(after['entries'][2]['id']==ids[1])
check(after['entries'][0]['metadata']['privateRecognitionProvenance']==before['entries'][0]['metadata']['privateRecognitionProvenance'])
for a,b in zip((after['entries'][0],after['entries'][2]),before['entries']):
    check({k:v for k,v in a.items() if k not in ('metadata','position','updated_at')}=={k:v for k,v in b.items() if k not in ('metadata','position','updated_at')})
check(after['set']['metadata']['boundaryNote']=='preserve')
check(after['set']['metadata']['mixInfo']['artist_profile_name']=='Literal $private_metadata_apply$ marker')
check(after['set']['metadata']['summary']['total_tracks']==28)
check(after['set']['metadata']['mixInfo']['artist_profile_image']=='https://example.invalid/profile.jpg')
check(after['set']['visibility']=='private')
check(query("SELECT source_metadata->'yoon_resume' AS state FROM ops.set_runs WHERE id=%s",(RUN,))[0]['state']==state)
check(query('SELECT count(*) AS n FROM app.tracks')[0]['n']==0)
check(query('SELECT count(*) AS n FROM app.artists')[0]['n']==0)
# Replayed publication must also verify the post-apply entry state.
query("UPDATE app.set_entries SET metadata=metadata||'{\"changed\":true}'::jsonb WHERE id=%s",(ids[0],))
denies(owner_apply)
print(json.dumps({'done':True,'checks':checks}),file=sys.__stdout__,flush=True)
