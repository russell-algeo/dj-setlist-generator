"use client";

import Link from "next/link";
import { useState } from "react";

import { formatTimestamp } from "@/lib/format";
import type { SubmissionRunDto } from "@/lib/jobs/public";
import { isActiveSetRunStatus } from "@/lib/jobs/status";

type RunRowProps = SubmissionRunDto & {
  retryPending: boolean;
  cancelPending: boolean;
  onRetry: (runId: string) => void;
  onCancel: (runId: string) => void;
};

const STATUS_COLOR: Record<string, string> = {
  queued: "#555",
  running: "#7a7a3a",
  dispatched: "#7a7a3a",
  resolving: "#7a7a3a",
  recognizing: "#7a7a3a",
  aggregating: "#7a7a3a",
  enriching: "#7a7a3a",
  publishing: "#7a7a3a",
  cancelling: "#7a5a3a",
  completed: "#3a7a3a",
  failed: "#8a3a3a",
  cancelled: "#555",
  claimed: "#7a7a3a",
};

const actionButtonStyle = {
  border: "1px solid #2a2a2a",
  borderRadius: 4,
  background: "#111",
  color: "#9a9a9a",
  fontSize: 9,
  letterSpacing: "0.08em",
  padding: "4px 8px",
  textTransform: "uppercase" as const,
};

export function RunRow({
  id,
  sourceUrl,
  sourcePlatform,
  title,
  stage,
  status,
  errorSummary,
  publishedSetId,
  attemptCount,
  updatedAt,
  progress,
  actions,
  retryPending,
  cancelPending,
  onRetry,
  onCancel,
}: RunRowProps) {
  const [expanded, setExpanded] = useState(false);
  const color = isActiveSetRunStatus(status) ? "#7a7a3a" : (STATUS_COLOR[status] ?? "#555");

  return (
    <>
      <div
        onClick={() => setExpanded((value) => !value)}
        style={{
          display: "grid",
          gridTemplateColumns: "2.2fr 0.8fr 0.8fr 90px 160px 16px",
          gap: 10,
          padding: "10px 0",
          borderBottom: "1px solid #0f0f0f",
          alignItems: "center",
          cursor: "pointer",
          minWidth: 860,
        }}
      >
        <div>
          <div style={{ color: "#bbb", fontSize: 11 }}>{title ?? sourceUrl ?? id}</div>
          <div
            style={{
              color: "#2a2a2a",
              fontSize: 9,
              marginTop: 2,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              maxWidth: 320,
            }}
          >
            {sourceUrl}
          </div>
        </div>
        <span style={{ color: "#555", fontSize: 10 }}>{sourcePlatform ?? "—"}</span>
        <span style={{ color: "#555", fontSize: 10 }}>{stage ?? "—"}</span>
        <span
          style={{
            textAlign: "right",
            fontSize: 9,
            letterSpacing: "0.08em",
            padding: "2px 8px",
            borderRadius: 3,
            border: "1px solid",
            color,
            borderColor: color,
            background: `${color}18`,
          }}
        >
          {status}
        </span>
        <div
          onClick={(event) => event.stopPropagation()}
          style={{ display: "flex", justifyContent: "flex-end", gap: 6, flexWrap: "wrap" }}
        >
          {actions.canRetry ? (
            <button
              disabled={retryPending}
              onClick={() => onRetry(id)}
              style={{
                ...actionButtonStyle,
                opacity: retryPending ? 0.5 : 1,
              }}
              type="button"
            >
              {retryPending ? "Retrying…" : "Retry"}
            </button>
          ) : null}
          {actions.canCancel ? (
            <button
              disabled={cancelPending}
              onClick={() => onCancel(id)}
              style={{
                ...actionButtonStyle,
                opacity: cancelPending ? 0.5 : 1,
              }}
              type="button"
            >
              {cancelPending ? "Cancelling…" : "Cancel"}
            </button>
          ) : null}
          {!actions.canRetry && actions.retryExhausted ? (
            <span style={{ color: "#5a4747", fontSize: 9 }}>Max retries</span>
          ) : null}
        </div>
        <span style={{ color: "#444", fontSize: 11 }}>{expanded ? "∨" : "›"}</span>
      </div>

      {expanded ? (
        <div
          style={{
            background: "#0d0d0d",
            border: "1px solid #1a1a1a",
            borderRadius: 6,
            padding: "16px 18px",
            margin: "4px 0 8px",
          }}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
              gap: 16,
              marginBottom: 14,
            }}
          >
            {[
              { label: "Attempts", value: String(attemptCount) },
              { label: "Last activity", value: formatTimestamp(updatedAt) },
              { label: "Stage", value: stage ?? "—" },
              { label: "Retry budget", value: `${actions.retryBudgetRemaining} remaining` },
            ].map(({ label, value }) => (
              <div key={label}>
                <div
                  style={{
                    color: "#444",
                    fontSize: 9,
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    marginBottom: 4,
                  }}
                >
                  {label}
                </div>
                <div style={{ color: "#888", fontSize: 11 }}>{value}</div>
              </div>
            ))}
          </div>

          {progress ? (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
                gap: 16,
                marginBottom: 14,
              }}
            >
              <div>
                <div
                  style={{
                    color: "#444",
                    fontSize: 9,
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    marginBottom: 4,
                  }}
                >
                  Recognition
                </div>
                <div style={{ color: "#888", fontSize: 11 }}>
                  {progress.recognizedCount}/{progress.hitCount} tracks recognized
                </div>
              </div>
              <div>
                <div
                  style={{
                    color: "#444",
                    fontSize: 9,
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    marginBottom: 4,
                  }}
                >
                  Lease progress
                </div>
                <div style={{ color: "#888", fontSize: 11 }}>
                  {progress.completedLeases}/{progress.totalLeases} leases completed
                </div>
              </div>
            </div>
          ) : null}

          {errorSummary ? (
            <div
              style={{
                background: "#120a0a",
                border: "1px solid #3a1a1a",
                borderRadius: 4,
                padding: "10px 12px",
              }}
            >
              <div
                style={{
                  color: "#8a3a3a",
                  fontSize: 9,
                  letterSpacing: "0.1em",
                  textTransform: "uppercase",
                  marginBottom: 6,
                }}
              >
                Error
              </div>
              <div style={{ color: "#6a4a4a", fontSize: 10, lineHeight: 1.6 }}>{errorSummary}</div>
            </div>
          ) : null}

          {status === "completed" && publishedSetId ? (
            <Link
              href={`/sets/${publishedSetId}`}
              style={{
                display: "inline-block",
                marginTop: 12,
                fontSize: 10,
                color: "#666",
                border: "1px solid #2a2a2a",
                borderRadius: 3,
                padding: "4px 10px",
                letterSpacing: "0.06em",
                textDecoration: "none",
              }}
            >
              View Set in Archive →
            </Link>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
