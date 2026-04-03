-- Repair archive_home_set_library_index_mv so YouTube watch URLs always
-- synthesize a thumbnail, even when no image was persisted at publish time.
DROP MATERIALIZED VIEW IF EXISTS "app"."archive_home_set_library_index_mv";--> statement-breakpoint

CREATE MATERIALIZED VIEW "app"."archive_home_set_library_index_mv" AS
WITH primary_artist AS (
  SELECT DISTINCT ON (sa.set_id)
    sa.set_id,
    a.slug AS artist_slug,
    a.name AS artist_name
  FROM "app"."set_artists" sa
  INNER JOIN "app"."artists" a
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
FROM "app"."sets" s
LEFT JOIN primary_artist pa
  ON pa.set_id = s.id
LEFT JOIN "app"."set_entries" se
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
WITH NO DATA;--> statement-breakpoint

CREATE UNIQUE INDEX "archive_home_set_library_index_mv_set_slug_idx"
  ON "app"."archive_home_set_library_index_mv" ("set_slug");--> statement-breakpoint
CREATE INDEX "archive_home_set_library_index_mv_artist_slug_idx"
  ON "app"."archive_home_set_library_index_mv" ("artist_slug");--> statement-breakpoint
CREATE INDEX "archive_home_set_library_index_mv_sort_artist_name_idx"
  ON "app"."archive_home_set_library_index_mv" ("sort_artist_name", "set_slug");--> statement-breakpoint
CREATE INDEX "archive_home_set_library_index_mv_sort_duration_idx"
  ON "app"."archive_home_set_library_index_mv" ("sort_duration_seconds" DESC, "set_slug");--> statement-breakpoint
CREATE INDEX "archive_home_set_library_index_mv_sort_recognition_idx"
  ON "app"."archive_home_set_library_index_mv" ("sort_recognition_rate" DESC, "set_slug");--> statement-breakpoint
CREATE INDEX "archive_home_set_library_index_mv_sort_total_tracks_idx"
  ON "app"."archive_home_set_library_index_mv" ("sort_total_tracks" DESC, "set_slug");--> statement-breakpoint

REFRESH MATERIALIZED VIEW "app"."archive_home_set_library_index_mv";
