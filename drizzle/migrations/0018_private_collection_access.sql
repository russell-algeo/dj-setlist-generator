-- Shared archive item permissions. REVIEW/TEST ONLY until an approved migration.
-- Expand phase only: preserve legacy public defaults until guarded writers deploy.
-- Do not insert private content until old readers are contained and 0019 is applied.
CREATE TABLE "app"."archive_collections" (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), slug text NOT NULL UNIQUE, title text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
--> statement-breakpoint
CREATE TABLE "app"."archive_collection_members" (
  collection_id uuid NOT NULL REFERENCES app.archive_collections(id) ON DELETE CASCADE,
  user_id text NOT NULL REFERENCES authn.users(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'viewer' CHECK (role IN ('viewer','manager')),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(collection_id,user_id)
);
--> statement-breakpoint
ALTER TABLE app.sets ADD COLUMN visibility text NOT NULL DEFAULT 'public';
--> statement-breakpoint
ALTER TABLE app.sets ADD COLUMN collection_id uuid REFERENCES app.archive_collections(id) ON DELETE RESTRICT;
--> statement-breakpoint
ALTER TABLE app.sets ADD CONSTRAINT sets_visibility_check CHECK (visibility IN ('public','private'));
--> statement-breakpoint
ALTER TABLE app.sets ADD CONSTRAINT sets_private_scope_check CHECK ((visibility='public' AND collection_id IS NULL) OR (visibility='private' AND collection_id IS NOT NULL));
--> statement-breakpoint
CREATE INDEX sets_collection_idx ON app.sets(collection_id);
--> statement-breakpoint
CREATE TABLE app.set_media (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), set_id uuid NOT NULL UNIQUE REFERENCES app.sets(id) ON DELETE CASCADE,
 revision text NOT NULL, content_type text NOT NULL, duration_seconds numeric(12,6) NOT NULL,
 recording_sources jsonb NOT NULL, source_spans jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
--> statement-breakpoint
ALTER TABLE ops.submissions ADD COLUMN visibility text NOT NULL DEFAULT 'public';
--> statement-breakpoint
ALTER TABLE ops.submissions ADD COLUMN collection_id uuid REFERENCES app.archive_collections(id) ON DELETE RESTRICT;
--> statement-breakpoint
ALTER TABLE ops.submissions ADD CONSTRAINT submissions_private_scope_check CHECK ((visibility='public' AND collection_id IS NULL) OR (visibility='private' AND collection_id IS NOT NULL));
--> statement-breakpoint
ALTER TABLE ops.set_runs ADD COLUMN publication_visibility text NOT NULL DEFAULT 'public';
--> statement-breakpoint
ALTER TABLE ops.set_runs ADD COLUMN target_set_id uuid REFERENCES app.sets(id) ON DELETE RESTRICT;
--> statement-breakpoint
ALTER TABLE ops.set_runs ADD COLUMN collection_id uuid REFERENCES app.archive_collections(id) ON DELETE RESTRICT;
--> statement-breakpoint
ALTER TABLE ops.set_runs ADD CONSTRAINT set_runs_private_target_check CHECK ((publication_visibility='public' AND target_set_id IS NULL AND collection_id IS NULL) OR (publication_visibility='private' AND target_set_id IS NOT NULL AND collection_id IS NOT NULL));
--> statement-breakpoint
CREATE VIEW app.public_sets AS SELECT * FROM app.sets WHERE visibility='public';
--> statement-breakpoint
CREATE VIEW app.public_set_entries AS SELECT se.* FROM app.set_entries se JOIN app.public_sets s ON s.id=se.set_id;
--> statement-breakpoint
CREATE VIEW app.public_set_artists AS SELECT sa.* FROM app.set_artists sa JOIN app.public_sets s ON s.id=sa.set_id;
--> statement-breakpoint
CREATE VIEW app.public_set_source_links AS SELECT sl.* FROM app.set_source_links sl JOIN app.public_sets s ON s.id=sl.set_id;
--> statement-breakpoint
CREATE VIEW app.public_artists AS SELECT a.* FROM app.artists a WHERE EXISTS (SELECT 1 FROM app.public_set_artists sa WHERE sa.artist_id=a.id);
--> statement-breakpoint
CREATE VIEW app.public_tracks AS SELECT t.* FROM app.tracks t WHERE EXISTS (SELECT 1 FROM app.public_set_entries se WHERE se.track_id=t.id);
--> statement-breakpoint
CREATE VIEW ops.public_submissions AS SELECT * FROM ops.submissions WHERE visibility='public';
--> statement-breakpoint
CREATE VIEW ops.public_set_runs AS SELECT * FROM ops.set_runs WHERE publication_visibility='public';
--> statement-breakpoint
-- Drop all three materialized views (must drop before recreating)
DROP MATERIALIZED VIEW IF EXISTS "app"."archive_home_pair_summaries_mv";
--> statement-breakpoint
DROP MATERIALIZED VIEW IF EXISTS "app"."archive_home_set_library_index_mv";
--> statement-breakpoint
DROP MATERIALIZED VIEW IF EXISTS "app"."archive_home_artist_atlas_mv";
--> statement-breakpoint
-- Recreate archive_home_artist_atlas_mv (legacy_path removed, WHERE filter removed)
CREATE MATERIALIZED VIEW "app"."archive_home_artist_atlas_mv" AS
WITH base_entries AS (
  SELECT
    a.id AS artist_id,
    a.slug AS artist_slug,
    a.name AS artist_name,
    COALESCE(
      'track:' || se.track_id::text,
      'fallback:' || lower(
        regexp_replace(
          concat_ws(' ', COALESCE(se.display_artist, ''), COALESCE(se.display_title, '')),
          '[^a-z0-9]+',
          ' ',
          'gi'
        )
      )
    ) AS track_key,
    se.display_artist AS track_artist,
    se.display_title AS track_title,
    COALESCE(
      NULLIF(tr.spotify_url, ''),
      NULLIF(tr.metadata ->> 'spotify_url', ''),
      NULLIF(se.metadata ->> 'spotify_url', '')
    ) AS spotify_url,
    COALESCE(
      NULLIF(tr.metadata ->> 'spotify_album_art', ''),
      NULLIF(se.metadata ->> 'spotify_album_art', ''),
      NULLIF(tr.metadata ->> 'albumArt', ''),
      NULLIF(se.metadata ->> 'albumArt', '')
    ) AS album_art,
    COALESCE(NULLIF(a.metadata ->> 'artist_image', ''), a.image_url) AS artist_image,
    COALESCE(
      NULLIF(a.metadata ->> 'artist_profile_image', ''),
      NULLIF(a.metadata ->> 'artist_image', ''),
      a.image_url
    ) AS artist_profile_image,
    COALESCE(
      NULLIF(tr.metadata ->> 'discogs_label', ''),
      NULLIF(se.metadata ->> 'discogs_label', '')
    ) AS label,
    COALESCE(
      NULLIF(tr.metadata ->> 'discogs_label_url', ''),
      NULLIF(se.metadata ->> 'discogs_label_url', '')
    ) AS label_url,
    ARRAY(
      SELECT DISTINCT initcap(lower(trim(genre_value)))
      FROM jsonb_array_elements_text(
        COALESCE(tr.metadata -> 'discogs_styles', '[]'::jsonb) ||
        COALESCE(tr.metadata -> 'spotify_genres', '[]'::jsonb) ||
        COALESCE(tr.metadata -> 'discogs_genres', '[]'::jsonb) ||
        COALESCE(se.metadata -> 'discogs_styles', '[]'::jsonb) ||
        COALESCE(se.metadata -> 'spotify_genres', '[]'::jsonb) ||
        COALESCE(se.metadata -> 'discogs_genres', '[]'::jsonb)
      ) AS genre_value
      WHERE trim(genre_value) <> ''
        AND initcap(lower(trim(genre_value))) <> 'House'
    ) AS row_genres,
    upper(COALESCE(se.confidence, 'UNCERTAIN')) AS confidence,
    s.slug AS set_slug,
    s.title AS set_title,
    se.position AS track_position
  FROM "app"."public_set_artists" sa
  INNER JOIN "app"."public_artists" a
    ON a.id = sa.artist_id
  INNER JOIN "app"."public_sets" s
    ON s.id = sa.set_id
  INNER JOIN "app"."public_set_entries" se
    ON se.set_id = s.id
  LEFT JOIN "app"."public_tracks" tr
    ON tr.id = se.track_id
  WHERE sa.role = 'primary'
    AND se.display_title <> 'Unknown Track'
),
entry_groups AS (
  SELECT
    artist_id,
    artist_slug,
    artist_name,
    track_key,
    min(track_artist) AS track_artist,
    min(track_title) AS track_title,
    max(spotify_url) FILTER (WHERE spotify_url IS NOT NULL) AS spotify_url,
    max(album_art) FILTER (WHERE album_art IS NOT NULL) AS album_art,
    max(artist_image) FILTER (WHERE artist_image IS NOT NULL) AS artist_image,
    max(artist_profile_image) FILTER (WHERE artist_profile_image IS NOT NULL) AS artist_profile_image,
    max(label) FILTER (WHERE label IS NOT NULL) AS label,
    max(label_url) FILTER (WHERE label_url IS NOT NULL) AS label_url,
    count(*)::int AS appearances,
    count(*) FILTER (WHERE confidence = 'HIGH')::int AS high_count,
    count(*) FILTER (WHERE confidence = 'MEDIUM')::int AS medium_count,
    count(*) FILTER (WHERE confidence = 'LOW')::int AS low_count,
    count(*) FILTER (WHERE confidence = 'UNCERTAIN')::int AS uncertain_count,
    jsonb_agg(
      jsonb_build_object(
        'confidence', confidence,
        'setSlug', set_slug,
        'title', set_title,
        'trackPosition', track_position
      )
      ORDER BY set_title, track_position
    ) AS set_refs
  FROM base_entries
  GROUP BY
    artist_id,
    artist_slug,
    artist_name,
    track_key
),
genre_groups AS (
  SELECT
    artist_id,
    track_key,
    COALESCE(array_agg(DISTINCT genre ORDER BY genre), '{}'::text[]) AS genres
  FROM (
    SELECT artist_id, track_key, unnest(row_genres) AS genre
    FROM base_entries
  ) genres
  GROUP BY artist_id, track_key
)
SELECT
  eg.artist_id,
  eg.artist_slug,
  eg.artist_name,
  eg.track_key,
  eg.track_artist,
  eg.track_title,
  eg.spotify_url,
  eg.album_art,
  eg.artist_image,
  eg.artist_profile_image,
  eg.label,
  eg.label_url,
  COALESCE(gg.genres, '{}'::text[]) AS genres,
  eg.appearances,
  jsonb_build_object(
    'HIGH', eg.high_count,
    'MEDIUM', eg.medium_count,
    'LOW', eg.low_count,
    'UNCERTAIN', eg.uncertain_count
  ) AS confidence_counts,
  CASE
    WHEN eg.high_count >= eg.medium_count
      AND eg.high_count >= eg.low_count
      AND eg.high_count >= eg.uncertain_count
      THEN 'HIGH'
    WHEN eg.medium_count >= eg.low_count
      AND eg.medium_count >= eg.uncertain_count
      THEN 'MEDIUM'
    WHEN eg.low_count >= eg.uncertain_count
      THEN 'LOW'
    ELSE 'UNCERTAIN'
  END AS primary_confidence,
  eg.set_refs,
  lower(
    regexp_replace(
      trim(
        concat_ws(
          ' ',
          eg.artist_name,
          eg.track_artist,
          eg.track_title,
          COALESCE(eg.label, ''),
          array_to_string(COALESCE(gg.genres, '{}'::text[]), ' ')
        )
      ),
      '\s+',
      ' ',
      'g'
    )
  ) AS search_blob
FROM entry_groups eg
LEFT JOIN genre_groups gg
  ON gg.artist_id = eg.artist_id
 AND gg.track_key = eg.track_key
WITH NO DATA;
--> statement-breakpoint
CREATE UNIQUE INDEX "archive_home_artist_atlas_mv_artist_slug_track_key_idx"
  ON "app"."archive_home_artist_atlas_mv" ("artist_slug", "track_key");
--> statement-breakpoint
CREATE INDEX "archive_home_artist_atlas_mv_artist_slug_idx"
  ON "app"."archive_home_artist_atlas_mv" ("artist_slug");
--> statement-breakpoint
-- Recreate archive_home_pair_summaries_mv (legacy_path removed from artist_directory and all CTEs)
CREATE MATERIALIZED VIEW "app"."archive_home_pair_summaries_mv" AS
WITH artist_directory AS (
  SELECT DISTINCT
    artist_id,
    artist_slug,
    artist_name
  FROM "app"."archive_home_artist_atlas_mv"
),
artist_pairs AS (
  SELECT
    left_artist.artist_id AS artist_a_id,
    left_artist.artist_slug AS artist_a_slug,
    left_artist.artist_name AS artist_a_name,
    right_artist.artist_id AS artist_b_id,
    right_artist.artist_slug AS artist_b_slug,
    right_artist.artist_name AS artist_b_name
  FROM artist_directory left_artist
  INNER JOIN artist_directory right_artist
    ON left_artist.artist_slug < right_artist.artist_slug
),
pair_tracks AS (
  SELECT
    a.artist_id AS artist_a_id,
    a.artist_slug AS artist_a_slug,
    a.artist_name AS artist_a_name,
    b.artist_id AS artist_b_id,
    b.artist_slug AS artist_b_slug,
    b.artist_name AS artist_b_name,
    a.track_key,
    COALESCE(a.track_artist, b.track_artist) AS track_artist,
    COALESCE(a.track_title, b.track_title) AS track_title,
    COALESCE(a.spotify_url, b.spotify_url) AS spotify_url,
    COALESCE(a.album_art, b.album_art) AS album_art,
    COALESCE(a.artist_image, b.artist_image) AS artist_image,
    COALESCE(a.artist_profile_image, b.artist_profile_image) AS artist_profile_image,
    COALESCE(a.label, b.label) AS label,
    COALESCE(a.label_url, b.label_url) AS label_url,
    a.appearances AS appearances_a,
    b.appearances AS appearances_b,
    a.set_refs AS sets_a,
    b.set_refs AS sets_b,
    COALESCE(a.confidence_counts ->> 'HIGH', '0')::int
      + COALESCE(b.confidence_counts ->> 'HIGH', '0')::int AS high_count,
    COALESCE(a.confidence_counts ->> 'MEDIUM', '0')::int
      + COALESCE(b.confidence_counts ->> 'MEDIUM', '0')::int AS medium_count,
    COALESCE(a.confidence_counts ->> 'LOW', '0')::int
      + COALESCE(b.confidence_counts ->> 'LOW', '0')::int AS low_count,
    COALESCE(a.confidence_counts ->> 'UNCERTAIN', '0')::int
      + COALESCE(b.confidence_counts ->> 'UNCERTAIN', '0')::int AS uncertain_count,
    ARRAY(
      SELECT DISTINCT genre
      FROM unnest(COALESCE(a.genres, '{}'::text[]) || COALESCE(b.genres, '{}'::text[])) AS genre
      WHERE genre IS NOT NULL AND genre <> ''
      ORDER BY genre
    ) AS genres
  FROM "app"."archive_home_artist_atlas_mv" a
  INNER JOIN "app"."archive_home_artist_atlas_mv" b
    ON a.track_key = b.track_key
   AND a.artist_slug < b.artist_slug
),
shared_tracks_agg AS (
  SELECT
    artist_a_slug,
    artist_b_slug,
    count(*)::int AS shared_tracks_count,
    COALESCE(
      jsonb_agg(
        jsonb_build_object(
          'albumArt', album_art,
          'appearancesA', appearances_a,
          'appearancesB', appearances_b,
          'artist', track_artist,
          'artistImage', artist_image,
          'artistProfileImage', artist_profile_image,
          'confidence', CASE
            WHEN high_count >= medium_count
              AND high_count >= low_count
              AND high_count >= uncertain_count
              THEN 'HIGH'
            WHEN medium_count >= low_count
              AND medium_count >= uncertain_count
              THEN 'MEDIUM'
            WHEN low_count >= uncertain_count
              THEN 'LOW'
            ELSE 'UNCERTAIN'
          END,
          'confidenceCounts', jsonb_build_object(
            'HIGH', high_count,
            'MEDIUM', medium_count,
            'LOW', low_count,
            'UNCERTAIN', uncertain_count
          ),
          'genres', to_jsonb(genres),
          'label', label,
          'labelUrl', label_url,
          'setsA', sets_a,
          'setsB', sets_b,
          'spotifyUrl', spotify_url,
          'title', track_title,
          'trackKey', track_key
        )
        ORDER BY (appearances_a + appearances_b) DESC, track_artist, track_title
      ),
      '[]'::jsonb
    ) AS shared_tracks
  FROM pair_tracks
  GROUP BY artist_a_slug, artist_b_slug
),
artist_label_counts AS (
  SELECT
    artist_slug,
    label,
    count(*)::int AS label_count
  FROM "app"."archive_home_artist_atlas_mv"
  WHERE label IS NOT NULL AND label <> ''
  GROUP BY artist_slug, label
),
artist_music_counts AS (
  SELECT
    artist_slug,
    track_artist,
    count(*)::int AS track_artist_count
  FROM "app"."archive_home_artist_atlas_mv"
  WHERE track_artist IS NOT NULL
    AND track_artist <> ''
    AND lower(track_artist) <> 'unknown'
  GROUP BY artist_slug, track_artist
),
artist_genre_counts AS (
  SELECT
    artist_slug,
    genre,
    count(*)::int AS genre_count
  FROM "app"."archive_home_artist_atlas_mv",
  LATERAL unnest(COALESCE(genres, '{}'::text[])) AS genre
  WHERE genre IS NOT NULL AND genre <> ''
  GROUP BY artist_slug, genre
),
shared_label_keys AS (
  SELECT
    artist_a_slug,
    artist_b_slug,
    label
  FROM pair_tracks
  WHERE label IS NOT NULL AND label <> ''
  GROUP BY artist_a_slug, artist_b_slug, label
),
shared_music_keys AS (
  SELECT
    artist_a_slug,
    artist_b_slug,
    track_artist AS music_artist
  FROM pair_tracks
  WHERE track_artist IS NOT NULL
    AND track_artist <> ''
    AND lower(track_artist) <> 'unknown'
  GROUP BY artist_a_slug, artist_b_slug, track_artist
),
shared_genre_keys AS (
  SELECT
    artist_a_slug,
    artist_b_slug,
    genre
  FROM pair_tracks,
  LATERAL unnest(COALESCE(genres, '{}'::text[])) AS genre
  WHERE genre IS NOT NULL AND genre <> ''
  GROUP BY artist_a_slug, artist_b_slug, genre
),
shared_labels_agg AS (
  SELECT
    sl.artist_a_slug,
    sl.artist_b_slug,
    count(*)::int AS shared_labels_count,
    COALESCE(
      jsonb_agg(
        jsonb_build_object(
          'countA', alc_a.label_count,
          'countB', alc_b.label_count,
          'id', sl.label,
          'name', sl.label,
          'trackKeys', COALESCE(label_tracks.track_keys, '[]'::jsonb)
        )
        ORDER BY (alc_a.label_count + alc_b.label_count) DESC, sl.label
      ),
      '[]'::jsonb
    ) AS shared_labels
  FROM shared_label_keys sl
  INNER JOIN artist_label_counts alc_a
    ON alc_a.artist_slug = sl.artist_a_slug
   AND alc_a.label = sl.label
  INNER JOIN artist_label_counts alc_b
    ON alc_b.artist_slug = sl.artist_b_slug
   AND alc_b.label = sl.label
  LEFT JOIN LATERAL (
    SELECT jsonb_agg(track_key ORDER BY track_key) AS track_keys
    FROM pair_tracks pt
    WHERE pt.artist_a_slug = sl.artist_a_slug
      AND pt.artist_b_slug = sl.artist_b_slug
      AND pt.label = sl.label
  ) label_tracks ON TRUE
  GROUP BY sl.artist_a_slug, sl.artist_b_slug
),
shared_music_agg AS (
  SELECT
    sm.artist_a_slug,
    sm.artist_b_slug,
    count(*)::int AS shared_music_artists_count,
    COALESCE(
      jsonb_agg(
        jsonb_build_object(
          'countA', amc_a.track_artist_count,
          'countB', amc_b.track_artist_count,
          'id', sm.music_artist,
          'name', sm.music_artist,
          'trackKeys', COALESCE(music_tracks.track_keys, '[]'::jsonb)
        )
        ORDER BY (amc_a.track_artist_count + amc_b.track_artist_count) DESC, sm.music_artist
      ),
      '[]'::jsonb
    ) AS shared_music_artists
  FROM shared_music_keys sm
  INNER JOIN artist_music_counts amc_a
    ON amc_a.artist_slug = sm.artist_a_slug
   AND amc_a.track_artist = sm.music_artist
  INNER JOIN artist_music_counts amc_b
    ON amc_b.artist_slug = sm.artist_b_slug
   AND amc_b.track_artist = sm.music_artist
  LEFT JOIN LATERAL (
    SELECT jsonb_agg(track_key ORDER BY track_key) AS track_keys
    FROM pair_tracks pt
    WHERE pt.artist_a_slug = sm.artist_a_slug
      AND pt.artist_b_slug = sm.artist_b_slug
      AND pt.track_artist = sm.music_artist
  ) music_tracks ON TRUE
  GROUP BY sm.artist_a_slug, sm.artist_b_slug
),
shared_genres_agg AS (
  SELECT
    sg.artist_a_slug,
    sg.artist_b_slug,
    count(*)::int AS shared_genres_count,
    COALESCE(
      jsonb_agg(
        jsonb_build_object(
          'countA', agc_a.genre_count,
          'countB', agc_b.genre_count,
          'id', sg.genre,
          'name', sg.genre,
          'trackKeys', COALESCE(genre_tracks.track_keys, '[]'::jsonb)
        )
        ORDER BY (agc_a.genre_count + agc_b.genre_count) DESC, sg.genre
      ),
      '[]'::jsonb
    ) AS shared_genres
  FROM shared_genre_keys sg
  INNER JOIN artist_genre_counts agc_a
    ON agc_a.artist_slug = sg.artist_a_slug
   AND agc_a.genre = sg.genre
  INNER JOIN artist_genre_counts agc_b
    ON agc_b.artist_slug = sg.artist_b_slug
   AND agc_b.genre = sg.genre
  LEFT JOIN LATERAL (
    SELECT jsonb_agg(track_key ORDER BY track_key) AS track_keys
    FROM pair_tracks pt
    WHERE pt.artist_a_slug = sg.artist_a_slug
      AND pt.artist_b_slug = sg.artist_b_slug
      AND pt.genres @> ARRAY[sg.genre]::text[]
  ) genre_tracks ON TRUE
  GROUP BY sg.artist_a_slug, sg.artist_b_slug
),
pair_scores AS (
  SELECT
    ap.artist_a_id,
    ap.artist_a_slug,
    ap.artist_a_name,
    ap.artist_b_id,
    ap.artist_b_slug,
    ap.artist_b_name,
    COALESCE(st.shared_tracks_count, 0) AS shared_tracks_count,
    COALESCE(sl.shared_labels_count, 0) AS shared_labels_count,
    COALESCE(sg.shared_genres_count, 0) AS shared_genres_count,
    COALESCE(sm.shared_music_artists_count, 0) AS shared_music_artists_count,
    COALESCE(st.shared_tracks, '[]'::jsonb) AS shared_tracks,
    COALESCE(sl.shared_labels, '[]'::jsonb) AS shared_labels,
    COALESCE(sg.shared_genres, '[]'::jsonb) AS shared_genres,
    COALESCE(sm.shared_music_artists, '[]'::jsonb) AS shared_music_artists,
    (COALESCE(st.shared_tracks_count, 0) * 3)
      + COALESCE(sl.shared_labels_count, 0)
      + COALESCE(sm.shared_music_artists_count, 0) AS score
  FROM artist_pairs ap
  LEFT JOIN shared_tracks_agg st
    ON st.artist_a_slug = ap.artist_a_slug
   AND st.artist_b_slug = ap.artist_b_slug
  LEFT JOIN shared_labels_agg sl
    ON sl.artist_a_slug = ap.artist_a_slug
   AND sl.artist_b_slug = ap.artist_b_slug
  LEFT JOIN shared_genres_agg sg
    ON sg.artist_a_slug = ap.artist_a_slug
   AND sg.artist_b_slug = ap.artist_b_slug
  LEFT JOIN shared_music_agg sm
    ON sm.artist_a_slug = ap.artist_a_slug
   AND sm.artist_b_slug = ap.artist_b_slug
)
SELECT
  artist_a_id,
  artist_a_slug,
  artist_a_name,
  artist_b_id,
  artist_b_slug,
  artist_b_name,
  score,
  CASE
    WHEN max(score) OVER () > 0
      THEN round((score::numeric / max(score) OVER ()) * 100)::int
    ELSE 0
  END AS normalized_score,
  shared_tracks_count,
  shared_labels_count,
  shared_genres_count,
  shared_music_artists_count,
  shared_tracks,
  shared_labels,
  shared_genres,
  shared_music_artists,
  lower(
    regexp_replace(
      trim(concat_ws(' ', artist_a_name, artist_b_name)),
      '\s+',
      ' ',
      'g'
    )
  ) AS search_blob
FROM pair_scores
WITH NO DATA;
--> statement-breakpoint
CREATE UNIQUE INDEX "archive_home_pair_summaries_mv_artist_pair_idx"
  ON "app"."archive_home_pair_summaries_mv" ("artist_a_slug", "artist_b_slug");
--> statement-breakpoint
CREATE INDEX "archive_home_pair_summaries_mv_normalized_score_idx"
  ON "app"."archive_home_pair_summaries_mv" ("normalized_score");
--> statement-breakpoint
-- Recreate archive_home_set_library_index_mv (legacy_path removed, WHERE removed)
-- Repair archive_home_set_library_index_mv so YouTube watch URLs always
-- synthesize a thumbnail, even when no image was persisted at publish time.
DROP MATERIALIZED VIEW IF EXISTS "app"."archive_home_set_library_index_mv";
--> statement-breakpoint
CREATE MATERIALIZED VIEW "app"."archive_home_set_library_index_mv" AS
WITH primary_artist AS (
  SELECT DISTINCT ON (sa.set_id)
    sa.set_id,
    a.slug AS artist_slug,
    a.name AS artist_name
  FROM "app"."public_set_artists" sa
  INNER JOIN "app"."public_artists" a
    ON a.id = sa.artist_id
  WHERE sa.role = 'primary'
  ORDER BY sa.set_id, a.name
)
SELECT
  s.id AS set_id,
  s.slug AS set_slug,
  s.title AS set_title,
  pa.artist_slug,
  pa.artist_name,
  COALESCE(
    NULLIF(s.metadata -> 'mixInfo' ->> 'thumbnail_url', ''),
    NULLIF(s.metadata -> 'mixInfo' ->> 'thumbnail', ''),
    NULLIF(s.metadata -> 'mixInfo' ->> 'image_url', ''),
    NULLIF(s.metadata -> 'mixInfo' ->> 'image', ''),
    NULLIF(s.metadata -> 'mixInfo' ->> 'artwork_url', ''),
    NULLIF(s.metadata -> 'mixInfo' ->> 'artwork', ''),
    NULLIF(s.metadata -> 'mixInfo' ->> 'cover_image', ''),
    NULLIF(s.metadata -> 'mixInfo' ->> 'coverUrl', ''),
    NULLIF(s.metadata -> 'mixInfo' ->> 'poster_url', ''),
    s.image_url,
    CASE
      WHEN lower(COALESCE(s.source_platform, '')) IN ('youtube', 'youtu') THEN
        CASE
          WHEN position('youtu.be/' IN lower(COALESCE(s.source_url, ''))) > 0 THEN
            'https://img.youtube.com/vi/' || substring(s.source_url FROM 'youtu\.be/([^?&/]+)') || '/hqdefault.jpg'
          WHEN position('youtube.com' IN lower(COALESCE(s.source_url, ''))) > 0 THEN
            'https://img.youtube.com/vi/' || substring(s.source_url FROM '[?&]v=([^?&/]+)') || '/hqdefault.jpg'
          ELSE NULL
        END
      ELSE NULL
    END
  ) AS thumbnail_url,
  COALESCE(s.duration_seconds, 0) AS duration_seconds,
  COALESCE(
    s.recognition_rate::double precision,
    CASE
      WHEN count(se.id) > 0
        THEN (count(*) FILTER (WHERE se.display_title <> 'Unknown Track'))::double precision
          / count(se.id)::double precision
          * 100
      ELSE NULL
    END
  ) AS recognition_rate,
  count(se.id)::int AS total_tracks,
  jsonb_build_object(
    'HIGH', count(*) FILTER (WHERE upper(COALESCE(se.confidence, 'UNCERTAIN')) = 'HIGH'),
    'MEDIUM', count(*) FILTER (WHERE upper(COALESCE(se.confidence, 'UNCERTAIN')) = 'MEDIUM'),
    'LOW', count(*) FILTER (WHERE upper(COALESCE(se.confidence, 'UNCERTAIN')) = 'LOW'),
    'UNCERTAIN', count(*) FILTER (WHERE upper(COALESCE(se.confidence, 'UNCERTAIN')) = 'UNCERTAIN')
  ) AS confidence_counts,
  CASE
    WHEN COALESCE(s.duration_seconds, 0) > 0 THEN
      COALESCE(
        jsonb_agg(
          jsonb_build_object(
            'confidence', upper(COALESCE(se.confidence, 'UNCERTAIN')),
            'startPct', greatest(
              0,
              least(
                100,
                (COALESCE(se.start_time_seconds, 0)::double precision / s.duration_seconds::double precision) * 100
              )
            ),
            'widthPct', greatest(
              1,
              least(
                100,
                (
                  (COALESCE(se.end_time_seconds, s.duration_seconds) - COALESCE(se.start_time_seconds, 0))::double precision
                  / s.duration_seconds::double precision
                ) * 100
              )
            )
          )
          ORDER BY se.start_time_seconds
        ) FILTER (WHERE se.display_title <> 'Unknown Track'),
        '[]'::jsonb
      )
    ELSE '[]'::jsonb
  END AS mini_timeline,
  s.source_url,
  s.source_platform,
  lower(
    COALESCE(
      string_agg(
        CASE WHEN se.display_title <> 'Unknown Track'
          THEN se.display_artist || ' ' || se.display_title
          ELSE NULL
        END,
        ' '
        ORDER BY se.position
      ),
      ''
    )
  ) AS track_search_text,
  lower(COALESCE(pa.artist_name, '')) AS sort_artist_name,
  COALESCE(s.duration_seconds, 0) AS sort_duration_seconds,
  COALESCE(
    s.recognition_rate::double precision,
    CASE
      WHEN count(se.id) > 0
        THEN (count(*) FILTER (WHERE se.display_title <> 'Unknown Track'))::double precision
          / count(se.id)::double precision
          * 100
      ELSE 0
    END
  ) AS sort_recognition_rate,
  count(se.id)::int AS sort_total_tracks
FROM "app"."public_sets" s
LEFT JOIN primary_artist pa
  ON pa.set_id = s.id
LEFT JOIN "app"."public_set_entries" se
  ON se.set_id = s.id
GROUP BY
  s.id,
  s.slug,
  s.title,
  pa.artist_slug,
  pa.artist_name,
  s.metadata,
  s.image_url,
  s.duration_seconds,
  s.recognition_rate,
  s.source_url,
  s.source_platform
WITH NO DATA;
--> statement-breakpoint
CREATE UNIQUE INDEX "archive_home_set_library_index_mv_set_slug_idx"
  ON "app"."archive_home_set_library_index_mv" ("set_slug");
--> statement-breakpoint
CREATE INDEX "archive_home_set_library_index_mv_artist_slug_idx"
  ON "app"."archive_home_set_library_index_mv" ("artist_slug");
--> statement-breakpoint
CREATE INDEX "archive_home_set_library_index_mv_sort_artist_name_idx"
  ON "app"."archive_home_set_library_index_mv" ("sort_artist_name", "set_slug");
--> statement-breakpoint
CREATE INDEX "archive_home_set_library_index_mv_sort_duration_idx"
  ON "app"."archive_home_set_library_index_mv" ("sort_duration_seconds" DESC, "set_slug");
--> statement-breakpoint
CREATE INDEX "archive_home_set_library_index_mv_sort_recognition_idx"
  ON "app"."archive_home_set_library_index_mv" ("sort_recognition_rate" DESC, "set_slug");
--> statement-breakpoint
CREATE INDEX "archive_home_set_library_index_mv_sort_total_tracks_idx"
  ON "app"."archive_home_set_library_index_mv" ("sort_total_tracks" DESC, "set_slug");
--> statement-breakpoint
REFRESH MATERIALIZED VIEW "app"."archive_home_set_library_index_mv";
--> statement-breakpoint
REFRESH MATERIALIZED VIEW "app"."archive_home_artist_atlas_mv";
--> statement-breakpoint
REFRESH MATERIALIZED VIEW "app"."archive_home_pair_summaries_mv";
--> statement-breakpoint
CREATE OR REPLACE FUNCTION "ops"."claim_next_artist_submission"()
RETURNS SETOF "ops"."submissions"
LANGUAGE sql
AS $$
  WITH candidate AS (
    SELECT id
    FROM ops.submissions
    WHERE visibility = 'public' AND mode = 'artist'
      AND status = 'queued'
      AND cancel_requested_at IS NULL
    ORDER BY created_at ASC, id ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
  ),
  updated AS (
    UPDATE ops.submissions submission
    SET status = 'running',
        updated_at = now()
    WHERE submission.id IN (SELECT id FROM candidate)
    RETURNING submission.*
  )
  SELECT * FROM updated;
$$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION "ops"."claim_next_dispatchable_set_run"("max_active" integer DEFAULT 10)
RETURNS SETOF "ops"."set_runs"
LANGUAGE plpgsql
AS $$
DECLARE
  available_slots integer;
BEGIN
  -- Serialize the active-count + claim decision so concurrent finalize/dispatch
  -- requests cannot overfill the global process-set window.
  PERFORM pg_advisory_xact_lock(
    hashtext('ops.set_runs'),
    hashtext('claim_next_dispatchable_set_run')
  );

  SELECT GREATEST(COALESCE(max_active, 10), 0) - count(*)::integer
  INTO available_slots
  FROM ops.set_runs
  WHERE publication_visibility = 'public' AND status IN (
    'dispatched',
    'resolving',
    'recognizing',
    'aggregating',
    'enriching',
    'publishing',
    'cancelling'
  );

  available_slots := GREATEST(COALESCE(available_slots, 0), 0);

  IF available_slots <= 0 THEN
    RETURN;
  END IF;

  RETURN QUERY
  WITH candidate AS (
    SELECT id
    FROM ops.set_runs
    WHERE publication_visibility = 'public' AND status = 'queued'
      AND cancel_requested_at IS NULL
    ORDER BY created_at ASC, id ASC
    LIMIT available_slots
    FOR UPDATE SKIP LOCKED
  ),
  updated AS (
    UPDATE ops.set_runs set_run
    SET status = 'dispatched',
        stage = 'dispatching',
        heartbeat_at = now(),
        updated_at = now()
    WHERE set_run.id IN (SELECT id FROM candidate)
    RETURNING set_run.*
  )
  SELECT *
  FROM updated
  ORDER BY created_at ASC, id ASC;
END;
$$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION "ops"."claim_next_lease"(
  "p_set_run_id" uuid,
  "p_slot_index" integer,
  "p_worker_name" text
)
RETURNS SETOF "ops"."set_run_leases"
LANGUAGE sql
AS $$
  WITH candidate AS (
    SELECT id
    FROM ops.set_run_leases
    WHERE set_run_id = p_set_run_id
      AND EXISTS (SELECT 1 FROM ops.set_runs r WHERE r.id = p_set_run_id AND r.publication_visibility = 'public')
      AND status = 'pending'
    ORDER BY segment_start_index ASC, id ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
  ),
  updated AS (
    UPDATE ops.set_run_leases lease
    SET status = 'claimed',
        claimed_by = p_worker_name,
        claimed_at = now(),
        updated_at = now()
    WHERE lease.id IN (SELECT id FROM candidate)
    RETURNING lease.*
  )
  SELECT * FROM updated;
$$;
--> statement-breakpoint
-- Treat the dispatched item's security scope as immutable. A worker may replace
-- recognition evidence, never choose/change its audience or publishing target.
CREATE FUNCTION app.prevent_archive_scope_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF ROW(NEW.visibility, NEW.collection_id) IS DISTINCT FROM ROW(OLD.visibility, OLD.collection_id) THEN
    RAISE EXCEPTION 'Archive security scope is immutable';
  END IF;
  RETURN NEW;
END;
$$;
--> statement-breakpoint
CREATE TRIGGER sets_scope_immutable BEFORE UPDATE ON app.sets
FOR EACH ROW EXECUTE FUNCTION app.prevent_archive_scope_change();
--> statement-breakpoint
CREATE TRIGGER submissions_scope_immutable BEFORE UPDATE ON ops.submissions
FOR EACH ROW EXECUTE FUNCTION app.prevent_archive_scope_change();
--> statement-breakpoint
CREATE FUNCTION ops.validate_set_run_scope() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent_scope record; target_scope record;
BEGIN
  IF TG_OP = 'UPDATE' AND ROW(NEW.publication_visibility, NEW.target_set_id, NEW.collection_id, NEW.submission_id, NEW.requested_by)
    IS DISTINCT FROM ROW(OLD.publication_visibility, OLD.target_set_id, OLD.collection_id, OLD.submission_id, OLD.requested_by) THEN
    RAISE EXCEPTION 'Set run security scope is immutable';
  END IF;
  SELECT visibility, collection_id INTO parent_scope FROM ops.submissions WHERE id = NEW.submission_id;
  IF NOT FOUND OR parent_scope.visibility IS DISTINCT FROM NEW.publication_visibility
    OR parent_scope.collection_id IS DISTINCT FROM NEW.collection_id THEN
    RAISE EXCEPTION 'Set run submission scope does not match';
  END IF;
  IF NEW.publication_visibility = 'private' THEN
    SELECT visibility, collection_id INTO target_scope FROM app.sets WHERE id = NEW.target_set_id;
    IF NOT FOUND OR target_scope.visibility <> 'private' OR target_scope.collection_id IS DISTINCT FROM NEW.collection_id
      OR (NEW.published_set_id IS NOT NULL AND NEW.published_set_id IS DISTINCT FROM NEW.target_set_id) THEN
      RAISE EXCEPTION 'Private set run target does not match';
    END IF;
  ELSIF NEW.published_set_id IS NOT NULL THEN
    SELECT visibility INTO target_scope FROM app.sets WHERE id = NEW.published_set_id;
    IF NOT FOUND OR target_scope.visibility <> 'public' THEN
      RAISE EXCEPTION 'Public set run cannot reference a private item';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
--> statement-breakpoint
CREATE TRIGGER set_runs_scope_guard BEFORE INSERT OR UPDATE ON ops.set_runs
FOR EACH ROW EXECUTE FUNCTION ops.validate_set_run_scope();
