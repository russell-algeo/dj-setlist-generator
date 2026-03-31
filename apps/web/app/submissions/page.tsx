import Link from "next/link";

import { requireSessionActor } from "@/lib/auth/session";
import { formatTimestamp } from "@/lib/format";
import { listSubmissionsForActor } from "@/lib/jobs/submissions";

type SubmissionRow = {
  id: string;
  mode: string;
  status: string;
  artistName: string | null;
  sourceUrl: string | null;
  createdAt: Date;
};

type SubmissionsPageProps = {
  searchParams: Promise<{ status?: string }>;
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

export default async function SubmissionsPage({ searchParams }: SubmissionsPageProps) {
  const actor = await requireSessionActor("/submissions");
  const { status: filterStatus } = await searchParams;

  const allSubmissions = await listSubmissionsForActor(actor) as unknown as SubmissionRow[];

  const submissions =
    !filterStatus || filterStatus === "all"
      ? allSubmissions
      : filterStatus === "active"
        ? allSubmissions.filter((s) => s.status === "queued" || s.status === "running")
        : allSubmissions.filter((s) => s.status === filterStatus);

  const tabs = [
    { label: "All", value: "all" },
    { label: "Active", value: "active" },
    { label: "Complete", value: "completed" },
    { label: "Failed", value: "failed" },
  ];

  const activeTab = filterStatus ?? "all";

  return (
    <div style={{ minHeight: "100vh", background: "#0a0a0a", color: "#ccc", fontFamily: "monospace" }}>
      <div style={{ maxWidth: 960, margin: "0 auto", padding: "40px 24px" }}>
        <div style={{ marginBottom: 32 }}>
          <Link href="/" style={{ color: "#555", fontSize: 11, letterSpacing: "0.06em" }}>
            ← Archive
          </Link>
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 28 }}>
          <div>
            <h1 style={{ color: "#fff", fontSize: 14, letterSpacing: "0.1em", textTransform: "uppercase", margin: "0 0 6px" }}>
              My Submissions
            </h1>
            <p style={{ color: "#444", fontSize: 10, letterSpacing: "0.05em", margin: 0 }}>
              Work you&apos;ve submitted for processing
            </p>
          </div>

          <div style={{ display: "flex", background: "#111", border: "1px solid #1c1c1c", borderRadius: 4, overflow: "hidden" }}>
            {tabs.map((tab) => (
              <Link
                key={tab.value}
                href={tab.value === "all" ? "/submissions" : `/submissions?status=${tab.value}`}
                style={{
                  display: "block",
                  padding: "5px 12px",
                  fontSize: 10,
                  letterSpacing: "0.08em",
                  background: activeTab === tab.value ? "#fff" : "transparent",
                  color: activeTab === tab.value ? "#000" : "#555",
                  borderLeft: tab.value !== "all" ? "1px solid #222" : "none",
                  textDecoration: "none",
                }}
              >
                {tab.label}
              </Link>
            ))}
          </div>
        </div>

        {/* Table header */}
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr 80px", gap: 12, padding: "0 0 8px", borderBottom: "1px solid #1a1a1a", fontSize: 9, color: "#444", letterSpacing: "0.1em", textTransform: "uppercase" }}>
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
              style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr 80px", gap: 12, padding: "12px 0", borderBottom: "1px solid #0f0f0f", alignItems: "center", textDecoration: "none", color: "inherit" }}
            >
              <div>
                <div style={{ color: "#ccc", fontSize: 11 }}>
                  {submission.artistName ?? submission.sourceUrl ?? submission.id}
                </div>
                <div style={{ color: "#333", fontSize: 9, marginTop: 2 }}>{submission.id.slice(0, 8)}…</div>
              </div>
              <span style={{ color: "#666", fontSize: 10 }}>{MODE_LABEL[submission.mode] ?? submission.mode}</span>
              <span style={{ color: "#666", fontSize: 10 }}>—</span>
              <span style={{ color: "#555", fontSize: 10 }}>{formatTimestamp(submission.createdAt)}</span>
              <div style={{ textAlign: "right" }}>
                <span style={{ fontSize: 9, letterSpacing: "0.08em", padding: "2px 8px", borderRadius: 3, border: "1px solid", color: STATUS_COLOR[submission.status] ?? "#555", borderColor: STATUS_COLOR[submission.status] ?? "#555" }}>
                  {submission.status}
                </span>
              </div>
            </Link>
          ))
        )}
      </div>
    </div>
  );
}
