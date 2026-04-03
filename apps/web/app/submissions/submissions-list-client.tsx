"use client";

import Link from "next/link";

import { formatTimestamp } from "@/lib/format";
import type {
  PublicSubmissionFilter,
  SubmissionListItemDto,
} from "@/lib/jobs/public";

import { usePolledJson } from "./use-polled-json";
import { StatusPill } from "./status-pill";

type SubmissionsListClientProps = {
  filterStatus: PublicSubmissionFilter;
  initialSubmissions: SubmissionListItemDto[];
};

const MODE_LABEL: Record<string, string> = {
  url: "Single Set URL",
  artist: "Artist Discovery",
  curated_artist: "Curated Artist",
};

const submissionsHaveActiveWork = (items: SubmissionListItemDto[]) =>
  items.some((submission) => submission.hasActiveWork);

const getListActivityToken = (items: SubmissionListItemDto[]) =>
  items
    .filter((submission) => submission.hasActiveWork)
    .map((submission) => `${submission.id}:${submission.lastActivityAt}`)
    .join("|");

const describeCounts = (submission: SubmissionListItemDto) => {
  const parts = [`${submission.counts.completedCount}/${submission.counts.totalCount} complete`];

  if (submission.counts.queuedCount > 0) {
    parts.push(`${submission.counts.queuedCount} queued`);
  }

  if (submission.counts.inFlightCount > 0) {
    parts.push(`${submission.counts.inFlightCount} in flight`);
  }

  if (submission.counts.failedCount > 0) {
    parts.push(`${submission.counts.failedCount} failed`);
  }

  if (submission.counts.cancelledCount > 0) {
    parts.push(`${submission.counts.cancelledCount} cancelled`);
  }

  return parts.join(" · ");
};

export function SubmissionsListClient({
  filterStatus,
  initialSubmissions,
}: SubmissionsListClientProps) {
  const {
    data: submissions,
    isRefreshing,
    refreshError,
    lastUpdatedAt,
    isPollingPausedForInactivity,
    resumePolling,
  } = usePolledJson<SubmissionListItemDto[]>({
    initialData: initialSubmissions,
    url: filterStatus === "all" ? "/api/jobs" : `/api/jobs?status=${filterStatus}`,
    shouldPoll: submissionsHaveActiveWork,
    getActivityToken: getListActivityToken,
    parseResponse: async (response) => {
      const body = await response.json();
      return (body as { submissions: SubmissionListItemDto[] }).submissions;
    },
  });

  return (
    <>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 16,
          marginBottom: 12,
          color: "#4f4f4f",
          fontSize: 9,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
        }}
      >
        <span>
          {submissionsHaveActiveWork(submissions)
            ? isPollingPausedForInactivity
              ? "Live updates paused after 5 minutes without new activity"
              : "Live updates active"
            : "Snapshot"}
        </span>
        <span>{isRefreshing ? "Refreshing…" : `Updated ${formatTimestamp(lastUpdatedAt)}`}</span>
      </div>

      {submissionsHaveActiveWork(submissions) && isPollingPausedForInactivity ? (
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
          <button
            onClick={() => void resumePolling()}
            style={{
              border: "1px solid #2a2a2a",
              borderRadius: 4,
              background: "#111",
              color: "#b5b5b5",
              fontSize: 9,
              letterSpacing: "0.08em",
              padding: "5px 9px",
              textTransform: "uppercase",
            }}
            type="button"
          >
            Resume live updates
          </button>
        </div>
      ) : null}

      {refreshError ? (
        <div
          style={{
            marginBottom: 12,
            padding: "10px 12px",
            border: "1px solid #3a1a1a",
            borderRadius: 6,
            background: "#120a0a",
            color: "#8a3a3a",
            fontSize: 10,
          }}
        >
          Live refresh failed: {refreshError}
        </div>
      ) : null}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "2fr 1fr 1.25fr 1fr 80px",
          gap: 12,
          padding: "0 0 8px",
          borderBottom: "1px solid #1a1a1a",
          fontSize: 9,
          color: "#444",
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          minWidth: 760,
        }}
      >
        <span>Submission</span>
        <span>Mode</span>
        <span>Sets</span>
        <span>Submitted</span>
        <span style={{ textAlign: "right" }}>Status</span>
      </div>

      {submissions.length === 0 ? (
        <div style={{ padding: "40px 0", color: "#444", fontSize: 11, textAlign: "center" }}>
          No submissions yet.
        </div>
      ) : (
        submissions.map((submission) => (
          <Link
            key={submission.id}
            href={`/submissions/${submission.id}`}
            style={{
              display: "grid",
              gridTemplateColumns: "2fr 1fr 1.25fr 1fr 80px",
              gap: 12,
              padding: "12px 0",
              borderBottom: "1px solid #0f0f0f",
              alignItems: "center",
              textDecoration: "none",
              color: "inherit",
              minWidth: 760,
            }}
          >
            <div>
              <div style={{ color: "#ccc", fontSize: 11 }}>{submission.displayTitle}</div>
              <div style={{ color: "#333", fontSize: 9, marginTop: 2 }}>{submission.id.slice(0, 8)}…</div>
            </div>
            <span style={{ color: "#666", fontSize: 10 }}>{MODE_LABEL[submission.mode] ?? submission.mode}</span>
            <div style={{ color: "#666", fontSize: 10, lineHeight: 1.6 }}>{describeCounts(submission)}</div>
            <span style={{ color: "#555", fontSize: 10 }}>{formatTimestamp(submission.createdAt)}</span>
            <StatusPill align="right" status={submission.status} />
          </Link>
        ))
      )}
    </>
  );
}
