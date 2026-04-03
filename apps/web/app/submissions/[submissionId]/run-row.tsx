"use client";

import Link from "next/link";
import { useState } from "react";

import { formatTimestamp } from "@/lib/format";
import type { SubmissionRunDto } from "@/lib/jobs/public";

import { StatusPill } from "../status-pill";
import { RunWorkflowTimeline } from "./run-workflow-timeline";

type RunRowProps = SubmissionRunDto & {
  retryPending: boolean;
  cancelPending: boolean;
  onRetry: (runId: string) => void;
  onCancel: (runId: string) => void;
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
  displayStatus,
  errorSummary,
  publishedSetId,
  attemptCount,
  updatedAt,
  lastActivityAt,
  lastActivityMessage,
  workflowSteps,
  recentEvents,
  actions,
  retryPending,
  cancelPending,
  onRetry,
  onCancel,
}: RunRowProps) {
  const [expanded, setExpanded] = useState(false);
  const [eventsOpen, setEventsOpen] = useState(false);

  return (
    <>
      <div
        onClick={() => setExpanded((value) => !value)}
        style={{
          display: "grid",
          gridTemplateColumns: "2.2fr 0.8fr 0.8fr 160px 90px 16px",
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
        <StatusPill align="right" status={displayStatus} />
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
              marginBottom: 16,
            }}
          >
            {[
              { label: "Attempts", value: String(attemptCount) },
              { label: "Last activity", value: formatTimestamp(lastActivityAt ?? updatedAt) },
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

          {lastActivityMessage ? (
            <div
              style={{
                marginBottom: 16,
                padding: "10px 12px",
                borderRadius: 6,
                background: "#101010",
                border: "1px solid #1c1c1c",
              }}
            >
              <div
                style={{
                  color: "#444",
                  fontSize: 9,
                  letterSpacing: "0.1em",
                  textTransform: "uppercase",
                  marginBottom: 4,
                }}
              >
                Latest update
              </div>
              <div style={{ color: "#7a7a7a", fontSize: 10, lineHeight: 1.5 }}>{lastActivityMessage}</div>
            </div>
          ) : null}

          <div
            style={{
              marginBottom: 16,
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
              Processing timeline
            </div>
            <RunWorkflowTimeline steps={workflowSteps} />
          </div>

          {recentEvents.length > 0 ? (
            <div
              style={{
                marginBottom: errorSummary || (status === "completed" && publishedSetId) ? 16 : 0,
                padding: "12px 14px",
                borderRadius: 6,
                border: "1px solid #1c1c1c",
                background: "#0f0f0f",
              }}
            >
              <button
                onClick={(event) => {
                  event.stopPropagation();
                  setEventsOpen((value) => !value);
                }}
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
                {eventsOpen ? "Hide recent events" : "Show recent events"}
              </button>

              {eventsOpen ? (
                <div style={{ marginTop: 14, display: "grid", gap: 10 }}>
                  {recentEvents.map((event) => (
                    <div
                      key={event.id}
                      style={{
                        padding: "10px 12px",
                        borderRadius: 6,
                        border:
                          event.tone === "danger"
                            ? "1px solid #3a1a1a"
                            : event.tone === "success"
                              ? "1px solid #1f3a22"
                              : "1px solid #202020",
                        background:
                          event.tone === "danger"
                            ? "#120a0a"
                            : event.tone === "success"
                              ? "#0d130d"
                              : "#111",
                      }}
                    >
                      <div
                        style={{
                          color:
                            event.tone === "danger"
                              ? "#b97a7a"
                              : event.tone === "success"
                                ? "#88b08a"
                                : "#9a9a9a",
                          fontSize: 10,
                          marginBottom: 4,
                        }}
                      >
                        {event.summary}
                      </div>
                      {event.message !== event.summary ? (
                        <div style={{ color: "#666", fontSize: 10, lineHeight: 1.5 }}>{event.message}</div>
                      ) : null}
                      <div style={{ color: "#444", fontSize: 9, marginTop: 6 }}>
                        {formatTimestamp(event.createdAt)}
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
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
