"""Prepare (never execute) a fingerprint-guarded repair of lost coverage metadata.

Use the retained pre-enrichment snapshot and a fresh current snapshot from
--run-id. This operator restores only original coverage/provenance and rate;
it does not rerun enrichment, change tracks or alter access/media.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.yoon_metadata_apply import snapshot_sql, PUBLICATION_KEY
from worker.jobs.yoon_metadata_enrich import KEY, build_apply_plan
from worker.jobs.yoon_spotify_enrich import REVIEWED_RUNS, digest

REPAIR_KEY = 'yoon_metadata_coverage_repair_v1'
RESTORE_KEYS = ('recognitionCoverage', 'privateRecognitionProvenance')


def prepare_repair(run_id, before, current):
    if run_id not in REVIEWED_RUNS or any(s['run']['id'] != run_id for s in (before, current)):
        raise RuntimeError('reviewed_run_required')
    old_run, run = before['run'], current['run']
    receipt = old_run['source_metadata'].get(KEY) or {}
    proof = run['source_metadata'].get(PUBLICATION_KEY) or {}
    if (receipt.get('status') != 'complete' or receipt.get('conflicts') or receipt.get('applied')
            or receipt.get('publication_mode') != 'reviewed-owner-apply'
            or digest(receipt.get('results')) != receipt.get('results_digest')
            or digest(before['publication']) != receipt.get('publication_digest')
            or proof.get('before_fingerprints') != before['fingerprints']
            or proof.get('results_digest') != receipt.get('results_digest')
            or proof.get('post_fingerprint') != current['fingerprints']['publication']):
        raise RuntimeError('original_publication_proof_required')
    for key in ('run', 'hits', 'members', 'origin'):
        if before['fingerprints'][key] != current['fingerprints'][key]:
            raise RuntimeError('recognition_or_access_changed')
    old, now = before['publication'], current['publication']
    target = old_run['target_set_id']
    if (now['set']['id'] != target or old['set']['id'] != target
            or now['set']['visibility'] != 'private'
            or now['set']['collection_id'] != run['collection_id']
            or old['media'] != now['media'] or old['source_links'] != now['source_links']):
        raise RuntimeError('private_publication_scope_changed')
    summary = old['set']['metadata'].get('summary') or {}
    if not all(key in summary for key in RESTORE_KEYS) or old['set'].get('recognition_rate') is None:
        raise RuntimeError('original_coverage_required')
    plan = build_apply_plan(old_run, old_run['source_metadata']['yoon_resume']['clustered_setlist'],
                            old, receipt['results'])
    if plan['conflicts']:
        raise RuntimeError('metadata_conflicts_require_review')
    expected_metadata = deepcopy(plan['set_metadata'])
    # The original buggy publication replaced summary instead of merging it.
    expected_metadata['summary'] = deepcopy(receipt['results']['metadata'])
    total = receipt['results']['metadata']['total_tracks']
    uncertain = receipt['results']['metadata'].get('uncertain_tracks', 0)
    old_buggy_rate = round((total - uncertain) / total * 100, 2) if total else None
    if now['set']['metadata'] != expected_metadata or now['set']['recognition_rate'] != old_buggy_rate:
        raise RuntimeError('expected_unrepaired_publication_required')
    expected = {entry['id']: entry for entry in plan['entries']}
    if len(now['entries']) != len(expected):
        raise RuntimeError('published_entries_changed')
    for entry in now['entries']:
        wanted = expected.get(entry['id'])
        if (not wanted or entry['metadata'] != wanted['metadata'] or entry['position'] != wanted['position']):
            raise RuntimeError('published_entries_changed')
    repaired_summary = deepcopy(now['set']['metadata']['summary'])
    repaired_summary.update({key: deepcopy(summary[key]) for key in RESTORE_KEYS})
    payload = dict(run_id=run_id, set_id=target, collection_id=run['collection_id'],
                   fingerprints=current['fingerprints'], summary=repaired_summary,
                   recognition_rate=old['set']['recognition_rate'],
                   receipt=dict(version=1, run_id=run_id, restored_keys=list(RESTORE_KEYS),
                     original_snapshot_sha256=digest(before), reviewed_snapshot_sha256=digest(current),
                     restored_recognition_rate=old['set']['recognition_rate']))
    literal="'"+json.dumps(payload,separators=(',',':')).replace("'","''")+"'::jsonb"
    body="""DECLARE p jsonb := %s; current_snapshot jsonb; n integer;
    BEGIN
      IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'coverage_repair_requires_read_committed'; END IF;
      PERFORM pg_advisory_xact_lock(183601,2);
      PERFORM 1 FROM ops.set_runs WHERE id=(p->>'run_id')::uuid FOR UPDATE;
      PERFORM 1 FROM app.archive_collections WHERE id=(p->>'collection_id')::uuid FOR UPDATE;
      PERFORM 1 FROM app.archive_collection_members WHERE collection_id=(p->>'collection_id')::uuid ORDER BY user_id FOR UPDATE;
      PERFORM 1 FROM app.sets WHERE id=(p->>'set_id')::uuid FOR UPDATE;
      PERFORM 1 FROM app.set_entries WHERE set_id=(p->>'set_id')::uuid ORDER BY position,id FOR SHARE;
      PERFORM 1 FROM app.set_media WHERE set_id=(p->>'set_id')::uuid FOR SHARE;
      PERFORM 1 FROM app.set_source_links WHERE set_id=(p->>'set_id')::uuid FOR SHARE;
      PERFORM 1 FROM ops.segment_hits WHERE set_run_id=(p->>'run_id')::uuid ORDER BY segment_index FOR SHARE;
      PERFORM 1 FROM ops.set_runs o WHERE o.id=(SELECT
        (source_metadata->'yoon_resume'->'origin'->>'run_id')::uuid
        FROM ops.set_runs WHERE id=(p->>'run_id')::uuid) FOR SHARE;
      current_snapshot := (%s)::jsonb;
      IF current_snapshot IS NULL OR current_snapshot->'fingerprints' IS DISTINCT FROM p->'fingerprints'
      THEN RAISE EXCEPTION 'coverage_repair_reviewed_snapshot_changed'; END IF;
      UPDATE app.sets SET metadata=jsonb_set(metadata,'{summary}',p->'summary') ||
          jsonb_build_object('%s',p->'receipt'), recognition_rate=(p->>'recognition_rate')::numeric, updated_at=now()
        WHERE id=(p->>'set_id')::uuid AND collection_id=(p->>'collection_id')::uuid AND visibility='private';
      GET DIAGNOSTICS n=ROW_COUNT;
      IF n<>1 THEN RAISE EXCEPTION 'coverage_repair_target_changed'; END IF;
    END""" % (literal,snapshot_sql(run_id),REPAIR_KEY)
    counter=0
    while True:
        delimiter='$coverage_repair_'+digest([body,counter])[:20]+'$'
        if delimiter not in body: break
        counter+=1
    return dict(mode='reviewed-private-coverage-repair', run_id=run_id,
                plan_digest=digest(payload), restored_keys=list(RESTORE_KEYS),
                sql_statements=["SET LOCAL lock_timeout='5s'", "SET LOCAL statement_timeout='30s'",
                                'DO '+delimiter+' '+body+' '+delimiter])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-id',required=True)
    p.add_argument('--before-snapshot',type=Path)
    p.add_argument('--current-snapshot',type=Path)
    a=p.parse_args()
    if a.before_snapshot and a.current_snapshot:
        print(json.dumps(prepare_repair(a.run_id,json.loads(a.before_snapshot.read_text()),
                                       json.loads(a.current_snapshot.read_text())),indent=2))
    elif a.before_snapshot or a.current_snapshot:
        p.error('both snapshots are required')
    else: print(snapshot_sql(a.run_id))


if __name__ == '__main__': main()
