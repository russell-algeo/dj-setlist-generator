-- Six reviewed partial Yoon recordings as new private families.
--
-- * Sealed identities: only six digest-pinned families may be added beside the
--   27 bootstrapped originals; any other predecessor-less registration fails.
--   The rows themselves (private names, source spans) are seeded by the owner.
-- * Recognition evidence is append-only and validated against the sealed
--   fragment/window grid (30 s windows every 15 s, never across a modeled gap).
-- * Release is owner-only and atomic. It re-checks the pinned two-member
--   audience (Russell as manager, Hal as viewer), private visibility on every
--   row, the exact source spans and every imported entry before anything
--   becomes readable.
-- * The app checks the pinned audience on every Yoon access decision.
-- Private recording links are inserted separately by the owner, never here.

CREATE TABLE ops.yoon_partial_families (
 set_id uuid PRIMARY KEY, run_id uuid UNIQUE NOT NULL, submission_id uuid UNIQUE NOT NULL,
 media_id uuid UNIQUE NOT NULL, source_id text UNIQUE NOT NULL, slug text UNIQUE NOT NULL,
 name text NOT NULL, manifest_sha256 text NOT NULL CHECK(manifest_sha256 ~ '^[0-9a-f]{64}$'),
 expected_windows integer NOT NULL CHECK(expected_windows>0),
 recorded_frames bigint NOT NULL CHECK(recorded_frames>0),
 fragments jsonb NOT NULL CHECK(jsonb_typeof(fragments)='array' AND jsonb_array_length(fragments)>0),
 coverage jsonb NOT NULL CHECK(jsonb_typeof(coverage)='object')
);
--> statement-breakpoint

-- Owner-supplied private links for exactly the masters the six families use.
CREATE TABLE ops.yoon_partial_sources (
 file text PRIMARY KEY CHECK(file ~ '^[0-9]{6}_[0-9]{4}_3-4\.wav$'),
 url text NOT NULL CHECK(length(url)<=4096 AND url ~ '^https://www\.dropbox\.com/scl/f[io]/[A-Za-z0-9_/.-]+\?[^#]*rlkey=[A-Za-z0-9_-]+')
);
--> statement-breakpoint
CREATE TABLE ops.yoon_partial_hits (
 set_id uuid NOT NULL REFERENCES ops.yoon_partial_families(set_id),
 segment_index integer NOT NULL CHECK(segment_index>=0),
 pcm_sha256 text NOT NULL CHECK(pcm_sha256 ~ '^[0-9a-f]{64}$'),
 hit jsonb NOT NULL CHECK(octet_length(hit::text)<=262144),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(set_id,segment_index)
);
--> statement-breakpoint
CREATE TABLE ops.yoon_partial_imports (
 id bigserial PRIMARY KEY,
 set_id uuid NOT NULL REFERENCES ops.yoon_partial_families(set_id),
 hits_sha256 text NOT NULL, payload jsonb NOT NULL CHECK(octet_length(payload::text)<=4194304),
 payload_sha256 text UNIQUE NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
--> statement-breakpoint
CREATE TABLE ops.yoon_partial_releases (
 set_id uuid PRIMARY KEY REFERENCES ops.yoon_partial_families(set_id),
 import_id bigint UNIQUE NOT NULL REFERENCES ops.yoon_partial_imports(id),
 receipt jsonb NOT NULL, released_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
--> statement-breakpoint
-- The six family rows hold private names and source spans, so they are seeded by
-- the owner from the private handoff. Only rows whose exact digest is pinned here
-- can ever be inserted.
CREATE FUNCTION ops.yoon_partial_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='yoon_partial_families' AND TG_OP='INSERT' AND (NEW.set_id, ops.yoon_sha(to_jsonb(NEW))) NOT IN (
  ('0c7bdc16-d885-5d3b-b759-aafab912ee32'::uuid,'1b634f91790980aaa0b169145bfbbdd9fd6215e5e9b589c18a86aab895e22098'),
  ('68a6bf67-8151-5381-8e0c-dcc106d978c3'::uuid,'aee92a789b13510ef888000b4404c10bc89208ed75720be6cca5dc9c2d5a6369'),
  ('6fce4eb8-27f5-5966-9185-dfc9622fcb35'::uuid,'e868ce6d188fa4124564c9460385edf917ce213b9b85dd47c8372d9747edc09e'),
  ('9ed06b2e-738a-5444-aea1-76efefa9a41e'::uuid,'70a61cc7d92eae2d5e61737828e3d9fdcbbeeeebe561d8b8a8e40961dd9d9d7d'),
  ('bcb95699-4a9c-536b-a1a6-589090680c5b'::uuid,'651e6ffe1b4356ba30f19731f82e4154aced2c70dbdd7fef6b19507324701f7d'),
  ('c24afb76-a453-5c85-9a4f-e6de2e151a68'::uuid,'832c55a45d85e583cb3d435f3170c6ed6beb5eff8b2b3837fbce8578451ba8f0'))
 THEN RAISE EXCEPTION 'yoon_partial_families_sealed'; END IF;
 IF TG_OP IN ('UPDATE','DELETE') THEN RAISE EXCEPTION 'yoon_partial_append_only'; END IF;
 RETURN NEW;
END $$;
--> statement-breakpoint
CREATE TRIGGER yoon_partial_sealed BEFORE INSERT OR UPDATE OR DELETE ON ops.yoon_partial_families FOR EACH ROW EXECUTE FUNCTION ops.yoon_partial_append_only();
--> statement-breakpoint
CREATE TRIGGER yoon_partial_append_only BEFORE UPDATE OR DELETE ON ops.yoon_partial_hits FOR EACH ROW EXECUTE FUNCTION ops.yoon_partial_append_only();
--> statement-breakpoint
CREATE TRIGGER yoon_partial_append_only BEFORE UPDATE OR DELETE ON ops.yoon_partial_imports FOR EACH ROW EXECUTE FUNCTION ops.yoon_partial_append_only();
--> statement-breakpoint
CREATE TRIGGER yoon_partial_append_only BEFORE UPDATE OR DELETE ON ops.yoon_partial_releases FOR EACH ROW EXECUTE FUNCTION ops.yoon_partial_append_only();
--> statement-breakpoint

-- Deterministic window grid: fragment-local, full 30 s windows every 15 s.
CREATE FUNCTION ops.yoon_partial_windows(p_set uuid) RETURNS TABLE(segment_index integer, fragment integer, start_frame bigint)
LANGUAGE sql STABLE SET search_path=pg_catalog,public AS $$
 SELECT (row_number() OVER (ORDER BY (f->>'index')::int, k)-1)::int, (f->>'index')::int,
  (f->>'startFrame')::bigint+k*661500
 FROM ops.yoon_partial_families p, jsonb_array_elements(p.fragments) f,
  generate_series(0::bigint, ((f->>'frames')::bigint-1323000)/661500) k
 WHERE p.set_id=p_set AND (f->>'frames')::bigint>=1323000 $$;
--> statement-breakpoint
CREATE FUNCTION ops.yoon_partial_valid_hit(p_set uuid, p_index integer, p_hit jsonb) RETURNS boolean
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public AS $$
DECLARE w record; p ops.yoon_partial_families; r jsonb; raw jsonb; BEGIN
 SELECT * INTO p FROM ops.yoon_partial_families WHERE set_id=p_set;
 IF NOT FOUND THEN RETURN false; END IF;
 SELECT * INTO w FROM ops.yoon_partial_windows(p_set) x WHERE x.segment_index=p_index;
 IF NOT FOUND OR jsonb_typeof(p_hit) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
 IF (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(p_hit) k) IS DISTINCT FROM ARRAY['fragment','index','recorded_start_frame','response','source_manifest_sha256'] THEN RETURN false; END IF;
 r:=p_hit->'response'; raw:=r->'raw_data';
 IF p_hit->'index' IS DISTINCT FROM to_jsonb(p_index) OR p_hit->'fragment' IS DISTINCT FROM to_jsonb(w.fragment)
  OR p_hit->'recorded_start_frame' IS DISTINCT FROM to_jsonb(w.start_frame)
  OR p_hit->>'source_manifest_sha256' IS DISTINCT FROM p.manifest_sha256
  OR jsonb_typeof(r) IS DISTINCT FROM 'object' OR r->'segment_index' IS DISTINCT FROM to_jsonb(p_index)
  OR jsonb_typeof(r->'timestamp') IS DISTINCT FROM 'number'
  OR abs((r->>'timestamp')::numeric*44100-w.start_frame)>0.5
  OR r->'http_status' IS DISTINCT FROM '200'::jsonb OR jsonb_typeof(r->'recognized') IS DISTINCT FROM 'boolean'
  OR jsonb_typeof(raw) IS DISTINCT FROM 'object' OR jsonb_typeof(raw->'matches') IS DISTINCT FROM 'array'
  OR (r->>'recognized')::boolean IS DISTINCT FROM (jsonb_array_length(raw->'matches')>0)
 THEN RETURN false; END IF;
 IF jsonb_array_length(raw->'matches')>0 AND (jsonb_typeof(raw->'track') IS DISTINCT FROM 'object'
  OR coalesce(btrim(raw->'track'->>'title'),'')='' OR coalesce(btrim(raw->'track'->>'subtitle'),'')=''
  OR coalesce(btrim(raw->'track'->>'key'),'')='') THEN RETURN false; END IF;
 RETURN true;
END $$;
--> statement-breakpoint
-- Worker API: sources, progress, append-only evidence, staged enrichment.
CREATE FUNCTION ops.yoon_partial_sources_for(p_set uuid) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public AS $$
DECLARE files text[]; out jsonb; BEGIN
 IF EXISTS(SELECT 1 FROM ops.yoon_partial_releases WHERE set_id=p_set) THEN RAISE EXCEPTION 'yoon_partial_already_released'; END IF;
 SELECT array_agg(DISTINCT x->>'file') INTO files FROM ops.yoon_partial_families p, jsonb_array_elements(p.fragments) f, jsonb_array_elements(f->'parts') x WHERE p.set_id=p_set;
 IF files IS NULL THEN RAISE EXCEPTION 'yoon_partial_unknown_family'; END IF;
 SELECT jsonb_object_agg(s.file, s.url) INTO out FROM ops.yoon_partial_sources s WHERE s.file=ANY(files);
 IF out IS NULL OR (SELECT count(*) FROM jsonb_object_keys(out))<>cardinality(files) THEN RAISE EXCEPTION 'yoon_partial_sources_missing'; END IF;
 RETURN out;
END $$;
--> statement-breakpoint
CREATE FUNCTION ops.yoon_partial_progress(p_set uuid) RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public AS $$
 SELECT jsonb_build_object('name',p.name,'expected',p.expected_windows,'fragments',p.fragments,
  'manifest_sha256',p.manifest_sha256,'released',EXISTS(SELECT 1 FROM ops.yoon_partial_releases r WHERE r.set_id=p.set_id),
  'done',(SELECT coalesce(jsonb_agg(h.segment_index ORDER BY h.segment_index),'[]') FROM ops.yoon_partial_hits h WHERE h.set_id=p.set_id))
 FROM ops.yoon_partial_families p WHERE p.set_id=p_set $$;
--> statement-breakpoint
CREATE FUNCTION ops.yoon_partial_record_hit(p_set uuid, p_index integer, p_pcm_sha256 text, p_hit jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE n integer; BEGIN
 IF EXISTS(SELECT 1 FROM ops.yoon_partial_releases WHERE set_id=p_set) THEN RAISE EXCEPTION 'yoon_partial_already_released'; END IF;
 IF p_pcm_sha256 IS NULL OR p_pcm_sha256 !~ '^[0-9a-f]{64}$' OR NOT ops.yoon_partial_valid_hit(p_set,p_index,p_hit) THEN RAISE EXCEPTION 'yoon_partial_invalid_hit'; END IF;
 INSERT INTO ops.yoon_partial_hits(set_id,segment_index,pcm_sha256,hit) VALUES(p_set,p_index,p_pcm_sha256,p_hit) ON CONFLICT DO NOTHING;
 GET DIAGNOSTICS n = ROW_COUNT; RETURN n=1;
END $$;
--> statement-breakpoint
CREATE FUNCTION ops.yoon_partial_hits_sha256(p_set uuid) RETURNS text LANGUAGE sql STABLE SET search_path=pg_catalog,public AS $$
 SELECT encode(sha256(convert_to(coalesce(jsonb_agg(jsonb_build_array(segment_index,pcm_sha256,hit) ORDER BY segment_index),'[]')::text,'UTF8')),'hex')
 FROM ops.yoon_partial_hits WHERE set_id=p_set $$;
--> statement-breakpoint
CREATE FUNCTION ops.yoon_partial_hits_for(p_set uuid) RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public AS $$
DECLARE p ops.yoon_partial_families; BEGIN
 SELECT * INTO STRICT p FROM ops.yoon_partial_families WHERE set_id=p_set;
 IF (SELECT count(*) FROM ops.yoon_partial_hits WHERE set_id=p_set)<>p.expected_windows THEN RAISE EXCEPTION 'yoon_partial_recognition_incomplete'; END IF;
 RETURN jsonb_build_object('hits_sha256',ops.yoon_partial_hits_sha256(p_set),
  'hits',(SELECT jsonb_agg(hit ORDER BY segment_index) FROM ops.yoon_partial_hits WHERE set_id=p_set));
END $$;
--> statement-breakpoint
CREATE FUNCTION ops.yoon_partial_stage_import(p_set uuid, p_hits_sha256 text, p_payload jsonb) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE p ops.yoon_partial_families; digest text; BEGIN
 SELECT * INTO STRICT p FROM ops.yoon_partial_families WHERE set_id=p_set;
 IF EXISTS(SELECT 1 FROM ops.yoon_partial_releases WHERE set_id=p_set) THEN RAISE EXCEPTION 'yoon_partial_already_released'; END IF;
 IF (SELECT count(*) FROM ops.yoon_partial_hits WHERE set_id=p_set)<>p.expected_windows
  OR p_hits_sha256 IS DISTINCT FROM ops.yoon_partial_hits_sha256(p_set) THEN RAISE EXCEPTION 'yoon_partial_hits_changed'; END IF;
 IF jsonb_typeof(p_payload) IS DISTINCT FROM 'object' OR jsonb_typeof(p_payload->'tracks') IS DISTINCT FROM 'array'
  OR jsonb_typeof(p_payload->'mix_info') IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'yoon_partial_payload_shape'; END IF;
 digest:=encode(sha256(convert_to(p_payload::text,'UTF8')),'hex');
 INSERT INTO ops.yoon_partial_imports(set_id,hits_sha256,payload,payload_sha256) VALUES(p_set,p_hits_sha256,p_payload,digest) ON CONFLICT (payload_sha256) DO NOTHING;
 RETURN digest;
END $$;
--> statement-breakpoint

-- Pinned audience, checked on every app access decision (fail closed).
CREATE FUNCTION app.yoon_audience_intact(p_collection uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public AS $$
 SELECT coalesce((SELECT c.audience_sha256=ops.yoon_audience(c.collection_id)
  AND (SELECT count(*) FROM app.archive_collection_members m WHERE m.collection_id=c.collection_id)=2
  AND (SELECT count(*) FROM app.archive_collection_members m WHERE m.collection_id=c.collection_id AND m.role='manager')=1
  FROM ops.yoon_version_collections c JOIN app.archive_collections a ON a.id=c.collection_id
  WHERE c.collection_id=p_collection AND a.slug='yoon-fest'),false) $$;
--> statement-breakpoint

-- Close the registry: no predecessor-less family except bootstrap or a released sealed partial.
CREATE FUNCTION ops.yoon_new_family_allowed(p_set uuid, p_collection uuid) RETURNS boolean LANGUAGE sql STABLE
SET search_path=pg_catalog,public AS $$
 SELECT EXISTS(SELECT 1 FROM ops.yoon_version_collections c WHERE c.collection_id=p_collection
   AND c.bootstrap_manifest @> jsonb_build_array(jsonb_build_object('set_id',p_set::text)))
 OR EXISTS(SELECT 1 FROM ops.yoon_partial_releases r JOIN ops.yoon_partial_families f USING(set_id)
   JOIN ops.yoon_versions v ON v.set_id=f.set_id
   WHERE f.set_id=p_set AND v.collection_id=p_collection AND v.logical_set_id=f.set_id AND v.run_id=f.run_id
   AND v.submission_id=f.submission_id AND v.media_id=f.media_id AND v.source_id=f.source_id AND v.slug=f.slug
   AND v.manifest_sha256=f.manifest_sha256 AND v.model_version='partial-first-family-mean-gaps-v1') $$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION ops.yoon_registration_check()
 RETURNS trigger LANGUAGE plpgsql AS $function$
BEGIN
 PERFORM ops.assert_yoon_version_identity(NEW.set_id);
 IF NEW.predecessor_set_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM ops.yoon_reserved_versions r WHERE
 ROW(r.set_id,r.run_id,r.submission_id,r.media_id,r.logical_set_id,r.source_id,r.model_version)=ROW(NEW.set_id,NEW.run_id,NEW.submission_id,NEW.media_id,NEW.logical_set_id,NEW.source_id,NEW.model_version)) THEN RAISE EXCEPTION 'yoon_not_finite_reviewed_version'; END IF;
 IF NEW.predecessor_set_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM ops.yoon_reserved_versions p JOIN ops.set_runs r ON r.id=NEW.run_id WHERE p.set_id=NEW.set_id AND NEW.media_revision=p.media_revision AND r.source_metadata->'yoon_fixed_input' @> p.descriptor) THEN RAISE EXCEPTION 'yoon_fixed_source_pins'; END IF;
 IF NEW.predecessor_set_id IS NULL AND NEW.logical_set_id<>NEW.set_id THEN RAISE EXCEPTION 'yoon_invalid_legacy_family'; END IF;
 IF NEW.predecessor_set_id IS NULL AND NOT ops.yoon_new_family_allowed(NEW.set_id,NEW.collection_id) THEN RAISE EXCEPTION 'yoon_unreviewed_new_family'; END IF;
 RETURN NEW; END $function$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION ops.yoon_selection_receipt_check()
 RETURNS trigger LANGUAGE plpgsql AS $function$
BEGIN
 IF TG_OP='UPDATE' AND (NEW.logical_set_id IS DISTINCT FROM OLD.logical_set_id OR NEW.collection_id IS DISTINCT FROM OLD.collection_id
  OR NEW.selection_revision IS DISTINCT FROM OLD.selection_revision+1
  OR NOT EXISTS(SELECT 1 FROM ops.yoon_version_history h WHERE h.logical_set_id=NEW.logical_set_id AND h.revision=NEW.selection_revision AND h.old_set_id=OLD.selected_set_id AND h.new_set_id=NEW.selected_set_id)) THEN RAISE EXCEPTION 'yoon_selection_receipt_required'; END IF;
 IF TG_OP='INSERT' AND (NEW.selection_revision<>0 OR NEW.selected_set_id<>NEW.logical_set_id
  OR NOT ops.yoon_new_family_allowed(NEW.logical_set_id,NEW.collection_id)) THEN RAISE EXCEPTION 'yoon_unreviewed_new_family'; END IF;
 IF NOT EXISTS(SELECT 1 FROM ops.yoon_versions v WHERE v.set_id=NEW.selected_set_id AND v.logical_set_id=NEW.logical_set_id AND v.collection_id=NEW.collection_id AND v.released) THEN RAISE EXCEPTION 'yoon_selected_version_unreleased'; END IF;
 RETURN NEW;
END $function$;
--> statement-breakpoint

-- Owner-only atomic first release of one sealed partial family.
CREATE FUNCTION ops.yoon_release_partial_family(p_set uuid, p_payload_sha256 text) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE p ops.yoon_partial_families; imp ops.yoon_partial_imports; cid uuid; audience text; owner_id text;
 spans jsonb; sources jsonb; descriptor jsonb; source_url text; media app.set_media; meta jsonb; track jsonb;
 pos integer:=0; prev_end integer:=-1; frag jsonb; fstart numeric; fend numeric; ix integer; h jsonb; ts integer; te integer;
 matched integer; receipt jsonb; rate constant integer:=44100;
BEGIN
 PERFORM ops.yoon_registry_lock();
 PERFORM pg_advisory_xact_lock(183602,hashtext(p_set::text));
 SELECT * INTO STRICT p FROM ops.yoon_partial_families WHERE set_id=p_set;
 IF EXISTS(SELECT 1 FROM ops.yoon_partial_releases WHERE set_id=p_set) THEN RAISE EXCEPTION 'yoon_partial_already_released'; END IF;
 SELECT * INTO STRICT imp FROM ops.yoon_partial_imports WHERE set_id=p_set AND payload_sha256=p_payload_sha256;
 IF (SELECT count(*) FROM ops.yoon_partial_hits WHERE set_id=p_set)<>p.expected_windows
  OR imp.hits_sha256 IS DISTINCT FROM ops.yoon_partial_hits_sha256(p_set)
  OR EXISTS(SELECT 1 FROM ops.yoon_partial_hits WHERE set_id=p_set AND NOT ops.yoon_partial_valid_hit(set_id,segment_index,hit))
  THEN RAISE EXCEPTION 'yoon_partial_recognition_incomplete'; END IF;

 -- Ownership: the private Yoon collection, its pinned audience, its single manager.
 SELECT a.id INTO STRICT cid FROM app.archive_collections a WHERE a.slug='yoon-fest';
 IF NOT app.yoon_audience_intact(cid) THEN RAISE EXCEPTION 'yoon_partial_audience_changed'; END IF;
 SELECT audience_sha256 INTO STRICT audience FROM ops.yoon_version_collections WHERE collection_id=cid;
 SELECT user_id INTO STRICT owner_id FROM app.archive_collection_members WHERE collection_id=cid AND role='manager';

 IF EXISTS(SELECT 1 FROM app.sets WHERE id IN (p.set_id,p.run_id,p.submission_id,p.media_id) OR slug=p.slug OR source_id=p.source_id)
  OR EXISTS(SELECT 1 FROM ops.yoon_versions WHERE set_id=p.set_id OR logical_set_id=p.set_id OR run_id=p.run_id OR submission_id=p.submission_id OR media_id=p.media_id OR source_id=p.source_id OR slug=p.slug)
  OR EXISTS(SELECT 1 FROM ops.set_runs WHERE id=p.run_id) OR EXISTS(SELECT 1 FROM ops.submissions WHERE id=p.submission_id)
  OR EXISTS(SELECT 1 FROM app.set_media WHERE id=p.media_id)
  THEN RAISE EXCEPTION 'yoon_partial_identity_collision'; END IF;

 -- Exact media: every source span in fragment order, links only for those masters.
 SELECT jsonb_agg(jsonb_build_object('recordingId',x->>'file','startSample',(x->>'start')::bigint,'endSample',(x->>'end')::bigint,'sampleRate',rate) ORDER BY (f->>'index')::int, n)
  INTO spans FROM jsonb_array_elements(p.fragments) f, jsonb_array_elements(f->'parts') WITH ORDINALITY y(x,n);
 SELECT jsonb_agg(jsonb_build_object('recordingId',s.file,'url',s.url) ORDER BY s.file) INTO sources
  FROM ops.yoon_partial_sources s WHERE s.file IN (SELECT DISTINCT e->>'recordingId' FROM jsonb_array_elements(spans) e);
 IF jsonb_array_length(sources) IS DISTINCT FROM (SELECT count(DISTINCT e->>'recordingId') FROM jsonb_array_elements(spans) e)::int
  OR (SELECT sum((e->>'endSample')::bigint-(e->>'startSample')::bigint) FROM jsonb_array_elements(spans) e)<>p.recorded_frames
  THEN RAISE EXCEPTION 'yoon_partial_sources_missing'; END IF;

 source_url:='local:yoon-partial:'||p.source_id;
 descriptor:=jsonb_build_object('source_id',p.source_id,'recognition_mode','partial-first-family-v1',
  'manifest_sha256',p.manifest_sha256,'fragments',p.fragments);
 SELECT count(*) INTO matched FROM ops.yoon_partial_hits WHERE set_id=p_set AND (hit->'response'->>'recognized')::boolean;

 -- Entries: identified clusters only, each inside one fragment, ordered and non-overlapping,
 -- every cited window recognized as the same track.
 IF jsonb_array_length(imp.payload->'tracks')=0 THEN RAISE EXCEPTION 'yoon_partial_entries_required'; END IF;
 FOR track IN SELECT value FROM jsonb_array_elements(imp.payload->'tracks') LOOP
  pos:=pos+1;
  IF track->'position' IS DISTINCT FROM to_jsonb(pos) OR jsonb_typeof(track->'fragment') IS DISTINCT FROM 'number'
   OR coalesce(btrim(track->>'artist'),'')='' OR coalesce(btrim(track->>'title'),'')='' OR track->>'title'='Unknown Track'
   OR track->>'confidence' NOT IN ('HIGH','MEDIUM','LOW','UNCERTAIN') OR jsonb_typeof(track->'metadata') IS DISTINCT FROM 'object'
   OR jsonb_typeof(track->'segment_indices') IS DISTINCT FROM 'array' OR jsonb_array_length(track->'segment_indices')=0
   OR (track->>'detection_count')::int IS DISTINCT FROM jsonb_array_length(track->'segment_indices')
   THEN RAISE EXCEPTION 'yoon_partial_entry_shape'; END IF;
  frag:=p.fragments->((track->>'fragment')::int);
  IF frag IS NULL THEN RAISE EXCEPTION 'yoon_partial_entry_fragment'; END IF;
  fstart:=(frag->>'startFrame')::numeric/rate; fend:=((frag->>'startFrame')::bigint+(frag->>'frames')::bigint)::numeric/rate;
  ts:=(track->>'start_seconds')::int; te:=(track->>'end_seconds')::int;
  IF ts IS NULL OR te IS NULL OR ts<ceil(fstart) OR te>floor(fend) OR te<=ts OR ts<prev_end THEN RAISE EXCEPTION 'yoon_partial_entry_crosses_gap_or_overlaps'; END IF;
  prev_end:=te;
  FOR ix IN SELECT value::text::int FROM jsonb_array_elements(track->'segment_indices') LOOP
   SELECT hit INTO h FROM ops.yoon_partial_hits WHERE set_id=p_set AND segment_index=ix;
   IF h IS NULL OR h->'fragment' IS DISTINCT FROM track->'fragment' OR (h->'response'->>'recognized')::boolean IS NOT TRUE
    OR h->'response'->'raw_data'->'track'->>'title' IS DISTINCT FROM track->>'title'
    OR h->'response'->'raw_data'->'track'->>'subtitle' IS DISTINCT FROM track->>'artist'
    THEN RAISE EXCEPTION 'yoon_partial_entry_evidence'; END IF;
  END LOOP;
 END LOOP;

 meta:=jsonb_build_object('mixInfo',(imp.payload->'mix_info')||jsonb_build_object('artist_name',p.name,'title',p.name||' (partial recording)'),
  'summary',coalesce(imp.payload->'summary','{}'::jsonb)||jsonb_build_object('recognitionCoverage',
   jsonb_build_object('expectedWindows',p.expected_windows,'validResponses',p.expected_windows,'matchedWindows',matched)),
  'boundaryStatus','provisional',
  'boundaryNote','Partial recording; timing provisional. Performer boundaries follow the four-gap mean schedule model and have not been verified by listening.',
  'partialCoverage',p.coverage,'timingModelVersion','partial-first-family-mean-gaps-v1');

 -- The media row is fixed before registration so its fingerprint can be pinned up front.
 media:=ROW(p.media_id,p.set_id,p.source_id||'-original-wav-v1','audio/wav',(p.recorded_frames::numeric/rate)::numeric(12,6),sources,spans,now(),now())::app.set_media;
 INSERT INTO ops.yoon_versions(set_id,logical_set_id,model_version,source_id,run_id,submission_id,media_id,slug,media_revision,
  collection_id,requested_by,predecessor_set_id,manifest_sha256,source_sha256,media_sha256,audience_sha256,staging_approved,processing_approved,released,frozen)
 VALUES(p.set_id,p.set_id,'partial-first-family-mean-gaps-v1',p.source_id,p.run_id,p.submission_id,p.media_id,p.slug,p.source_id||'-original-wav-v1',
  cid,owner_id,NULL,p.manifest_sha256,ops.yoon_sha(jsonb_build_object('source_url',source_url,'descriptor',descriptor)),
  ops.yoon_sha(to_jsonb(media)-'created_at'-'updated_at'),audience,false,true,true,false);
 INSERT INTO ops.yoon_version_families(logical_set_id,collection_id,selected_set_id) VALUES(p.set_id,cid,p.set_id);
 INSERT INTO app.sets(id,slug,title,normalized_title,source_platform,source_id,duration_seconds,recognition_rate,metadata,visibility,collection_id)
 VALUES(p.set_id,p.slug,p.name||' (partial recording)',lower(p.name||' (partial recording)'),'local',p.source_id,
  floor(p.recorded_frames::numeric/rate)::int,round(100.0*matched/p.expected_windows,2),meta,'private',cid);
 INSERT INTO ops.submissions(id,requested_by,mode,status,visibility,collection_id) VALUES(p.submission_id,owner_id,'set','private_analysis_complete','private',cid);
 INSERT INTO ops.set_runs(id,submission_id,requested_by,status,stage,source_url,source_platform,set_title,publication_visibility,target_set_id,published_set_id,collection_id,source_metadata)
 VALUES(p.run_id,p.submission_id,owner_id,'private_resume_complete','private_import_complete',source_url,'local',p.name,'private',p.set_id,p.set_id,cid,
  jsonb_build_object('yoon_fixed_input',descriptor,'yoon_partial_import',jsonb_build_object('import_id',imp.id,'payload_sha256',imp.payload_sha256,'hits_sha256',imp.hits_sha256)));
 INSERT INTO app.set_media SELECT media.*;
 INSERT INTO ops.segment_hits(set_run_id,segment_index,timestamp_seconds,track_title,artist,shazam_track_id,recognized,raw_data)
 SELECT p.run_id,segment_index,floor((hit->'response'->>'timestamp')::numeric*100)/100,
  hit->'response'->'raw_data'->'track'->>'title',hit->'response'->'raw_data'->'track'->>'subtitle',hit->'response'->'raw_data'->'track'->>'key',
  (hit->'response'->>'recognized')::boolean,jsonb_build_object('yoon_partial',hit,'pcm_sha256',pcm_sha256)
 FROM ops.yoon_partial_hits WHERE set_id=p_set ORDER BY segment_index;
 INSERT INTO app.set_entries(set_id,position,display_artist,display_title,start_time_seconds,end_time_seconds,confidence,detection_count,cluster_density,cluster_span,metadata)
 SELECT p.set_id,(t->>'position')::int,t->>'artist',t->>'title',(t->>'start_seconds')::int,(t->>'end_seconds')::int,t->>'confidence',
  (t->>'detection_count')::int,round((t->>'cluster_density')::numeric,4),(t->>'cluster_span')::int,
  (t->'metadata')||jsonb_build_object('fragment',(t->>'fragment')::int,'segment_indices',t->'segment_indices','source_deep_link',NULL)
 FROM jsonb_array_elements(imp.payload->'tracks') t;
 UPDATE ops.yoon_versions SET processing_approved=false WHERE set_id=p.set_id;
 PERFORM ops.assert_yoon_version_identity(p.set_id);
 receipt:=jsonb_build_object('kind','YOON_PARTIAL_FIRST_RELEASE_V1','set_id',p.set_id,'payload_sha256',imp.payload_sha256,
  'hits_sha256',imp.hits_sha256,'audience_sha256',audience,'owner',owner_id,'entries',pos,'matched_windows',matched,
  'snapshot_sha256',ops.yoon_sha(ops.yoon_version_snapshot(p.set_id)));
 -- The release row is what admits this family; the deferred registry checks read it at commit.
 INSERT INTO ops.yoon_partial_releases(set_id,import_id,receipt) VALUES(p.set_id,imp.id,receipt);
 RETURN receipt;
END $$;
--> statement-breakpoint

-- Grants: workers get only the narrow evidence API; the app gets only the audience check.
DO $$ DECLARE r text; f text; BEGIN
 FOREACH f IN ARRAY ARRAY['ops.yoon_partial_windows(uuid)','ops.yoon_partial_valid_hit(uuid,integer,jsonb)','ops.yoon_partial_sources_for(uuid)',
  'ops.yoon_partial_progress(uuid)','ops.yoon_partial_record_hit(uuid,integer,text,jsonb)','ops.yoon_partial_hits_sha256(uuid)',
  'ops.yoon_partial_hits_for(uuid)','ops.yoon_partial_stage_import(uuid,text,jsonb)','app.yoon_audience_intact(uuid)',
  'ops.yoon_new_family_allowed(uuid,uuid)','ops.yoon_release_partial_family(uuid,text)','ops.yoon_partial_append_only()'] LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC',f);
 END LOOP;
 FOR r IN SELECT rolname FROM pg_roles WHERE rolname IN ('set_list_app','set_list_dev_app','set_list_worker','set_list_dev_worker') LOOP
  EXECUTE format('REVOKE ALL ON ops.yoon_partial_families,ops.yoon_partial_sources,ops.yoon_partial_hits,ops.yoon_partial_imports,ops.yoon_partial_releases FROM %I',r);
 END LOOP;
 FOR r IN SELECT rolname FROM pg_roles WHERE rolname IN ('set_list_dev_worker') LOOP
  EXECUTE format('GRANT EXECUTE ON FUNCTION ops.yoon_partial_sources_for(uuid),ops.yoon_partial_progress(uuid),ops.yoon_partial_record_hit(uuid,integer,text,jsonb),ops.yoon_partial_hits_for(uuid),ops.yoon_partial_stage_import(uuid,text,jsonb) TO %I',r);
 END LOOP;
 FOR r IN SELECT rolname FROM pg_roles WHERE rolname IN ('set_list_app','set_list_dev_app') LOOP
  EXECUTE format('GRANT EXECUTE ON FUNCTION app.yoon_audience_intact(uuid) TO %I',r);
 END LOOP;
END $$;
