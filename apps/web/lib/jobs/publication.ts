import { and, isNull, sql } from "drizzle-orm";

import { setRuns } from "@/lib/db/schema";

// This stage is an irrevocable cancellation boundary while the archive writer is
// running. Cancellation and publication must compete in UPDATE predicates, never
// in a read-then-write check. Keep it intact on timeouts/unknown outcomes.
export const publicationCommittedStage = "publishing_committed";

export const hasUncommittedPublication = () =>
  and(
    isNull(setRuns.publishedSetId),
    sql`${setRuns.stage} is distinct from ${publicationCommittedStage}`,
  );

export const matchesWorkflowOwner = (workflowRunId?: string | null) =>
  sql`(
    ${setRuns.sourceMetadata}->>'active_workflow_run_id' is null
    or ${setRuns.sourceMetadata}->>'active_workflow_run_id' = ${workflowRunId ?? ""}
  )`;

// Fence the previous workflow before exposing a retry. A nonempty sentinel is
// necessary: absent ownership is deliberately permitted for first-time runs.
export const retireWorkflowOwner = () => sql`
  jsonb_set(jsonb_set(
    jsonb_set(coalesce(${setRuns.sourceMetadata}, '{}'::jsonb),
      '{retired_workflow_run_ids}',
      coalesce(${setRuns.sourceMetadata}->'retired_workflow_run_ids', '[]'::jsonb)
      || case
        when ${setRuns.sourceMetadata}->>'active_workflow_run_id' is not null
          and ${setRuns.sourceMetadata}->>'active_workflow_run_id' <> 'awaiting_dispatch'
        then jsonb_build_array(${setRuns.sourceMetadata}->>'active_workflow_run_id')
        else '[]'::jsonb
      end
    ),
    '{active_workflow_run_id}', '"awaiting_dispatch"'::jsonb
  ), '{dispatch_generation}', '"awaiting_dispatch"'::jsonb)
`;

export const matchesDispatchGeneration = (generation?: string | null) =>
  sql`coalesce(${setRuns.sourceMetadata}->>'dispatch_generation', '') = ${generation ?? ""}`;

export const prepareDispatchMetadata = (generation: string) =>
  sql`${retireWorkflowOwner()} || jsonb_build_object('dispatch_generation', ${generation}::text)`;
