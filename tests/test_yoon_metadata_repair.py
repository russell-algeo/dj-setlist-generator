import copy
import unittest
from unittest.mock import patch
from scripts.yoon_metadata_repair import prepare_repair, REPAIR_KEY
from scripts.yoon_metadata_apply import PUBLICATION_KEY
from worker.jobs.yoon_metadata_enrich import KEY
from worker.jobs.yoon_spotify_enrich import RUN, digest


def fixture():
    target='10000000-0000-4000-8000-000000000001'
    collection='20000000-0000-4000-8000-000000000001'
    original={'recognitionCoverage':{'expectedWindows':100,'validResponses':100,'matchedWindows':69},
              'privateRecognitionProvenance':{'runId':RUN}}
    payload={'tracks':[], 'mix_info':{}, 'metadata':{'total_tracks':3,'uncertain_tracks':1,'generated_at':'2026-11-10'}}
    metadata={'summary':original,'mixInfo':{'artist_name':'Synthetic'}}
    before=dict(run=dict(id=RUN,target_set_id=target,collection_id=collection,
                  source_metadata={'yoon_resume':{'clustered_setlist':[]}}),
                publication=dict(set=dict(id=target,visibility='private',collection_id=collection,metadata=metadata,recognition_rate=69),
                                 entries=[],media=[{'id':'synthetic-media'}],source_links=[]),
                fingerprints={key:'original-'+key for key in ('run','publication','hits','members','origin')})
    before['run']['source_metadata'][KEY]=dict(status='complete',conflicts=[],applied=False,
        publication_mode='reviewed-owner-apply',results=payload,results_digest=digest(payload),publication_digest=digest(before['publication']))
    current=copy.deepcopy(before)
    current['publication']['set']['metadata']['summary']=copy.deepcopy(payload['metadata'])
    current['publication']['set']['recognition_rate']=66.67
    current['fingerprints']['publication']='post-publication'
    current['run']['source_metadata'][PUBLICATION_KEY]=dict(before_fingerprints=before['fingerprints'],
        results_digest=digest(payload),post_fingerprint='post-publication')
    plan=dict(entries=[],set_metadata=copy.deepcopy(metadata),conflicts=[])
    plan['set_metadata']['summary'].update(payload['metadata'])
    return before,current,plan


class RepairTests(unittest.TestCase):
    def test_plan_only_restores_original_summary_and_rate(self):
        before,current,plan=fixture();saved=copy.deepcopy(current)
        with patch('scripts.yoon_metadata_repair.build_apply_plan',return_value=plan):
            result=prepare_repair(RUN,before,current)
        sql=result['sql_statements'][-1]
        self.assertEqual(current,saved)
        self.assertIn("current_snapshot->'fingerprints' IS DISTINCT FROM p->'fingerprints'",sql)
        self.assertIn('UPDATE app.sets SET metadata=jsonb_set',sql)
        self.assertNotIn('UPDATE app.set_entries',sql)
        self.assertNotIn('UPDATE ops.set_runs',sql)
        self.assertIn("source_metadata->'yoon_resume'->'origin'->>'run_id'",sql)
        self.assertIn("FROM ops.set_runs WHERE id=(p->>'run_id')::uuid) FOR SHARE;",sql)
        self.assertIn(REPAIR_KEY,sql)
        self.assertIn('recognitionCoverage',sql)
        self.assertIn('privateRecognitionProvenance',sql)
        self.assertEqual(result['restored_keys'],['recognitionCoverage','privateRecognitionProvenance'])

    def test_rejects_changed_access_recognition_media_metadata_and_prior_repair(self):
        for mutate in (
            lambda c:c['fingerprints'].update(hits='changed'),
            lambda c:c['fingerprints'].update(members='changed'),
            lambda c:c['publication']['media'].append({'id':'new'}),
            lambda c:c['publication']['set']['metadata'].update(extra='changed'),
            lambda c:c['publication']['set']['metadata'].update({REPAIR_KEY:{'version':1}}),
            lambda c:c['publication']['set'].update(recognition_rate=99),
            lambda c:c['publication']['entries'].append({'id':'new'}),
            lambda c:c['run']['source_metadata'][PUBLICATION_KEY].update(post_fingerprint='stale'),
        ):
            before,current,plan=fixture();mutate(current)
            with patch('scripts.yoon_metadata_repair.build_apply_plan',return_value=plan):
                with self.assertRaises(RuntimeError):prepare_repair(RUN,before,current)

    def test_requires_original_coverage(self):
        before,current,plan=fixture()
        del before['publication']['set']['metadata']['summary']['recognitionCoverage']
        before['run']['source_metadata'][KEY]['publication_digest']=digest(before['publication'])
        with self.assertRaisesRegex(RuntimeError,'original_coverage_required'):
            prepare_repair(RUN,before,current)
