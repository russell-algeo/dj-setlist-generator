"""Read-only pin preparation; never connects, dispatches, or publishes.

Without --snapshot-json, emit a read-only SELECT for the reviewed run. Capture
its single `value` result privately as JSON (the snapshot contains private media
references). With --snapshot-json, emit only identity/digest dispatch pins.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worker.jobs.yoon_spotify_enrich import REVIEWED_RUNS, digest


def snapshot_sql(run_id):
    if run_id not in REVIEWED_RUNS:
        raise RuntimeError('reviewed_run_required')
    return """SELECT jsonb_build_object(
      'identity',jsonb_build_object('run_id',r.id,'status',r.status,
          'target_set_id',r.target_set_id,'collection_id',r.collection_id,
          'submission_id',r.submission_id,'requested_by',r.requested_by,
          'published_set_id',r.published_set_id),
      'source',r.source_metadata->'yoon_fixed_input',
      'tracks',r.source_metadata->'yoon_resume'->'clustered_setlist',
      'publication',jsonb_build_object(
        'set',to_jsonb(s)-'updated_at',
        'entries',(SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY position,id),'[]'::jsonb)
            FROM app.set_entries e WHERE set_id=s.id),
        'media',(SELECT coalesce(jsonb_agg(to_jsonb(m) ORDER BY id),'[]'::jsonb)
            FROM app.set_media m WHERE set_id=s.id),
        'source_links',(SELECT coalesce(jsonb_agg(to_jsonb(l) ORDER BY id),'[]'::jsonb)
            FROM app.set_source_links l WHERE set_id=s.id))) AS value
      FROM ops.set_runs r JOIN app.sets s ON s.id=r.target_set_id
      JOIN ops.submissions u ON u.id=r.submission_id
      WHERE r.id='%s'::uuid AND r.publication_visibility='private'
        AND s.visibility='private' AND u.visibility='private'
        AND s.collection_id=r.collection_id AND u.collection_id=r.collection_id
        AND r.requested_by=u.requested_by AND r.published_set_id=r.target_set_id
        AND r.cancel_requested_at IS NULL AND u.cancel_requested_at IS NULL
        AND r.create_playlist=false AND u.create_playlist=false""" % run_id


def prepare_pins(run_id, snapshot):
    if run_id not in REVIEWED_RUNS:
        raise RuntimeError('reviewed_run_required')
    identity = snapshot['identity']
    if (identity['run_id'] != run_id or identity['status'] != 'private_resume_complete'
            or identity['published_set_id'] != identity['target_set_id']
            or not isinstance(snapshot['source'],dict)
            or not snapshot['tracks'] or not snapshot['publication']['entries']):
        raise RuntimeError('published_complete_private_run_required')
    pins = {key:identity[key] for key in ('target_set_id','collection_id','submission_id','requested_by')}
    pins.update(rich_metadata=True,source_digest=digest(snapshot['source']),cluster_digest=digest(snapshot['tracks']),
                publication_digest=digest(snapshot['publication']))
    return pins


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--snapshot-json',type=Path)
    args=parser.parse_args()
    if args.snapshot_json:
        print(json.dumps(prepare_pins(args.run_id,json.loads(args.snapshot_json.read_text())),sort_keys=True))
    else:
        print(snapshot_sql(args.run_id))

if __name__=='__main__':main()
