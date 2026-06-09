CREATE TABLE IF NOT EXISTS "app"."user_set_listen_progress" (
  "user_id" text NOT NULL,
  "set_id" uuid NOT NULL,
  "duration_seconds" numeric(10, 2) DEFAULT 0 NOT NULL,
  "intervals" jsonb DEFAULT '[]'::jsonb NOT NULL,
  "coverage_ratio" numeric(6, 5) DEFAULT 0 NOT NULL,
  "last_position_seconds" numeric(10, 2) DEFAULT 0 NOT NULL,
  "source_url" text,
  "listened_at" timestamp with time zone,
  "created_at" timestamp with time zone DEFAULT now() NOT NULL,
  "updated_at" timestamp with time zone DEFAULT now() NOT NULL,
  CONSTRAINT "user_set_listen_progress_user_id_set_id_pk" PRIMARY KEY("user_id", "set_id")
);
--> statement-breakpoint
DO $$ BEGIN
 ALTER TABLE "app"."user_set_listen_progress" ADD CONSTRAINT "user_set_listen_progress_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "authn"."users"("id") ON DELETE cascade ON UPDATE no action;
EXCEPTION
 WHEN duplicate_object THEN null;
END $$;
--> statement-breakpoint
DO $$ BEGIN
 ALTER TABLE "app"."user_set_listen_progress" ADD CONSTRAINT "user_set_listen_progress_set_id_sets_id_fk" FOREIGN KEY ("set_id") REFERENCES "app"."sets"("id") ON DELETE cascade ON UPDATE no action;
EXCEPTION
 WHEN duplicate_object THEN null;
END $$;
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "user_set_listen_progress_set_id_idx" ON "app"."user_set_listen_progress" USING btree ("set_id");
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "user_set_listen_progress_user_updated_idx" ON "app"."user_set_listen_progress" USING btree ("user_id", "updated_at");
