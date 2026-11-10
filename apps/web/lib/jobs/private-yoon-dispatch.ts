import "server-only";

import { sql } from "drizzle-orm";
import { getWorkerDb } from "@/lib/db/client";
import { env } from "@/lib/env";
import { buildPrivateYoonDispatchClaim, type PrivateYoonDispatch } from "./private-yoon-dispatch-query";
import { dispatchPrivateYoonWorkflow } from "@/lib/github/workflows";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const owner = /^[1-9][0-9]{0,19}$/;
export const privateYoonDispatchConfigured = () => env.deploymentTarget === "development"
  && env.githubOwner === "russell-algeo" && env.githubRepo === "dj-setlist-generator"
  && env.githubWorkflowRef === "preview" && env.githubWorkflowProcessSet === "process-set.yml"
  && Boolean(env.githubDispatchToken);

// No ordinary dispatch helper is broadened. Only pre-enqueued private runs are
// accepted; UUIDs/generations are the entire callback payload and result.
export async function dispatchPrivateYoon(input: PrivateYoonDispatch) {
  if (!privateYoonDispatchConfigured()) return { dispatched: false, reason: "private_configuration_required" };
  if (!uuid.test(input.setRunId) || (input.controller
    ? !owner.test(input.workflowRunId ?? "") || !owner.test(input.runAttempt ?? "")
    : !uuid.test(input.generation ?? ""))) return { dispatched: false, reason: "invalid_request" };
  const db = getWorkerDb();
  // Recheck audience, private identity and source snapshot at the final send
  // gate, after the Python admission transaction and before external dispatch.
  const fence = input.generation!;
  const claim = buildPrivateYoonDispatchClaim(input);
  if ((await db.execute(claim)).rows.length !== 1) return { dispatched: false, reason: "fence_changed" };
  try {
    const result = await dispatchPrivateYoonWorkflow(input.setRunId, input.controller ? { resume_mode: "private_queue" } : { dispatch_generation: input.generation! });
    if (!result.dispatched) throw new Error("private_dispatch_not_confirmed");
    if (!input.controller) await db.execute(sql`UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{yoon_queue_v1,status}','"dispatched"'::jsonb)
      WHERE id=${input.setRunId}::uuid AND source_metadata->'yoon_queue_v1'->>'generation'=${fence}
      AND source_metadata->'yoon_queue_v1'->>'status'='sending'`);
    return { dispatched: true };
  } catch {
    // A network error is not evidence GitHub rejected the workflow. Retain the
    // reservation; never roll back to queued or repeat the external action.
    return { dispatched: false, reason: "dispatch_requires_reconciliation" };
  }
}
