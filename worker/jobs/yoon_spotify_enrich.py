"""One-shot, private Spotify enrichment. No recognition or public publication.

A committed reservation is never automatically retried after interruption. The
controller must reconcile it; matching calls can have completed before a crash.
"""
import hashlib
import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from worker.jobs.yoon_enrichment_registrations import ADDITIONAL_ENRICHMENT_RUNS
from worker.jobs.yoon_version_sources import VERSION_ENRICHMENT_RUNS
REGISTERED_ENRICHMENT_RUNS = {**ADDITIONAL_ENRICHMENT_RUNS, **VERSION_ENRICHMENT_RUNS}

RUN = '80d8f052-2222-45e5-a164-6cfb197ec5d7'
DONALD_RUN = '63c98e06-08e8-4073-972d-4861a59f5f8d'
HALO_RUN = 'd157e002-f047-4afe-a560-c7b837d4bdc9'
GRISHA_RUN = 'f329482f-5c27-4d79-892e-504371e3ffb6'
HIGHKIN_RUN = 'bbf3ec9d-4d8f-415c-a1ac-57c5657db77c'
DEEP_HOUSE_RUN = '207d90dd-006c-522d-9928-8727b2a8cefe'
BRETT_RUN = 'f0a66788-adb4-4c3e-8545-882fcc67ed90'
REVIEWED_RUNS = frozenset((RUN, DONALD_RUN, HALO_RUN, GRISHA_RUN, HIGHKIN_RUN, DEEP_HOUSE_RUN, BRETT_RUN)) | frozenset(REGISTERED_ENRICHMENT_RUNS)
DONALD_SCOPE = dict(target_set_id='0ce1797e-e55e-41c7-b665-c593c217d218',
    collection_id='1d50c599-3150-43f9-a7e9-50d00fc996b7',
    submission_id='6b6671d9-dc59-48c7-84a4-6e19b0a54940',
    requested_by='65c06333-323d-48a8-9389-f03946d32264')
HALO_SCOPE = dict(DONALD_SCOPE, target_set_id='b8dcffbe-a858-4306-aad4-9cb7cbf0e757', submission_id='db078f27-682b-49ad-ab21-6d9b8ed94332')
GRISHA_SCOPE = dict(DONALD_SCOPE, target_set_id='fbd06998-4f88-4c8a-a2cd-1fc50a91280b', submission_id='f74d0374-6ff5-4991-9ebc-12d46c58a84d')
HIGHKIN_SCOPE = dict(DONALD_SCOPE, target_set_id='8c63960c-e12a-4917-9d19-b45f574c0769', submission_id='a466b70e-0050-4639-84fc-5fe821b54055')
DEEP_HOUSE_SCOPE = dict(DONALD_SCOPE, target_set_id='783abc91-1f8d-528e-862b-93612aac5b3b', submission_id='d0e7b8d4-0b7a-55cf-af61-7a02ca02ff60')
BRETT_SCOPE = dict(DONALD_SCOPE, target_set_id='15407f01-3656-456d-8d61-d6c52303b36d', submission_id='85114998-61e5-4b28-aae3-3696291a9009')
DONALD_MEMBERS = [dict(user_id=DONALD_SCOPE['requested_by'],role='manager'),
    dict(user_id='d8e3668b-7bf1-4b7e-8530-109c38bb6d89',role='viewer')]
KEY = 'yoon_spotify_enrichment' 


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False).encode()).hexdigest()


def validate(row, state, hits, expected, origin=None):
    if str(row['id']) not in REVIEWED_RUNS or row['status'] != 'private_resume_complete':
        raise RuntimeError('completed_private_run_required')
    additional = REGISTERED_ENRICHMENT_RUNS.get(str(row['id']))
    if additional is not None:
        required = {'target_set_id', 'collection_id', 'submission_id', 'requested_by',
                    'source_digest', 'cluster_digest'}
        if (not isinstance(expected, dict) or not required <= set(expected)
                or set(expected) - required - {'rich_metadata'}
                or ('rich_metadata' in expected and expected['rich_metadata'] is not True)):
            raise RuntimeError('expected_identity_required')
    for key in ('target_set_id', 'collection_id', 'submission_id', 'requested_by'):
        if str(row[key]) != expected[key]:
            raise RuntimeError('private_identity_changed')
    if digest(row['source_metadata']['yoon_fixed_input']) != expected['source_digest']:
        raise RuntimeError('source_changed')
    fresh = str(row['id']) != RUN
    windows = 359 if str(row['id']) in (HALO_RUN, DEEP_HOUSE_RUN) else 479
    if fresh:
        from worker.jobs.yoon_sources import CATALOG, DONALD, HALO, GRISHA, HIGHKIN, DEEP_HOUSE, BRETT, reviewed_source
        source = BRETT if str(row['id']) == BRETT_RUN else DEEP_HOUSE if str(row['id']) == DEEP_HOUSE_RUN else HIGHKIN if str(row['id']) == HIGHKIN_RUN else GRISHA if str(row['id']) == GRISHA_RUN else HALO if str(row['id']) == HALO_RUN else DONALD
        scope = BRETT_SCOPE if str(row['id']) == BRETT_RUN else DEEP_HOUSE_SCOPE if str(row['id']) == DEEP_HOUSE_RUN else HIGHKIN_SCOPE if str(row['id']) == HIGHKIN_RUN else GRISHA_SCOPE if str(row['id']) == GRISHA_RUN else HALO_SCOPE if str(row['id']) == HALO_RUN else DONALD_SCOPE
        additional = REGISTERED_ENRICHMENT_RUNS.get(str(row['id']))
        if additional is not None:
            source = CATALOG.get(additional['source_id'])
            if source is None:
                raise RuntimeError('reviewed_source_registration_missing')
            scope = dict(DONALD_SCOPE, target_set_id=additional['target_set_id'],
                         submission_id=additional['submission_id'])
            windows = source.windows
        descriptor = row['source_metadata']['yoon_fixed_input']
        if additional is not None:
            from worker.jobs.yoon_highkin_source import JoinedSource
            url_key = 'source_urls' if isinstance(source, JoinedSource) else 'source_url'
            if (not isinstance(descriptor, dict)
                    or set(descriptor) - set(source.pins()) - {'source_id', 'recognition_mode', url_key}):
                raise RuntimeError('fixed_input_mismatch')
        if (reviewed_source(descriptor) != source or origin is not None
                or any(str(row[k]) != v for k,v in scope.items())
                or state.get('initialization_mode') != 'fresh'
                or state.get('fresh_source_initialized') is not True
                or state.get('origin') or state.get('provenance_seeded')
                or state.get('source_id') != source.id or state.get('source_pins') != source.pins()
                or state.get('members') != DONALD_MEMBERS
                or not re.fullmatch('[0-9a-f]{64}', str(state.get('audio_sha256', '')))
                or state.get('audio_sha256') != state.get('expected_audio_sha256')):
            raise RuntimeError('reviewed_fresh_source_required')
    tracks = state.get('clustered_setlist')
    if (state.get('status') != 'complete' or state.get('valid_responses') != windows
            or state.get('review_required') or state.get('in_flight')
            or not isinstance(tracks, list) or (not 1 <= len(tracks) <= windows if fresh else len(tracks) != 28)
            or digest(tracks) != expected['cluster_digest']):
        raise RuntimeError('completed_cluster_changed')
    from worker.pipeline.models import Recognition
    if len(hits) != windows or [h['segment_index'] for h in hits] != list(range(windows)):
        raise RuntimeError('window_coverage_changed')
    seeded = 0
    for h in hits:
        d = h['raw_data']['private_jackson_v2']
        r = Recognition.from_checkpoint(d['response'])
        if (d.get('valid') is not True or d.get('in_flight') or not r.is_valid
                or r.http_status not in (None,200) or r.segment_index != h['segment_index']
                or r.timestamp != h['segment_index'] * 15):
            raise RuntimeError('window_evidence_changed')
        attempts = d.get('attempts') or []
        if fresh and (d.get('origin') or r.http_status != 200):
            raise RuntimeError('fresh_window_evidence_changed')
        if d.get('origin'):
            pin = state.get('origin') or {}
            original = (origin or {}).get('source_metadata', {}).get('yoon_analysis', {})
            old = next((v for v in original.get('raw_recognitions', [])
                        if v.get('segment_index') == h['segment_index']), None)
            diagnostics = [v for v in original.get('recognition_diagnostics', {}).get('attempts', [])
                           if v.get('segment_index') == h['segment_index']]
            if (not origin or str(origin['id']) != pin.get('run_id')
                    or origin['metadata_sha256'] != pin.get('metadata_sha256')
                    or original.get('workflow_run_id') != pin.get('workflow_run_id')
                    or original.get('status') != 'partial' or attempts
                    or d['origin'] != dict(pin,segment_index=h['segment_index'])
                    or old != d['response'] or not diagnostics or diagnostics[-1].get('http_status') != 200):
                raise RuntimeError('origin_evidence_changed')
            seeded += 1
        else:
            last = attempts[-1] if attempts else {}
            diagnostic = last.get('diagnostic') or {}
            if (last.get('state') != 'finished' or diagnostic.get('http_status') != 200
                    or diagnostic.get('outcome') != ('recognized' if r.recognized else 'no_match')
                    or str(last.get('workflow_run_id'))+':'+str(last.get('run_attempt')) not in state.get('used_owners', [])):
                raise RuntimeError('attempt_evidence_changed')
    if seeded != (state.get('origin') or {}).get('valid_windows',0):
        raise RuntimeError('origin_seed_count_changed')
    return tracks


class Store:
    key = KEY

    def __init__(self, expected, workflow, attempt, run_id=RUN):
        if run_id not in REVIEWED_RUNS:
            raise RuntimeError('reviewed_run_required')
        self.run_id = run_id
        from worker.db import connect
        if not workflow.isdecimal() or not attempt.isdecimal():
            raise RuntimeError('invalid_owner')
        self.connect = connect
        self.owner = dict(workflow_run_id=workflow, run_attempt=attempt)
        self.expected = expected

    @contextmanager
    def locked(self):
        with self.connect() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute("SET LOCAL statement_timeout = '15s'")
            from worker.jobs.yoon_admission import lock
            lock(cur)
            cur.execute("""SELECT r.* FROM ops.set_runs r
                JOIN ops.submissions u ON u.id=r.submission_id
                JOIN app.sets s ON s.id=r.target_set_id
                JOIN app.archive_collections c ON c.id=r.collection_id
                WHERE r.id=%s AND r.publication_visibility='private'
                AND s.visibility='private' AND u.visibility='private'
                AND s.collection_id=r.collection_id AND u.collection_id=r.collection_id
                AND r.requested_by=u.requested_by AND r.cancel_requested_at IS NULL
                AND u.cancel_requested_at IS NULL AND r.create_playlist=false
                AND u.create_playlist=false FOR UPDATE OF r,u""", (self.run_id,))
            row = cur.fetchone()
            if not row:
                raise RuntimeError('private_scope_required')
            state = row['source_metadata'].get('yoon_resume') or {}
            cur.execute('SELECT user_id,role FROM app.archive_collection_members '
                        'WHERE collection_id=%s ORDER BY user_id', (row['collection_id'],))
            members = [dict(user_id=str(m['user_id']),role=m['role']) for m in cur.fetchall()]
            if len(members)!=2 or members!=state.get('members'):
                raise RuntimeError('private_audience_changed')
            cur.execute('SELECT segment_index,raw_data FROM ops.segment_hits '
                        'WHERE set_run_id=%s ORDER BY segment_index FOR SHARE', (self.run_id,))
            hits = cur.fetchall()
            origin = None
            if state.get('origin'):
                cur.execute("SELECT id,source_metadata,encode(digest(source_metadata::text,'sha256'),'hex') AS metadata_sha256 FROM ops.set_runs WHERE id=%s FOR SHARE", (state['origin']['run_id'],))
                origin = cur.fetchone()
            tracks = validate(row, state, hits, self.expected, origin)
            yield cur, row, tracks

    def write(self, cur, value):
        cur.execute("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,"
                    "%s::text[],%s::jsonb),updated_at=now() WHERE id=%s",
                    ([self.key], json.dumps(value), self.run_id))

    def reserve(self):
        with self.locked() as (cur, row, tracks):
            prior = row['source_metadata'].get(self.key)
            if prior is not None:
                if (prior.get('status') == 'complete' and prior.get('input') == self.expected
                        and digest(prior.get('results')) == prior.get('results_digest')):
                    return None, tracks
                raise RuntimeError('uncertain_or_changed_enrichment_requires_review')
            from worker.jobs.yoon_admission import check
            check(cur, self.run_id, row['target_set_id'])
            ticket = str(uuid.uuid4())
            self.write(cur, dict(version=1,status='reserved',ticket=ticket,
                                 owner=self.owner,input=self.expected))
            return ticket, tracks

    def finish(self, ticket, results):
        with self.locked() as (cur, row, tracks):
            prior = row['source_metadata'].get(self.key) or {}
            if (prior.get('status') != 'reserved' or prior.get('ticket') != ticket
                    or prior.get('input') != self.expected or prior.get('owner') != self.owner):
                raise RuntimeError('enrichment_reservation_changed')
            prior.update(status='complete',results=results,results_digest=digest(results))
            self.write(cur, prior)


def enrich(tracks, enricher):
    from setlist_builder import Track
    out = []
    for i, data in enumerate(tracks):
        if data['title'] == 'Unknown Track':
            continue
        metadata = enricher.enrich_track(Track(**data))
        url = metadata.get('spotify_url')
        evidence = (metadata.get('platform_matches') or {}).get('spotify') or {}
        if url and (not re.fullmatch(r'https://open\.spotify\.com/track/[A-Za-z0-9]{22}', url)
                    or evidence.get('url') != url or evidence.get('status') != 'matched'):
            raise RuntimeError('unverified_spotify_result')
        out.append(dict(index=i,spotify_url=url,match=evidence,
                        link_matching_version=metadata.get('link_matching_version')))
    return out


def main():
    # Fail before loading configuration, DB connection or any provider client.
    if (os.environ.get('WORKER_DEPLOYMENT_TARGET') != 'development'
            or os.environ.get('GITHUB_REF') != 'refs/heads/preview'
            or os.environ.get('GITHUB_REPOSITORY') != 'russell-algeo/dj-setlist-generator'
            or os.environ.get('PRIVATE_RUN_ID') not in REVIEWED_RUNS):
        raise RuntimeError('private_preview_only')
    expected = json.loads(os.environ['PRIVATE_ENRICHMENT_EXPECTED'])
    recheck = expected.pop('recheck', False)
    if type(recheck) is not bool:
        raise RuntimeError('invalid_recheck_request')
    if set(expected) != {'target_set_id','collection_id','submission_id','requested_by',
                         'source_digest','cluster_digest'}:
        raise RuntimeError('expected_identity_required')
    os.environ.update(ENABLE_SPOTIFY='true',ENABLE_YOUTUBE='false',ENABLE_DISCOGS='false',
                      ENABLE_SPOTIFY_PLAYLISTS='false',ENABLE_CHECKPOINTS='false',NTFY_TOPIC='')
    from metadata_enricher import MetadataEnricher
    from spotipy.cache_handler import MemoryCacheHandler
    store_class = Store
    if recheck:
        from worker.jobs.yoon_spotify_recheck import RecheckStore
        store_class = RecheckStore
    store = store_class(expected, os.environ['GITHUB_RUN_ID'], os.environ['GITHUB_RUN_ATTEMPT'], os.environ['PRIVATE_RUN_ID'])
    ticket, tracks = store.reserve()
    if ticket is None:
        return
    enricher = MetadataEnricher()
    if not enricher.spotify_enabled or not enricher.spotify:
        raise RuntimeError('spotify_unavailable')
    enricher.spotify.auth_manager.cache_handler = MemoryCacheHandler()
    if recheck:
        from worker.jobs.yoon_spotify_recheck import enrich_selected
        results = enrich_selected(tracks, enricher)
    else:
        results = enrich(tracks, enricher)
    store.finish(ticket, results)


if __name__ == '__main__':
    # FD suppression also captures dependencies and subprocess output. No log files.
    with open(os.devnull,'w') as sink, tempfile.TemporaryDirectory(prefix='private-enrichment-') as tmp:
        os.dup2(sink.fileno(),1)
        os.dup2(sink.fileno(),2)
        os.chdir(tmp)
        main()
