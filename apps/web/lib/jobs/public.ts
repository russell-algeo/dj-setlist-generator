import { summarizeSetRunCounts } from "@/lib/jobs/status";

export const publicSubmissionFilterValues = [
  "all",
  "active",
  "completed",
  "partial",
  "failed",
  "cancelled",
] as const;

export type PublicSubmissionFilter = (typeof publicSubmissionFilterValues)[number];

export const submissionRunSortModes = ["status_first", "original_order"] as const;

export type SubmissionRunSortMode = (typeof submissionRunSortModes)[number];

export type SubmissionCountsDto = ReturnType<typeof summarizeSetRunCounts>;

export type SubmissionActionSummary = {
  retryableCount: number;
  exhaustedRetryCount: number;
  cancellableCount: number;
  canRetry: boolean;
  canCancel: boolean;
};

export type TimelineItemTone = "neutral" | "success" | "danger";

export type TimelineItemDto = {
  id: string;
  eventType: string;
  summary: string;
  message: string;
  createdAt: string;
  setRunId: string | null;
  tone: TimelineItemTone;
};

export type SubmissionRunProgressDto = {
  totalLeases: number;
  completedLeases: number;
  hitCount: number;
  recognizedCount: number;
} | null;

export type SubmissionRunWorkflowStepState =
  | "pending"
  | "active"
  | "complete"
  | "failed"
  | "cancelled";

export type SubmissionRunWorkflowStepDto = {
  key: "bootstrap" | "recognize" | "publish" | "complete";
  label: string;
  state: SubmissionRunWorkflowStepState;
  detail: string | null;
  progress:
    | {
        current: number;
        total: number;
        label: string;
      }
    | null;
};

export type SubmissionRunEventDto = TimelineItemDto;

export type SubmissionRunActionSummary = SubmissionActionSummary & {
  retryBudgetRemaining: number;
  retryExhausted: boolean;
};

export type SubmissionRunDto = {
  id: string;
  sourceUrl: string | null;
  sourcePlatform: string | null;
  title: string | null;
  stage: string | null;
  status: string;
  errorSummary: string | null;
  publishedSetId: string | null;
  attemptCount: number;
  createdAt: string;
  updatedAt: string | null;
  lastActivityAt: string;
  lastActivityMessage: string | null;
  progress: SubmissionRunProgressDto;
  workflowSteps: SubmissionRunWorkflowStepDto[];
  recentEvents: SubmissionRunEventDto[];
  actions: SubmissionRunActionSummary;
};

export type SubmissionListItemDto = {
  id: string;
  mode: string;
  status: string;
  displayTitle: string;
  artistName: string | null;
  sourceUrl: string | null;
  createdAt: string;
  lastActivityAt: string;
  lastActivityMessage: string | null;
  counts: SubmissionCountsDto;
  actions: SubmissionActionSummary;
  hasActiveWork: boolean;
};

export type SubmissionDetailDto = {
  submission: {
    id: string;
    mode: string;
    status: string;
    artistName: string | null;
    sourceUrl: string | null;
    createdAt: string;
    updatedAt: string;
  };
  counts: SubmissionCountsDto;
  actions: SubmissionActionSummary;
  totalHits: number;
  totalRecognized: number;
  recognitionRate: number | null;
  hasActiveWork: boolean;
  lastActivityAt: string;
  lastActivityMessage: string | null;
  discoveryCandidateCount: number;
  runs: SubmissionRunDto[];
};

const timelineEventSummaries: Record<string, string> = {
  "submission.created": "Submission queued",
  "submission.discovery.started": "Discovery started",
  "submission.discovery.completed": "Discovery completed",
  "submission.discovery.empty": "No sets discovered",
  "submission.discovery.failed": "Discovery failed",
  "submission.retried": "Failed sets retried",
  "submission.cancel_requested": "Cancellation requested",
  "set_run.dispatch": "Set processing started",
  "set_run.retried": "Set retried",
  "set_run.cancel_requested": "Run cancellation requested",
  "set_run.requeued": "Set requeued",
  "set_run.bootstrap.started": "Bootstrap started",
  "set_run.bootstrap.completed": "Bootstrap completed",
  "set_run.recognition.started": "Recognition started",
  "set_run.recognition.completed": "Recognition completed",
  "set_run.aggregate.started": "Aggregation started",
  "set_run.enrich.started": "Enrichment started",
  "set_run.publish.started": "Publish started",
  "set_run.publish.deferred": "Publish deferred",
  "set_run.dispatch_failed": "Dispatch failed",
  "set_run.completed": "Set completed",
  "set_run.failed": "Set failed",
  "set_run.cancelled": "Set cancelled",
  "set_run.publish_retry_dispatched": "Publish retry started",
};

const timelineEventTones: Record<string, TimelineItemTone> = {
  "submission.discovery.completed": "success",
  "submission.discovery.empty": "danger",
  "submission.discovery.failed": "danger",
  "submission.retried": "success",
  "submission.cancel_requested": "neutral",
  "set_run.failed": "danger",
  "set_run.cancelled": "neutral",
  "set_run.dispatch": "neutral",
  "set_run.retried": "success",
  "set_run.cancel_requested": "neutral",
  "set_run.requeued": "neutral",
  "set_run.bootstrap.completed": "success",
  "set_run.recognition.completed": "success",
  "set_run.completed": "success",
  "set_run.dispatch_failed": "danger",
  "set_run.publish.deferred": "neutral",
  "set_run.publish_retry_dispatched": "success",
};

const statusSortRank: Record<string, number> = {
  failing: 0,
  failed: 0,
  cancelling: 1,
  queued: 2,
  dispatched: 3,
  resolving: 3,
  recognizing: 3,
  aggregating: 3,
  enriching: 3,
  publishing: 3,
  completed: 4,
  cancelled: 5,
};

export const normalizePublicSubmissionFilter = (value: string | undefined | null): PublicSubmissionFilter =>
  publicSubmissionFilterValues.includes((value ?? "all") as PublicSubmissionFilter)
    ? ((value ?? "all") as PublicSubmissionFilter)
    : "all";

export const getTimelineSummary = (eventType: string, message: string) =>
  timelineEventSummaries[eventType] ?? message;

export const getTimelineTone = (eventType: string): TimelineItemTone =>
  timelineEventTones[eventType] ?? "neutral";

type BuildRunWorkflowStepsInput = {
  status: string;
  stage: string | null;
  progress: SubmissionRunProgressDto;
  recognitionSlotCount: number | null;
  completedRecognitionSlots: number;
};

const publishStageDetails: Record<string, string> = {
  aggregating: "Aggregating recognized tracks",
  enriching: "Enriching track metadata",
  publishing: "Publishing canonical set data",
  published: "Published to archive",
  published_with_errors: "Published with follow-up bookkeeping errors",
  publish_failed: "Publish failed",
};

export const buildRunWorkflowSteps = ({
  status,
  stage,
  progress,
  recognitionSlotCount,
  completedRecognitionSlots,
}: BuildRunWorkflowStepsInput): SubmissionRunWorkflowStepDto[] => {
  const normalizedStage = stage ?? "";
  const stageStartsWithSlot = normalizedStage.startsWith("slot_");
  const bootstrapFailed = normalizedStage === "bootstrap_failed";
  const publishFailed = normalizedStage === "publish_failed";
  const bootstrapStarted =
    status !== "queued" ||
    normalizedStage === "dispatching" ||
    normalizedStage === "resolving" ||
    normalizedStage === "queued_recognition" ||
    stageStartsWithSlot ||
    normalizedStage === "aggregating" ||
    normalizedStage === "enriching" ||
    normalizedStage === "publishing" ||
    normalizedStage === "published" ||
    normalizedStage === "published_with_errors";
  const bootstrapComplete =
    !bootstrapFailed &&
    (normalizedStage === "queued_recognition" ||
      stageStartsWithSlot ||
      normalizedStage === "aggregating" ||
      normalizedStage === "enriching" ||
      normalizedStage === "publishing" ||
      normalizedStage === "published" ||
      normalizedStage === "published_with_errors" ||
      normalizedStage === "publish_failed" ||
      normalizedStage === "workflow_incomplete" ||
      Boolean(progress && (progress.totalLeases > 0 || progress.hitCount > 0)) ||
      (status === "failed" && normalizedStage !== "bootstrap_failed") ||
      status === "completed");
  const recognizeStarted =
    normalizedStage === "queued_recognition" ||
    stageStartsWithSlot ||
    normalizedStage === "aggregating" ||
    normalizedStage === "enriching" ||
    normalizedStage === "publishing" ||
    normalizedStage === "published" ||
    normalizedStage === "published_with_errors" ||
    normalizedStage === "publish_failed" ||
    normalizedStage === "workflow_incomplete" ||
    Boolean(progress && (progress.totalLeases > 0 || progress.hitCount > 0)) ||
    (status === "failed" && normalizedStage !== "bootstrap_failed") ||
    status === "completed";
  const recognizeComplete =
    !bootstrapFailed &&
    (normalizedStage === "aggregating" ||
      normalizedStage === "enriching" ||
      normalizedStage === "publishing" ||
      normalizedStage === "published" ||
      normalizedStage === "published_with_errors" ||
      normalizedStage === "publish_failed" ||
      status === "completed" ||
      Boolean(progress && progress.totalLeases > 0 && progress.completedLeases >= progress.totalLeases));
  const publishStarted =
    normalizedStage === "aggregating" ||
    normalizedStage === "enriching" ||
    normalizedStage === "publishing" ||
    normalizedStage === "published" ||
    normalizedStage === "published_with_errors" ||
    normalizedStage === "publish_failed" ||
    normalizedStage === "workflow_incomplete" ||
    status === "completed";
  const publishComplete =
    status === "completed" ||
    normalizedStage === "published" ||
    normalizedStage === "published_with_errors";

  const failedStepKey =
    bootstrapFailed
      ? "bootstrap"
      : publishFailed
        ? "publish"
        : status === "failed"
          ? publishStarted
            ? "publish"
            : bootstrapComplete
              ? "recognize"
              : "bootstrap"
          : null;
  const cancelledStepKey =
    status === "cancelled"
      ? publishStarted && !publishComplete
        ? "publish"
        : recognizeStarted && !recognizeComplete
          ? "recognize"
          : "bootstrap"
      : null;

  const baseBootstrapState: SubmissionRunWorkflowStepState = bootstrapComplete
    ? "complete"
    : bootstrapStarted
      ? "active"
      : "pending";
  const baseRecognizeState: SubmissionRunWorkflowStepState = recognizeComplete
    ? "complete"
    : recognizeStarted
      ? "active"
      : "pending";
  const basePublishState: SubmissionRunWorkflowStepState = publishComplete
    ? "complete"
    : publishStarted
      ? "active"
      : "pending";

  const bootstrapState =
    failedStepKey === "bootstrap"
      ? "failed"
      : cancelledStepKey === "bootstrap"
        ? "cancelled"
        : baseBootstrapState;
  const recognizeState =
    failedStepKey === "recognize"
      ? "failed"
      : cancelledStepKey === "recognize"
        ? "cancelled"
        : baseRecognizeState;
  const publishState =
    failedStepKey === "publish"
      ? "failed"
      : cancelledStepKey === "publish"
        ? "cancelled"
        : basePublishState;
  const completeState: SubmissionRunWorkflowStepState =
    status === "completed" ? "complete" : publishComplete ? "active" : "pending";

  const recognitionProgress =
    recognitionSlotCount && recognitionSlotCount > 0
      ? {
          current: recognizeState === "complete"
            ? recognitionSlotCount
            : Math.min(completedRecognitionSlots, recognitionSlotCount),
          total: recognitionSlotCount,
          label: "slots",
        }
      : progress && progress.totalLeases > 0
        ? {
            current: recognizeState === "complete" ? progress.totalLeases : progress.completedLeases,
            total: progress.totalLeases,
            label: "leases",
          }
        : null;

  const recognitionDetailParts = [
    progress && progress.totalLeases > 0
      ? `${progress.completedLeases}/${progress.totalLeases} leases complete`
      : null,
    progress && progress.hitCount > 0
      ? `${progress.recognizedCount}/${progress.hitCount} tracks recognized`
      : null,
  ].filter((value): value is string => Boolean(value));

  const publishDetail =
    publishState === "active" || publishState === "complete" || publishState === "failed"
      ? publishStageDetails[normalizedStage] ?? (publishState === "complete" ? "Published to archive" : null)
      : publishState === "cancelled"
        ? "Publish cancelled"
        : null;

  return [
    {
      key: "bootstrap",
      label: "Bootstrap",
      state: bootstrapState,
      detail:
        bootstrapState === "active"
          ? "Preparing audio and scheduler plan"
          : bootstrapState === "complete"
            ? "Bootstrap complete"
            : bootstrapState === "failed"
              ? "Bootstrap failed"
              : bootstrapState === "cancelled"
                ? "Cancelled before recognition"
                : null,
      progress: null,
    },
    {
      key: "recognize",
      label: "Recognize",
      state: recognizeState,
      detail:
        recognitionDetailParts.join(" · ") ||
        (recognizeState === "active"
          ? "Recognition slots are running"
          : recognizeState === "complete"
            ? "Recognition complete"
            : recognizeState === "failed"
              ? "Recognition failed"
              : recognizeState === "cancelled"
                ? "Recognition cancelled"
                : null),
      progress: recognitionProgress,
    },
    {
      key: "publish",
      label: "Publish",
      state: publishState,
      detail: publishDetail,
      progress: null,
    },
    {
      key: "complete",
      label: "Complete",
      state: completeState,
      detail:
        completeState === "complete"
          ? "Set is ready in the archive"
          : completeState === "active"
            ? "Final bookkeeping"
            : null,
      progress: null,
    },
  ];
};

export const sortSubmissionRuns = (
  runs: readonly SubmissionRunDto[],
  mode: SubmissionRunSortMode,
) => {
  if (mode === "original_order") {
    return [...runs].sort((left, right) => left.createdAt.localeCompare(right.createdAt));
  }

  return [...runs].sort((left, right) => {
    const leftRank = statusSortRank[left.status] ?? 99;
    const rightRank = statusSortRank[right.status] ?? 99;

    if (leftRank !== rightRank) {
      return leftRank - rightRank;
    }

    return left.createdAt.localeCompare(right.createdAt);
  });
};
