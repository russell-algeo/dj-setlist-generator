import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from worker.jobs.yoon_metadata_enrich import (
    KEY, CORE, production_payload, build_apply_plan, merge_metadata, verified_spotify)
from worker.jobs.yoon_spotify_enrich import RUN, digest


def fixture():
    tracks = [dict(title='First',artist='Synthetic',start_time=0,end_time=30,
        confidence='HIGH',detection_count=3,shazam_track_id='1',isrc='GBXXX0000001',
        cluster_density=1.0,cluster_span=3,segment_indices=[0,1,2]),
        dict(title='Unknown Track',artist='Unknown',start_time=30,end_time=60,
        confidence='UNCERTAIN',detection_count=0,shazam_track_id=None,isrc=None,
        cluster_density=0,cluster_span=0,segment_indices=[]),
        dict(title='Last',artist='Synthetic',start_time=60,end_time=90,
        confidence='MEDIUM',detection_count=2,shazam_track_id='2',isrc=None,
        cluster_density=.5,cluster_span=4,segment_indices=[4,5])]
    rows=[]
    for i,track in enumerate([tracks[0], tracks[2]]):
        meta=dict(track,position=i+1,spotify_url=None,youtube_url=None,
            privateRecognitionProvenance={'sourceSpans':[{'start':1,'end':2}],'runId':RUN})
        rows.append(dict(id='10000000-0000-4000-8000-00000000000'+str(i+1),
            track_id=None,position=i+1,metadata=meta))
    snapshot=dict(set={'metadata':{'mixInfo':{'title':'Synthetic','artist_name':'Synthetic DJ','duration':90},
                                  'boundaryNote':'preserve','importProvenance':{'source':'reviewed'}}},entries=rows)
    row=dict(id=RUN,source_metadata={})
    return row,tracks,snapshot


class MetadataTests(unittest.TestCase):
    def payload(self, tracks, snapshot):
        from metadata_enricher import MetadataEnricher
        def track_meta(self, track):
            if track.title=='Unknown Track':
                return {'platform_matches':{'spotify':{'status':'unverified'},'youtube':{'status':'unverified'}}}
            return dict(spotify_url='https://open.spotify.com/track/'+'A'*22,
                youtube_url='https://www.youtube.com/watch?v=abcdefghijk',
                discogs_url='https://www.discogs.com/release/123',
                spotify_album_art='https://i.scdn.co/image/synthetic',
                spotify_genres=['house'],discogs_genres=['Electronic'],discogs_styles=['Deep House'],
                discogs_label='Synthetic Label',discogs_label_url='https://www.discogs.com/label/123',
                platform_matches={'spotify':{'status':'matched','url':'https://open.spotify.com/track/'+'A'*22},
                    'youtube':{'status':'matched','url':'https://www.youtube.com/watch?v=abcdefghijk'}},link_matching_version=2)
        def features(self, enriched):
            for value in enriched:
                if value['track'].title!='Unknown Track':value['metadata'].update(bpm=122,key='8A',energy=.7,danceability=.8)
        with patch.object(MetadataEnricher,'__init__',lambda self:None), \
             patch.object(MetadataEnricher,'enrich_track',track_meta), \
             patch.object(MetadataEnricher,'_batch_fetch_reccobeats',features), \
             patch.object(MetadataEnricher,'enrich_set_artist_profile',return_value={'artist_profile_image':'https://example.invalid/profile.jpg'}) as profile:
            payload=production_payload(tracks,snapshot['set']['metadata']['mixInfo'])
        self.assertEqual(profile.call_args.kwargs['expected_genres'],['deep house','electronic','house'])
        return payload

    def test_full_production_path_and_preserving_apply_plan(self):
        row,tracks,snapshot=fixture(); before=copy.deepcopy(snapshot)
        payload=self.payload(tracks,snapshot)
        self.assertEqual(len(payload['tracks']),3)
        self.assertEqual(payload['metadata']['total_tracks'],3)
        self.assertEqual(payload['metadata']['uncertain_tracks'],1)
        self.assertTrue(payload['metadata']['generated_at'])
        for key in ('youtube_url','discogs_url','spotify_album_art','discogs_label','bpm','key','energy','danceability'):
            self.assertIsNotNone(payload['tracks'][0][key],key)
        plan=build_apply_plan(row,tracks,snapshot,payload)
        self.assertEqual(plan['conflicts'],[])
        self.assertEqual(plan['entries'][0]['id'],snapshot['entries'][0]['id'])
        self.assertEqual(plan['entries'][2]['id'],snapshot['entries'][1]['id'])
        self.assertEqual([e['position'] for e in plan['entries']],[1,2,3])
        self.assertTrue(plan['entries'][1]['insert'])
        self.assertIsNone(plan['entries'][1]['metadata']['source_deep_link'])
        self.assertEqual(plan['entries'][0]['metadata']['privateRecognitionProvenance'],snapshot['entries'][0]['metadata']['privateRecognitionProvenance'])
        self.assertEqual(plan['set_metadata']['boundaryNote'],'preserve')
        self.assertEqual(plan['set_metadata']['mixInfo']['artist_profile_image'],'https://example.invalid/profile.jpg')
        self.assertEqual(snapshot,before)

    def test_missing_and_conflicting_verified_links(self):
        old={'spotify_url':'https://open.spotify.com/track/'+'A'*22,'spotify_album_art':'old-art'}
        receipt={0:{'spotify_url':old['spotify_url'],'match':{'status':'matched','url':old['spotify_url']}}}
        missing={'spotify_url':None,'spotify_album_art':None,'platform_matches':{'spotify':{'status':'unverified'}}}
        merged,conflicts=merge_metadata(old,missing,0,receipt)
        self.assertEqual(merged['spotify_url'],old['spotify_url'])
        self.assertEqual(merged['spotify_album_art'],'old-art')
        self.assertEqual(merged['platform_matches']['spotify']['status'],'matched')
        self.assertEqual(conflicts,[])
        inconsistent=dict(missing,spotify_album_art='wrong-art',bpm=199)
        merged,_=merge_metadata(old,inconsistent,0,receipt)
        self.assertEqual(merged['spotify_album_art'],'old-art')
        self.assertIsNone(merged['bpm'])
        new=copy.deepcopy(missing);new['spotify_url']='https://open.spotify.com/track/'+'B'*22
        new['platform_matches']['spotify']={'status':'matched','url':new['spotify_url']}
        _,conflicts=merge_metadata(old,new,0,receipt)
        self.assertEqual(conflicts[0]['platform'],'spotify')
        with self.assertRaisesRegex(RuntimeError,'evidence_missing'):merge_metadata(old,missing,0,{})

    def test_recognition_mutations_fail_closed(self):
        row,tracks,snapshot=fixture();payload=self.payload(tracks,snapshot)
        for mutate in (lambda p:p['tracks'][0].update(title='Changed'),lambda p:p['tracks'].pop()):
            p=copy.deepcopy(payload);mutate(p)
            with self.assertRaises(RuntimeError):build_apply_plan(row,tracks,snapshot,p)
        snapshot['entries'][0]['metadata']['detection_count']=99
        with self.assertRaisesRegex(RuntimeError,'recognition_changed'):build_apply_plan(row,tracks,snapshot,payload)

    def test_receipt_hash_verified(self):
        row,tracks,_=fixture()
        result={'index':0,'spotify_url':'https://open.spotify.com/track/'+'A'*22,
            'match':{'status':'matched','url':'https://open.spotify.com/track/'+'A'*22}}
        row['source_metadata']['yoon_spotify_enrichment']=dict(status='complete',results=[result],
            results_digest=digest([result]),input={'cluster_digest':digest(tracks)})
        self.assertEqual(verified_spotify(row,tracks)[0],result)
        result['match']['status']='unverified'
        with self.assertRaises(RuntimeError):verified_spotify(row,tracks)

    def test_common_admission_counts_rich_reservations(self):
        from worker.jobs.yoon_admission import occupied, ROWS_SQL, check
        row=dict(status='private_resume_complete',uncertain_hit=False,claimed_lease=False,
            source_metadata={KEY:{'status':'reserved','owner':{'workflow_run_id':'1','run_attempt':'1'}}})
        self.assertTrue(occupied(row));self.assertIn(KEY,ROWS_SQL)
        from test_yoon_admission import Cursor, row as running
        row.update(id='1',target_set_id='set1')
        with self.assertRaisesRegex(RuntimeError,'capacity'):
            check(Cursor([row,running(2)]),'3','set3')
        row['source_metadata'][KEY]['status']='complete';self.assertFalse(occupied(row))

    def test_workflow_private_scope_and_step_scoped_credentials(self):
        root=Path(__file__).resolve().parents[1]
        text=(root/'.github/workflows/process-set.yml').read_text()
        legacy,rich=text.split('  private-production-metadata:')
        legacy=legacy.split('  private-enrichment:')[1]
        self.assertNotIn('DISCOGS',legacy)
        self.assertIn('rich_metadata != true',legacy)
        self.assertIn('rich_metadata == true',rich)
        for guard in ("private_analysis == 'true'", "deployment_target == 'development'",
                      "github.ref == 'refs/heads/preview'", "private_enrichment_only == 'true'"):
            self.assertIn(guard,rich)
        before,after=rich.split('      - name: Enrich and stage the completed private set')
        self.assertNotIn('secrets.',before)
        self.assertIn('secrets.DISCOGS_TOKEN',after)
        self.assertIn('secrets.DEVELOPMENT_DATABASE_URL_DIRECT',after)
        self.assertNotIn('upload-artifact',rich)
        self.assertNotIn('persist-credentials: true',rich)
        self.assertIn('python -m worker.jobs.yoon_metadata_enrich',after)
        from worker.jobs.yoon_metadata_enrich import diagnostic_code
        self.assertEqual(diagnostic_code(RuntimeError('private source secret')),'private_metadata_failed')
        self.assertEqual(diagnostic_code(RuntimeError('private_audience_changed')),'private_audience_changed')

    def test_shared_modules_unchanged(self):
        root=Path(__file__).resolve().parents[1]
        source=root.parent/'yoon-parallel-release'
        if not source.exists():self.skipTest('local production parity reference unavailable')
        for path in ('metadata_enricher.py','output_formatter.py','worker/pipeline/enrich.py',
                     'track_recognizer.py','recognition_transport.py','worker/pipeline/aggregate.py'):
            self.assertEqual((root/path).read_bytes(),(source/path).read_bytes(),path)

if __name__=='__main__':unittest.main()
