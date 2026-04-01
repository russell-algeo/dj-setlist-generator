"use client";

import Link from "next/link";
import { useState } from "react";

type RunRowProps = {
  id: string;
  title: string | null;
  sourceUrl: string | null;
  sourcePlatform: string | null;
  stage: string | null;
  status: string;
  errorSummary: string | null;
  publishedSetId: string | null;
  attemptCount: number;
  updatedAt: Date | null;
};

const STATUS_COLOR: Record<string, string> = {
  queued: "#555",
  running: "#7a7a3a",
  completed: "#3a7a3a",
  failed: "#8a3a3a",
  cancelled: "#555",
  claimed: "#7a7a3a",
};

const PUBLISHED_WITH_ERRORS_STAGES = new Set(["published_with_errors"]);

export function RunRow({
  id,
  title,
  sourceUrl,
  sourcePlatform,
  stage,
  status,
  errorSummary,
  publishedSetId,
  attemptCount,
  updatedAt,
}: RunRowProps) {
  const [expanded, setExpanded] = useState(false);
  const color = STATUS_COLOR[status] ?? "#555";

  return (
    <>
      <div
        onClick={() => setExpanded((v) => !v)}
        style={{ display: "grid", gridTemplateColumns: "2.5fr 1fr 1fr 80px 16px", gap: 10, padding: "10px 0", borderBottom: "1px solid #0f0f0f", alignItems: "center", cursor: "pointer" }}
      >
        <div>
          <div style={{ color: "#bbb", fontSize: 11 }}>{title ?? id}</div>
          <div style={{ color: "#2a2a2a", fontSize: 9, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 320 }}>
            {sourceUrl}
          </div>
        </div>
        <span style={{ color: "#555", fontSize: 10 }}>{sourcePlatform ?? "—"}</span>
        <span style={{ color: "#555", fontSize: 10 }}>{stage ?? "—"}</span>
        <span style={{ textAlign: "right", fontSize: 9, letterSpacing: "0.08em", padding: "2px 8px", borderRadius: 3, border: "1px solid", color, borderColor: color, background: `${color}18` }}>
          {status}
        </span>
        <span style={{ color: "#444", fontSize: 11 }}>{expanded ? "∨" : "›"}</span>
      </div>

      {expanded && (
        <div style={{ background: "#0d0d0d", border: "1px solid #1a1a1a", borderRadius: 6, padding: "16px 18px", margin: "4px 0 8px" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 14 }}>
            {[
              { label: "Attempts", value: String(attemptCount) },
              { label: "Last activity", value: updatedAt ? new Date(updatedAt).toLocaleString() : "—" },
              { label: "Stage", value: stage ?? "—" },
            ].map(({ label, value }) => (
              <div key={label}>
                <div style={{ color: "#444", fontSize: 9, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 4 }}>{label}</div>
                <div style={{ color: "#888", fontSize: 11 }}>{value}</div>
              </div>
            ))}
          </div>

          {stage && PUBLISHED_WITH_ERRORS_STAGES.has(stage) && (
            <div style={{ background: "#0f0d08", border: "1px solid #4a3a10", borderRadius: 4, padding: "10px 12px", marginBottom: 10 }}>
              <div style={{ color: "#9a7a20", fontSize: 9, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>Published with errors</div>
              <div style={{ color: "#7a6a40", fontSize: 10, lineHeight: 1.6 }}>
                Set data is visible in the archive, but post-publish steps (such as Spotify playlist creation or cache refresh) did not complete. Re-running this submission is recommended to finish the remaining steps.
              </div>
              {errorSummary && (
                <div style={{ color: "#6a5a30", fontSize: 9, marginTop: 8, fontFamily: "monospace" }}>{errorSummary}</div>
              )}
            </div>
          )}

          {!PUBLISHED_WITH_ERRORS_STAGES.has(stage ?? "") && errorSummary && (
            <div style={{ background: "#120a0a", border: "1px solid #3a1a1a", borderRadius: 4, padding: "10px 12px" }}>
              <div style={{ color: "#8a3a3a", fontSize: 9, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>Error</div>
              <div style={{ color: "#6a4a4a", fontSize: 10, lineHeight: 1.6 }}>{errorSummary}</div>
            </div>
          )}

          {status === "completed" && publishedSetId && (
            <Link
              href={`/sets/${publishedSetId}`}
              style={{ display: "inline-block", marginTop: 12, fontSize: 10, color: "#666", border: "1px solid #2a2a2a", borderRadius: 3, padding: "4px 10px", letterSpacing: "0.06em", textDecoration: "none" }}
            >
              View Set in Archive →
            </Link>
          )}
        </div>
      )}
    </>
  );
}
