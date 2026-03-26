import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { neon } from "@neondatabase/serverless";

type BenchmarkConfig = {
  slotCount: number;
  leaseSize: number;
};

type BenchmarkResult = {
  config: BenchmarkConfig;
  submissionId: string;
  setRunId: string;
  workflowRunId: number;
  workflowUrl: string;
  totalSeconds: number;
  bootstrapSeconds: number | null;
  publishSeconds: number | null;
  finalizeSeconds: number | null;
  longestRecognizeSeconds: number | null;
  shortestRecognizeSeconds: number | null;
  averageRecognizeSeconds: number | null;
  recognizeJobCount: number;
  segmentCount: number;
  leaseCount: number;
  leasesPerSlot: number;
  status: string;
  conclusion: string;
  createdAt: string;
  updatedAt: string;
};

type WorkflowJob = {
  name: string;
  startedAt: string;
  completedAt: string;
};

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "../../..");
const outputDir = resolve(repoRoot, "docs/codex");
const defaultJsonPath = resolve(outputDir, "recognition_scheduler_benchmark.json");
const defaultMarkdownPath = resolve(outputDir, "recognition_scheduler_benchmark.md");
const defaultSourceUrl =
  "https://soundcloud.com/soundofthecity/dyed-soundorom-sound-of-the";
const defaultEmail = "russellalgeo@gmail.com";
const defaultSlotCounts = [8, 10, 12, 16];
const defaultLeaseSizes = [10, 8, 6, 5, 4];
const defaultRetries = 2;

const sleep = (ms: number) => new Promise((resolvePromise) => setTimeout(resolvePromise, ms));

const parseListArg = (flag: string, fallback: number[]) => {
  const index = process.argv.indexOf(flag);
  if (index === -1 || index === process.argv.length - 1) {
    return fallback;
  }

  return process.argv[index + 1]
    .split(",")
    .map((value) => Number.parseInt(value.trim(), 10))
    .filter((value) => Number.isFinite(value) && value > 0);
};

const parseStringArg = (flag: string, fallback: string) => {
  const index = process.argv.indexOf(flag);
  if (index === -1 || index === process.argv.length - 1) {
    return fallback;
  }

  return process.argv[index + 1];
};

const parseNumberArg = (flag: string, fallback: number) => {
  const index = process.argv.indexOf(flag);
  if (index === -1 || index === process.argv.length - 1) {
    return fallback;
  }

  const value = Number.parseInt(process.argv[index + 1], 10);
  return Number.isFinite(value) && value > 0 ? value : fallback;
};

const resolveOutputPath = (value: string) => (isAbsolute(value) ? value : resolve(repoRoot, value));

const buildConfigs = (slotCounts: number[], leaseSizes: number[]) => {
  const pairs: BenchmarkConfig[] = [];
  for (const slotCount of slotCounts) {
    for (const leaseSize of leaseSizes) {
      pairs.push({ slotCount, leaseSize });
    }
  }
  return pairs;
};

const gh = (args: string[]) =>
  execFileSync("gh", args, {
    cwd: repoRoot,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();

const sql = neon(process.env.DATABASE_URL_MIGRATIONS ?? "");

if (!process.env.DATABASE_URL_MIGRATIONS) {
  throw new Error("DATABASE_URL_MIGRATIONS is required");
}

const listCurrentRunIds = () => {
  const raw = gh([
    "run",
    "list",
    "--workflow",
    "process-set.yml",
    "--limit",
    "20",
    "--json",
    "databaseId,createdAt,event",
  ]);

  const rows = JSON.parse(raw) as Array<{ databaseId: number; createdAt: string; event: string }>;
  return rows.filter((row) => row.event === "workflow_dispatch").map((row) => row.databaseId);
};

const waitForNewWorkflowRun = async (existingIds: Set<number>) => {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const raw = gh([
      "run",
      "list",
      "--workflow",
      "process-set.yml",
      "--limit",
      "20",
      "--json",
      "databaseId,createdAt,event,status,conclusion",
    ]);

    const rows = JSON.parse(raw) as Array<{
      databaseId: number;
      createdAt: string;
      event: string;
      status: string;
      conclusion: string;
    }>;

    const match = rows.find(
      (row) => row.event === "workflow_dispatch" && !existingIds.has(row.databaseId),
    );
    if (match) {
      return match.databaseId;
    }

    await sleep(2000);
  }

  throw new Error("Failed to discover the newly dispatched workflow run");
};

const createBenchmarkRun = async (email: string, sourceUrl: string) => {
  const [profile] = await sql`
    select user_id, email
    from authn.user_profiles
    where email = ${email}
    limit 1
  `;

  if (!profile) {
    throw new Error(`No user profile found for ${email}`);
  }

  const [submission] = await sql`
    insert into ops.submissions (
      requested_by,
      mode,
      status,
      source_url,
      source_urls,
      create_playlist
    )
    values (
      ${profile.user_id},
      'url',
      'queued',
      ${sourceUrl},
      ${JSON.stringify([sourceUrl])}::jsonb,
      false
    )
    returning id
  `;

  const [setRun] = await sql`
    insert into ops.set_runs (
      submission_id,
      requested_by,
      status,
      source_url,
      source_platform,
      set_title,
      create_playlist,
      source_metadata
    )
    values (
      ${submission.id},
      ${profile.user_id},
      'queued',
      ${sourceUrl},
      'soundcloud',
      null,
      false,
      '{}'::jsonb
    )
    returning id
  `;

  await sql`
    insert into ops.worker_events (
      submission_id,
      event_type,
      message,
      details
    )
    values (
      ${submission.id},
      'submission.created',
      'Submission queued in url mode',
      ${JSON.stringify({
        mode: "url",
        sourceUrl,
        sourceUrls: [sourceUrl],
        artistName: null,
      })}::jsonb
    )
  `;

  return {
    submissionId: String(submission.id),
    setRunId: String(setRun.id),
  };
};

const dispatchBenchmark = async (setRunId: string, config: BenchmarkConfig) => {
  const beforeIds = new Set(listCurrentRunIds());

  gh([
    "workflow",
    "run",
    "process-set.yml",
    "--ref",
    "remote-deployment",
    "-f",
    `set_run_id=${setRunId}`,
    "-f",
    "deployment_target=development",
    "-f",
    `recognition_slot_count=${config.slotCount}`,
    "-f",
    `lease_size=${config.leaseSize}`,
  ]);

  return waitForNewWorkflowRun(beforeIds);
};

const waitForRunCompletion = async (runId: number) => {
  while (true) {
    const raw = gh([
      "run",
      "view",
      String(runId),
      "--json",
      "status,conclusion,createdAt,updatedAt,jobs",
    ]);
    const summary = JSON.parse(raw) as {
      status: string;
      conclusion: string;
      createdAt: string;
      updatedAt: string;
      jobs: Array<WorkflowJob>;
    };

    if (summary.status === "completed") {
      return summary;
    }

    await sleep(5000);
  }
};

const toSeconds = (startedAt?: string | null, completedAt?: string | null) => {
  if (!startedAt || !completedAt) {
    return null;
  }

  return Math.round((Date.parse(completedAt) - Date.parse(startedAt)) / 1000);
};

const summarizeResult = async (
  config: BenchmarkConfig,
  submissionId: string,
  setRunId: string,
  workflowRunId: number,
) => {
  const workflow = await waitForRunCompletion(workflowRunId);
  const jobs = workflow.jobs ?? [];
  const bootstrap = jobs.find((job) => job.name === "bootstrap");
  const publish = jobs.find((job) => job.name === "publish");
  const finalize = jobs.find((job) => job.name === "finalize");
  const recognizeJobs = jobs.filter((job) => job.name.startsWith("recognize"));
  const recognizeDurations = recognizeJobs
    .map((job) => toSeconds(job.startedAt, job.completedAt))
    .filter((value): value is number => value !== null);

  const [runRow] = await sql`
    select
      source_metadata->>'segment_count' as segment_count,
      source_metadata->>'lease_size' as lease_size,
      source_metadata->>'recognition_slot_count' as recognition_slot_count
    from ops.set_runs
    where id = ${setRunId}
  `;
  const [leaseRow] = await sql`
    select count(*)::int as lease_count
    from ops.set_run_leases
    where set_run_id = ${setRunId}
  `;

  const totalSeconds = Math.round(
    (Date.parse(workflow.updatedAt) - Date.parse(workflow.createdAt)) / 1000,
  );
  const longestRecognizeSeconds =
    recognizeDurations.length > 0 ? Math.max(...recognizeDurations) : null;
  const shortestRecognizeSeconds =
    recognizeDurations.length > 0 ? Math.min(...recognizeDurations) : null;
  const averageRecognizeSeconds =
    recognizeDurations.length > 0
      ? Math.round(
          recognizeDurations.reduce((sum, value) => sum + value, 0) / recognizeDurations.length,
        )
      : null;

  const segmentCount = Number.parseInt(runRow?.segment_count ?? "0", 10);
  const leaseCount = Number.parseInt(String(leaseRow?.lease_count ?? 0), 10);

  return {
    config,
    submissionId,
    setRunId,
    workflowRunId,
    workflowUrl: `https://github.com/russell-algeo/dj-setlist-generator/actions/runs/${workflowRunId}`,
    totalSeconds,
    bootstrapSeconds: toSeconds(bootstrap?.startedAt, bootstrap?.completedAt),
    publishSeconds: toSeconds(publish?.startedAt, publish?.completedAt),
    finalizeSeconds: toSeconds(finalize?.startedAt, finalize?.completedAt),
    longestRecognizeSeconds,
    shortestRecognizeSeconds,
    averageRecognizeSeconds,
    recognizeJobCount: recognizeJobs.length,
    segmentCount,
    leaseCount,
    leasesPerSlot:
      config.slotCount > 0 ? Number((leaseCount / config.slotCount).toFixed(2)) : leaseCount,
    status: workflow.status,
    conclusion: workflow.conclusion,
    createdAt: workflow.createdAt,
    updatedAt: workflow.updatedAt,
  } satisfies BenchmarkResult;
};

const writeArtifacts = (results: BenchmarkResult[], jsonPath: string, markdownPath: string) => {
  mkdirSync(dirname(jsonPath), { recursive: true });
  writeFileSync(jsonPath, JSON.stringify(results, null, 2));

  const sorted = [...results].sort((left, right) => left.totalSeconds - right.totalSeconds);
  const best = sorted[0];
  const lines = [
    "# Recognition Scheduler Benchmark",
    "",
    `Generated at: ${new Date().toISOString()}`,
    "",
    `Best configuration so far: slots=${best.config.slotCount}, lease_size=${best.config.leaseSize}, total=${best.totalSeconds}s`,
    "",
    "| Slots | Lease Size | Leases/Slot | Total (s) | Bootstrap (s) | Longest Recognize (s) | Avg Recognize (s) | Publish (s) | Finalize (s) | Workflow |",
    "|-------|------------|-------------|-----------|---------------|------------------------|-------------------|-------------|--------------|----------|",
    ...sorted.map(
      (result) =>
        `| ${result.config.slotCount} | ${result.config.leaseSize} | ${result.leasesPerSlot} | ${result.totalSeconds} | ${result.bootstrapSeconds ?? "-"} | ${result.longestRecognizeSeconds ?? "-"} | ${result.averageRecognizeSeconds ?? "-"} | ${result.publishSeconds ?? "-"} | ${result.finalizeSeconds ?? "-"} | ${result.workflowRunId} |`,
    ),
    "",
  ];

  writeFileSync(markdownPath, lines.join("\n"));
};

const main = async () => {
  const slotCounts = parseListArg("--slot-counts", defaultSlotCounts);
  const leaseSizes = parseListArg("--lease-sizes", defaultLeaseSizes);
  const sourceUrl = parseStringArg("--source-url", defaultSourceUrl);
  const email = parseStringArg("--email", defaultEmail);
  const jsonPath = resolveOutputPath(parseStringArg("--json-out", defaultJsonPath));
  const markdownPath = resolveOutputPath(parseStringArg("--markdown-out", defaultMarkdownPath));
  const retries = parseNumberArg("--retries", defaultRetries);

  const configs = buildConfigs(slotCounts, leaseSizes);
  const results: BenchmarkResult[] = [];

  for (const config of configs) {
    let successfulResult: BenchmarkResult | null = null;

    for (let attempt = 1; attempt <= retries; attempt += 1) {
      console.log(
        `\n=== Benchmark: slots=${config.slotCount}, lease_size=${config.leaseSize}, attempt=${attempt}/${retries} ===`,
      );
      const run = await createBenchmarkRun(email, sourceUrl);
      console.log(
        `Created submission ${run.submissionId} and set run ${run.setRunId} for ${sourceUrl}`,
      );

      const workflowRunId = await dispatchBenchmark(run.setRunId, config);
      console.log(`Dispatched workflow run ${workflowRunId}`);

      const result = await summarizeResult(
        config,
        run.submissionId,
        run.setRunId,
        workflowRunId,
      );

      if (result.conclusion === "success") {
        successfulResult = result;
        break;
      }

      console.warn(
        `Workflow ${workflowRunId} finished with conclusion=${result.conclusion}; retrying config`,
      );
      await sleep(5000);
    }

    if (!successfulResult) {
      throw new Error(
        `Benchmark failed for slots=${config.slotCount}, lease_size=${config.leaseSize} after ${retries} attempt(s)`,
      );
    }

    results.push(successfulResult);
    writeArtifacts(results, jsonPath, markdownPath);

    console.log(
      `Completed run ${successfulResult.workflowRunId}: total=${successfulResult.totalSeconds}s, longest_recognize=${successfulResult.longestRecognizeSeconds}s, leases_per_slot=${successfulResult.leasesPerSlot}`,
    );
  }

  console.log(`\nWrote JSON results to ${jsonPath}`);
  console.log(`Wrote Markdown results to ${markdownPath}`);
};

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
