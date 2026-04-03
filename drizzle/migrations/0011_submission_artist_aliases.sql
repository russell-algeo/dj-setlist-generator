ALTER TABLE "ops"."submissions"
ADD COLUMN IF NOT EXISTS "artist_aliases" jsonb DEFAULT '[]'::jsonb NOT NULL;--> statement-breakpoint
