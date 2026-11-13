"""Regression for real private skeleton title placement; no live providers or DB."""
import copy
import unittest
from contextlib import nullcontext
from unittest.mock import patch
from worker.jobs import yoon_metadata_enrich as m

class TitleTests(unittest.TestCase):
 def reserve(self,snapshot):
  store=object.__new__(m.MetadataStore);store.publication_digest=m.digest(snapshot);store.expected={};store.owner={'workflow_run_id':'1','run_attempt':'1'};store.run_id='54a97b8c-157a-5ea7-b64a-d0351e737d4e'
  row={'target_set_id':'target','source_metadata':{}}
  def locked(*,capacity=False):
   self.assertTrue(capacity);return nullcontext((None,row,[]))
  store.locked=locked;store.snapshot=lambda cur,row:snapshot;writes=[];store.write=lambda cur,value:writes.append(value)
  with patch('worker.jobs.yoon_admission.check'):
   return store.reserve()
 def test_fallback_preserves_snapshot(self):
  snapshot={'set':{'title':'Reviewed private title','metadata':{'mixInfo':{'artist_name':'Synthetic DJ'}}}};before=copy.deepcopy(snapshot)
  ticket,tracks,mix=self.reserve(snapshot);self.assertIsInstance(ticket,str);self.assertEqual(mix,{'title':'Reviewed private title','artist_name':'Synthetic DJ'});self.assertEqual(snapshot,before)
 def test_explicit_title_wins(self):
  snapshot={'set':{'title':'Fallback','metadata':{'mixInfo':{'title':'Explicit','artist_name':'Synthetic DJ'}}}}
  self.assertEqual(self.reserve(snapshot)[2]['title'],'Explicit')
 def test_absent_and_explicit_invalid_fail(self):
  for value in (None,'',' ',0,False,[],{}):
   for explicit in (False,True):
    snapshot={'set':{'title':value,'metadata':{'mixInfo':{'artist_name':'Synthetic DJ'}}}}
    if explicit:snapshot['set']['title']='Do not use';snapshot['set']['metadata']['mixInfo']['title']=value
    with self.subTest(value=value,explicit=explicit),self.assertRaisesRegex(RuntimeError,'private_mix_info_required'):self.reserve(snapshot)
 def test_url_and_artist_still_guarded(self):
  for field,value,error in [('url','https://example.invalid','private_mix_source_url_forbidden'),('artist_name','','private_mix_info_required')]:
   snapshot={'set':{'title':'Title','metadata':{'mixInfo':{'artist_name':'Synthetic DJ',field:value}}}}
   with self.assertRaisesRegex(RuntimeError,error):self.reserve(snapshot)
