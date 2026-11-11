"""Offline SQL compiler for reviewed Yoon version registry operations.

No network, credentials, automatic inference, registration or execution. Inputs
are private owner-reviewed PostgreSQL snapshots, never capability-bearing logs.
The caller must review and execute the returned transaction through its existing
owner route. The migration deliberately performs no bootstrap or dispatch.
"""
import json
import re
import uuid

COLUMNS = (
    'set_id', 'logical_set_id', 'model_version', 'source_id', 'run_id',
    'submission_id', 'media_id', 'slug', 'media_revision', 'collection_id',
    'requested_by', 'predecessor_set_id', 'manifest_sha256', 'source_sha256',
    'media_sha256', 'audience_sha256', 'staging_approved',
    'processing_approved', 'released', 'frozen',
)
CHECKS = ('independent_review', 'source_matched', 'ordered_windows',
          'stable_derivative', 'import_complete', 'metadata_complete',
          'timestamps_and_spans', 'audience_unchanged')


def literal(value):
    if value is None:
        return 'NULL'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return "'" + str(value).replace("'", "''") + "'"


def json_literal(value):
    return literal(json.dumps(value, separators=(',', ':'), allow_nan=False)) + '::jsonb'


def valid_hash(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('reviewed_sha256_required')
    return value


def registration(row):
    if set(row) != set(COLUMNS):
        raise ValueError('exact_registry_columns_required')
    for key in ('set_id', 'logical_set_id', 'run_id', 'submission_id', 'media_id', 'collection_id'):
        if str(uuid.UUID(row[key])) != row[key]:
            raise ValueError('canonical_uuid_required')
    for key in ('manifest_sha256', 'source_sha256', 'media_sha256', 'audience_sha256'):
        valid_hash(row[key])
    for key in ('staging_approved', 'processing_approved', 'released', 'frozen'):
        if type(row[key]) is not bool:
            raise ValueError('boolean_required')
    return ('INSERT INTO ops.yoon_versions(' + ','.join(COLUMNS) + ') VALUES(' +
            ','.join(literal(row[k]) for k in COLUMNS) + ');')


def bootstrap_sql(collection_id, audience_sha256, reviewed_rows, reviewed_snapshots):
    """Exactly 27 explicit identities plus DB-produced snapshot hashes.

    Reads and preserves existing rows. Initial released status does not freeze
    ongoing final-chain work. Deliberately non-idempotent: a repeated bootstrap
    fails instead of overwriting the previous review.
    """
    uuid.UUID(collection_id)
    valid_hash(audience_sha256)
    if len(reviewed_rows) != 27 or len(reviewed_snapshots) != 27:
        raise ValueError('reviewed_27_required')
    ids = {r['set_id'] for r in reviewed_rows}
    if len(ids) != 27 or ids != {x['set_id'] for x in reviewed_snapshots}:
        raise ValueError('snapshot_identity_mismatch')
    for item in reviewed_snapshots:
        if set(item) != {'set_id', 'snapshot_sha256'}:
            raise ValueError('exact_snapshot_pins_required')
        valid_hash(item['snapshot_sha256'])
    manifest = json_literal(reviewed_snapshots)
    statements = ['BEGIN;', 'SELECT ops.yoon_registry_lock();',
                  'INSERT INTO ops.yoon_version_collections(collection_id,audience_sha256,bootstrap_manifest,bootstrap_sha256) VALUES(' +
                  ','.join((literal(collection_id), literal(audience_sha256), manifest, 'ops.yoon_sha(' + manifest + ')')) + ');']
    for row in reviewed_rows:
        if (row['collection_id'] != collection_id or row['audience_sha256'] != audience_sha256
                or row['predecessor_set_id'] is not None or row['logical_set_id'] != row['set_id']
                or not row['released'] or row['frozen']):
            raise ValueError('legacy_bootstrap_scope_invalid')
        statements.append('INSERT INTO ops.yoon_version_families(logical_set_id,collection_id,selected_set_id) VALUES(' +
                          ','.join(literal(row[k]) for k in ('logical_set_id', 'collection_id', 'set_id')) + ');')
        statements.append(registration(row))
    statements.append('COMMIT;')
    return '\n'.join(statements)


def stage_sql(row, initial_rows):
    """Register fresh staged identity and skeleton rows atomically, unapproved
    for execution. The SQL constraints verify finite IDs, source pins and media.
    Private input rows must be reviewed in full; this helper never prints them.
    """
    if (not row['staging_approved'] or row['processing_approved'] or row['released']
            or row['frozen'] or not row['predecessor_set_id']):
        raise ValueError('fresh_unapproved_staging_required')
    if set(initial_rows) != {'app.sets', 'ops.submissions', 'ops.set_runs', 'app.set_media'}:
        raise ValueError('exact_fresh_rows_required')
    statements = ['BEGIN;', 'SELECT ops.yoon_registry_lock();', registration(row)]
    for table in ('app.sets', 'ops.submissions', 'ops.set_runs', 'app.set_media'):
        values = initial_rows[table]
        if not values or any(not re.fullmatch('[a-z_]+', k) for k in values):
            raise ValueError('invalid_row_columns')
        columns = ','.join('"' + k + '"' for k in values)
        statements.append(f'INSERT INTO {table}({columns}) SELECT {columns} FROM jsonb_populate_record(NULL::{table},{json_literal(values)});')
    statements.append('COMMIT;')
    return '\n'.join(statements)


def approve_execution_sql(set_id, expected_registration):
    """A distinct reviewed approval; never implicit in staging or release."""
    uuid.UUID(set_id)
    if expected_registration['set_id'] != set_id or expected_registration['processing_approved']:
        raise ValueError('unapproved_identity_required')
    registration(expected_registration)
    return "\n".join(['BEGIN;', 'SELECT ops.yoon_registry_lock();',
        'DO $approval$ BEGIN IF NOT EXISTS(SELECT 1 FROM ops.yoon_versions v WHERE to_jsonb(v)=' + json_literal(expected_registration) +
        ") THEN RAISE EXCEPTION 'yoon_approval_identity_changed'; END IF; END $approval$;",
        'SELECT ops.assert_yoon_version_identity(' + literal(set_id) + ');',
        'UPDATE ops.yoon_versions SET processing_approved=true WHERE set_id=' + literal(set_id) + ';', 'COMMIT;'])


def selection_sql(family, expected_set, expected_revision, new_set, review, *, rollback=False):
    for value in (family, expected_set, new_set):
        uuid.UUID(value)
    if type(expected_revision) is not int or expected_revision < 0 or type(rollback) is not bool:
        raise ValueError('exact_cas_required')
    if (review.get('old_set_id') != expected_set or review.get('new_set_id') != new_set
            or not isinstance(review.get('reviewer'), str) or not review['reviewer'].strip()
            or any(review.get('checks', {}).get(k) is not True for k in CHECKS)):
        raise ValueError('independent_complete_review_required')
    old = valid_hash(review.get('old_snapshot_sha256'))
    new = valid_hash(review.get('new_snapshot_sha256'))
    document = json_literal(review)
    args = [literal(family), literal(expected_set), str(expected_revision), literal(new_set),
            literal(old), literal(new), f'ops.yoon_sha({document})', literal(rollback)]
    return '\n'.join(['BEGIN;', 'SELECT ops.yoon_registry_lock();',
        f'INSERT INTO ops.yoon_release_reviews(review_sha256,review) VALUES(ops.yoon_sha({document}),{document});',
        'SELECT ops.select_yoon_version(' + ','.join(args) + ');', 'COMMIT;'])


def initialize_execution_sql(set_id):
    """Separately approved fresh initialization using DB pins and audience.

    No queue enrollment, dispatch or provider requests. Repeated initialization
    fails closed rather than resetting counters or reusing existing evidence.
    """
    if str(uuid.UUID(set_id)) != set_id:
        raise ValueError('canonical_uuid_required')
    return '\n'.join(['BEGIN;', 'SELECT ops.yoon_registry_lock();',
                      'SELECT ops.initialize_yoon_version_execution(' + literal(set_id) + ');', 'COMMIT;'])
