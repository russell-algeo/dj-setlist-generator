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
  progress: SubmissionRunProgressDto;
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
  timeline: TimelineItemDto[];
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
