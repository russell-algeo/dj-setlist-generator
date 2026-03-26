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

export const dispatchProcessSetWorkflow = async (setRunId: string) =>
  dispatchWorkflow(env.githubWorkflowProcessSet, { set_run_id: setRunId });

export const dispatchDiscoverArtistWorkflow = async (submissionId: string) =>
  dispatchWorkflow(env.githubWorkflowDiscoverArtist, { submission_id: submissionId });
