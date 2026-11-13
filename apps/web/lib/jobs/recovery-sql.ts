import { sql } from "drizzle-orm";
import { retireWorkflowOwner } from "./publication";

// Keep recovery predicates in the application release. The older database
// functions predate cancellation's publication boundary and can erase it.
export const recoverStaleLeasesQuery = sql`
  with recovered as (
    update ops.set_run_leases lease
    set status = 'pending', claimed_by = null, claimed_at = null, updated_at = now()
    from ops.set_runs run
    where lease.set_run_id = run.id
      and lease.status = 'claimed' and lease.claimed_at < now() - interval '15 minutes'
      and run.publication_visibility = 'public'
      and not (coalesce(run.source_metadata, '{}'::jsonb) ? 'shared_recognition')
      and not (coalesce(run.source_metadata, '{}'::jsonb) ? 'sampling_capacity_deferral_v1')
      and run.cancel_requested_at is null
      and run.status in ('dispatched', 'resolving', 'recognizing', 'aggregating', 'enriching')
      and run.published_set_id is null
      and run.stage is distinct from 'publishing_committed'
    returning lease.id
  ) select count(*)::integer as recovered from recovered
`;

export const recoverStaleRunsQuery = sql`
  with recovered as (
    update ops.set_runs
    set status = case when cancel_requested_at is not null or status = 'cancelling'
                      then 'cancelled' else 'queued' end,
        stage = case when cancel_requested_at is not null or status = 'cancelling'
                     then 'cancelled' else 'queued' end,
        completed_at = case when cancel_requested_at is not null or status = 'cancelling'
                            then now() else null end,
        source_metadata = case when cancel_requested_at is not null or status = 'cancelling'
                               then source_metadata else ${retireWorkflowOwner()} end,
        heartbeat_at = null, updated_at = now()
    where publication_visibility = 'public'
      and not (coalesce(source_metadata, '{}'::jsonb) ? 'shared_recognition')
      and not (coalesce(source_metadata, '{}'::jsonb) ? 'sampling_capacity_deferral_v1')
      and status in ('dispatched', 'resolving', 'recognizing', 'aggregating', 'enriching', 'publishing', 'cancelling')
      and coalesce(heartbeat_at, updated_at, created_at) < now() - interval '30 minutes'
      and published_set_id is null
      and stage is distinct from 'publishing_committed'
    returning id, status
  ), cancelled_leases as (
    update ops.set_run_leases
    set status = 'cancelled', completed_at = now(), updated_at = now()
    where set_run_id in (select id from recovered where status = 'cancelled')
      and status in ('pending', 'claimed')
  ), expired_shared as (
    -- A cooldown can outlast the remaining lifetime. Do not leave that queued
    -- run permanently unclaimable, or dispatch a workflow merely to expire it.
    update ops.set_runs run
    set status = 'failed', stage = 'recognition_budget_exhausted',
        error_summary = 'Durable recognition deadline exhausted',
        completed_at = now(), updated_at = now()
    where run.publication_visibility = 'public' and run.status = 'queued'
      and run.cancel_requested_at is null and run.published_set_id is null
      and run.stage is distinct from 'publishing_committed'
      and not (coalesce(run.source_metadata, '{}'::jsonb) ? 'sampling_capacity_deferral_v1')
      and run.source_metadata->'shared_recognition'->>'version' = '1'
      and run.source_metadata->'shared_recognition'->'policy_version' is distinct from '3'::jsonb
      and run.source_metadata->'shared_recognition'->>'review_required' = 'false'
      and run.source_metadata->'shared_recognition'->>'in_flight' = 'false'
      and case when jsonb_typeof(run.source_metadata->'shared_recognition'->'deadline') = 'number'
        then (run.source_metadata->'shared_recognition'->>'deadline')::numeric <= extract(epoch from now())
        else false end
      and not exists (select 1 from ops.segment_hits h where h.set_run_id=run.id
        and h.raw_data->'shared_recognition'->>'in_flight' = 'true')
    returning id
  ) select ((select count(*) from recovered) + (select count(*) from expired_shared))::integer as recovered
`;
