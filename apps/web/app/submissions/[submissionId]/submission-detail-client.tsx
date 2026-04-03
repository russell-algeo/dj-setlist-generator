"use client";

import { useState } from "react";

import { formatTimestamp } from "@/lib/format";
import {
  sortSubmissionRuns,
  type SubmissionDetailDto,
  type SubmissionRunSortMode,
} from "@/lib/jobs/public";

import { RunRow } from "./run-row";
import { usePolledJson } from "../use-polled-json";
import { StatusPill } from "../status-pill";
import { WorkflowTimeline } from "./run-workflow-timeline";

type SubmissionDetailClientProps = {
  initialDetail: SubmissionDetailDto;
};

const MODE_LABEL: Record<string, string> = {
  url: "Single Set URL",
  artist: "Artist Discovery",
  curated_artist: "Curated Artist",
};

const detailHasActiveWork = (detail: SubmissionDetailDto) => detail.hasActiveWork;

const getOutcomeBanner = (detail: SubmissionDetailDto) => {
  switch (detail.submission.status) {
    case "completed":
      return {
        title: "Submission complete",
        body: "All eligible set runs have finished processing.",
        borderColor: "#1f3a22",
        background: "#0c140d",
        color: "#88b08a",
      };
    case "partial":
      return {
        title: "Submission completed with failures",
        body: "Some set runs completed successfully while others failed or were cancelled.",
        borderColor: "#4a3a10",
        background: "#120f08",
        color: "#b79b55",
      };
    case "failed":
      return {
        title: "Submission failed",
        body: "No remaining active work was able to complete successfully.",
        borderColor: "#4a1d1d",
        background: "#140b0b",
        color: "#b97a7a",
      };
    case "cancelled":
      return {
        title: "Submission cancelled",
        body: "Queued work was cancelled and active work was asked to stop.",
        borderColor: "#2f2f2f",
        background: "#0f0f0f",
        color: "#8a8a8a",
      };
    default:
      return null;
  }
};

export function SubmissionDetailClient({
  initialDetail,
}: SubmissionDetailClientProps) {
  const [sortMode, setSortMode] = useState<SubmissionRunSortMode>("status_first");
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingActionKey, setPendingActionKey] = useState<string | null>(null);

  const {
    data: detail,
    isRefreshing,
    refreshError,
    lastUpdatedAt,
    refreshNow,
    isPollingPausedForInactivity,
    resumePolling,
  } = usePolledJson<SubmissionDetailDto>({
    initialData: initialDetail,
    url: `/api/jobs/${initialDetail.submission.id}`,
    shouldPoll: detailHasActiveWork,
    getActivityToken: (nextDetail) => nextDetail.lastActivityAt,
  });

  const sortedRuns = sortSubmissionRuns(detail.runs, sortMode);

  const metricCards = [
    { value: detail.counts.totalCount, label: "Total Sets" },
    { value: detail.counts.queuedCount, label: "Queued" },
    { value: detail.counts.inFlightCount, label: "In Flight" },
    { value: detail.counts.completedCount, label: "Complete" },
    { value: detail.counts.failedCount, label: "Failed" },
  ];

  if (detail.counts.cancelledCount > 0) {
    metricCards.push({ value: detail.counts.cancelledCount, label: "Cancelled" });
  }

  const outcomeBanner = getOutcomeBanner(detail);

  const runAction = async (url: string, actionKey: string) => {
    setPendingActionKey(actionKey);
    setActionError(null);

    try {
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          accept: "application/json",
        },
      });

      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error((body as { error?: string }).error ?? `HTTP ${response.status}`);
      }

      await refreshNow();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Action failed");
    } finally {
      setPendingActionKey(null);
    }
  };

  return (
    <>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 20,
          marginBottom: 24,
          paddingBottom: 20,
          borderBottom: "1px solid #1a1a1a",
        }}
      >
        <div>
          <h1
            style={{
              color: "#fff",
              fontSize: 14,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              margin: "0 0 8px",
            }}
          >
            {detail.submission.artistName ?? detail.submission.sourceUrl ?? detail.submission.id}
          </h1>
          <div style={{ display: "flex", gap: 20, flexWrap: "wrap", marginBottom: 8 }}>
            <span style={{ color: "#555", fontSize: 10 }}>
              <strong style={{ color: "#888" }}>Mode:</strong>{" "}
              {MODE_LABEL[detail.submission.mode] ?? detail.submission.mode}
            </span>
            <span style={{ color: "#555", fontSize: 10 }}>
              <strong style={{ color: "#888" }}>Submitted:</strong>{" "}
              {formatTimestamp(detail.submission.createdAt)}
            </span>
          </div>
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              alignItems: "center",
              gap: 10,
              color: "#444",
              fontSize: 9,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
            }}
          >
            <span>
              {detail.hasActiveWork
                ? isPollingPausedForInactivity
                  ? "Live updates paused after 5 minutes without new activity"
                  : "Live updates active"
                : "Snapshot"}{" "}
              · {isRefreshing ? "Refreshing…" : `Updated ${formatTimestamp(lastUpdatedAt)}`}
            </span>
            {detail.hasActiveWork && isPollingPausedForInactivity ? (
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
            ) : null}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 10, alignItems: "flex-end" }}>
          <StatusPill status={detail.submission.status} />

          {detail.hasActiveWork ? (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
              {detail.actions.canRetry ? (
                <button
                  disabled={pendingActionKey === "submission:retry"}
                  onClick={() =>
                    void runAction(`/api/jobs/${detail.submission.id}/retry`, "submission:retry")
                  }
                  style={{
                    border: "1px solid #2a2a2a",
                    borderRadius: 4,
                    background: "#111",
                    color: "#b5b5b5",
                    fontSize: 9,
                    letterSpacing: "0.08em",
                    padding: "6px 10px",
                    textTransform: "uppercase",
                  }}
                  type="button"
                >
                  {pendingActionKey === "submission:retry" ? "Retrying…" : "Retry Failed Sets"}
                </button>
              ) : null}
              {detail.actions.canCancel ? (
                <button
                  disabled={pendingActionKey === "submission:cancel"}
                  onClick={() =>
                    void runAction(`/api/jobs/${detail.submission.id}/cancel`, "submission:cancel")
                  }
                  style={{
                    border: "1px solid #2a2a2a",
                    borderRadius: 4,
                    background: "#111",
                    color: "#b5b5b5",
                    fontSize: 9,
                    letterSpacing: "0.08em",
                    padding: "6px 10px",
                    textTransform: "uppercase",
                  }}
                  type="button"
                >
                  {pendingActionKey === "submission:cancel" ? "Cancelling…" : "Cancel Submission"}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>

      {refreshError ? (
        <div
          style={{
            marginBottom: 16,
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

      {actionError ? (
        <div
          style={{
            marginBottom: 16,
            padding: "10px 12px",
            border: "1px solid #3a1a1a",
            borderRadius: 6,
            background: "#120a0a",
            color: "#8a3a3a",
            fontSize: 10,
          }}
        >
          Action failed: {actionError}
        </div>
      ) : null}

      {outcomeBanner ? (
        <div
          style={{
            marginBottom: 16,
            padding: "14px 16px",
            border: `1px solid ${outcomeBanner.borderColor}`,
            borderRadius: 6,
            background: outcomeBanner.background,
            color: outcomeBanner.color,
          }}
        >
          <div style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>
            {outcomeBanner.title}
          </div>
          <div style={{ fontSize: 11, lineHeight: 1.6 }}>{outcomeBanner.body}</div>
          {detail.actions.canRetry ? (
            <button
              disabled={pendingActionKey === "submission:retry"}
              onClick={() =>
                void runAction(`/api/jobs/${detail.submission.id}/retry`, "submission:retry")
              }
              style={{
                marginTop: 12,
                border: "1px solid #2a2a2a",
                borderRadius: 4,
                background: "#111",
                color: "#b5b5b5",
                fontSize: 9,
                letterSpacing: "0.08em",
                padding: "6px 10px",
                textTransform: "uppercase",
              }}
              type="button"
            >
              {pendingActionKey === "submission:retry" ? "Retrying…" : "Retry Failed Sets"}
            </button>
          ) : null}
        </div>
      ) : null}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${metricCards.length}, minmax(0, 1fr))`,
          gap: 12,
          marginBottom: 28,
        }}
      >
        {metricCards.map(({ value, label }) => (
          <div
            key={label}
            style={{
              background: "#111",
              border: "1px solid #1c1c1c",
              borderRadius: 6,
              padding: "14px 16px",
            }}
          >
            <div style={{ color: "#ddd", fontSize: 20, marginBottom: 4 }}>{value}</div>
            <div style={{ color: "#444", fontSize: 9, letterSpacing: "0.12em", textTransform: "uppercase" }}>
              {label}
            </div>
          </div>
        ))}
      </div>

      {detail.recognitionRate !== null ? (
        <div
          style={{
            marginBottom: 16,
            padding: "10px 14px",
            background: "#0d0d0d",
            border: "1px solid #1c1c1c",
            borderRadius: 5,
            display: "flex",
            gap: 24,
            flexWrap: "wrap",
          }}
        >
          <span style={{ color: "#666", fontSize: 10 }}>
            <strong style={{ color: "#888" }}>Tracks identified:</strong> {detail.totalRecognized}
          </span>
          <span style={{ color: "#666", fontSize: 10 }}>
            <strong style={{ color: "#888" }}>Recognition rate:</strong> {detail.recognitionRate}%
          </span>
          {detail.discoveryCandidateCount > 0 ? (
            <span style={{ color: "#666", fontSize: 10 }}>
              <strong style={{ color: "#888" }}>Discovery candidates:</strong> {detail.discoveryCandidateCount}
            </span>
          ) : null}
        </div>
      ) : null}

      {detail.submission.mode === "artist" && detail.workflowSteps ? (
        <div
          style={{
            marginBottom: 20,
            padding: "12px 14px",
            borderRadius: 6,
            border: "1px solid #1c1c1c",
            background: "#0f0f0f",
          }}
        >
          <div
            style={{
              color: "#666",
              fontSize: 9,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              marginBottom: 12,
            }}
          >
            Submission timeline
          </div>
          <WorkflowTimeline steps={detail.workflowSteps} />
        </div>
      ) : null}

      {detail.submission.mode === "artist" && detail.runs.length === 0 && detail.hasActiveWork ? (
        <div
          style={{
            marginBottom: 16,
            padding: "10px 14px",
            background: "#0d0d0d",
            border: "1px solid #1c1c1c",
            borderRadius: 5,
            color: "#666",
            fontSize: 10,
          }}
        >
          Discovery is still running. Set runs will appear here as soon as discovery finishes and queued sets are created.
        </div>
      ) : null}

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 12,
          marginBottom: 10,
        }}
      >
        <div style={{ color: "#555", fontSize: 10 }}>Run order</div>
        <div
          style={{
            display: "flex",
            border: "1px solid #1c1c1c",
            borderRadius: 4,
            overflow: "hidden",
            background: "#111",
          }}
        >
          <button
            onClick={() => setSortMode("status_first")}
            style={{
              border: "none",
              background: sortMode === "status_first" ? "#fff" : "transparent",
              color: sortMode === "status_first" ? "#000" : "#666",
              padding: "6px 10px",
              fontSize: 9,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
            }}
            type="button"
          >
            Status first
          </button>
          <button
            onClick={() => setSortMode("original_order")}
            style={{
              border: "none",
              borderLeft: "1px solid #222",
              background: sortMode === "original_order" ? "#fff" : "transparent",
              color: sortMode === "original_order" ? "#000" : "#666",
              padding: "6px 10px",
              fontSize: 9,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
            }}
            type="button"
          >
            Original order
          </button>
        </div>
      </div>

      <div style={{ overflowX: "auto" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "2.2fr 0.8fr 0.8fr 160px 90px 16px",
            gap: 10,
            padding: "0 0 8px",
            borderBottom: "1px solid #1a1a1a",
            fontSize: 9,
            color: "#444",
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            marginTop: 8,
            minWidth: 860,
          }}
        >
          <span>Set Title</span>
          <span>Platform</span>
          <span>Stage</span>
          <span style={{ textAlign: "right" }}>Actions</span>
          <span style={{ textAlign: "right" }}>Status</span>
          <span />
        </div>

        {sortedRuns.map((run) => (
          <RunRow
            key={run.id}
            {...run}
            retryPending={pendingActionKey === `run:${run.id}:retry`}
            cancelPending={pendingActionKey === `run:${run.id}:cancel`}
            onRetry={(runId) =>
              void runAction(
                `/api/jobs/${detail.submission.id}/runs/${runId}/retry`,
                `run:${runId}:retry`,
              )
            }
            onCancel={(runId) =>
              void runAction(
                `/api/jobs/${detail.submission.id}/runs/${runId}/cancel`,
                `run:${runId}:cancel`,
              )
            }
          />
        ))}
      </div>

      {detail.runs.length === 0 ? (
        <div style={{ padding: "40px 0", color: "#444", fontSize: 11, textAlign: "center" }}>
          No set runs yet.
        </div>
      ) : null}
    </>
  );
}
