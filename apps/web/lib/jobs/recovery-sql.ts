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
    where status in ('dispatched', 'resolving', 'recognizing', 'aggregating', 'enriching', 'publishing', 'cancelling')
      and coalesce(heartbeat_at, updated_at, created_at) < now() - interval '30 minutes'
      and published_set_id is null
      and stage is distinct from 'publishing_committed'
    returning id, status
  ), cancelled_leases as (
    update ops.set_run_leases
    set status = 'cancelled', completed_at = now(), updated_at = now()
    where set_run_id in (select id from recovered where status = 'cancelled')
      and status in ('pending', 'claimed')
  ) select count(*)::integer as recovered from recovered
`;
