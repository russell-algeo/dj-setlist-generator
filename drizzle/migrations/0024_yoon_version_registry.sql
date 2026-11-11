-- Offline-reviewed rollout only. This migration deliberately bootstraps NO rows.
-- Apply reviewed 27-row bootstrap before deploying readers, then stage siblings.
-- All functions are SECURITY INVOKER. Registry writes belong to the migration
-- owner, never the worker. Read gates supplement, never replace, private ACLs.
CREATE TABLE ops.yoon_reserved_versions (set_id uuid PRIMARY KEY,run_id uuid UNIQUE NOT NULL,submission_id uuid UNIQUE NOT NULL,media_id uuid UNIQUE NOT NULL,logical_set_id uuid NOT NULL,source_id text UNIQUE NOT NULL,model_version text NOT NULL, descriptor jsonb NOT NULL, expected_windows integer NOT NULL, media_revision text NOT NULL);
--> statement-breakpoint

INSERT INTO ops.yoon_reserved_versions VALUES
('ef5f147f-f403-56bb-a5ac-9b585906c02e','54a97b8c-157a-5ea7-b64a-d0351e737d4e','7aa4c603-c82b-5cf3-a811-f1ee2aa5979b','a1a2c207-4823-5632-82e4-c9ae56ca6d97','993fcd7f-b399-585e-b673-57c5d8a5ae43','airgordon-saturday-mean-gaps-v2','user-mean-gaps-v2-20261110','{"source_sha256":"f7035c693dc4d95546196fa02357ba6ea5fa144e5eaa627af885d026e905a944","source_bytes":4290463660,"source_start_seconds":7085.016099773243,"source_end_seconds":12485.016099773242,"source_start_frame":312449210,"source_end_frame":550589210,"source_sample_rate":44100,"source_id":"airgordon-saturday-mean-gaps-v2","recognition_mode":"resumable"}'::jsonb,359,'airgordon-saturday-mean-gaps-v2-original-wav-v2'),
('8a3804db-90e9-5afa-b65e-02c22526826e','31d068aa-1d30-5018-9b93-c01ddfaf3fd7','813d36ae-a097-51ff-ac83-3fd7575bfaaf','b3432519-7fed-5c39-9f43-bf89df5b4f81','ec17fc00-fcaf-536d-929b-394d4dec7242','artur-saturday-mean-gaps-v2','user-mean-gaps-v2-20261110','{"source_sha256":"f7035c693dc4d95546196fa02357ba6ea5fa144e5eaa627af885d026e905a944","source_bytes":4290463660,"source_start_seconds":1685.0160997732426,"source_end_seconds":7085.016099773243,"source_start_frame":74309210,"source_end_frame":312449210,"source_sample_rate":44100,"source_id":"artur-saturday-mean-gaps-v2","recognition_mode":"resumable"}'::jsonb,359,'artur-saturday-mean-gaps-v2-original-wav-v2'),
('4311c755-7012-5a00-b0c7-729fe982223b','a8102221-e559-53df-a680-7f0299aaec47','ab1715a9-e5ef-584f-bc66-487455d0bc73','592326f3-3a8f-5390-b90b-bc39394b044b','db7fca04-ba53-51ab-937f-b7e572113e67','barbie-fish-santiago-gammelli-saturday-mean-gaps-v2','user-mean-gaps-v2-20261110','{"source_sha256":"cf1842a175f02bd8ea5afe2dd38ddd8778d26dff8482fb2c9abba1ea920f5ff9","source_bytes":4290463660,"source_start_seconds":1670.1328344671201,"source_end_seconds":8870.13283446712,"source_start_frame":73652858,"source_end_frame":391172858,"source_sample_rate":44100,"source_id":"barbie-fish-santiago-gammelli-saturday-mean-gaps-v2","recognition_mode":"resumable"}'::jsonb,479,'barbie-fish-santiago-gammelli-saturday-mean-gaps-v2-original-wav-v2'),
('4c38a89c-288a-59b5-a4f0-ef0fd3362116','d9f58e84-7d4e-599d-92c8-b894cc867e50','11968f9e-56c6-5108-ae46-a27c29b9272a','a28304ac-c128-5d5d-86c4-3dda16b7f199','6c6f4b7c-779b-5eb2-b464-a079343150c4','choice-friday-mean-gaps-v2','user-mean-gaps-v2-20261110','{"source_sha256":"e89ad04e8f69ad25c47f2f153862087c203dfd0b8fbe53c1a7f7a3119299c073","source_bytes":4290463660,"source_start_seconds":5314.782630385487,"source_end_seconds":12514.782630385487,"source_start_frame":234381914,"source_end_frame":551901914,"source_sample_rate":44100,"source_id":"choice-friday-mean-gaps-v2","recognition_mode":"resumable"}'::jsonb,479,'choice-friday-mean-gaps-v2-original-wav-v2'),
('dc8a5ee0-2f1b-5022-991b-31f5aac16ba1','802964dd-5976-5d0d-85cc-71dbaca129ab','ec02a2f5-2526-58b9-8c76-8078251a788c','f4b0e232-4e82-5119-aa0f-2afd45472a75','dfd9efb0-b206-5593-bfc1-00856049f71d','hank-friday-mean-gaps-v2','user-mean-gaps-v2-20261110','{"source_parts":[{"filename":"260619_0119_3-4.wav","sha256":"e89ad04e8f69ad25c47f2f153862087c203dfd0b8fbe53c1a7f7a3119299c073","bytes":4290463660,"start_frame":551901914,"end_frame":715076352,"total_frames":715076352,"sample_rate":44100,"channels":2,"sample_width":3},{"filename":"260620_0120_3-4.wav","sha256":"bc52ca6689a9551f70aaa1742d3066da2b3f21f5628815d43c514d8fc0a0dd17","bytes":4290463660,"start_frame":0,"end_frame":74965562,"total_frames":715076352,"sample_rate":44100,"channels":2,"sample_width":3}],"source_duration_seconds":5400,"source_total_frames":238140000,"source_id":"hank-friday-mean-gaps-v2","recognition_mode":"resumable"}'::jsonb,359,'hank-friday-mean-gaps-v2-original-wav-v2'),
('32d52955-0b61-5d55-afae-c40ba65305d8','b38d2fb4-21a2-5570-b0d5-50dac12c9099','53b9cb68-add5-56d1-bcbe-ec38ae69794c','0a46a088-28c7-5426-b231-13c433feef0a','afe8b2e3-3aeb-5d5e-ab7b-b74207cd585b','honeydu-saturday-mean-gaps-v2','user-mean-gaps-v2-20261110','{"source_parts":[{"filename":"260620_0120_3-4.wav","sha256":"bc52ca6689a9551f70aaa1742d3066da2b3f21f5628815d43c514d8fc0a0dd17","bytes":4290463660,"start_frame":551245562,"end_frame":715076352,"total_frames":715076352,"sample_rate":44100,"channels":2,"sample_width":3},{"filename":"260620_0121_3-4.wav","sha256":"f7035c693dc4d95546196fa02357ba6ea5fa144e5eaa627af885d026e905a944","bytes":4290463660,"start_frame":0,"end_frame":74309210,"total_frames":715076352,"sample_rate":44100,"channels":2,"sample_width":3}],"source_duration_seconds":5400,"source_total_frames":238140000,"source_id":"honeydu-saturday-mean-gaps-v2","recognition_mode":"resumable"}'::jsonb,359,'honeydu-saturday-mean-gaps-v2-original-wav-v2'),
('e788dc31-017d-5660-88ea-c559c0f3727a','f7ceea97-b612-5dbd-9e7f-44776b6dedd9','c85047cc-eb0c-561f-a7ad-9610c807716e','fee7db96-782b-5948-af8e-56344339d610','de51a97f-563f-570b-af6a-a741457beaee','hunter-foshee-saturday-mean-gaps-v2','user-mean-gaps-v2-20261110','{"source_parts":[{"filename":"260620_0121_3-4.wav","sha256":"f7035c693dc4d95546196fa02357ba6ea5fa144e5eaa627af885d026e905a944","bytes":4290463660,"start_frame":550589210,"end_frame":715076352,"total_frames":715076352,"sample_rate":44100,"channels":2,"sample_width":3},{"filename":"260620_0122_3-4.wav","sha256":"cf1842a175f02bd8ea5afe2dd38ddd8778d26dff8482fb2c9abba1ea920f5ff9","bytes":4290463660,"start_frame":0,"end_frame":73652858,"total_frames":715076352,"sample_rate":44100,"channels":2,"sample_width":3}],"source_duration_seconds":5400,"source_total_frames":238140000,"source_id":"hunter-foshee-saturday-mean-gaps-v2","recognition_mode":"resumable"}'::jsonb,359,'hunter-foshee-saturday-mean-gaps-v2-original-wav-v2'),
('fac7dd34-e762-5696-a056-94a195055f25','42022ca4-f217-53b9-b31b-88046e4fe106','0a6b1720-9bd6-513f-9f19-b3b21f7eb571','ec78e819-88f7-51a1-b7be-16c8cd778c4c','542c7611-1d80-5b46-8d37-76b243c02655','jake-mora-friday-mean-gaps-v2','user-mean-gaps-v2-20261110','{"source_sha256":"bc52ca6689a9551f70aaa1742d3066da2b3f21f5628815d43c514d8fc0a0dd17","source_bytes":4290463660,"source_start_seconds":7099.899365079365,"source_end_seconds":12499.899365079365,"source_start_frame":313105562,"source_end_frame":551245562,"source_sample_rate":44100,"source_id":"jake-mora-friday-mean-gaps-v2","recognition_mode":"resumable"}'::jsonb,359,'jake-mora-friday-mean-gaps-v2-original-wav-v2'),
('ad408430-388c-512f-a4f8-277ad83dd0f7','827423fa-6a5a-5567-a5ca-6859b0a44310','d7bfe57d-ceae-54e1-a91e-473f27f33317','51e770b8-372b-5cee-8787-b6223fc68516','21eb3202-c5f8-5cbb-a30d-2e4ec5eb0d46','pily-saturday-mean-gaps-v2','user-mean-gaps-v2-20261110','{"source_sha256":"cf1842a175f02bd8ea5afe2dd38ddd8778d26dff8482fb2c9abba1ea920f5ff9","source_bytes":4290463660,"source_start_seconds":8870.13283446712,"source_end_seconds":14270.13283446712,"source_start_frame":391172858,"source_end_frame":629312858,"source_sample_rate":44100,"source_id":"pily-saturday-mean-gaps-v2","recognition_mode":"resumable"}'::jsonb,359,'pily-saturday-mean-gaps-v2-original-wav-v2'),
('2caf5a88-a4c2-582f-89ae-1c7fbb21ebaa','defa8bf1-5443-51bf-bfda-8b20969e9f9a','005f65c6-ebed-5cbf-b6bd-8083b469902c','0af8942a-8bc8-5fd6-8ffc-e9ee88b3a14c','c7a89fd3-0c13-578b-8c67-89e920144bd5','sydka-live-friday-mean-gaps-v2','user-mean-gaps-v2-20261110','{"source_sha256":"bc52ca6689a9551f70aaa1742d3066da2b3f21f5628815d43c514d8fc0a0dd17","source_bytes":4290463660,"source_start_seconds":1699.899365079365,"source_end_seconds":7099.899365079365,"source_start_frame":74965562,"source_end_frame":313105562,"source_sample_rate":44100,"source_id":"sydka-live-friday-mean-gaps-v2","recognition_mode":"resumable"}'::jsonb,359,'sydka-live-friday-mean-gaps-v2-original-wav-v2');
--> statement-breakpoint

CREATE TABLE ops.yoon_version_collections (
 collection_id uuid PRIMARY KEY REFERENCES app.archive_collections(id),
 audience_sha256 text NOT NULL CHECK (audience_sha256 ~ '^[0-9a-f]{64}$'),
 bootstrap_manifest jsonb NOT NULL CHECK(jsonb_typeof(bootstrap_manifest)='array' AND jsonb_array_length(bootstrap_manifest)=27),
 bootstrap_sha256 text NOT NULL CHECK (bootstrap_sha256 ~ '^[0-9a-f]{64}$'),
 created_at timestamptz NOT NULL DEFAULT now()
);
--> statement-breakpoint

CREATE TABLE ops.yoon_version_families (
 logical_set_id uuid PRIMARY KEY,
 collection_id uuid NOT NULL REFERENCES ops.yoon_version_collections(collection_id),
 selected_set_id uuid NOT NULL UNIQUE,
 selection_revision bigint NOT NULL DEFAULT 0 CHECK (selection_revision>=0)
);
--> statement-breakpoint

CREATE TABLE ops.yoon_versions (
 set_id uuid PRIMARY KEY,
 logical_set_id uuid NOT NULL REFERENCES ops.yoon_version_families(logical_set_id) DEFERRABLE INITIALLY DEFERRED,
 model_version text NOT NULL CHECK (length(model_version)>0),
 source_id text NOT NULL UNIQUE,
 run_id uuid NOT NULL UNIQUE,
 submission_id uuid NOT NULL UNIQUE,
 media_id uuid NOT NULL UNIQUE,
 slug text NOT NULL UNIQUE,
 media_revision text NOT NULL,
 collection_id uuid NOT NULL REFERENCES ops.yoon_version_collections(collection_id),
 requested_by text NOT NULL,
 predecessor_set_id uuid REFERENCES ops.yoon_versions(set_id),
 manifest_sha256 text NOT NULL CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
 source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
 media_sha256 text NOT NULL CHECK (media_sha256 ~ '^[0-9a-f]{64}$'),
 audience_sha256 text NOT NULL CHECK (audience_sha256 ~ '^[0-9a-f]{64}$'),
 staging_approved boolean NOT NULL DEFAULT false,
 processing_approved boolean NOT NULL DEFAULT false,
 released boolean NOT NULL DEFAULT false,
 frozen boolean NOT NULL DEFAULT false,
 UNIQUE(logical_set_id,model_version), UNIQUE(logical_set_id,set_id),
 CHECK (NOT frozen OR released),
 CHECK (predecessor_set_id IS NULL OR predecessor_set_id<>set_id)
);
--> statement-breakpoint

ALTER TABLE ops.yoon_version_families ADD CONSTRAINT yoon_selected_family_fk
 FOREIGN KEY(logical_set_id,selected_set_id) REFERENCES ops.yoon_versions(logical_set_id,set_id) DEFERRABLE INITIALLY DEFERRED;
--> statement-breakpoint

CREATE TABLE ops.yoon_release_reviews (
 review_sha256 text PRIMARY KEY CHECK(review_sha256 ~ '^[0-9a-f]{64}$'),
 review jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
--> statement-breakpoint

CREATE TABLE ops.yoon_version_history (
 logical_set_id uuid NOT NULL REFERENCES ops.yoon_version_families(logical_set_id),
 revision bigint NOT NULL,
 old_set_id uuid NOT NULL REFERENCES ops.yoon_versions(set_id),
 new_set_id uuid NOT NULL REFERENCES ops.yoon_versions(set_id),
 operation text NOT NULL CHECK(operation IN ('promote','rollback')),
 review_sha256 text NOT NULL CHECK(review_sha256 ~ '^[0-9a-f]{64}$'),
 old_snapshot jsonb NOT NULL, new_snapshot jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(logical_set_id,revision)
);
--> statement-breakpoint

CREATE FUNCTION ops.yoon_sha(p jsonb) RETURNS text LANGUAGE sql IMMUTABLE AS $$
 SELECT encode(digest(p::text,'sha256'),'hex') $$;
--> statement-breakpoint

CREATE FUNCTION ops.yoon_audience(p uuid) RETURNS text LANGUAGE sql STABLE AS $$
 SELECT ops.yoon_sha(coalesce(jsonb_agg(jsonb_build_object('user_id',user_id,'role',role) ORDER BY user_id),'[]'::jsonb))
 FROM app.archive_collection_members WHERE collection_id=p $$;
--> statement-breakpoint

CREATE FUNCTION ops.yoon_source_fingerprint(p uuid) RETURNS text LANGUAGE sql STABLE AS $$
 SELECT ops.yoon_sha(jsonb_build_object('source_url',source_url,'descriptor',source_metadata->'yoon_fixed_input')) FROM ops.set_runs WHERE id=p $$;
--> statement-breakpoint

CREATE FUNCTION ops.yoon_media_fingerprint(p uuid) RETURNS text LANGUAGE sql STABLE AS $$
 SELECT ops.yoon_sha(to_jsonb(m)-'created_at'-'updated_at') FROM app.set_media m WHERE set_id=p $$;
--> statement-breakpoint

CREATE FUNCTION ops.yoon_collection_scope(p uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM app.archive_collections WHERE id=p AND slug='yoon-fest')
 OR EXISTS(SELECT 1 FROM ops.yoon_version_collections WHERE collection_id=p) $$;
--> statement-breakpoint

CREATE FUNCTION ops.yoon_is_v2(p jsonb) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(p::text ~* '(mean.gaps.v2|user-mean-gaps-v2|timingModelVersion|timing_model_version|yoon_version)',false) $$;
--> statement-breakpoint

CREATE FUNCTION app.yoon_version_readable(p_set_id uuid,p_selected_only boolean DEFAULT false)
 RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT coalesce((SELECT CASE
 WHEN v.set_id IS NOT NULL THEN v.released AND s.visibility='private' AND s.collection_id=v.collection_id
   AND (NOT p_selected_only OR f.selected_set_id=v.set_id)
 WHEN c.collection_id IS NOT NULL OR EXISTS(SELECT 1 FROM ops.yoon_reserved_versions WHERE set_id=s.id) OR EXISTS(SELECT 1 FROM ops.yoon_reserved_versions WHERE submission_id=s.id) OR (ops.yoon_collection_scope(s.collection_id) AND ops.yoon_is_v2(to_jsonb(s))) THEN false
 ELSE true END
 FROM app.sets s LEFT JOIN ops.yoon_versions v ON v.set_id=s.id
 LEFT JOIN ops.yoon_version_families f ON f.logical_set_id=v.logical_set_id
 LEFT JOIN ops.yoon_version_collections c ON c.collection_id=s.collection_id
 WHERE s.id=p_set_id),false) $$;
--> statement-breakpoint

CREATE FUNCTION app.yoon_submission_version_readable(p_submission_id uuid)
 RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT coalesce((SELECT CASE
 WHEN EXISTS(SELECT 1 FROM ops.yoon_versions v WHERE v.submission_id=s.id)
 THEN EXISTS(SELECT 1 FROM ops.yoon_versions v WHERE v.submission_id=s.id AND app.yoon_version_readable(v.set_id,false))
 WHEN EXISTS(SELECT 1 FROM ops.yoon_version_collections c WHERE c.collection_id=s.collection_id)
 OR EXISTS(SELECT 1 FROM ops.yoon_reserved_versions WHERE submission_id=s.id) OR (ops.yoon_collection_scope(s.collection_id) AND ops.yoon_is_v2(to_jsonb(s))) THEN false
 ELSE NOT EXISTS(SELECT 1 FROM ops.set_runs r WHERE r.submission_id=s.id AND
   ((ops.yoon_collection_scope(r.collection_id) AND ops.yoon_is_v2(to_jsonb(r))) OR NOT app.yoon_version_readable(coalesce(r.target_set_id,r.published_set_id),false))
   AND r.publication_visibility='private') END FROM ops.submissions s WHERE s.id=p_submission_id),false) $$;
--> statement-breakpoint

-- Nonblocking acquisition prevents inversions with older callers already holding
-- a run lock. They must retry their entire transaction on this exception. The
-- supported order remains global 183601,2 -> family -> run/app rows. No network
-- calls are made while these transaction locks are held.
CREATE FUNCTION ops.yoon_registry_lock() RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'yoon_requires_read_committed'; END IF;
 IF NOT pg_try_advisory_xact_lock(183601,2) THEN RAISE EXCEPTION 'yoon_admission_busy_retry_transaction' USING ERRCODE='55P03'; END IF;
END $$;
--> statement-breakpoint

CREATE FUNCTION ops.yoon_run_busy(p uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT coalesce((SELECT
 status NOT IN ('private_analysis_pending','private_analysis_partial','private_analysis_complete','private_analysis_failed','private_resume_pending','private_resume_paused','private_resume_complete','cancelled')
 OR coalesce(source_metadata->'yoon_resume'->>'in_flight','false')<>'false'
 OR coalesce(source_metadata->'yoon_resume'->>'review_required','false')<>'false'
 OR coalesce(source_metadata->'yoon_queue_v1'->>'status','queued') NOT IN ('queued','complete','blocked')
 OR EXISTS(SELECT 1 FROM jsonb_each(source_metadata) e WHERE e.key IN ('yoon_spotify_enrichment','yoon_spotify_recheck_v1','yoon_metadata_enrichment_v1') AND e.value->>'status' IS DISTINCT FROM 'complete')
 OR EXISTS(SELECT 1 FROM ops.set_run_leases l WHERE l.set_run_id=p AND l.status='claimed')
 OR EXISTS(SELECT 1 FROM ops.segment_hits h WHERE h.set_run_id=p AND (h.raw_data->'private_jackson_v2'->>'in_flight'='true' OR h.raw_data->'shared_recognition'->>'in_flight'='true'))
 FROM ops.set_runs WHERE id=p),true) $$;
--> statement-breakpoint

CREATE FUNCTION ops.assert_yoon_version_identity(p_set_id uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE v ops.yoon_versions; r ops.set_runs; s app.sets; m app.set_media; u ops.submissions; f ops.yoon_version_families;
BEGIN
 SELECT * INTO STRICT v FROM ops.yoon_versions WHERE set_id=p_set_id;
 SELECT * INTO STRICT f FROM ops.yoon_version_families WHERE logical_set_id=v.logical_set_id;
 SELECT * INTO STRICT r FROM ops.set_runs WHERE id=v.run_id;
 SELECT * INTO STRICT s FROM app.sets WHERE id=v.set_id;
 SELECT * INTO STRICT m FROM app.set_media WHERE id=v.media_id;
 SELECT * INTO STRICT u FROM ops.submissions WHERE id=v.submission_id;
 IF s.visibility<>'private' OR u.visibility<>'private' OR r.publication_visibility<>'private'
 OR ROW(s.collection_id,u.collection_id,r.collection_id,f.collection_id) IS DISTINCT FROM ROW(v.collection_id,v.collection_id,v.collection_id,v.collection_id)
 OR ROW(r.target_set_id,r.submission_id,r.requested_by,u.requested_by,m.set_id,s.slug,m.revision) IS DISTINCT FROM ROW(v.set_id,v.submission_id,v.requested_by,v.requested_by,v.set_id,v.slug,v.media_revision)
 OR (s.source_id IS NOT NULL AND s.source_id<>v.source_id)
 OR ops.yoon_source_fingerprint(v.run_id) IS DISTINCT FROM v.source_sha256
 OR ops.yoon_media_fingerprint(v.set_id) IS DISTINCT FROM v.media_sha256
 OR ops.yoon_audience(v.collection_id) IS DISTINCT FROM v.audience_sha256
 OR v.audience_sha256 IS DISTINCT FROM (SELECT audience_sha256 FROM ops.yoon_version_collections WHERE collection_id=v.collection_id)
 OR (v.predecessor_set_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM ops.yoon_versions p WHERE p.set_id=v.predecessor_set_id AND p.logical_set_id=v.logical_set_id AND p.collection_id=v.collection_id))
 THEN RAISE EXCEPTION 'yoon_version_identity_drift'; END IF;
END $$;
--> statement-breakpoint

CREATE FUNCTION ops.assert_yoon_version_execution(p_run_id uuid,p_purpose text,p_generation text DEFAULT NULL)
 RETURNS void LANGUAGE plpgsql AS $$
DECLARE v ops.yoon_versions; r ops.set_runs;
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
 IF EXISTS(SELECT 1 FROM ops.set_runs other WHERE other.id<>p_run_id AND
   (other.target_set_id IN (SELECT set_id FROM ops.yoon_versions WHERE logical_set_id=v.logical_set_id)) AND ops.yoon_run_busy(other.id)) THEN
  RAISE EXCEPTION 'yoon_logical_family_occupied'; END IF;
END $$;
--> statement-breakpoint

-- Complete, private evidence. This table and snapshot function receive NO new
-- worker grants. Original rows are never restored/rewritten during rollback.
CREATE FUNCTION ops.yoon_version_snapshot(p uuid) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object(
 'set',to_jsonb(s),'media',(SELECT to_jsonb(m) FROM app.set_media m WHERE m.set_id=p),
 'runs',(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.id),'[]') FROM ops.set_runs r WHERE r.target_set_id=p),
 'submissions',(SELECT coalesce(jsonb_agg(to_jsonb(u) ORDER BY u.id),'[]') FROM ops.submissions u WHERE u.id IN (SELECT submission_id FROM ops.set_runs WHERE target_set_id=p)),
 'hits',(SELECT coalesce(jsonb_agg(to_jsonb(h) ORDER BY h.set_run_id,h.segment_index,h.id),'[]') FROM ops.segment_hits h WHERE h.set_run_id IN(SELECT id FROM ops.set_runs WHERE target_set_id=p)),
 'leases',(SELECT coalesce(jsonb_agg(to_jsonb(l) ORDER BY l.id),'[]') FROM ops.set_run_leases l WHERE l.set_run_id IN(SELECT id FROM ops.set_runs WHERE target_set_id=p)),
 'entries',(SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY e.position,e.id),'[]') FROM app.set_entries e WHERE e.set_id=p),
 'links',(SELECT coalesce(jsonb_agg(to_jsonb(l) ORDER BY l.id),'[]') FROM app.set_source_links l WHERE l.set_id=p),
 'set_artists',(SELECT coalesce(jsonb_agg(to_jsonb(a) ORDER BY a.artist_id,a.role),'[]') FROM app.set_artists a WHERE a.set_id=p),
 'tracks',(SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.id),'[]') FROM app.tracks t WHERE t.id IN(SELECT track_id FROM app.set_entries WHERE set_id=p)),
 'artists',(SELECT coalesce(jsonb_agg(to_jsonb(a) ORDER BY a.id),'[]') FROM app.artists a WHERE a.id IN(SELECT artist_id FROM app.set_artists WHERE set_id=p)),
 'members',(SELECT coalesce(jsonb_agg(to_jsonb(m) ORDER BY m.user_id),'[]') FROM app.archive_collection_members m WHERE m.collection_id=s.collection_id)) FROM app.sets s WHERE s.id=p $$;
--> statement-breakpoint

CREATE FUNCTION ops.yoon_immutable_registry() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME IN ('yoon_version_history','yoon_version_collections','yoon_release_reviews','yoon_reserved_versions') OR TG_OP='DELETE' THEN RAISE EXCEPTION 'yoon_append_only_registry'; END IF;
 IF (to_jsonb(NEW)-'processing_approved'-'released'-'frozen') IS DISTINCT FROM (to_jsonb(OLD)-'processing_approved'-'released'-'frozen')
 OR (OLD.released AND NOT NEW.released) OR (OLD.frozen AND NOT NEW.frozen) THEN RAISE EXCEPTION 'yoon_immutable_version'; END IF;
 RETURN NEW;
END $$;
--> statement-breakpoint

CREATE TRIGGER yoon_review_append_only BEFORE UPDATE OR DELETE ON ops.yoon_release_reviews FOR EACH ROW EXECUTE FUNCTION ops.yoon_immutable_registry();
--> statement-breakpoint

CREATE TRIGGER yoon_reserved_immutable BEFORE UPDATE OR DELETE ON ops.yoon_reserved_versions FOR EACH ROW EXECUTE FUNCTION ops.yoon_immutable_registry();
--> statement-breakpoint

CREATE TRIGGER yoon_version_pins BEFORE UPDATE OR DELETE ON ops.yoon_versions FOR EACH ROW EXECUTE FUNCTION ops.yoon_immutable_registry();
--> statement-breakpoint

CREATE TRIGGER yoon_history_append_only BEFORE UPDATE OR DELETE ON ops.yoon_version_history FOR EACH ROW EXECUTE FUNCTION ops.yoon_immutable_registry();
--> statement-breakpoint

CREATE TRIGGER yoon_collection_pins BEFORE UPDATE OR DELETE ON ops.yoon_version_collections FOR EACH ROW EXECUTE FUNCTION ops.yoon_immutable_registry();
--> statement-breakpoint

CREATE FUNCTION ops.yoon_registration_check() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM ops.assert_yoon_version_identity(NEW.set_id);
 IF NEW.predecessor_set_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM ops.yoon_reserved_versions r WHERE
 ROW(r.set_id,r.run_id,r.submission_id,r.media_id,r.logical_set_id,r.source_id,r.model_version)=ROW(NEW.set_id,NEW.run_id,NEW.submission_id,NEW.media_id,NEW.logical_set_id,NEW.source_id,NEW.model_version)) THEN RAISE EXCEPTION 'yoon_not_finite_reviewed_version'; END IF;
 IF NEW.predecessor_set_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM ops.yoon_reserved_versions p JOIN ops.set_runs r ON r.id=NEW.run_id WHERE p.set_id=NEW.set_id AND NEW.media_revision=p.media_revision AND r.source_metadata->'yoon_fixed_input' @> p.descriptor) THEN RAISE EXCEPTION 'yoon_fixed_source_pins'; END IF;
 IF NEW.predecessor_set_id IS NULL AND NEW.logical_set_id<>NEW.set_id THEN RAISE EXCEPTION 'yoon_invalid_legacy_family'; END IF;
 RETURN NEW; END $$;
--> statement-breakpoint

CREATE CONSTRAINT TRIGGER yoon_registration_identity AFTER INSERT OR UPDATE ON ops.yoon_versions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ops.yoon_registration_check();
--> statement-breakpoint

-- Guard both direct worker/import writes and ordinary publisher writes. Register
-- an approved identity first in the same transaction as staging app/raw rows.
CREATE FUNCTION ops.yoon_mutation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE j jsonb; oldj jsonb; sid uuid; rid uuid; v ops.yoon_versions; cid uuid; oldcid uuid; running boolean:=false; parent_status text;
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
  IF EXISTS(SELECT 1 FROM ops.set_runs r WHERE r.id<>coalesce(rid,v.run_id) AND r.target_set_id IN(SELECT set_id FROM ops.yoon_versions WHERE logical_set_id=v.logical_set_id) AND ops.yoon_run_busy(r.id)) THEN RAISE EXCEPTION 'yoon_logical_family_occupied'; END IF;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME IN ('set_entries','set_media','set_artists','set_source_links','segment_hits','set_run_leases') AND
  (j->'set_id' IS DISTINCT FROM oldj->'set_id' OR j->'set_run_id' IS DISTINCT FROM oldj->'set_run_id') THEN
  IF EXISTS(SELECT 1 FROM ops.yoon_versions WHERE set_id=(oldj->>'set_id')::uuid OR run_id=(oldj->>'set_run_id')::uuid) THEN RAISE EXCEPTION 'yoon_evidence_reparent'; END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END $$;
--> statement-breakpoint

CREATE FUNCTION ops.yoon_bootstrap_check() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE item jsonb;
BEGIN
 PERFORM ops.yoon_registry_lock();
 IF ops.yoon_sha(NEW.bootstrap_manifest)<>NEW.bootstrap_sha256 OR ops.yoon_audience(NEW.collection_id)<>NEW.audience_sha256
 OR (SELECT count(*) FROM ops.yoon_versions WHERE collection_id=NEW.collection_id AND predecessor_set_id IS NULL)<>27
 OR (SELECT count(*) FROM ops.yoon_version_families WHERE collection_id=NEW.collection_id)<>27
 OR (SELECT count(DISTINCT x->>'set_id') FROM jsonb_array_elements(NEW.bootstrap_manifest) x)<>27
 THEN RAISE EXCEPTION 'yoon_invalid_reviewed_bootstrap'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(NEW.bootstrap_manifest) LOOP
  IF NOT EXISTS(SELECT 1 FROM ops.yoon_versions v JOIN ops.yoon_version_families f USING(logical_set_id)
    WHERE v.set_id=(item->>'set_id')::uuid AND v.collection_id=NEW.collection_id AND v.released AND NOT v.frozen
    AND v.predecessor_set_id IS NULL AND f.selected_set_id=v.set_id AND f.selection_revision=0)
   OR ops.yoon_sha(ops.yoon_version_snapshot((item->>'set_id')::uuid)) IS DISTINCT FROM item->>'snapshot_sha256'
  THEN RAISE EXCEPTION 'yoon_bootstrap_snapshot_changed'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
--> statement-breakpoint

CREATE CONSTRAINT TRIGGER yoon_reviewed_bootstrap AFTER INSERT ON ops.yoon_version_collections DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ops.yoon_bootstrap_check();
--> statement-breakpoint

CREATE FUNCTION ops.yoon_audience_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM ops.yoon_version_collections WHERE collection_id=CASE WHEN TG_OP='INSERT' THEN NEW.collection_id ELSE OLD.collection_id END)
 OR (TG_OP='UPDATE' AND EXISTS(SELECT 1 FROM ops.yoon_version_collections WHERE collection_id=NEW.collection_id)) THEN
  RAISE EXCEPTION 'yoon_reviewed_audience_immutable'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END $$;
--> statement-breakpoint

CREATE TRIGGER yoon_members_guard BEFORE INSERT OR UPDATE OR DELETE ON app.archive_collection_members FOR EACH ROW EXECUTE FUNCTION ops.yoon_audience_guard();
--> statement-breakpoint

CREATE FUNCTION ops.select_yoon_version(p_family uuid,p_expected_set uuid,p_expected_revision bigint,p_new_set uuid,p_old_sha256 text,p_new_sha256 text,p_review_sha256 text,p_rollback boolean DEFAULT false)
 RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE f ops.yoon_version_families; v ops.yoon_versions; old_snapshot jsonb; new_snapshot jsonb; r ops.set_runs;
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
 IF EXISTS(SELECT 1 FROM ops.set_runs busy_run WHERE busy_run.target_set_id IN(SELECT set_id FROM ops.yoon_versions WHERE logical_set_id=p_family) AND ops.yoon_run_busy(busy_run.id)) THEN RAISE EXCEPTION 'yoon_family_not_quiescent'; END IF;
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
--> statement-breakpoint

CREATE TRIGGER yoon_version_write_guard BEFORE INSERT OR UPDATE OR DELETE ON app.sets FOR EACH ROW EXECUTE FUNCTION ops.yoon_mutation_guard();
--> statement-breakpoint

CREATE TRIGGER yoon_version_write_guard BEFORE INSERT OR UPDATE OR DELETE ON app.set_media FOR EACH ROW EXECUTE FUNCTION ops.yoon_mutation_guard();
--> statement-breakpoint

CREATE TRIGGER yoon_version_write_guard BEFORE INSERT OR UPDATE OR DELETE ON app.set_entries FOR EACH ROW EXECUTE FUNCTION ops.yoon_mutation_guard();
--> statement-breakpoint

CREATE TRIGGER yoon_version_write_guard BEFORE INSERT OR UPDATE OR DELETE ON app.set_artists FOR EACH ROW EXECUTE FUNCTION ops.yoon_mutation_guard();
--> statement-breakpoint

CREATE TRIGGER yoon_version_write_guard BEFORE INSERT OR UPDATE OR DELETE ON app.set_source_links FOR EACH ROW EXECUTE FUNCTION ops.yoon_mutation_guard();
--> statement-breakpoint

CREATE TRIGGER yoon_version_write_guard BEFORE INSERT OR UPDATE OR DELETE ON ops.submissions FOR EACH ROW EXECUTE FUNCTION ops.yoon_mutation_guard();
--> statement-breakpoint

CREATE TRIGGER yoon_version_write_guard BEFORE INSERT OR UPDATE OR DELETE ON ops.set_runs FOR EACH ROW EXECUTE FUNCTION ops.yoon_mutation_guard();
--> statement-breakpoint

CREATE TRIGGER yoon_version_write_guard BEFORE INSERT OR UPDATE OR DELETE ON ops.set_run_leases FOR EACH ROW EXECUTE FUNCTION ops.yoon_mutation_guard();
--> statement-breakpoint

CREATE TRIGGER yoon_version_write_guard BEFORE INSERT OR UPDATE OR DELETE ON ops.segment_hits FOR EACH ROW EXECUTE FUNCTION ops.yoon_mutation_guard();
--> statement-breakpoint

-- Only nonsecret identity/status metadata is exposed to existing workers.
GRANT SELECT ON ops.yoon_reserved_versions,ops.yoon_versions,ops.yoon_version_families TO set_list_worker;
--> statement-breakpoint

GRANT SELECT (collection_id,audience_sha256) ON ops.yoon_version_collections TO set_list_worker;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.select_yoon_version(uuid,uuid,bigint,uuid,text,text,text,boolean) FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.yoon_version_snapshot(uuid) FROM PUBLIC;
--> statement-breakpoint

-- Explicit owner operation AFTER separate processing approval, BEFORE enqueue.
-- Never copies predecessor state, queue receipts, owners, hits, or audio hashes.
CREATE FUNCTION ops.initialize_yoon_version_execution(p_set_id uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE v ops.yoon_versions; r ops.set_runs; pins jsonb; members jsonb;
BEGIN
 PERFORM ops.yoon_registry_lock();
 SELECT * INTO STRICT v FROM ops.yoon_versions WHERE set_id=p_set_id;
 PERFORM ops.assert_yoon_version_execution(v.run_id,'enqueue');
 SELECT * INTO STRICT r FROM ops.set_runs WHERE id=v.run_id FOR UPDATE;
 SELECT descriptor-'source_id'-'recognition_mode'-'source_url'-'source_urls' INTO STRICT pins FROM ops.yoon_reserved_versions WHERE set_id=p_set_id;
 SELECT jsonb_agg(jsonb_build_object('user_id',user_id,'role',role) ORDER BY user_id) INTO members FROM app.archive_collection_members WHERE collection_id=v.collection_id;
 IF v.released OR v.frozen OR v.predecessor_set_id IS NULL OR jsonb_array_length(members)<>2
 OR r.status<>'private_resume_pending' OR r.source_metadata-'yoon_fixed_input'<>'{}'::jsonb
 OR EXISTS(SELECT 1 FROM ops.segment_hits WHERE set_run_id=v.run_id)
 OR EXISTS(SELECT 1 FROM ops.set_run_leases WHERE set_run_id=v.run_id)
 THEN RAISE EXCEPTION 'yoon_execution_initialization_requires_fresh_run'; END IF;
 UPDATE ops.set_runs SET source_metadata=source_metadata || jsonb_build_object('yoon_resume',jsonb_build_object(
  'version',1,'created_at',extract(epoch from clock_timestamp()),'continuations',0,'requests',0,
  'spacing_seconds',30,'next_allowed_at',0,'consecutive_limits',0,'initialization_mode','fresh',
  'source_id',v.source_id,'source_pins',pins,'members',members)) WHERE id=v.run_id;
END $$;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.initialize_yoon_version_execution(uuid) FROM PUBLIC;
--> statement-breakpoint

-- Even an accidental owner UPDATE cannot select a staged sibling or silently
-- move a pointer outside the audited CAS transaction.
CREATE FUNCTION ops.yoon_selection_receipt_check() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' AND (NEW.logical_set_id IS DISTINCT FROM OLD.logical_set_id OR NEW.collection_id IS DISTINCT FROM OLD.collection_id
  OR NEW.selection_revision IS DISTINCT FROM OLD.selection_revision+1
  OR NOT EXISTS(SELECT 1 FROM ops.yoon_version_history h WHERE h.logical_set_id=NEW.logical_set_id AND h.revision=NEW.selection_revision AND h.old_set_id=OLD.selected_set_id AND h.new_set_id=NEW.selected_set_id)) THEN RAISE EXCEPTION 'yoon_selection_receipt_required'; END IF;
 IF NOT EXISTS(SELECT 1 FROM ops.yoon_versions v WHERE v.set_id=NEW.selected_set_id AND v.logical_set_id=NEW.logical_set_id AND v.collection_id=NEW.collection_id AND v.released) THEN RAISE EXCEPTION 'yoon_selected_version_unreleased'; END IF;
 RETURN NEW;
END $$;
--> statement-breakpoint

CREATE CONSTRAINT TRIGGER yoon_selection_receipt AFTER INSERT OR UPDATE ON ops.yoon_version_families DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ops.yoon_selection_receipt_check();
--> statement-breakpoint

CREATE FUNCTION ops.yoon_release_receipt_check() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF ((NOT OLD.released AND NEW.released) OR (NOT OLD.frozen AND NEW.frozen)) AND NOT EXISTS(SELECT 1 FROM ops.yoon_version_history h WHERE h.logical_set_id=NEW.logical_set_id AND (h.old_set_id=NEW.set_id OR h.new_set_id=NEW.set_id)) THEN RAISE EXCEPTION 'yoon_release_receipt_required'; END IF;
 RETURN NEW;
END $$;
--> statement-breakpoint

CREATE CONSTRAINT TRIGGER yoon_release_receipt AFTER UPDATE ON ops.yoon_versions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ops.yoon_release_receipt_check();
--> statement-breakpoint


--> statement-breakpoint

-- Finite new-object ACL seal: run in the SAME transaction as 0024 creation.
-- Existing/default ACLs and role membership are unchanged; absent dev roles stay absent.
REVOKE ALL ON TABLE ops.yoon_reserved_versions,ops.yoon_version_collections,ops.yoon_version_families,ops.yoon_versions,ops.yoon_release_reviews,ops.yoon_version_history FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.yoon_sha(jsonb) FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.yoon_audience(uuid) FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.yoon_source_fingerprint(uuid) FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.yoon_media_fingerprint(uuid) FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.yoon_collection_scope(uuid) FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.yoon_is_v2(jsonb) FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION app.yoon_version_readable(uuid,boolean) FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION app.yoon_submission_version_readable(uuid) FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.yoon_registry_lock() FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.yoon_run_busy(uuid) FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.assert_yoon_version_identity(uuid) FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.assert_yoon_version_execution(uuid,text,text) FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.yoon_version_snapshot(uuid) FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.yoon_immutable_registry() FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.yoon_registration_check() FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.yoon_mutation_guard() FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.yoon_bootstrap_check() FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.yoon_audience_guard() FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.select_yoon_version(uuid,uuid,bigint,uuid,text,text,text,boolean) FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.initialize_yoon_version_execution(uuid) FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.yoon_selection_receipt_check() FROM PUBLIC;
--> statement-breakpoint

REVOKE ALL ON FUNCTION ops.yoon_release_receipt_check() FROM PUBLIC;
--> statement-breakpoint

DO $yoon_acl_seal$
DECLARE target_role text;
BEGIN
 FOREACH target_role IN ARRAY ARRAY['set_list_worker','set_list_dev_worker','set_list_dev_app'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=target_role) THEN CONTINUE; END IF;
  EXECUTE format('REVOKE ALL ON TABLE ops.yoon_reserved_versions,ops.yoon_version_collections,ops.yoon_version_families,ops.yoon_versions,ops.yoon_release_reviews,ops.yoon_version_history FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_sha(jsonb) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_audience(uuid) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_source_fingerprint(uuid) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_media_fingerprint(uuid) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_collection_scope(uuid) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_is_v2(jsonb) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION app.yoon_version_readable(uuid,boolean) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION app.yoon_submission_version_readable(uuid) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_registry_lock() FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_run_busy(uuid) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.assert_yoon_version_identity(uuid) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.assert_yoon_version_execution(uuid,text,text) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_version_snapshot(uuid) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_immutable_registry() FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_registration_check() FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_mutation_guard() FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_bootstrap_check() FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_audience_guard() FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.select_yoon_version(uuid,uuid,bigint,uuid,text,text,text,boolean) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.initialize_yoon_version_execution(uuid) FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_selection_receipt_check() FROM %I',target_role);
  EXECUTE format('REVOKE ALL ON FUNCTION ops.yoon_release_receipt_check() FROM %I',target_role);
  IF target_role='set_list_dev_app' THEN
   EXECUTE format('GRANT SELECT(set_id,submission_id) ON ops.yoon_reserved_versions TO %I',target_role);
   EXECUTE format('GRANT SELECT(set_id,submission_id,logical_set_id,collection_id,released) ON ops.yoon_versions TO %I',target_role);
   EXECUTE format('GRANT SELECT(logical_set_id,selected_set_id) ON ops.yoon_version_families TO %I',target_role);
   EXECUTE format('GRANT SELECT(collection_id) ON ops.yoon_version_collections TO %I',target_role);
  ELSE
   EXECUTE format('GRANT SELECT ON ops.yoon_reserved_versions,ops.yoon_versions,ops.yoon_version_families TO %I',target_role);
   EXECUTE format('GRANT SELECT(collection_id,audience_sha256) ON ops.yoon_version_collections TO %I',target_role);
   EXECUTE format('GRANT EXECUTE ON FUNCTION ops.yoon_sha(jsonb),ops.yoon_audience(uuid),ops.yoon_source_fingerprint(uuid),ops.yoon_media_fingerprint(uuid),ops.yoon_registry_lock(),ops.yoon_run_busy(uuid),ops.assert_yoon_version_identity(uuid),ops.assert_yoon_version_execution(uuid,text,text) TO %I',target_role);
  END IF;
  EXECUTE format('GRANT EXECUTE ON FUNCTION app.yoon_version_readable(uuid,boolean),app.yoon_submission_version_readable(uuid),ops.yoon_collection_scope(uuid),ops.yoon_is_v2(jsonb) TO %I',target_role);
 END LOOP;
END $yoon_acl_seal$;
