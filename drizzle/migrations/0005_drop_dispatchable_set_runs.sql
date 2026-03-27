-- Remove the read-only dispatchable_set_runs(max_active) helper that was
-- superseded by claim_next_dispatchable_set_run() in migration 0001 and is
-- no longer referenced anywhere in the codebase.
--> statement-breakpoint
DROP FUNCTION IF EXISTS "ops"."dispatchable_set_runs"(integer);
