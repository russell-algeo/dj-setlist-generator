-- Seal phase: apply only after guarded web/worker code and old-reader containment
-- are verified. All ordinary producers now stamp public explicitly. Private jobs
-- must reserve an exact private collection/set/submission before dispatch.
ALTER TABLE app.sets ALTER COLUMN visibility SET DEFAULT 'private';
--> statement-breakpoint
ALTER TABLE ops.submissions ALTER COLUMN visibility SET DEFAULT 'private';
--> statement-breakpoint
ALTER TABLE ops.set_runs ALTER COLUMN publication_visibility SET DEFAULT 'private';
