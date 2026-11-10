"""Production metadata collection with a separate guarded private publication.

Recognition, credentials, source media and access are never changed here. A
reservation is durable before provider calls; interrupted attempts need review.
Provider results and conflicts are staged in ops. An existing owner connector
applies reviewed metadata separately; the worker needs no archive write grant.
"""
from copy import deepcopy
from discogs_matching import merge_discogs_metadata
import json
import os
import re
import tempfile
import uuid

from worker.jobs.yoon_spotify_enrich import Store, REVIEWED_RUNS, digest

KEY = 'yoon_metadata_enrichment_v1'
CORE = ('title', 'artist', 'start_time', 'end_time', 'confidence',
        'detection_count', 'cluster_density', 'cluster_span')
SPOTIFY_RE = r'https://open\.spotify\.com/track/[A-Za-z0-9]{22}'


def identity(track):
    return tuple(track.get(k) for k in ('artist', 'title', 'start_time', 'end_time'))


def production_payload(tracks, mix_info):
    """Do not fork production matching, feature batching, profiles or formatting."""
    from setlist_builder import Track
    from worker.pipeline.enrich import enrich_tracks, build_set_payload
    enriched, resolved = enrich_tracks([Track(**t) for t in tracks],
        mix_info=deepcopy(mix_info), artist_name=mix_info.get('artist_name'))
    return build_set_payload(enriched_tracks=enriched, mix_info=resolved)


def verified_spotify(row, tracks):
    """Earlier private receipts retain matching evidence missing from entry JSON."""
    verified = {}
    prior = row['source_metadata'].get('yoon_spotify_enrichment')
    if prior is None:
        return verified
    if (prior.get('status') != 'complete'
            or digest(prior.get('results')) != prior.get('results_digest')
            or prior.get('input', {}).get('cluster_digest') != digest(tracks)):
        raise RuntimeError('prior_spotify_evidence_changed')
    for result in prior['results']:
        index, url = result.get('index'), result.get('spotify_url')
        if not url:
            continue
        match = result.get('match') or {}
        if (type(index) is not int or not 0 <= index < len(tracks)
                or index in verified or not re.fullmatch(SPOTIFY_RE, url)
                or match.get('status') != 'matched' or match.get('url') != url):
            raise RuntimeError('prior_spotify_evidence_invalid')
        verified[index] = result
    return verified


def merge_metadata(old, new, index, verified):
    merged = deepcopy(old)
    conflicts = []
    # Null/empty provider results must not erase previously collected metadata.
    for key, value in new.items():
        if key not in CORE and key not in ('position', 'source_deep_link', 'platform_matches'):
            if value is not None and value != []:
                merged[key] = deepcopy(value)
            else:
                merged.setdefault(key, deepcopy(value))
    matches = deepcopy(old.get('platform_matches') or {})
    for platform in ('spotify', 'youtube'):
        field = platform + '_url'
        old_url = old.get(field)
        old_match = matches.get(platform) or {}
        if platform == 'spotify' and index in verified:
            receipt = verified[index]
            if old_url and old_url != receipt['spotify_url']:
                raise RuntimeError('published_spotify_receipt_conflict')
            old_url, old_match = receipt['spotify_url'], receipt['match']
        if old_url and (old_match.get('status') != 'matched' or old_match.get('url') != old_url):
            raise RuntimeError('published_link_evidence_missing')
        new_url = new.get(field)
        new_match = (new.get('platform_matches') or {}).get(platform) or {}
        if new_url and (new_match.get('status') != 'matched' or new_match.get('url') != new_url):
            raise RuntimeError('production_link_evidence_missing')
        if old_url and new_url and old_url != new_url:
            conflicts.append(dict(index=index, platform=platform, previous=old_url, proposed=new_url))
        if old_url and not new_url:
            # Provider-bound details must describe the retained verified track,
            # even if a future producer returns inconsistent unmatched details.
            if platform == 'spotify':
                for key in list(merged):
                    if key.startswith('spotify_') or key in ('bpm','key','energy','danceability'):
                        merged[key] = deepcopy(old.get(key, [] if key == 'spotify_genres' else None))
            merged[field], matches[platform] = old_url, deepcopy(old_match)
        else:
            matches[platform] = deepcopy(new_match)
    merge_discogs_metadata(old, new, merged, matches, index, conflicts)
    merged['platform_matches'] = matches
    return merged, conflicts


def build_apply_plan(row, tracks, snapshot, payload):
    if len(payload.get('tracks', [])) != len(tracks):
        raise RuntimeError('production_track_count_changed')
    existing = {}
    for entry in snapshot['entries']:
        key = identity(entry['metadata'])
        if key in existing or entry.get('track_id') is not None or entry.get('position', 0) <= 0:
            raise RuntimeError('private_entry_identity_ambiguous')
        existing[key] = entry
    verified = verified_spotify(row, tracks)
    changes, conflicts = [], []
    for index, (track, new) in enumerate(zip(tracks, payload['tracks'])):
        if any(new.get(k) != track.get(k) for k in CORE) or new.get('position') != index + 1:
            raise RuntimeError('production_recognition_changed')
        entry = existing.pop(identity(track), None)
        if entry is None and track['title'] != 'Unknown Track':
            raise RuntimeError('recognized_entry_missing')
        if entry:
            old = entry['metadata']
            if any(old.get(k) != track.get(k) for k in CORE):
                raise RuntimeError('published_recognition_changed')
            merged, found = merge_metadata(old, new, index, verified)
            conflicts.extend(found)
            merged['position'] = index + 1
            changes.append(dict(id=str(entry['id']), position=index + 1, metadata=merged, insert=False))
        else:
            unknown = deepcopy(new)
            unknown['source_deep_link'] = None
            unknown['privateRecognitionProvenance'] = dict(runId=str(row['id']),
                clusterSha256=digest(track), segmentIndices=track.get('segment_indices', []),
                timingBasis='shared clustered setlist', metadataBackfill=True)
            changes.append(dict(id=str(uuid.uuid5(uuid.UUID(str(row['id'])), 'metadata-unknown-'+str(index))),
                position=index + 1, metadata=unknown, insert=True))
    if existing:
        raise RuntimeError('published_entries_not_in_cluster')
    metadata = deepcopy(snapshot['set']['metadata'])
    mix = deepcopy(metadata.get('mixInfo') or {})
    for key, value in payload['mix_info'].items():
        if value is not None and value != []:
            mix[key] = deepcopy(value)
        else:
            mix.setdefault(key, deepcopy(value))
    summary = deepcopy(metadata.get('summary') or {})
    summary.update(deepcopy(payload['metadata']))
    metadata.update(mixInfo=mix, summary=summary)
    return dict(entries=changes, set_metadata=metadata,
        recognition_rate=snapshot['set'].get('recognition_rate'),
        conflicts=conflicts)


class MetadataStore(Store):
    key = KEY
    stage_only = True  # Worker role intentionally cannot write the private archive.

    def __init__(self, expected, workflow, attempt, run_id):
        pins = dict(expected)
        self.publication_digest = pins.pop('publication_digest')
        if not re.fullmatch('[0-9a-f]{64}', self.publication_digest):
            raise RuntimeError('publication_digest_required')
        super().__init__(pins, workflow, attempt, run_id)

    def snapshot(self, cur, row):
        # Worker-role metadata collection is ops-only. The separately reviewed
        # owner publication takes these app locks immediately before applying.
        if not self.stage_only:
            cur.execute('SELECT id FROM app.archive_collections WHERE id=%s FOR UPDATE', (row['collection_id'],))
            cur.execute('SELECT id FROM app.sets WHERE id=%s FOR UPDATE', (row['target_set_id'],))
            cur.execute('SELECT id FROM app.set_entries WHERE set_id=%s ORDER BY position,id FOR UPDATE', (row['target_set_id'],))
            cur.execute('SELECT id FROM app.set_media WHERE set_id=%s FOR SHARE', (row['target_set_id'],))
            cur.execute('SELECT id FROM app.set_source_links WHERE set_id=%s FOR SHARE', (row['target_set_id'],))
        cur.execute('SELECT user_id,role FROM app.archive_collection_members WHERE collection_id=%s ORDER BY user_id' + ('' if self.stage_only else ' FOR SHARE'), (row['collection_id'],))
        members = [dict(user_id=str(m['user_id']), role=m['role']) for m in cur.fetchall()]
        if members != row['source_metadata']['yoon_resume']['members']:
            raise RuntimeError('private_audience_changed')
        cur.execute("""SELECT jsonb_build_object(
            'set',(SELECT to_jsonb(s)-'updated_at' FROM app.sets s WHERE id=%s),
            'entries',(SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY position,id),'[]'::jsonb)
                FROM app.set_entries e WHERE set_id=%s),
            'media',(SELECT coalesce(jsonb_agg(to_jsonb(m) ORDER BY id),'[]'::jsonb)
                FROM app.set_media m WHERE set_id=%s),
            'source_links',(SELECT coalesce(jsonb_agg(to_jsonb(l) ORDER BY id),'[]'::jsonb)
                FROM app.set_source_links l WHERE set_id=%s)) AS value""",
            (row['target_set_id'],) * 4)
        snapshot = cur.fetchone()['value']
        target = snapshot['set']
        if (target['visibility'] != 'private' or str(target['collection_id']) != str(row['collection_id'])
                or not snapshot['entries'] or str(row.get('published_set_id')) != str(row['target_set_id'])):
            raise RuntimeError('published_private_set_required')
        return snapshot

    def reserve(self):
        with self.locked() as (cur, row, tracks):
            prior = row['source_metadata'].get(self.key)
            snapshot = self.snapshot(cur, row)
            if prior is not None:
                if (prior.get('status') == 'complete' and prior.get('input') == self.expected
                        and prior.get('publication_digest') == self.publication_digest
                        and digest(prior.get('results')) == prior.get('results_digest')
                        and (not prior.get('applied') or digest(snapshot) == prior.get('post_digest'))):
                    return None, None, None
                raise RuntimeError('uncertain_or_changed_enrichment_requires_review')
            if digest(snapshot) != self.publication_digest:
                raise RuntimeError('reviewed_publication_changed')
            from worker.jobs.yoon_admission import check
            check(cur, self.run_id, row['target_set_id'])
            verified_spotify(row, tracks)
            ticket = str(uuid.uuid4())
            self.write(cur, dict(version=1, status='reserved', ticket=ticket,
                owner=self.owner, input=self.expected, publication_digest=self.publication_digest))
            mix = deepcopy(snapshot['set']['metadata'].get('mixInfo') or {})
            if not mix.get('artist_name') or not mix.get('title'):
                raise RuntimeError('private_mix_info_required')
            # Private download URLs remain in protected media, not provider queries.
            if mix.get('url'):
                raise RuntimeError('private_mix_source_url_forbidden')
            return ticket, tracks, mix

    def finish(self, ticket, payload):
        with self.locked() as (cur, row, tracks):
            prior = row['source_metadata'].get(self.key) or {}
            if (prior.get('status') != 'reserved' or prior.get('ticket') != ticket
                    or prior.get('input') != self.expected or prior.get('owner') != self.owner
                    or prior.get('publication_digest') != self.publication_digest):
                raise RuntimeError('enrichment_reservation_changed')
            snapshot = self.snapshot(cur, row)
            if digest(snapshot) != self.publication_digest:
                raise RuntimeError('reviewed_publication_changed')
            plan = build_apply_plan(row, tracks, snapshot, payload)
            prior.update(status='complete', results=payload, results_digest=digest(payload),
                         conflicts=plan['conflicts'], applied=False, publication_mode='reviewed-owner-apply')
            if not plan['conflicts'] and not self.stage_only:
                self.apply(cur, row, plan)
                prior.update(applied=True, post_digest=digest(self.snapshot(cur, row)))
            self.write(cur, prior)

    def apply(self, cur, row, plan):
        # A temporary position range avoids uniqueness collisions while restoring
        # production Unknown Track placeholders. Existing IDs never change.
        cur.execute('UPDATE app.set_entries SET position=-position WHERE set_id=%s', (row['target_set_id'],))
        for change in plan['entries']:
            meta = change['metadata']
            if change['insert']:
                cur.execute("""INSERT INTO app.set_entries(id,set_id,position,display_artist,
                    display_title,start_time_seconds,end_time_seconds,confidence,detection_count,
                    cluster_density,cluster_span,source_deep_link,metadata)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s::jsonb)""",
                    (change['id'],row['target_set_id'],change['position'],meta['artist'],meta['title'],
                     round(meta['start_time']),None if meta['end_time'] is None else round(meta['end_time']),
                     meta['confidence'],meta['detection_count'],meta['cluster_density'],meta['cluster_span'],json.dumps(meta)))
            else:
                cur.execute("""UPDATE app.set_entries SET position=%s,metadata=%s::jsonb,updated_at=now()
                    WHERE id=%s AND set_id=%s""",
                    (change['position'],json.dumps(meta),change['id'],row['target_set_id']))
        cur.execute("""UPDATE app.sets SET metadata=%s::jsonb,recognition_rate=%s,updated_at=now()
            WHERE id=%s AND collection_id=%s AND visibility='private'""",
            (json.dumps(plan['set_metadata']),plan['recognition_rate'],row['target_set_id'],row['collection_id']))


DIAGNOSTIC_PHASE = 'preflight'


def diagnostic_code(error):
    if getattr(error, 'sqlstate', None) == '42501':
        return 'database_permission_denied'
    if getattr(error, 'sqlstate', None) in ('55P03', '40P01', '57014'):
        return 'database_lock_or_timeout'
    allowed = {
        'private_preview_only', 'explicit_rich_metadata_required', 'expected_identity_required',
        'discogs_credentials_required', 'spotify_credentials_required', 'publication_digest_required',
        'private_scope_required', 'private_audience_changed', 'published_private_set_required',
        'private_mix_info_required', 'private_mix_source_url_forbidden', 'reviewed_publication_changed',
        'private_admission_capacity', 'private_admission_duplicate_target', 'private_admission_uncertain_owner',
        'private_admission_unknown_state', 'private_admission_uncertain_enrichment',
        'source_changed', 'completed_cluster_changed', 'completed_private_run_required',
        'reviewed_fresh_source_required', 'private_identity_changed', 'window_coverage_changed',
        'window_evidence_changed', 'fresh_window_evidence_changed', 'attempt_evidence_changed',
        'uncertain_or_changed_enrichment_requires_review', 'prior_spotify_evidence_changed',
        'prior_spotify_evidence_invalid', 'production_track_count_changed', 'production_recognition_changed',
        'published_recognition_changed', 'recognized_entry_missing', 'published_entries_not_in_cluster',
        'enrichment_reservation_changed', 'published_spotify_receipt_conflict', 'published_link_evidence_missing',
        'production_link_evidence_missing', 'private_entry_identity_ambiguous',
    }
    return str(error) if type(error) is RuntimeError and str(error) in allowed else 'private_metadata_failed'


def main():
    global DIAGNOSTIC_PHASE
    if (os.environ.get('WORKER_DEPLOYMENT_TARGET') != 'development'
            or os.environ.get('GITHUB_REF') != 'refs/heads/preview'
            or os.environ.get('GITHUB_REPOSITORY') != 'russell-algeo/dj-setlist-generator'
            or os.environ.get('PRIVATE_RUN_ID') not in REVIEWED_RUNS):
        raise RuntimeError('private_preview_only')
    expected = json.loads(os.environ['PRIVATE_ENRICHMENT_EXPECTED'])
    if expected.pop('rich_metadata', False) is not True:
        raise RuntimeError('explicit_rich_metadata_required')
    if set(expected) != {'target_set_id','collection_id','submission_id','requested_by',
                         'source_digest','cluster_digest','publication_digest'}:
        raise RuntimeError('expected_identity_required')
    # These use existing approved credentials; granting this job credential access
    # belongs to the reviewed workflow change, never runtime credential discovery.
    if not (os.environ.get('DISCOGS_TOKEN') or
            os.environ.get('DISCOGS_CONSUMER_KEY') and os.environ.get('DISCOGS_CONSUMER_SECRET')):
        raise RuntimeError('discogs_credentials_required')
    if not os.environ.get('SPOTIFY_CLIENT_ID') or not os.environ.get('SPOTIFY_CLIENT_SECRET'):
        raise RuntimeError('spotify_credentials_required')
    os.environ.update(ENABLE_SPOTIFY='true',ENABLE_YOUTUBE='true',ENABLE_DISCOGS='true',
        ENABLE_SPOTIFY_PLAYLISTS='false',CREATE_SET_PLAYLISTS='false',ENABLE_CHECKPOINTS='false',NTFY_TOPIC='')
    store = MetadataStore(expected,os.environ['GITHUB_RUN_ID'],os.environ['GITHUB_RUN_ATTEMPT'],os.environ['PRIVATE_RUN_ID'])
    DIAGNOSTIC_PHASE = 'reservation'
    ticket, tracks, mix = store.reserve()
    if ticket is not None:
        DIAGNOSTIC_PHASE = 'providers'
        payload = production_payload(tracks, mix)
        DIAGNOSTIC_PHASE = 'stage_results'
        store.finish(ticket, payload)


if __name__ == '__main__':
    diagnostic_fd = os.dup(2)
    try:
        with open(os.devnull,'w') as sink, tempfile.TemporaryDirectory(prefix='private-metadata-') as tmp:
            os.dup2(sink.fileno(),1)
            os.dup2(sink.fileno(),2)
            os.chdir(tmp)
            main()
    except Exception as error:
        os.write(diagnostic_fd, ('private_metadata phase=' + DIAGNOSTIC_PHASE +
            ' code=' + diagnostic_code(error) + '\n').encode())
        raise SystemExit(1)
    finally:
        os.close(diagnostic_fd)
