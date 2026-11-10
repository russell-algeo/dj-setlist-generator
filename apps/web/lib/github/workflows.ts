import { env } from "@/lib/env";

const hasDispatchConfig = () =>
  Boolean(
    env.githubDispatchToken &&
      env.githubOwner &&
      env.githubRepo &&
      env.githubWorkflowRef,
  );

const dispatchWorkflow = async (workflowId: string | undefined, inputs: Record<string, string>) => {
  if (!workflowId || !hasDispatchConfig()) {
    return {
      dispatched: false,
      reason: "missing_config",
    } as const;
  }

  const response = await fetch(
    `https://api.github.com/repos/${env.githubOwner}/${env.githubRepo}/actions/workflows/${workflowId}/dispatches`,
    {
      method: "POST",
      headers: {
        authorization: `Bearer ${env.githubDispatchToken}`,
        "content-type": "application/json",
        accept: "application/vnd.github+json",
      },
      body: JSON.stringify({
        ref: env.githubWorkflowRef,
        inputs: {
          ...inputs,
          deployment_target: env.deploymentTarget,
        },
      }),
    },
  );

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`GitHub workflow dispatch failed: ${response.status} ${body}`);
  }

  return {
    dispatched: true,
  } as const;
};

type ProcessSetWorkflowInputs = {
  resume_mode?: "full" | "publish_only";
  dispatch_generation?: string;
};

export const dispatchProcessSetWorkflow = async (
  setRunId: string,
  inputs: ProcessSetWorkflowInputs = {},
) =>
  dispatchWorkflow(env.githubWorkflowProcessSet, {
    set_run_id: setRunId,
    ...inputs,
  });

export const dispatchDiscoverArtistWorkflow = async (submissionId: string) =>
  dispatchWorkflow(env.githubWorkflowDiscoverArtist, { submission_id: submissionId });

// Separate private route. Never allow a configurable public workflow/ref to
// receive private set identities or execute a production job by default.
export const dispatchPrivateYoonWorkflow = async (
  setRunId: string,
  inputs: { dispatch_generation?: string; resume_mode?: "private_queue" },
) => {
  if (env.deploymentTarget !== "development" || env.githubOwner !== "russell-algeo"
    || env.githubRepo !== "dj-setlist-generator" || env.githubWorkflowRef !== "preview"
    || env.githubWorkflowProcessSet !== "process-set.yml") {
    return { dispatched: false, reason: "private_configuration_required" } as const;
  }
  return dispatchWorkflow("process-set.yml", { set_run_id: setRunId, private_analysis: "true", ...inputs });
};
