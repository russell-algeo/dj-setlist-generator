import Link from "next/link";
import { notFound } from "next/navigation";

import { canAccessSubmission, requireSessionActor } from "@/lib/auth/session";
import { getPublicSubmissionDetail } from "@/lib/jobs/public.server";

import { SubmissionDetailClient } from "./submission-detail-client";

type DetailPageProps = {
  params: Promise<{ submissionId: string }>;
};

export default async function SubmissionDetailPage({ params }: DetailPageProps) {
  const { submissionId } = await params;
  const actor = await requireSessionActor(`/submissions/${submissionId}`);

  const hasAccess = await canAccessSubmission(actor, submissionId);
  if (!hasAccess) notFound();

  const detail = await getPublicSubmissionDetail(submissionId);
  if (!detail) notFound();

  return (
    <div style={{ minHeight: "100vh", background: "#0a0a0a", color: "#ccc", fontFamily: "monospace" }}>
      <div style={{ maxWidth: 960, margin: "0 auto", padding: "40px 24px" }}>
        <div style={{ marginBottom: 24, fontSize: 10, color: "#444", letterSpacing: "0.06em" }}>
          <Link href="/submissions" style={{ color: "#666" }}>My Submissions</Link>
          {" › "}
          <span>{detail.submission.artistName ?? detail.submission.id}</span>
        </div>
        <SubmissionDetailClient initialDetail={detail} />
      </div>
    </div>
  );
}
