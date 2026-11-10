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

RUN = '80d8f052-2222-45e5-a164-6cfb197ec5d7'
KEY = 'yoon_spotify_enrichment'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False).encode()).hexdigest()


def validate(row, state, hits, expected, origin=None):
    if row['id'].__str__() != RUN or row['status'] != 'private_resume_complete':
        raise RuntimeError('completed_private_run_required')
    for key in ('target_set_id', 'collection_id', 'submission_id', 'requested_by'):
        if str(row[key]) != expected[key]:
            raise RuntimeError('private_identity_changed')
    if digest(row['source_metadata']['yoon_fixed_input']) != expected['source_digest']:
        raise RuntimeError('source_changed')
    tracks = state.get('clustered_setlist')
    if (state.get('status') != 'complete' or state.get('valid_responses') != 479
            or state.get('review_required') or state.get('in_flight')
            or not isinstance(tracks, list) or len(tracks) != 28
            or digest(tracks) != expected['cluster_digest']):
        raise RuntimeError('completed_cluster_changed')
    from worker.pipeline.models import Recognition
    if len(hits) != 479 or [h['segment_index'] for h in hits] != list(range(479)):
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
    def __init__(self, expected, workflow, attempt):
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
            cur.execute("""SELECT r.* FROM ops.set_runs r
                JOIN ops.submissions u ON u.id=r.submission_id
                JOIN app.sets s ON s.id=r.target_set_id
                JOIN app.archive_collections c ON c.id=r.collection_id
                WHERE r.id=%s AND r.publication_visibility='private'
                AND s.visibility='private' AND u.visibility='private'
                AND s.collection_id=r.collection_id AND u.collection_id=r.collection_id
                AND r.requested_by=u.requested_by AND r.cancel_requested_at IS NULL
                AND u.cancel_requested_at IS NULL AND r.create_playlist=false
                AND u.create_playlist=false FOR UPDATE OF r,u""", (RUN,))
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
                        'WHERE set_run_id=%s ORDER BY segment_index FOR SHARE', (RUN,))
            hits = cur.fetchall()
            origin = None
            if state.get('origin'):
                cur.execute("SELECT id,source_metadata,encode(digest(source_metadata::text,'sha256'),'hex') AS metadata_sha256 FROM ops.set_runs WHERE id=%s FOR SHARE", (state['origin']['run_id'],))
                origin = cur.fetchone()
            tracks = validate(row, state, hits, self.expected, origin)
            yield cur, row, tracks

    def write(self, cur, value):
        cur.execute("UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,"
                    "'{yoon_spotify_enrichment}',%s::jsonb),updated_at=now() WHERE id=%s",
                    (json.dumps(value), RUN))

    def reserve(self):
        with self.locked() as (cur, row, tracks):
            prior = row['source_metadata'].get(KEY)
            if prior is not None:
                if (prior.get('status') == 'complete' and prior.get('input') == self.expected
                        and digest(prior.get('results')) == prior.get('results_digest')):
                    return None, tracks
                raise RuntimeError('uncertain_or_changed_enrichment_requires_review')
            ticket = str(uuid.uuid4())
            self.write(cur, dict(version=1,status='reserved',ticket=ticket,
                                 owner=self.owner,input=self.expected))
            return ticket, tracks

    def finish(self, ticket, results):
        with self.locked() as (cur, row, tracks):
            prior = row['source_metadata'].get(KEY) or {}
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
            or os.environ.get('PRIVATE_RUN_ID') != RUN):
        raise RuntimeError('private_preview_only')
    expected = json.loads(os.environ['PRIVATE_ENRICHMENT_EXPECTED'])
    if set(expected) != {'target_set_id','collection_id','submission_id','requested_by',
                         'source_digest','cluster_digest'}:
        raise RuntimeError('expected_identity_required')
    os.environ.update(ENABLE_SPOTIFY='true',ENABLE_YOUTUBE='false',ENABLE_DISCOGS='false',
                      ENABLE_SPOTIFY_PLAYLISTS='false',ENABLE_CHECKPOINTS='false',NTFY_TOPIC='')
    from metadata_enricher import MetadataEnricher
    from spotipy.cache_handler import MemoryCacheHandler
    store = Store(expected, os.environ['GITHUB_RUN_ID'], os.environ['GITHUB_RUN_ATTEMPT'])
    ticket, tracks = store.reserve()
    if ticket is None:
        return
    enricher = MetadataEnricher()
    if not enricher.spotify_enabled or not enricher.spotify:
        raise RuntimeError('spotify_unavailable')
    enricher.spotify.auth_manager.cache_handler = MemoryCacheHandler()
    store.finish(ticket, enrich(tracks,enricher))


if __name__ == '__main__':
    # FD suppression also captures dependencies and subprocess output. No log files.
    with open(os.devnull,'w') as sink, tempfile.TemporaryDirectory(prefix='private-enrichment-') as tmp:
        os.dup2(sink.fileno(),1)
        os.dup2(sink.fileno(),2)
        os.chdir(tmp)
        main()
