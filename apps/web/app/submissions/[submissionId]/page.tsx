import Link from "next/link";
import { notFound } from "next/navigation";

import { canAccessSubmission, requireSessionActor } from "@/lib/auth/session";
import { formatTimestamp } from "@/lib/format";
import { getSubmissionDetail } from "@/lib/jobs/submissions";
import { summarizeSetRunCounts } from "@/lib/jobs/status";

import { RunRow } from "./run-row";

type DetailPageProps = {
  params: Promise<{ submissionId: string }>;
};

type SubmissionDetail = {
  submission: {
    id: string;
    artistName: string | null;
    sourceUrl: string | null;
    mode: string;
    status: string;
    createdAt: Date;
  };
  runs: Array<{
    id: string;
    status: string;
    setTitle: string | null;
    sourceUrl: string | null;
    sourcePlatform: string | null;
    stage: string | null;
    errorSummary: string | null;
    publishedSetId: string | null;
    attemptCount: number;
    updatedAt: Date;
    segmentHitRollup: { hitCount: number; recognizedCount: number } | null;
  }>;
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
};

export default async function SubmissionDetailPage({ params }: DetailPageProps) {
  const { submissionId } = await params;
  const actor = await requireSessionActor(`/submissions/${submissionId}`);

  const hasAccess = await canAccessSubmission(actor, submissionId);
  if (!hasAccess) notFound();

  const detail = await getSubmissionDetail(submissionId) as unknown as SubmissionDetail | null;
  if (!detail) notFound();

  const { submission, runs } = detail;

  const runCounts = summarizeSetRunCounts(runs);
  const totalHits = runs.reduce((acc, r) => acc + (r.segmentHitRollup?.hitCount ?? 0), 0);
  const totalRecognized = runs.reduce((acc, r) => acc + (r.segmentHitRollup?.recognizedCount ?? 0), 0);
  const recognitionRate = totalHits > 0 ? Math.round((totalRecognized / totalHits) * 100) : null;
  const metricCards = [
    { value: runCounts.totalCount, label: "Total Sets" },
    { value: runCounts.queuedCount, label: "Queued" },
    { value: runCounts.inFlightCount, label: "In Flight" },
    { value: runCounts.completedCount, label: "Complete" },
    { value: runCounts.failedCount, label: "Failed" },
  ];

  if (runCounts.cancelledCount > 0) {
    metricCards.push({ value: runCounts.cancelledCount, label: "Cancelled" });
  }

  const statusColor = STATUS_COLOR[submission.status] ?? "#555";

  return (
    <div style={{ minHeight: "100vh", background: "#0a0a0a", color: "#ccc", fontFamily: "monospace" }}>
      <div style={{ maxWidth: 960, margin: "0 auto", padding: "40px 24px" }}>
        <div style={{ marginBottom: 24, fontSize: 10, color: "#444", letterSpacing: "0.06em" }}>
          <Link href="/submissions" style={{ color: "#666" }}>My Submissions</Link>
          {" › "}
          <span>{submission.artistName ?? submission.id}</span>
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24, paddingBottom: 20, borderBottom: "1px solid #1a1a1a" }}>
          <div>
            <h1 style={{ color: "#fff", fontSize: 14, letterSpacing: "0.08em", textTransform: "uppercase", margin: "0 0 8px" }}>
              {submission.artistName ?? submission.sourceUrl ?? submission.id}
            </h1>
            <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
              <span style={{ color: "#555", fontSize: 10 }}>
                <strong style={{ color: "#888" }}>Mode:</strong>{" "}
                {MODE_LABEL[submission.mode] ?? submission.mode}
              </span>
              <span style={{ color: "#555", fontSize: 10 }}>
                <strong style={{ color: "#888" }}>Submitted:</strong>{" "}
                {formatTimestamp(submission.createdAt)}
              </span>
            </div>
          </div>
          <span style={{ fontSize: 10, letterSpacing: "0.08em", padding: "4px 12px", borderRadius: 3, border: "1px solid", color: statusColor, borderColor: statusColor, background: `${statusColor}18`, whiteSpace: "nowrap" }}>
            {submission.status}
          </span>
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: `repeat(${metricCards.length}, 1fr)`,
            gap: 12,
            marginBottom: 28,
          }}
        >
          {metricCards.map(({ value, label }) => (
            <div key={label} style={{ background: "#111", border: "1px solid #1c1c1c", borderRadius: 6, padding: "14px 16px" }}>
              <div style={{ color: "#ddd", fontSize: 20, marginBottom: 4 }}>{value}</div>
              <div style={{ color: "#444", fontSize: 9, letterSpacing: "0.12em", textTransform: "uppercase" }}>{label}</div>
            </div>
          ))}
        </div>

        {recognitionRate !== null && (
          <div style={{ marginBottom: 16, padding: "10px 14px", background: "#0d0d0d", border: "1px solid #1c1c1c", borderRadius: 5, display: "flex", gap: 24 }}>
            <span style={{ color: "#666", fontSize: 10 }}>
              <strong style={{ color: "#888" }}>Tracks identified:</strong> {totalRecognized}
            </span>
            <span style={{ color: "#666", fontSize: 10 }}>
              <strong style={{ color: "#888" }}>Recognition rate:</strong> {recognitionRate}%
            </span>
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "2.5fr 1fr 1fr 80px 16px", gap: 10, padding: "0 0 8px", borderBottom: "1px solid #1a1a1a", fontSize: 9, color: "#444", letterSpacing: "0.1em", textTransform: "uppercase", marginTop: 8 }}>
          <span>Set Title</span>
          <span>Platform</span>
          <span>Stage</span>
          <span style={{ textAlign: "right" }}>Status</span>
          <span />
        </div>

        {runs.map((run) => (
          <RunRow
            key={run.id}
            id={run.id}
            title={run.setTitle}
            sourceUrl={run.sourceUrl}
            sourcePlatform={run.sourcePlatform}
            stage={run.stage}
            status={run.status}
            errorSummary={run.errorSummary}
            publishedSetId={run.publishedSetId}
            attemptCount={run.attemptCount}
            updatedAt={run.updatedAt}
          />
        ))}

        {runs.length === 0 && (
          <div style={{ padding: "40px 0", color: "#444", fontSize: 11, textAlign: "center" }}>
            No set runs yet.
          </div>
        )}
      </div>
    </div>
  );
}
