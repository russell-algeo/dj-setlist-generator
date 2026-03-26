CREATE EXTENSION IF NOT EXISTS pgcrypto;
--> statement-breakpoint
CREATE SCHEMA "app";
--> statement-breakpoint
CREATE SCHEMA "authn";
--> statement-breakpoint
CREATE SCHEMA "ops";
--> statement-breakpoint
CREATE TABLE "authn"."accounts" (
	"user_id" text NOT NULL,
	"type" text NOT NULL,
	"provider" text NOT NULL,
	"provider_account_id" text NOT NULL,
	"refresh_token" text,
	"access_token" text,
	"expires_at" integer,
	"token_type" text,
	"scope" text,
	"id_token" text,
	"session_state" text,
	CONSTRAINT "accounts_provider_provider_account_id_pk" PRIMARY KEY("provider","provider_account_id")
);
--> statement-breakpoint
CREATE TABLE "authn"."api_tokens" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" text NOT NULL,
	"name" text NOT NULL,
	"token_prefix" text NOT NULL,
	"token_hash" text NOT NULL,
	"last_used_at" timestamp with time zone,
	"revoked_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "app"."artists" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"slug" text NOT NULL,
	"name" text NOT NULL,
	"normalized_name" text NOT NULL,
	"image_url" text,
	"spotify_artist_url" text,
	"discogs_artist_url" text,
	"legacy_path" text,
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "ops"."discovery_candidates" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"submission_id" uuid NOT NULL,
	"source_url" text NOT NULL,
	"source_platform" text,
	"source_title" text,
	"duration_seconds" integer,
	"status" text NOT NULL,
	"rejection_reason" text,
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "ops"."segment_hits" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"set_run_id" uuid NOT NULL,
	"lease_id" uuid,
	"segment_index" integer NOT NULL,
	"timestamp_seconds" numeric(10, 2) NOT NULL,
	"track_title" text,
	"artist" text,
	"shazam_track_id" text,
	"recognized" boolean DEFAULT false NOT NULL,
	"raw_data" jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "authn"."sessions" (
	"session_token" text PRIMARY KEY NOT NULL,
	"user_id" text NOT NULL,
	"expires" timestamp with time zone NOT NULL
);
--> statement-breakpoint
CREATE TABLE "app"."set_artists" (
	"set_id" uuid NOT NULL,
	"artist_id" uuid NOT NULL,
	"role" text DEFAULT 'primary' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "set_artists_set_id_artist_id_role_pk" PRIMARY KEY("set_id","artist_id","role")
);
--> statement-breakpoint
CREATE TABLE "app"."set_entries" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"set_id" uuid NOT NULL,
	"track_id" uuid,
	"position" integer NOT NULL,
	"display_artist" text NOT NULL,
	"display_title" text NOT NULL,
	"start_time_seconds" integer NOT NULL,
	"end_time_seconds" integer,
	"confidence" text NOT NULL,
	"detection_count" integer DEFAULT 0 NOT NULL,
	"cluster_density" numeric(6, 4),
	"cluster_span" integer,
	"source_deep_link" text,
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "ops"."set_run_leases" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"set_run_id" uuid NOT NULL,
	"slot_index" integer DEFAULT 0 NOT NULL,
	"segment_start_index" integer NOT NULL,
	"segment_end_index" integer NOT NULL,
	"status" text NOT NULL,
	"claimed_by" text,
	"claimed_at" timestamp with time zone,
	"completed_at" timestamp with time zone,
	"error_text" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "ops"."set_runs" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"submission_id" uuid NOT NULL,
	"requested_by" text NOT NULL,
	"status" text NOT NULL,
	"stage" text,
	"attempt_count" integer DEFAULT 0 NOT NULL,
	"source_url" text NOT NULL,
	"source_platform" text,
	"set_title" text,
	"create_playlist" boolean DEFAULT false NOT NULL,
	"source_metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"heartbeat_at" timestamp with time zone,
	"published_set_id" uuid,
	"error_summary" text,
	"cancel_requested_at" timestamp with time zone,
	"completed_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "app"."sets" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"slug" text NOT NULL,
	"title" text NOT NULL,
	"normalized_title" text NOT NULL,
	"source_platform" text,
	"source_url" text,
	"source_id" text,
	"duration_seconds" integer,
	"uploader" text,
	"image_url" text,
	"recognition_rate" numeric(5, 2),
	"legacy_path" text,
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "app"."site_pages" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"path" text NOT NULL,
	"page_type" text NOT NULL,
	"artist_id" uuid,
	"set_id" uuid,
	"slug" text,
	"html" text NOT NULL,
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "authn"."spotify_connections" (
	"user_id" text PRIMARY KEY NOT NULL,
	"spotify_user_id" text NOT NULL,
	"refresh_token_ciphertext" text,
	"scopes" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"connected_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"last_refresh_at" timestamp with time zone,
	"last_error" text,
	"revoked_at" timestamp with time zone
);
--> statement-breakpoint
CREATE TABLE "ops"."submissions" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"requested_by" text NOT NULL,
	"mode" text NOT NULL,
	"status" text NOT NULL,
	"artist_name" text,
	"source_url" text,
	"source_urls" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"create_playlist" boolean DEFAULT false NOT NULL,
	"max_sets_override" integer,
	"warning_summary" text,
	"error_summary" text,
	"cancel_requested_at" timestamp with time zone,
	"completed_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "app"."track_artists" (
	"track_id" uuid NOT NULL,
	"artist_id" uuid NOT NULL,
	"role" text DEFAULT 'primary' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "track_artists_track_id_artist_id_role_pk" PRIMARY KEY("track_id","artist_id","role")
);
--> statement-breakpoint
CREATE TABLE "app"."tracks" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"slug" text NOT NULL,
	"title" text NOT NULL,
	"normalized_title" text NOT NULL,
	"primary_artist_name" text,
	"shazam_track_id" text,
	"spotify_url" text,
	"youtube_url" text,
	"discogs_url" text,
	"metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "authn"."user_profiles" (
	"user_id" text PRIMARY KEY NOT NULL,
	"email" text NOT NULL,
	"display_name" text,
	"is_allowlisted" boolean DEFAULT false NOT NULL,
	"is_admin" boolean DEFAULT false NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "authn"."users" (
	"id" text PRIMARY KEY DEFAULT gen_random_uuid()::text NOT NULL,
	"name" text,
	"email" text,
	"email_verified" timestamp with time zone,
	"image" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "users_email_unique" UNIQUE("email")
);
--> statement-breakpoint
CREATE TABLE "authn"."verification_tokens" (
	"identifier" text NOT NULL,
	"token" text NOT NULL,
	"expires" timestamp with time zone NOT NULL,
	CONSTRAINT "verification_tokens_identifier_token_pk" PRIMARY KEY("identifier","token")
);
--> statement-breakpoint
CREATE TABLE "ops"."worker_events" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"submission_id" uuid,
	"set_run_id" uuid,
	"lease_id" uuid,
	"event_type" text NOT NULL,
	"message" text NOT NULL,
	"details" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "authn"."accounts" ADD CONSTRAINT "accounts_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "authn"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "authn"."api_tokens" ADD CONSTRAINT "api_tokens_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "authn"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ops"."discovery_candidates" ADD CONSTRAINT "discovery_candidates_submission_id_submissions_id_fk" FOREIGN KEY ("submission_id") REFERENCES "ops"."submissions"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ops"."segment_hits" ADD CONSTRAINT "segment_hits_set_run_id_set_runs_id_fk" FOREIGN KEY ("set_run_id") REFERENCES "ops"."set_runs"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ops"."segment_hits" ADD CONSTRAINT "segment_hits_lease_id_set_run_leases_id_fk" FOREIGN KEY ("lease_id") REFERENCES "ops"."set_run_leases"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "authn"."sessions" ADD CONSTRAINT "sessions_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "authn"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "app"."set_artists" ADD CONSTRAINT "set_artists_set_id_sets_id_fk" FOREIGN KEY ("set_id") REFERENCES "app"."sets"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "app"."set_artists" ADD CONSTRAINT "set_artists_artist_id_artists_id_fk" FOREIGN KEY ("artist_id") REFERENCES "app"."artists"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "app"."set_entries" ADD CONSTRAINT "set_entries_set_id_sets_id_fk" FOREIGN KEY ("set_id") REFERENCES "app"."sets"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "app"."set_entries" ADD CONSTRAINT "set_entries_track_id_tracks_id_fk" FOREIGN KEY ("track_id") REFERENCES "app"."tracks"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ops"."set_run_leases" ADD CONSTRAINT "set_run_leases_set_run_id_set_runs_id_fk" FOREIGN KEY ("set_run_id") REFERENCES "ops"."set_runs"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ops"."set_runs" ADD CONSTRAINT "set_runs_submission_id_submissions_id_fk" FOREIGN KEY ("submission_id") REFERENCES "ops"."submissions"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ops"."set_runs" ADD CONSTRAINT "set_runs_requested_by_users_id_fk" FOREIGN KEY ("requested_by") REFERENCES "authn"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ops"."set_runs" ADD CONSTRAINT "set_runs_published_set_id_sets_id_fk" FOREIGN KEY ("published_set_id") REFERENCES "app"."sets"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "app"."site_pages" ADD CONSTRAINT "site_pages_artist_id_artists_id_fk" FOREIGN KEY ("artist_id") REFERENCES "app"."artists"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "app"."site_pages" ADD CONSTRAINT "site_pages_set_id_sets_id_fk" FOREIGN KEY ("set_id") REFERENCES "app"."sets"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "authn"."spotify_connections" ADD CONSTRAINT "spotify_connections_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "authn"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ops"."submissions" ADD CONSTRAINT "submissions_requested_by_users_id_fk" FOREIGN KEY ("requested_by") REFERENCES "authn"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "app"."track_artists" ADD CONSTRAINT "track_artists_track_id_tracks_id_fk" FOREIGN KEY ("track_id") REFERENCES "app"."tracks"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "app"."track_artists" ADD CONSTRAINT "track_artists_artist_id_artists_id_fk" FOREIGN KEY ("artist_id") REFERENCES "app"."artists"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "authn"."user_profiles" ADD CONSTRAINT "user_profiles_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "authn"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ops"."worker_events" ADD CONSTRAINT "worker_events_submission_id_submissions_id_fk" FOREIGN KEY ("submission_id") REFERENCES "ops"."submissions"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ops"."worker_events" ADD CONSTRAINT "worker_events_set_run_id_set_runs_id_fk" FOREIGN KEY ("set_run_id") REFERENCES "ops"."set_runs"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ops"."worker_events" ADD CONSTRAINT "worker_events_lease_id_set_run_leases_id_fk" FOREIGN KEY ("lease_id") REFERENCES "ops"."set_run_leases"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "accounts_user_id_idx" ON "authn"."accounts" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "api_tokens_user_id_idx" ON "authn"."api_tokens" USING btree ("user_id");--> statement-breakpoint
CREATE UNIQUE INDEX "artists_slug_idx" ON "app"."artists" USING btree ("slug");--> statement-breakpoint
CREATE INDEX "artists_normalized_name_idx" ON "app"."artists" USING btree ("normalized_name");--> statement-breakpoint
CREATE UNIQUE INDEX "artists_legacy_path_idx" ON "app"."artists" USING btree ("legacy_path");--> statement-breakpoint
CREATE INDEX "discovery_candidates_submission_id_idx" ON "ops"."discovery_candidates" USING btree ("submission_id");--> statement-breakpoint
CREATE UNIQUE INDEX "segment_hits_run_segment_idx" ON "ops"."segment_hits" USING btree ("set_run_id","segment_index");--> statement-breakpoint
CREATE INDEX "sessions_user_id_idx" ON "authn"."sessions" USING btree ("user_id");--> statement-breakpoint
CREATE UNIQUE INDEX "set_entries_set_position_idx" ON "app"."set_entries" USING btree ("set_id","position");--> statement-breakpoint
CREATE INDEX "set_entries_set_time_idx" ON "app"."set_entries" USING btree ("set_id","start_time_seconds");--> statement-breakpoint
CREATE INDEX "set_run_leases_set_run_id_idx" ON "ops"."set_run_leases" USING btree ("set_run_id");--> statement-breakpoint
CREATE INDEX "set_run_leases_status_idx" ON "ops"."set_run_leases" USING btree ("status");--> statement-breakpoint
CREATE INDEX "set_runs_submission_id_idx" ON "ops"."set_runs" USING btree ("submission_id");--> statement-breakpoint
CREATE INDEX "set_runs_status_idx" ON "ops"."set_runs" USING btree ("status");--> statement-breakpoint
CREATE UNIQUE INDEX "sets_slug_idx" ON "app"."sets" USING btree ("slug");--> statement-breakpoint
CREATE UNIQUE INDEX "sets_source_url_idx" ON "app"."sets" USING btree ("source_url");--> statement-breakpoint
CREATE UNIQUE INDEX "sets_legacy_path_idx" ON "app"."sets" USING btree ("legacy_path");--> statement-breakpoint
CREATE INDEX "sets_normalized_title_idx" ON "app"."sets" USING btree ("normalized_title");--> statement-breakpoint
CREATE UNIQUE INDEX "site_pages_path_idx" ON "app"."site_pages" USING btree ("path");--> statement-breakpoint
CREATE INDEX "site_pages_slug_idx" ON "app"."site_pages" USING btree ("slug");--> statement-breakpoint
CREATE UNIQUE INDEX "spotify_connections_spotify_user_id_idx" ON "authn"."spotify_connections" USING btree ("spotify_user_id");--> statement-breakpoint
CREATE INDEX "submissions_requested_by_idx" ON "ops"."submissions" USING btree ("requested_by");--> statement-breakpoint
CREATE INDEX "submissions_status_idx" ON "ops"."submissions" USING btree ("status");--> statement-breakpoint
CREATE UNIQUE INDEX "tracks_slug_idx" ON "app"."tracks" USING btree ("slug");--> statement-breakpoint
CREATE INDEX "tracks_normalized_title_idx" ON "app"."tracks" USING btree ("normalized_title");--> statement-breakpoint
CREATE UNIQUE INDEX "user_profiles_email_idx" ON "authn"."user_profiles" USING btree ("email");--> statement-breakpoint
CREATE INDEX "worker_events_submission_id_idx" ON "ops"."worker_events" USING btree ("submission_id");--> statement-breakpoint
CREATE INDEX "worker_events_set_run_id_idx" ON "ops"."worker_events" USING btree ("set_run_id");
--> statement-breakpoint
CREATE OR REPLACE FUNCTION "ops"."claim_next_lease"("p_set_run_id" uuid, "p_worker_name" text)
RETURNS SETOF "ops"."set_run_leases"
LANGUAGE sql
AS $$
  WITH candidate AS (
    SELECT id
    FROM ops.set_run_leases
    WHERE set_run_id = p_set_run_id
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
CREATE OR REPLACE FUNCTION "ops"."complete_lease"(
  "p_lease_id" uuid,
  "p_success" boolean,
  "p_error_text" text DEFAULT NULL
)
RETURNS void
LANGUAGE sql
AS $$
  UPDATE ops.set_run_leases
  SET status = CASE WHEN p_success THEN 'completed' ELSE 'failed' END,
      completed_at = now(),
      error_text = p_error_text,
      updated_at = now()
  WHERE id = p_lease_id;
$$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION "ops"."recover_stale_leases"("stale_before" interval)
RETURNS integer
LANGUAGE sql
AS $$
  WITH updated AS (
    UPDATE ops.set_run_leases
    SET status = 'pending',
        claimed_by = NULL,
        claimed_at = NULL,
        updated_at = now()
    WHERE status = 'claimed'
      AND claimed_at IS NOT NULL
      AND claimed_at < now() - stale_before
    RETURNING id
  )
  SELECT count(*)::integer FROM updated;
$$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION "ops"."recover_stale_set_runs"("stale_before" interval)
RETURNS integer
LANGUAGE sql
AS $$
  WITH updated AS (
    UPDATE ops.set_runs
    SET status = 'queued',
        stage = 'queued',
        updated_at = now()
    WHERE status IN ('dispatched', 'resolving', 'recognizing')
      AND COALESCE(heartbeat_at, updated_at, created_at) < now() - stale_before
    RETURNING id
  )
  SELECT count(*)::integer FROM updated;
$$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION "ops"."dispatchable_set_runs"("max_active" integer)
RETURNS SETOF "ops"."set_runs"
LANGUAGE sql
AS $$
  WITH active_count AS (
    SELECT count(*)::integer AS count
    FROM ops.set_runs
    WHERE status IN ('dispatched', 'resolving', 'recognizing', 'aggregating', 'enriching', 'publishing')
  )
  SELECT *
  FROM ops.set_runs
  WHERE status = 'queued'
    AND (SELECT count FROM active_count) < max_active
  ORDER BY created_at ASC, id ASC;
$$;
--> statement-breakpoint
CREATE OR REPLACE FUNCTION "ops"."mark_run_stage"(
  "p_set_run_id" uuid,
  "p_status" text,
  "p_stage" text,
  "p_error_summary" text DEFAULT NULL,
  "p_published_set_id" uuid DEFAULT NULL
)
RETURNS SETOF "ops"."set_runs"
LANGUAGE sql
AS $$
  UPDATE ops.set_runs
  SET status = p_status,
      stage = p_stage,
      error_summary = COALESCE(p_error_summary, error_summary),
      published_set_id = COALESCE(p_published_set_id, published_set_id),
      heartbeat_at = now(),
      completed_at = CASE
        WHEN p_status IN ('completed', 'failed', 'cancelled') THEN now()
        ELSE completed_at
      END,
      updated_at = now()
  WHERE id = p_set_run_id
  RETURNING *;
$$;
