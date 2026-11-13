-- Review follow-ups for the partial-family release (before any real release):
-- * Fragments are found by their index field, cited windows must be distinct and
--   overlap the entry's own span.
-- * Worker-staged display data is reduced to known keys, and links or images are
--   kept only on known provider hosts, so a staged payload cannot make a viewer's
--   browser contact an arbitrary host.

CREATE FUNCTION ops.yoon_partial_mix_keys() RETURNS text[] LANGUAGE sql IMMUTABLE AS $$
 SELECT ARRAY['artist_name','artist_profile_confidence','artist_profile_expected_genres','artist_profile_genre_overlap',
  'artist_profile_image','artist_profile_name','artist_profile_provider_genres','artist_profile_rejected_reason',
  'artist_profile_source','artist_profile_url','discogs_artist_profile_genres','discogs_artist_profile_image',
  'discogs_artist_profile_name','discogs_artist_profile_url','spotify_artist_profile_genres','spotify_artist_profile_image',
  'spotify_artist_profile_name','spotify_artist_profile_url'] $$;
--> statement-breakpoint
CREATE FUNCTION ops.yoon_partial_entry_keys() RETURNS text[] LANGUAGE sql IMMUTABLE AS $$
 SELECT ARRAY['artist','bpm','cluster_density','cluster_span','confidence','danceability','detection_count','discogs_genres',
  'discogs_label','discogs_label_url','discogs_matching_version','discogs_metadata_scope','discogs_styles','discogs_url',
  'end_time','end_time_formatted','energy','isrc','key','link_matching_version','platform_matches','position',
  'shazam_track_id','source_deep_link','spotify_album_art','spotify_artist_id','spotify_artist_image','spotify_artist_name',
  'spotify_artist_profile_image','spotify_artist_url','spotify_genres','spotify_preview_url','spotify_url','start_time',
  'start_time_formatted','title','youtube_url'] $$;
--> statement-breakpoint
CREATE FUNCTION ops.yoon_partial_safe_value(v jsonb) RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
 IF jsonb_typeof(v)='string' THEN
  IF (v#>>'{}') ~* '^\s*[a-z][a-z0-9+.-]*:' AND (v#>>'{}') !~ '^https://(open\.spotify\.com|i\.scdn\.co|p\.scdn\.co|mosaic\.scdn\.co|www\.youtube\.com|music\.youtube\.com|www\.discogs\.com|i\.discogs\.com|st\.discogs\.com)/[^\s]*$'
   AND (v#>>'{}') ~* '^\s*(https?|javascript|data|vbscript|file|ftp|blob):' THEN RETURN 'null'::jsonb; END IF;
  RETURN v;
 ELSIF jsonb_typeof(v)='array' THEN
  RETURN coalesce((SELECT jsonb_agg(ops.yoon_partial_safe_value(e) ORDER BY n) FROM jsonb_array_elements(v) WITH ORDINALITY x(e,n)),'[]'::jsonb);
 ELSIF jsonb_typeof(v)='object' THEN
  RETURN coalesce((SELECT jsonb_object_agg(k,ops.yoon_partial_safe_value(e)) FROM jsonb_each(v) x(k,e)),'{}'::jsonb);
 END IF;
 RETURN v;
END $$;
--> statement-breakpoint
CREATE FUNCTION ops.yoon_partial_safe(v jsonb, allowed text[]) RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce((SELECT jsonb_object_agg(k,ops.yoon_partial_safe_value(e)) FROM jsonb_each(CASE WHEN jsonb_typeof(v)='object' THEN v ELSE '{}'::jsonb END) x(k,e)
  WHERE k=ANY(allowed)),'{}'::jsonb) $$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION ops.yoon_release_partial_family(p_set uuid, p_payload_sha256 text) RETURNS jsonb
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
  SELECT x INTO frag FROM jsonb_array_elements(p.fragments) x WHERE x->'index'=track->'fragment';
  IF (SELECT count(DISTINCT v) FROM jsonb_array_elements(track->'segment_indices') v)<>jsonb_array_length(track->'segment_indices')
   THEN RAISE EXCEPTION 'yoon_partial_entry_duplicate_evidence'; END IF;
  IF frag IS NULL THEN RAISE EXCEPTION 'yoon_partial_entry_fragment'; END IF;
  fstart:=(frag->>'startFrame')::numeric/rate; fend:=((frag->>'startFrame')::bigint+(frag->>'frames')::bigint)::numeric/rate;
  ts:=(track->>'start_seconds')::int; te:=(track->>'end_seconds')::int;
  IF ts IS NULL OR te IS NULL OR ts<ceil(fstart) OR te>floor(fend) OR te<=ts OR ts<prev_end THEN RAISE EXCEPTION 'yoon_partial_entry_crosses_gap_or_overlaps'; END IF;
  prev_end:=te;
  FOR ix IN SELECT value::text::int FROM jsonb_array_elements(track->'segment_indices') LOOP
   SELECT hit INTO h FROM ops.yoon_partial_hits WHERE set_id=p_set AND segment_index=ix;
   IF h IS NULL OR h->'fragment' IS DISTINCT FROM track->'fragment'
    -- The cited 30 s window must overlap the entry's own time span.
    OR (h->>'recorded_start_frame')::numeric/rate>=te OR (h->>'recorded_start_frame')::numeric/rate+30<=ts OR (h->'response'->>'recognized')::boolean IS NOT TRUE
    OR h->'response'->'raw_data'->'track'->>'title' IS DISTINCT FROM track->>'title'
    OR h->'response'->'raw_data'->'track'->>'subtitle' IS DISTINCT FROM track->>'artist'
    THEN RAISE EXCEPTION 'yoon_partial_entry_evidence'; END IF;
  END LOOP;
 END LOOP;

 meta:=jsonb_build_object('mixInfo',ops.yoon_partial_safe(imp.payload->'mix_info',ops.yoon_partial_mix_keys())||jsonb_build_object('artist_name',p.name,'title',p.name||' (partial recording)'),
  'summary',jsonb_build_object('trackCount',pos)||jsonb_build_object('recognitionCoverage',
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
  ops.yoon_partial_safe(t->'metadata',ops.yoon_partial_entry_keys())||jsonb_build_object('fragment',(t->>'fragment')::int,'segment_indices',t->'segment_indices','source_deep_link',NULL)
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
DO $$ DECLARE f text; BEGIN
 FOREACH f IN ARRAY ARRAY['ops.yoon_partial_mix_keys()','ops.yoon_partial_entry_keys()','ops.yoon_partial_safe_value(jsonb)',
  'ops.yoon_partial_safe(jsonb,text[])','ops.yoon_release_partial_family(uuid,text)'] LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC',f);
 END LOOP;
END $$;
