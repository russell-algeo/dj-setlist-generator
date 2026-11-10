"""Credential-free snapshot/SQL compiler for the existing private DB connector.

No connection, execution, credential handling or workflow dispatch is provided.
Read snapshot_sql(ids) through the authorized connector, review its private result,
then compile_enqueue(rows, ids). The emitted SQL contains IDs/hashes only; source
capability URLs and audience lists are copied inside the database, not embedded.
"""
import json
import hashlib
import re
import uuid

from worker.jobs.yoon_once import validate_descriptor
from worker.jobs.yoon_sources import JACKSON, reviewed_source
from worker.jobs.yoon_queue import KEY, identity, validate_identity


def _ids(values):
    ids = [str(uuid.UUID(value)) for value in values]
    if not ids or len(ids) > 100 or len(set(ids)) != len(ids):
        raise RuntimeError('private_queue_manifest_ids_invalid')
    return sorted(ids)


# Scope matches ResumeStore.locked: only joined private run/set/submission rows,
# no playlist, cancellation or ordinary publication, with unchanged requester.
_SCOPE = """
 r.publication_visibility='private' AND r.target_set_id=s.id AND s.visibility='private'
 AND r.collection_id=s.collection_id AND u.id=r.submission_id AND u.visibility='private'
 AND u.collection_id=r.collection_id AND r.requested_by=u.requested_by
 AND c.id=r.collection_id AND r.create_playlist=false AND u.create_playlist=false
 AND r.cancel_requested_at IS NULL AND u.cancel_requested_at IS NULL
 AND r.published_set_id IS NULL
"""
_MEMBERS = """(SELECT jsonb_agg(jsonb_build_object('user_id',m.user_id,'role',m.role) ORDER BY m.user_id)
 FROM app.archive_collection_members m WHERE m.collection_id=r.collection_id)"""


def snapshot_sql(run_ids):
    ids = _ids(run_ids)
    literals = ','.join("'" + value + "'::uuid" for value in ids)
    return f"""SELECT r.*, {_MEMBERS} AS current_members,
 encode(digest((r.source_metadata-'yoon_queue_v1')::text,'sha256'),'hex') AS state_sha256,
 encode(digest((r.source_metadata->'yoon_fixed_input')::text,'sha256'),'hex') AS descriptor_sha256,
 encode(digest(({_MEMBERS})::text,'sha256'),'hex') AS members_sha256
 FROM ops.set_runs r,app.sets s,ops.submissions u,app.archive_collections c
 WHERE r.id IN ({literals}) AND {_SCOPE} ORDER BY r.id;"""


def compile_enqueue(rows, run_ids):
    """Compile reviewed connector rows, never arbitrary IDs alone.

    Fresh admission pins the entire reviewed source/resume metadata and status.
    A repeat is a no-op only for the same source/audience identity already queued,
    even if a legitimate worker has since claimed it. No existing owner is reset.
    """
    ids = _ids(run_ids)
    if len(rows) != len(ids) or sorted(str(row['id']) for row in rows) != ids:
        raise RuntimeError('private_queue_snapshot_incomplete')
    expected, targets = [], set()
    for row in sorted(rows, key=lambda r: str(r['id'])):
        if (row.get('publication_visibility') != 'private' or row.get('create_playlist') is not False
                or row.get('cancel_requested_at') is not None or row.get('published_set_id') is not None):
            raise RuntimeError('private_queue_snapshot_scope_invalid')
        metadata = row['source_metadata']
        state = metadata.get('yoon_resume')
        descriptor = metadata.get('yoon_fixed_input')
        validate_descriptor(descriptor)
        source = reviewed_source(descriptor)
        if (not isinstance(state, dict) or type(state.get('version')) is not int or state['version'] != 1
                or descriptor.get('recognition_mode') != 'resumable'):
            raise RuntimeError('private_resume_required')
        if source != JACKSON and (state.get('initialization_mode') != 'fresh' or state.get('origin') or state.get('provenance_seeded')):
            raise RuntimeError('private_fresh_source_required')
        if source != JACKSON or 'source_id' in state:
            if state.get('source_id') != source.id or state.get('source_pins') != source.pins():
                raise RuntimeError('private_resume_source_changed')
        members = row['current_members']
        if not isinstance(members, list) or len(members) != 2 or members != state.get('members'):
            raise RuntimeError('private_resume_audience_changed')
        target = str(uuid.UUID(str(row['target_set_id'])))
        if target in targets:
            raise RuntimeError('private_queue_duplicate_target')
        targets.add(target)
        if KEY in metadata:
            validate_identity(row, state, metadata[KEY])
        elif row['status'] not in ('private_resume_pending','private_resume_paused','private_resume_complete'):
            raise RuntimeError('private_queue_active_or_ineligible')
        pins = {k: row[k] for k in ('state_sha256','descriptor_sha256','members_sha256')}
        if any(not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value) for value in pins.values()):
            raise RuntimeError('private_queue_snapshot_digest_invalid')
        expected.append({**{k: str(row[k]) for k in ('id','submission_id','target_set_id','collection_id','requested_by')},
                         **pins, 'status': row['status']})
    payload = json.dumps(expected, separators=(',', ':'), sort_keys=True)
    tag = '$queue_' + hashlib.sha256(payload.encode()).hexdigest()[:24] + '$'
    assert tag not in payload
    literal = "'" + payload.replace("'", "''") + "'::jsonb"
    return f"""DO {tag}
DECLARE expected jsonb; current_row record; members jsonb; scope_identity jsonb;
BEGIN
 IF current_setting('transaction_isolation') <> 'read committed' THEN
   RAISE EXCEPTION 'private_admission_requires_read_committed';
 END IF;
 PERFORM set_config('lock_timeout','5s',true);
 PERFORM set_config('statement_timeout','15s',true);
 PERFORM pg_advisory_xact_lock(183601,2);
 FOR expected IN SELECT value FROM jsonb_array_elements({literal}) LOOP
   SELECT r.* INTO current_row FROM ops.set_runs r,app.sets s,ops.submissions u,app.archive_collections c
   WHERE r.id=(expected->>'id')::uuid AND {_SCOPE}
   FOR UPDATE OF r,u;
   IF NOT FOUND THEN RAISE EXCEPTION 'private_queue_scope_changed'; END IF;
   SELECT jsonb_agg(jsonb_build_object('user_id',m.user_id,'role',m.role) ORDER BY m.user_id)
     INTO members FROM app.archive_collection_members m WHERE m.collection_id=current_row.collection_id;
   IF current_row.target_set_id::text IS DISTINCT FROM expected->>'target_set_id'
      OR current_row.submission_id::text IS DISTINCT FROM expected->>'submission_id'
      OR current_row.collection_id::text IS DISTINCT FROM expected->>'collection_id'
      OR current_row.requested_by IS DISTINCT FROM expected->>'requested_by'
      OR encode(digest((current_row.source_metadata->'yoon_fixed_input')::text,'sha256'),'hex') IS DISTINCT FROM expected->>'descriptor_sha256'
      OR encode(digest(members::text,'sha256'),'hex') IS DISTINCT FROM expected->>'members_sha256'
      OR members IS DISTINCT FROM current_row.source_metadata->'yoon_resume'->'members'
   THEN RAISE EXCEPTION 'private_queue_identity_changed'; END IF;
   scope_identity := jsonb_build_object('id',current_row.id::text,'submission_id',current_row.submission_id::text,
     'target_set_id',current_row.target_set_id::text,'collection_id',current_row.collection_id::text,
     'requested_by',current_row.requested_by,'descriptor',current_row.source_metadata->'yoon_fixed_input','members',members);
   IF current_row.source_metadata ? 'yoon_queue_v1' THEN
     IF current_row.source_metadata->'yoon_queue_v1'->'version' IS DISTINCT FROM '1'::jsonb
        OR current_row.source_metadata->'yoon_queue_v1'->'identity' IS DISTINCT FROM scope_identity
     THEN RAISE EXCEPTION 'private_queue_existing_identity_changed'; END IF;
     CONTINUE;
   END IF;
   IF current_row.status IS DISTINCT FROM expected->>'status'
      OR current_row.status NOT IN ('private_resume_pending','private_resume_paused','private_resume_complete')
      OR encode(digest((current_row.source_metadata-'yoon_queue_v1')::text,'sha256'),'hex') IS DISTINCT FROM expected->>'state_sha256'
   THEN RAISE EXCEPTION 'private_queue_snapshot_changed'; END IF;
   IF EXISTS(SELECT 1 FROM ops.set_runs r WHERE r.target_set_id=current_row.target_set_id
       AND r.id<>current_row.id AND r.source_metadata ? 'yoon_queue_v1')
   THEN RAISE EXCEPTION 'private_queue_duplicate_target'; END IF;
   UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{{yoon_queue_v1}}',
      jsonb_build_object('version',1,'identity',scope_identity,
        'status',CASE WHEN current_row.status='private_resume_complete' THEN 'complete' ELSE 'queued' END,
        'enqueued_at',extract(epoch from clock_timestamp()),'dispatch_count',0)),updated_at=now()
     WHERE id=current_row.id;
 END LOOP;
END
{tag};"""
