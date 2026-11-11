"""Portable synthetic SQL/consumer oracle. No provider, media or live database."""
import copy,json,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from worker.jobs.yoon_enrichment_projection import FULL_SQL,PROJECTED_SQL,evidence_sql
from worker.jobs.yoon_spotify_enrich import REGISTERED_ENRICHMENT_RUNS,validate,RUN
from worker.jobs.yoon_version_sources import VERSION_ENRICHMENT_RUNS
from tests.test_yoon_enrichment_registrations import fixture
import tests.test_yoon_enrichment_registrations as f

def definitions():
 result=[]
 with patch.object(f,'ADDITIONAL_ENRICHMENT_RUNS',REGISTERED_ENRICHMENT_RUNS):
  for run in VERSION_ENRICHMENT_RUNS:
   row,state,hits,expected=fixture(run)
   for hit in hits:
    hit['raw_data']['private_jackson_v2']['response']['raw_data'].update(track={'unused':'x'*1024},ignored={'nested':[1,2,3]})
   result.append(dict(run=run,row=row,state=state,hits=hits,expected=expected))
 return result

def variations(raw):
 result=[]
 def add(name,value):result.append({'name':name,'raw_text':json.dumps(value)})
 for i,value in enumerate((raw,None,False,0,[],{},'x')):add('root'+str(i),value)
 for path in [('private_jackson_v2',),('private_jackson_v2','response'),('private_jackson_v2','response','raw_data'),('private_jackson_v2','response','raw_data','matches'),('private_jackson_v2','response','raw_data','track'),('private_jackson_v2','attempts'),('private_jackson_v2','origin')]:
  for i,value in enumerate((None,False,0,[],{},'x',[{}],[1])):
   r=copy.deepcopy(raw);o=r
   for key in path[:-1]:o=o[key]
   o[path[-1]]=value;add('/'.join(path)+str(i),r)
  r=copy.deepcopy(raw);o=r
  for key in path[:-1]:o=o[key]
  o.pop(path[-1],None);add('/'.join(path)+'missing',r)
 result.extend([{'name':'giant-number','raw_text':'{"private_jackson_v2":{"response":{"raw_data":{"matches":[],"track":{"unused":'+('9'*4301)+'}}}}}'},
 {'name':'deep-json','raw_text':'{"private_jackson_v2":{"response":{"raw_data":{"matches":[],"unused":'+('['*700)+'0'+(']'*700)+'}}}}'}])
 return result

def decode(rows):return [dict(segment_index=r['segment_index'],raw_data=None if r['raw_text'] is None else json.loads(r['raw_text'])) for r in rows]
def outcome(fn):
 try:return ['ok',fn()]
 except Exception as e:return ['error',type(e).__name__,str(e)]
def compare(value):
 defs=definitions();by={d['run']:d for d in defs};checks=0
 for pair in value['runs']:
  d=by[pair['run']];old,new=decode(pair['old']),decode(pair['new'])
  assert len(old)==len(new)==len(d['hits']);checks+=1
  assert validate(d['row'],d['state'],old,d['expected'])==validate(d['row'],d['state'],new,d['expected']);checks+=1
  for a,b in zip(old,new):
   restored=copy.deepcopy(b);restored['raw_data']['private_jackson_v2']['response']['raw_data']=a['raw_data']['private_jackson_v2']['response']['raw_data'];assert a==restored
   assert b['raw_data']['private_jackson_v2']['response']['raw_data']=={'matches':[],'track':{}};checks+=2
 d=defs[0]
 for pair in value['variations']:
  def one(rows):
   hits=copy.deepcopy(d['hits']);hits[0]=decode(rows)[0];return validate(d['row'],d['state'],hits,d['expected'])
  assert outcome(lambda:one(pair['old']))==outcome(lambda:one(pair['new'])),pair['name'];checks+=1
  if pair['name'] in ('giant-number','deep-json'):assert pair['old']==pair['new'];checks+=1
 assert value['null_preserved'];assert evidence_sql(RUN)==FULL_SQL;assert evidence_sql('unknown')==FULL_SQL;checks+=3
 with patch('worker.jobs.yoon_enrichment_projection.sys.getrecursionlimit',return_value=511):assert evidence_sql(d['run'])==FULL_SQL;checks+=1
 return dict(status='passed',assertions=checks,registered_sources=len(defs),windows=sum(len(d['hits']) for d in defs),shape_cases=len(value['variations']),whole_transaction_or_live_billing=False)
if __name__=='__main__':
 if sys.argv[1]=='input':
  defs=definitions();print(json.dumps({'runs':defs,'variations':variations(defs[0]['hits'][0]['raw_data']),'fullSql':FULL_SQL.replace('%s','$1'),'projectionSql':PROJECTED_SQL.replace('%s','$1')}))
 else:print(json.dumps(compare(json.load(sys.stdin))))
