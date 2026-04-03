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

type SubmissionDetailClientProps = {
  initialDetail: SubmissionDetailDto;
};

const MODE_LABEL: Record<string, string> = {
  url: "Single Set URL",
  artist: "Artist Discovery",
  curated_artist: "Curated Artist",
};

const STATUS_COLOR: Record<string, string> = {
  queued: "#555",
  running: "#7a7a3a",
  partial: "#7a5a3a",
  completed: "#3a7a3a",
  failed: "#8a3a3a",
  cancelled: "#555",
  cancelling: "#7a5a3a",
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
  const [timelineOpen, setTimelineOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingActionKey, setPendingActionKey] = useState<string | null>(null);

  const {
    data: detail,
    isRefreshing,
    refreshError,
    lastUpdatedAt,
    refreshNow,
  } = usePolledJson<SubmissionDetailDto>({
    initialData: initialDetail,
    url: `/api/jobs/${initialDetail.submission.id}`,
    shouldPoll: detailHasActiveWork,
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
          <div style={{ color: "#444", fontSize: 9, letterSpacing: "0.08em", textTransform: "uppercase" }}>
            {detail.hasActiveWork ? "Live updates active" : "Snapshot"} ·{" "}
            {isRefreshing ? "Refreshing…" : `Updated ${formatTimestamp(lastUpdatedAt)}`}
          </div>
          {detail.lastActivityMessage ? (
            <div style={{ color: "#4d4d4d", fontSize: 10, marginTop: 8 }}>
              Latest activity: {detail.lastActivityMessage} · {formatTimestamp(detail.lastActivityAt)}
            </div>
          ) : null}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 10, alignItems: "flex-end" }}>
          <span
            style={{
              fontSize: 10,
              letterSpacing: "0.08em",
              padding: "4px 12px",
              borderRadius: 3,
              border: "1px solid",
              color: STATUS_COLOR[detail.submission.status] ?? "#555",
              borderColor: STATUS_COLOR[detail.submission.status] ?? "#555",
              background: `${STATUS_COLOR[detail.submission.status] ?? "#555"}18`,
              whiteSpace: "nowrap",
            }}
          >
            {detail.submission.status}
          </span>

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
            gridTemplateColumns: "2.2fr 0.8fr 0.8fr 90px 160px 16px",
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
          <span style={{ textAlign: "right" }}>Status</span>
          <span style={{ textAlign: "right" }}>Actions</span>
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

      <div
        style={{
          marginTop: 24,
          padding: "14px 16px",
          border: "1px solid #1c1c1c",
          borderRadius: 6,
          background: "#0d0d0d",
        }}
      >
        <button
          onClick={() => setTimelineOpen((value) => !value)}
          style={{
            border: "none",
            background: "transparent",
            padding: 0,
            color: "#8a8a8a",
            fontSize: 10,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            cursor: "pointer",
          }}
          type="button"
        >
          {timelineOpen ? "Hide recent activity" : "Show recent activity"}
        </button>

        {timelineOpen ? (
          detail.timeline.length > 0 ? (
            <div style={{ marginTop: 14, display: "grid", gap: 10 }}>
              {detail.timeline.map((item) => (
                <div
                  key={item.id}
                  style={{
                    padding: "10px 12px",
                    borderRadius: 6,
                    border:
                      item.tone === "danger"
                        ? "1px solid #3a1a1a"
                        : item.tone === "success"
                          ? "1px solid #1f3a22"
                          : "1px solid #202020",
                    background:
                      item.tone === "danger"
                        ? "#120a0a"
                        : item.tone === "success"
                          ? "#0d130d"
                          : "#111",
                  }}
                >
                  <div
                    style={{
                      color:
                        item.tone === "danger"
                          ? "#b97a7a"
                          : item.tone === "success"
                            ? "#88b08a"
                            : "#9a9a9a",
                      fontSize: 10,
                      marginBottom: 4,
                    }}
                  >
                    {item.summary}
                  </div>
                  {item.message !== item.summary ? (
                    <div style={{ color: "#666", fontSize: 10, lineHeight: 1.5 }}>{item.message}</div>
                  ) : null}
                  <div style={{ color: "#444", fontSize: 9, marginTop: 6 }}>
                    {formatTimestamp(item.createdAt)}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ marginTop: 14, color: "#555", fontSize: 10 }}>No recent activity yet.</div>
          )
        ) : null}
      </div>
    </>
  );
}
