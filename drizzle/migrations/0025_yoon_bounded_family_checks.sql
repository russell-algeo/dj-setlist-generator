-- Keep all original scope, locking, ACL and fail-closed checks. PostgreSQL may
-- evaluate a costly busy() predicate before a same-family filter. Bound calls
-- procedurally to matching set_runs (including historical origin runs), without
-- changing yoon_run_busy, adding grants, or adding per-window global locks.
CREATE OR REPLACE FUNCTION ops.assert_yoon_version_execution(p_run_id uuid,p_purpose text,p_generation text DEFAULT NULL)
 RETURNS void LANGUAGE plpgsql AS $$
DECLARE v ops.yoon_versions; r ops.set_runs;
 family_run_id uuid;
BEGIN
 SELECT * INTO STRICT r FROM ops.set_runs WHERE id=p_run_id;
 SELECT * INTO v FROM ops.yoon_versions WHERE run_id=p_run_id;
 IF NOT FOUND THEN
  IF EXISTS(SELECT 1 FROM ops.yoon_version_collections WHERE collection_id=r.collection_id) OR EXISTS(SELECT 1 FROM ops.yoon_reserved_versions WHERE run_id=r.id) OR (ops.yoon_collection_scope(r.collection_id) AND ops.yoon_is_v2(to_jsonb(r))) THEN RAISE EXCEPTION 'yoon_unregistered_version'; END IF;
  RETURN;
 END IF;
 PERFORM ops.yoon_registry_lock();
 PERFORM pg_advisory_xact_lock(183602,hashtext(v.logical_set_id::text));
 SELECT * INTO STRICT v FROM ops.yoon_versions WHERE run_id=p_run_id;
 SELECT * INTO STRICT r FROM ops.set_runs WHERE id=p_run_id;
 PERFORM ops.assert_yoon_version_identity(v.set_id);
 IF p_purpose IS NULL OR p_purpose NOT IN ('recognition','metadata','import','queue','mutation','admit','enqueue') OR NOT v.processing_approved OR v.frozen THEN RAISE EXCEPTION 'yoon_execution_not_approved'; END IF;
 IF p_generation IS NOT NULL AND p_generation IS DISTINCT FROM r.source_metadata->'yoon_queue_v1'->>'generation' THEN RAISE EXCEPTION 'yoon_generation_mismatch'; END IF;
 IF p_purpose='enqueue' AND EXISTS(SELECT 1 FROM ops.set_runs other WHERE other.id<>p_run_id
  AND other.target_set_id IN(SELECT set_id FROM ops.yoon_versions WHERE logical_set_id=v.logical_set_id)
  AND other.source_metadata ? 'yoon_queue_v1'
  AND other.source_metadata->'yoon_queue_v1'->>'status' IS DISTINCT FROM 'complete') THEN
  RAISE EXCEPTION 'yoon_logical_family_already_enrolled'; END IF;
 FOR family_run_id IN SELECT other.id FROM ops.set_runs other WHERE other.id<>p_run_id
  AND other.target_set_id IN(SELECT set_id FROM ops.yoon_versions WHERE logical_set_id=v.logical_set_id) LOOP
  IF ops.yoon_run_busy(family_run_id) THEN RAISE EXCEPTION 'yoon_logical_family_occupied'; END IF;
 END LOOP;
END $$;
--> statement-breakpoint

CREATE OR REPLACE FUNCTION ops.yoon_mutation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE j jsonb; oldj jsonb; sid uuid; rid uuid; v ops.yoon_versions; cid uuid; oldcid uuid; running boolean:=false; parent_status text;
 family_run_id uuid;
BEGIN
 j:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 oldj:=CASE WHEN TG_OP='INSERT' THEN NULL ELSE to_jsonb(OLD) END;
 IF TG_OP='UPDATE' AND EXISTS(SELECT 1 FROM ops.yoon_versions ov WHERE
 (TG_TABLE_NAME='sets' AND ov.set_id=(oldj->>'id')::uuid) OR
 (TG_TABLE_NAME='set_runs' AND ov.run_id=(oldj->>'id')::uuid) OR
 (TG_TABLE_NAME='submissions' AND ov.submission_id=(oldj->>'id')::uuid)) AND
 (j->'id' IS DISTINCT FROM oldj->'id' OR j->'target_set_id' IS DISTINCT FROM oldj->'target_set_id' OR j->'collection_id' IS DISTINCT FROM oldj->'collection_id') THEN RAISE EXCEPTION 'yoon_identity_reparent'; END IF;

 IF TG_TABLE_NAME='sets' THEN sid:=(j->>'id')::uuid;
 ELSIF TG_TABLE_NAME IN ('set_entries','set_media','set_artists','set_source_links') THEN sid:=(j->>'set_id')::uuid;
 ELSIF TG_TABLE_NAME='set_runs' THEN sid:=(j->>'target_set_id')::uuid; rid:=(j->>'id')::uuid;
 ELSIF TG_TABLE_NAME='submissions' THEN SELECT set_id INTO sid FROM ops.yoon_versions WHERE submission_id=(j->>'id')::uuid;
 ELSE rid:=(j->>'set_run_id')::uuid; SELECT target_set_id INTO sid FROM ops.set_runs WHERE id=rid;
 END IF;
 SELECT * INTO v FROM ops.yoon_versions WHERE set_id=sid;
 IF NOT FOUND THEN
  cid:=coalesce((j->>'collection_id')::uuid,(SELECT collection_id FROM app.sets WHERE id=sid));
  oldcid:=coalesce((oldj->>'collection_id')::uuid,
    (SELECT collection_id FROM app.sets WHERE id=(oldj->>'set_id')::uuid),
    (SELECT collection_id FROM ops.set_runs WHERE id=(oldj->>'set_run_id')::uuid));
  IF EXISTS(SELECT 1 FROM ops.yoon_version_collections WHERE collection_id=cid) OR EXISTS(SELECT 1 FROM ops.yoon_reserved_versions WHERE set_id=sid OR run_id=rid OR submission_id=(j->>'id')::uuid OR media_id=(j->>'id')::uuid) OR (ops.yoon_collection_scope(cid) AND ops.yoon_is_v2(j)) OR (ops.yoon_collection_scope(oldcid) AND ops.yoon_is_v2(oldj)) THEN RAISE EXCEPTION 'yoon_unregistered_write'; END IF;
 ELSE
  -- Narrow raw-write fast path: a committed running owner makes promotion
  -- fail quiescence until this transaction commits. Child writes lock the
  -- registered parent first, preventing release from racing their final write.
  IF TG_TABLE_NAME='set_runs' AND TG_OP='UPDATE' AND rid=v.run_id
   AND oldj->>'status' IN ('private_resume_running','private_analysis_running')
   AND ((j->'source_metadata')-'yoon_resume'-'yoon_analysis') IS NOT DISTINCT FROM ((oldj->'source_metadata')-'yoon_resume'-'yoon_analysis') THEN running:=true;
  ELSIF TG_TABLE_NAME IN ('segment_hits','set_run_leases') AND rid=v.run_id THEN
   SELECT status INTO parent_status FROM ops.set_runs WHERE id=v.run_id FOR UPDATE;
   running:=parent_status IN ('private_resume_running','private_analysis_running');
  END IF;
  IF NOT coalesce(running,false) THEN PERFORM ops.yoon_registry_lock(); END IF;
  -- Never use the registry snapshot read before lock acquisition.
  SELECT * INTO STRICT v FROM ops.yoon_versions WHERE set_id=sid;
  IF v.frozen THEN RAISE EXCEPTION 'yoon_frozen_evidence'; END IF;
  IF NOT v.processing_approved AND NOT (v.staging_approved AND TG_OP='INSERT' AND TG_TABLE_NAME IN ('sets','submissions','set_runs','set_media')) THEN RAISE EXCEPTION 'yoon_unapproved_write'; END IF;
  IF TG_OP='INSERT' AND TG_TABLE_NAME='set_runs' AND v.predecessor_set_id IS NOT NULL AND (j->>'status'<>'private_resume_pending' OR (j->'source_metadata')-'yoon_fixed_input'<>'{}'::jsonb) THEN RAISE EXCEPTION 'yoon_new_run_must_be_fresh'; END IF;
  IF ops.yoon_audience(v.collection_id) IS DISTINCT FROM v.audience_sha256 THEN RAISE EXCEPTION 'yoon_audience_drift'; END IF;
  IF TG_OP='DELETE' AND TG_TABLE_NAME IN ('sets','set_runs','set_media','submissions') THEN RAISE EXCEPTION 'yoon_identity_delete'; END IF;
  IF TG_TABLE_NAME='sets' AND ROW(j->>'id',j->>'slug',j->>'visibility',j->>'collection_id') IS DISTINCT FROM ROW(v.set_id::text,v.slug,'private',v.collection_id::text) THEN RAISE EXCEPTION 'yoon_set_identity'; END IF;
  IF TG_TABLE_NAME='set_runs' AND (ROW(j->>'id',j->>'submission_id',j->>'requested_by',j->>'target_set_id',j->>'collection_id',j->>'publication_visibility') IS DISTINCT FROM ROW(v.run_id::text,v.submission_id::text,v.requested_by,v.set_id::text,v.collection_id::text,'private') OR ops.yoon_sha(jsonb_build_object('source_url',j->'source_url','descriptor',j->'source_metadata'->'yoon_fixed_input')) IS DISTINCT FROM v.source_sha256) THEN RAISE EXCEPTION 'yoon_run_identity'; END IF;
  IF TG_TABLE_NAME='set_media' AND ops.yoon_sha(j-'created_at'-'updated_at') IS DISTINCT FROM v.media_sha256 THEN RAISE EXCEPTION 'yoon_media_identity'; END IF;
  IF TG_TABLE_NAME='submissions' AND ROW(j->>'id',j->>'requested_by',j->>'collection_id',j->>'visibility') IS DISTINCT FROM ROW(v.submission_id::text,v.requested_by,v.collection_id::text,'private') THEN RAISE EXCEPTION 'yoon_submission_identity'; END IF;
  FOR family_run_id IN SELECT r.id FROM ops.set_runs r WHERE r.id<>coalesce(rid,v.run_id)
   AND r.target_set_id IN(SELECT set_id FROM ops.yoon_versions WHERE logical_set_id=v.logical_set_id) LOOP
   IF ops.yoon_run_busy(family_run_id) THEN RAISE EXCEPTION 'yoon_logical_family_occupied'; END IF;
  END LOOP;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME IN ('set_entries','set_media','set_artists','set_source_links','segment_hits','set_run_leases') AND
  (j->'set_id' IS DISTINCT FROM oldj->'set_id' OR j->'set_run_id' IS DISTINCT FROM oldj->'set_run_id') THEN
  IF EXISTS(SELECT 1 FROM ops.yoon_versions WHERE set_id=(oldj->>'set_id')::uuid OR run_id=(oldj->>'set_run_id')::uuid) THEN RAISE EXCEPTION 'yoon_evidence_reparent'; END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END $$;
--> statement-breakpoint

CREATE OR REPLACE FUNCTION ops.select_yoon_version(p_family uuid,p_expected_set uuid,p_expected_revision bigint,p_new_set uuid,p_old_sha256 text,p_new_sha256 text,p_review_sha256 text,p_rollback boolean DEFAULT false)
 RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE f ops.yoon_version_families; v ops.yoon_versions; old_snapshot jsonb; new_snapshot jsonb; r ops.set_runs;
 family_run_id uuid;
BEGIN
 PERFORM ops.yoon_registry_lock();
 PERFORM pg_advisory_xact_lock(183602,hashtext(p_family::text));
 SELECT * INTO STRICT f FROM ops.yoon_version_families WHERE logical_set_id=p_family FOR UPDATE;
 IF f.selected_set_id IS DISTINCT FROM p_expected_set OR f.selection_revision IS DISTINCT FROM p_expected_revision OR p_new_set IS NULL OR p_rollback IS NULL OR p_new_set=p_expected_set THEN RAISE EXCEPTION 'yoon_selection_cas_conflict'; END IF;
 SELECT * INTO STRICT v FROM ops.yoon_versions WHERE set_id=p_new_set AND logical_set_id=p_family FOR UPDATE;
 IF p_review_sha256 IS NULL OR NOT EXISTS(SELECT 1 FROM ops.yoon_release_reviews rr WHERE rr.review_sha256=p_review_sha256 AND ops.yoon_sha(rr.review)=p_review_sha256
  AND rr.review->>'old_set_id'=p_expected_set::text AND rr.review->>'new_set_id'=p_new_set::text
  AND rr.review->>'old_snapshot_sha256'=p_old_sha256 AND rr.review->>'new_snapshot_sha256'=p_new_sha256
  AND length(rr.review->>'reviewer')>0
  AND rr.review->'checks' @> '{"independent_review":true,"source_matched":true,"ordered_windows":true,"stable_derivative":true,"import_complete":true,"metadata_complete":true,"timestamps_and_spans":true,"audience_unchanged":true}'::jsonb) THEN RAISE EXCEPTION 'yoon_independent_review_required'; END IF;
 PERFORM ops.assert_yoon_version_identity(p_expected_set);
 PERFORM ops.assert_yoon_version_identity(p_new_set);
 -- Every writer of version-local app/raw rows takes the same admission lock;
 -- no expiry takeover, and uncertain legacy owners block review as well.
 FOR family_run_id IN SELECT busy_run.id FROM ops.set_runs busy_run WHERE busy_run.target_set_id
  IN(SELECT set_id FROM ops.yoon_versions WHERE logical_set_id=p_family) LOOP
  IF ops.yoon_run_busy(family_run_id) THEN RAISE EXCEPTION 'yoon_family_not_quiescent'; END IF;
 END LOOP;
 old_snapshot:=ops.yoon_version_snapshot(p_expected_set); new_snapshot:=ops.yoon_version_snapshot(p_new_set);
 IF ops.yoon_sha(old_snapshot) IS DISTINCT FROM p_old_sha256 OR ops.yoon_sha(new_snapshot) IS DISTINCT FROM p_new_sha256 THEN RAISE EXCEPTION 'yoon_review_snapshot_changed'; END IF;
 IF p_rollback THEN
  IF NOT v.released OR NOT v.frozen OR NOT EXISTS(SELECT 1 FROM ops.yoon_version_history h WHERE h.logical_set_id=p_family AND (h.old_set_id=p_new_set OR h.new_set_id=p_new_set)) THEN RAISE EXCEPTION 'yoon_rollback_unreleased'; END IF;
 ELSE
  SELECT * INTO STRICT r FROM ops.set_runs WHERE id=v.run_id;
  IF v.released OR NOT v.processing_approved OR v.predecessor_set_id<>p_expected_set
   OR r.status<>'private_resume_complete' OR r.source_metadata->'yoon_resume'->>'status' IS DISTINCT FROM 'complete'
   OR coalesce(r.source_metadata->'yoon_resume'->>'expected_audio_sha256','') !~ '^[0-9a-f]{64}$'
   OR r.source_metadata->'yoon_resume'->>'audio_sha256' IS DISTINCT FROM r.source_metadata->'yoon_resume'->>'expected_audio_sha256'
   OR r.source_metadata->'yoon_resume'->>'source_id' IS DISTINCT FROM v.source_id
   OR r.source_metadata->'yoon_resume' ? 'origin' OR r.source_metadata->'yoon_resume'->>'provenance_seeded'='true'
   OR r.source_metadata->'yoon_metadata_publication_v1'->>'status' IS DISTINCT FROM 'complete'
   OR r.source_metadata->'yoon_metadata_publication_v1'->>'run_id' IS DISTINCT FROM v.run_id::text
   OR r.source_metadata->'yoon_metadata_publication_v1'->>'target_set_id' IS DISTINCT FROM v.set_id::text
   OR NOT EXISTS(SELECT 1 FROM app.set_entries WHERE set_id=p_new_set)
   OR (SELECT count(*) FROM ops.segment_hits WHERE set_run_id=v.run_id) IS DISTINCT FROM (SELECT expected_windows FROM ops.yoon_reserved_versions WHERE set_id=v.set_id)
   OR EXISTS(SELECT 1 FROM generate_series(0,(SELECT expected_windows-1 FROM ops.yoon_reserved_versions WHERE set_id=v.set_id)) i WHERE NOT EXISTS(SELECT 1 FROM ops.segment_hits h WHERE h.set_run_id=v.run_id AND h.segment_index=i AND h.timestamp_seconds=i*15
     AND h.raw_data->'private_jackson_v2'->>'valid'='true'
     AND h.raw_data->'private_jackson_v2'->>'in_flight'='false'
     AND h.raw_data->'private_jackson_v2'->'response'->>'segment_index'=i::text
     AND (h.raw_data->'private_jackson_v2'->'response'->>'timestamp')::numeric=i*15
     AND coalesce(h.raw_data->'private_jackson_v2'->'response'->>'error_type','')=''
     AND coalesce(h.raw_data->'private_jackson_v2'->'response'->>'was_rate_limited','false')='false'))
   OR EXISTS(SELECT 1 FROM ops.set_run_leases WHERE set_run_id=v.run_id AND status<>'completed')
   THEN RAISE EXCEPTION 'yoon_candidate_not_complete'; END IF;
 END IF;
 UPDATE ops.yoon_versions SET released=true,frozen=true WHERE set_id IN(p_expected_set,p_new_set);
 UPDATE ops.yoon_version_families SET selected_set_id=p_new_set,selection_revision=selection_revision+1 WHERE logical_set_id=p_family;
 INSERT INTO ops.yoon_version_history(logical_set_id,revision,old_set_id,new_set_id,operation,review_sha256,old_snapshot,new_snapshot)
 VALUES(p_family,f.selection_revision+1,p_expected_set,p_new_set,CASE WHEN p_rollback THEN 'rollback' ELSE 'promote' END,p_review_sha256,old_snapshot,new_snapshot);
 RETURN f.selection_revision+1;
END $$;
