CREATE TABLE "ops"."archive_deletions" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "entity_type" text NOT NULL,
  "entity_id" uuid,
  "slug" text NOT NULL,
  "title" text NOT NULL,
  "action" text NOT NULL,
  "actor_role" text NOT NULL,
  "requested_by" text,
  "requested_by_email" text,
  "reason" text,
  "affected_set_ids" jsonb DEFAULT '[]'::jsonb NOT NULL,
  "affected_artist_slugs" jsonb DEFAULT '[]'::jsonb NOT NULL,
  "row_counts" jsonb DEFAULT '{}'::jsonb NOT NULL,
  "metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
  "created_at" timestamp with time zone DEFAULT now() NOT NULL
);--> statement-breakpoint

ALTER TABLE "ops"."archive_deletions"
  ADD CONSTRAINT "archive_deletions_requested_by_users_id_fk"
  FOREIGN KEY ("requested_by") REFERENCES "authn"."users"("id")
  ON DELETE set null ON UPDATE no action;--> statement-breakpoint

ALTER TABLE "ops"."set_runs"
  ADD COLUMN "archive_removed_at" timestamp with time zone;--> statement-breakpoint

ALTER TABLE "ops"."set_runs"
  ADD COLUMN "archive_removal_id" uuid;--> statement-breakpoint

ALTER TABLE "ops"."set_runs"
  ADD CONSTRAINT "set_runs_archive_removal_id_archive_deletions_id_fk"
  FOREIGN KEY ("archive_removal_id") REFERENCES "ops"."archive_deletions"("id")
  ON DELETE set null ON UPDATE no action;--> statement-breakpoint

CREATE INDEX "archive_deletions_created_at_idx"
  ON "ops"."archive_deletions" ("created_at");--> statement-breakpoint

CREATE INDEX "archive_deletions_entity_idx"
  ON "ops"."archive_deletions" ("entity_type", "slug");--> statement-breakpoint

CREATE INDEX "archive_deletions_requested_by_idx"
  ON "ops"."archive_deletions" ("requested_by");--> statement-breakpoint

CREATE INDEX "set_runs_archive_removed_at_idx"
  ON "ops"."set_runs" ("archive_removed_at");--> statement-breakpoint

CREATE INDEX "set_runs_published_set_id_idx"
  ON "ops"."set_runs" ("published_set_id");--> statement-breakpoint

CREATE INDEX "set_runs_requested_by_idx"
  ON "ops"."set_runs" ("requested_by");--> statement-breakpoint

CREATE INDEX "set_runs_source_url_idx"
  ON "ops"."set_runs" ("source_url");
