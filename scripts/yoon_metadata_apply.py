"""Compile a guarded owner-connector apply from a private read-only snapshot.

No connection or credential handling. Capture --run-id SQL's snapshot_json
privately, then pass --snapshot-json to produce a reviewed SQL transaction plan.
Only metadata/positions/Unknown placeholders change; access and media do not.
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from worker.jobs.yoon_spotify_enrich import REVIEWED_RUNS, validate, digest
from worker.jobs.yoon_metadata_enrich import KEY, build_apply_plan
from scripts.yoon_metadata_pins import snapshot_sql as pin_snapshot_sql

PUBLICATION_KEY = 'yoon_metadata_publication_v1'


def snapshot_sql(run_id):
    if run_id not in REVIEWED_RUNS:
        raise RuntimeError('reviewed_run_required')
    # Fingerprints are produced and compared by PostgreSQL, avoiding JSON number
    # formatting differences between connectors, JavaScript and Python.
    return """WITH p AS (%s), detail AS (
      SELECT r.*,to_jsonb(r) AS full_row,p.value->'publication' AS publication,
        (SELECT coalesce(jsonb_agg(jsonb_build_object('segment_index',h.segment_index,'raw_data',h.raw_data)
            ORDER BY h.segment_index),'[]'::jsonb) FROM ops.segment_hits h WHERE h.set_run_id=r.id) AS hits,
        (SELECT coalesce(jsonb_agg(jsonb_build_object('user_id',m.user_id,'role',m.role)
            ORDER BY m.user_id),'[]'::jsonb) FROM app.archive_collection_members m WHERE m.collection_id=r.collection_id) AS members,
        (SELECT jsonb_build_object('id',o.id,'source_metadata',o.source_metadata,
            'metadata_sha256',encode(digest(o.source_metadata::text,'sha256'),'hex')) FROM ops.set_runs o
            WHERE o.id=(r.source_metadata->'yoon_resume'->'origin'->>'run_id')::uuid) AS origin
      FROM ops.set_runs r CROSS JOIN p WHERE r.id='%s'::uuid)
      SELECT jsonb_build_object('run',full_row,'publication',publication,'hits',hits,'members',members,'origin',origin,
        'fingerprints',jsonb_build_object(
          'run',encode(digest(((full_row-'updated_at'-'source_metadata') ||
              jsonb_build_object('source_metadata',source_metadata-'%s'))::text,'sha256'),'hex'),
          'publication',encode(digest(publication::text,'sha256'),'hex'),
          'hits',encode(digest(hits::text,'sha256'),'hex'),
          'members',encode(digest(members::text,'sha256'),'hex'),
          'origin',encode(digest(coalesce(origin,'null'::jsonb)::text,'sha256'),'hex')))::text AS snapshot_json
      FROM detail""" % (pin_snapshot_sql(run_id),run_id,PUBLICATION_KEY)


def prepare_apply(run_id, snapshot):
    row=snapshot['run'];receipt=row['source_metadata'].get(KEY) or {}
    if str(row['id']) != run_id or run_id not in REVIEWED_RUNS:
        raise RuntimeError('reviewed_run_required')
    expected=receipt.get('input') or {}
    tracks=validate(row,row['source_metadata']['yoon_resume'],snapshot['hits'],expected,snapshot['origin'])
    if (receipt.get('status')!='complete' or receipt.get('conflicts') or receipt.get('applied')
            or receipt.get('publication_mode')!='reviewed-owner-apply'
            or digest(receipt.get('results'))!=receipt.get('results_digest')
            or digest(snapshot['publication'])!=receipt.get('publication_digest')
            or snapshot['members']!=row['source_metadata']['yoon_resume']['members']):
        raise RuntimeError('reviewed_metadata_receipt_required')
    plan=build_apply_plan(row,tracks,snapshot['publication'],receipt['results'])
    if plan['conflicts']:
        raise RuntimeError('metadata_conflicts_require_review')
    fingerprints=snapshot['fingerprints']
    proof=dict(version=1,status='complete',run_id=run_id,target_set_id=expected['target_set_id'],
        results_digest=receipt['results_digest'],plan_digest=digest(plan),
        before_fingerprints=fingerprints,entry_count=len(plan['entries']))
    payload=dict(run_id=run_id,set_id=expected['target_set_id'],collection_id=expected['collection_id'],
        submission_id=expected['submission_id'],fingerprints=fingerprints,plan=plan,receipt=proof)
    literal="'"+json.dumps(payload,separators=(',',':'),ensure_ascii=False).replace("'","''")+"'::jsonb"
    read="("+snapshot_sql(run_id)+")::jsonb"
    sql="""DO $private_metadata_apply$ DECLARE
      p jsonb := %s; current_snapshot jsonb; prior jsonb; item jsonb; n integer; post text;
    BEGIN
      IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'private_metadata_requires_read_committed';
      END IF;
      PERFORM pg_advisory_xact_lock(183601,2);
      PERFORM 1 FROM ops.set_runs WHERE id=(p->>'run_id')::uuid FOR UPDATE;
      PERFORM 1 FROM ops.submissions WHERE id=(p->>'submission_id')::uuid FOR UPDATE;
      PERFORM 1 FROM app.archive_collections WHERE id=(p->>'collection_id')::uuid FOR UPDATE;
      PERFORM 1 FROM app.archive_collection_members WHERE collection_id=(p->>'collection_id')::uuid ORDER BY user_id FOR UPDATE;
      PERFORM 1 FROM app.sets WHERE id=(p->>'set_id')::uuid FOR UPDATE;
      PERFORM 1 FROM app.set_entries WHERE set_id=(p->>'set_id')::uuid ORDER BY position,id FOR UPDATE;
      PERFORM 1 FROM app.set_media WHERE set_id=(p->>'set_id')::uuid FOR SHARE;
      PERFORM 1 FROM app.set_source_links WHERE set_id=(p->>'set_id')::uuid FOR SHARE;
      PERFORM 1 FROM ops.segment_hits WHERE set_run_id=(p->>'run_id')::uuid ORDER BY segment_index FOR SHARE;
      PERFORM 1 FROM ops.set_runs o WHERE o.id=(SELECT
        (source_metadata->'yoon_resume'->'origin'->>'run_id')::uuid
        FROM ops.set_runs WHERE id=(p->>'run_id')::uuid) FOR SHARE;
      current_snapshot := %s;
      IF current_snapshot IS NULL THEN RAISE EXCEPTION 'private_metadata_scope_changed'; END IF;
      prior := current_snapshot#>'{run,source_metadata,%s}';
      IF prior IS NOT NULL THEN
        IF prior-'post_fingerprint' IS DISTINCT FROM p->'receipt'
          OR current_snapshot#>>'{fingerprints,publication}' IS DISTINCT FROM prior->>'post_fingerprint'
          OR current_snapshot#>>'{fingerprints,run}' IS DISTINCT FROM p#>>'{fingerprints,run}'
          OR current_snapshot#>>'{fingerprints,hits}' IS DISTINCT FROM p#>>'{fingerprints,hits}'
          OR current_snapshot#>>'{fingerprints,members}' IS DISTINCT FROM p#>>'{fingerprints,members}'
          OR current_snapshot#>>'{fingerprints,origin}' IS DISTINCT FROM p#>>'{fingerprints,origin}'
        THEN RAISE EXCEPTION 'private_metadata_prior_publication_changed'; END IF;
        RETURN;
      END IF;
      IF current_snapshot->'fingerprints' IS DISTINCT FROM p->'fingerprints'
      THEN RAISE EXCEPTION 'private_metadata_reviewed_snapshot_changed'; END IF;
      UPDATE app.set_entries SET position=-position WHERE set_id=(p->>'set_id')::uuid;
      FOR item IN SELECT value FROM jsonb_array_elements(p#>'{plan,entries}') LOOP
        IF (item->>'insert')::boolean THEN
          INSERT INTO app.set_entries(id,set_id,position,display_artist,display_title,start_time_seconds,
            end_time_seconds,confidence,detection_count,cluster_density,cluster_span,source_deep_link,metadata)
          VALUES((item->>'id')::uuid,(p->>'set_id')::uuid,(item->>'position')::integer,
            item#>>'{metadata,artist}',item#>>'{metadata,title}',round((item#>>'{metadata,start_time}')::numeric)::integer,
            round((item#>>'{metadata,end_time}')::numeric)::integer,item#>>'{metadata,confidence}',
            (item#>>'{metadata,detection_count}')::integer,(item#>>'{metadata,cluster_density}')::numeric,
            (item#>>'{metadata,cluster_span}')::integer,NULL,item->'metadata');
        ELSE
          UPDATE app.set_entries SET position=(item->>'position')::integer,metadata=item->'metadata',updated_at=now()
            WHERE id=(item->>'id')::uuid AND set_id=(p->>'set_id')::uuid;
          GET DIAGNOSTICS n=ROW_COUNT;
          IF n<>1 THEN RAISE EXCEPTION 'private_metadata_entry_changed'; END IF;
        END IF;
      END LOOP;
      UPDATE app.sets SET metadata=p#>'{plan,set_metadata}',recognition_rate=(p#>>'{plan,recognition_rate}')::numeric,
        updated_at=now() WHERE id=(p->>'set_id')::uuid AND visibility='private' AND collection_id=(p->>'collection_id')::uuid;
      GET DIAGNOSTICS n=ROW_COUNT;
      IF n<>1 THEN RAISE EXCEPTION 'private_metadata_target_changed'; END IF;
      current_snapshot := %s;
      post:=current_snapshot#>>'{fingerprints,publication}';
      UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{%s}',
        (p->'receipt')||jsonb_build_object('post_fingerprint',post)),updated_at=now()
        WHERE id=(p->>'run_id')::uuid;
    END $private_metadata_apply$""" % (literal,read,PUBLICATION_KEY,read,PUBLICATION_KEY)
    # A dollar quote inside a song title/profile/metadata value must remain
    # literal data, never terminate the PL/pgSQL body.
    body=sql.removeprefix('DO $private_metadata_apply$ ').removesuffix(' $private_metadata_apply$')
    counter=0
    while True:
        delimiter='$private_metadata_'+digest([body,counter])[:20]+'$'
        if delimiter not in body:break
        counter+=1
    sql='DO '+delimiter+' '+body+' '+delimiter
    return dict(mode='reviewed-private-metadata-apply',run_id=run_id,
        plan_digest=digest(plan),entry_count=len(plan['entries']),
        sql_statements=["SET LOCAL lock_timeout='5s'","SET LOCAL statement_timeout='30s'",sql])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True);parser.add_argument('--snapshot-json',type=Path)
    args=parser.parse_args()
    if args.snapshot_json:
        print(json.dumps(prepare_apply(args.run_id,json.loads(args.snapshot_json.read_text())),indent=2))
    else:print(snapshot_sql(args.run_id))

if __name__=='__main__':main()
