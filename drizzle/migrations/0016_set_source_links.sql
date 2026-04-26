CREATE TABLE IF NOT EXISTS "app"."set_source_links" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "set_id" uuid NOT NULL,
  "platform" text NOT NULL,
  "url" text NOT NULL,
  "title" text,
  "duration_seconds" integer,
  "is_primary" boolean DEFAULT false NOT NULL,
  "match_confidence" numeric(5, 4),
  "metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
  "created_at" timestamp with time zone DEFAULT now() NOT NULL,
  "updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
DO $$ BEGIN
 ALTER TABLE "app"."set_source_links" ADD CONSTRAINT "set_source_links_set_id_sets_id_fk" FOREIGN KEY ("set_id") REFERENCES "app"."sets"("id") ON DELETE cascade ON UPDATE no action;
EXCEPTION
 WHEN duplicate_object THEN null;
END $$;
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "set_source_links_set_platform_idx" ON "app"."set_source_links" USING btree ("set_id", "platform");
--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS "set_source_links_set_platform_url_idx" ON "app"."set_source_links" USING btree ("set_id", "platform", "url");
--> statement-breakpoint
INSERT INTO "app"."set_source_links" (
  "set_id",
  "platform",
  "url",
  "title",
  "duration_seconds",
  "is_primary",
  "match_confidence",
  "metadata"
)
SELECT
  "id",
  COALESCE(NULLIF("source_platform", ''), 'unknown'),
  "source_url",
  "title",
  "duration_seconds",
  true,
  1.0,
  jsonb_build_object('source', 'canonical_seed')
FROM "app"."sets"
WHERE "source_url" IS NOT NULL
ON CONFLICT ("set_id", "platform", "url") DO UPDATE SET
  "title" = EXCLUDED."title",
  "duration_seconds" = EXCLUDED."duration_seconds",
  "is_primary" = true,
  "updated_at" = now();
