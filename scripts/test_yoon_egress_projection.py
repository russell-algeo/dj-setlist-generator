"""Synthetic SQL projection oracle. No live access."""
import ast,copy,json,sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from worker.jobs import yoon_admission as a,yoon_queue as q
from worker.jobs.yoon_sources import CATALOG

def fixtures():
 s=CATALOG['airgordon-saturday-mean-gaps-v2'];owner={'workflow_run_id':'1234','run_attempt':'1'}
 base=dict(id='x',submission_id='x',target_set_id='x',collection_id='x',requested_by='synthetic',status='private_resume_pending',publication_visibility='private',uncertain_hit=False,claimed_lease=False,source_metadata={'yoon_fixed_input':{**s.pins(),'source_id':s.id,'recognition_mode':'resumable','source_url':'https://example.invalid/synthetic.wav'},'yoon_resume':{'version':1,'status':'pending','members':[{'user_id':'synthetic','role':'manager'}],**owner,'padding':'synthetic'*200},'irrelevant_archive':'synthetic'*2048})
 rows=[]
 def add(label,change=lambda r:None):
  r=copy.deepcopy(base);r['label']=label
  for k in ('id','submission_id','target_set_id','collection_id'):r[k]=str(uuid.uuid5(uuid.NAMESPACE_URL,label+k))
  r['source_metadata'][q.KEY]={'version':1,'identity':q.identity(r,r['source_metadata']['yoon_resume']),'status':'queued','generation':str(uuid.uuid5(uuid.NAMESPACE_URL,label+'generation')),'owner':None,'history':'synthetic'*200}
  change(r);rows.append(r)
 add('valid')
 for v in list(a.IDLE)+['private_resume_running','private_analysis_running','bad']:add('status'+v,lambda r,v=v:r.update(status=v))
 for k in ('yoon_resume','yoon_analysis','yoon_spotify_enrichment','yoon_spotify_recheck_v1','yoon_metadata_enrichment_v1',q.KEY):
  for v in [None,False,True,0,7,'bad',[],['bad'],{}, {'foo':'bar'}]:add(k+json.dumps(v),lambda r,k=k,v=v:r['source_metadata'].__setitem__(k,v))
  add(k+'missing',lambda r,k=k:r['source_metadata'].pop(k,None))
 for k in ('review_required','in_flight'):
  for v in [None,False,True,0,1,'false',[],{},['bad']]:add(k+json.dumps(v),lambda r,k=k,v=v:r['source_metadata']['yoon_resume'].__setitem__(k,v))
 for k in ('yoon_spotify_enrichment','yoon_spotify_recheck_v1','yoon_metadata_enrichment_v1'):
  for status in ['complete','reserved','bad',None]:
   for who in [owner,None,{},['bad'],{'workflow_run_id':12,'run_attempt':'1'},{**owner,'extra':'kept'}]:add(k+str(status)+json.dumps(who),lambda r,k=k,status=status,who=who:r['source_metadata'].__setitem__(k,{'status':status,'owner':who,'results':'synthetic'*2048}))
 for status in ['reserved','sending','dispatched','running','complete','blocked','bad',None]:add('queue'+str(status),lambda r,status=status:r['source_metadata'][q.KEY].update(status=status))
 for k in ('uncertain_hit','claimed_lease'):add(k,lambda r,k=k:r.__setitem__(k,True))
 for v in [None,[],['yoon_resume'],['yoon_queue_v1'],False,1,'yoon_resume']:add('metadata'+json.dumps(v),lambda r,v=v:r.__setitem__('source_metadata',v))
 def extra(r):
  r['status']='private_resume_running';r['source_metadata'][q.KEY].update(status='running',owner={**owner,'extra':'same'});r['source_metadata']['yoon_resume']['extra']='same'
 add('extra-owner',extra);return rows

def outcome(fn,row):
 try:return ['returned',fn(row)]
 except Exception as e:return ['raised',type(e).__name__,str(e)]
if sys.argv[1]=='input':
 tree=ast.parse(Path(q.__file__).read_text());method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='blocked_ids');sql=next(ast.literal_eval(n.args[0]) for n in ast.walk(method) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='execute');print(json.dumps({'rows':fixtures(),'admissionSql':a.ROWS_SQL,'blockedSql':sql}))
else:
 data=json.load(sys.stdin);rows={r['id']:r for r in fixtures()};checks=0
 for name,fn in [('admission',a.occupied),('blocked',q.requires_review)]:
  assert set(x['id'] for x in data[name])==set(data[name+'OriginalIds']);checks+=1
  for p in data[name]:
   o=rows[p['id']];assert outcome(fn,o)==outcome(fn,p),(name,o['label'],outcome(fn,o),outcome(fn,p));checks+=1
 print(json.dumps({'status':'passed','assertions':checks,'fixtures':len(rows),'sizes':data['sizes']}))
