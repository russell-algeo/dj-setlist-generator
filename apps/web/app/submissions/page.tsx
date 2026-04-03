import Link from "next/link";

import { requireSessionActor } from "@/lib/auth/session";
import {
  normalizePublicSubmissionFilter,
  type PublicSubmissionFilter,
} from "@/lib/jobs/public";
import { listPublicSubmissionsForActor } from "@/lib/jobs/public.server";

import { SubmissionsListClient } from "./submissions-list-client";

type SubmissionsPageProps = {
  searchParams: Promise<{ status?: string }>;
};

export default async function SubmissionsPage({ searchParams }: SubmissionsPageProps) {
  const actor = await requireSessionActor("/submissions");
  const { status: filterStatus } = await searchParams;
  const activeTab = normalizePublicSubmissionFilter(filterStatus) as PublicSubmissionFilter;
  const submissions = await listPublicSubmissionsForActor(actor, activeTab);

  const tabs = [
    { label: "All", value: "all" },
    { label: "Active", value: "active" },
    { label: "Partial", value: "partial" },
    { label: "Complete", value: "completed" },
    { label: "Failed", value: "failed" },
    { label: "Cancelled", value: "cancelled" },
  ];

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

        <div style={{ overflowX: "auto" }}>
          <SubmissionsListClient filterStatus={activeTab} initialSubmissions={submissions} />
        </div>
      </div>
    </div>
  );
}
