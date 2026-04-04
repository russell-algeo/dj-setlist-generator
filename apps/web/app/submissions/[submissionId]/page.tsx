import { notFound } from "next/navigation";

import { OperatorFrame } from "@/components/operator/operator-ui";
import { canAccessSubmission, requireSessionActor } from "@/lib/auth/session";
import { getPublicSubmissionDetail } from "@/lib/jobs/public.server";

import { SubmissionDetailClient } from "./submission-detail-client";

type DetailPageProps = {
  params: Promise<{ submissionId: string }>;
};

export default async function SubmissionDetailPage({ params }: DetailPageProps) {
  const { submissionId } = await params;
  const actor = await requireSessionActor(`/submissions/${submissionId}`);
  const headerNavLinks = actor.isAdmin
    ? [
        { href: "/submissions", label: "My Submissions" },
        { href: "/admin", label: "Admin Panel" },
      ]
    : [{ href: "/submissions", label: "My Submissions" }];

  const hasAccess = await canAccessSubmission(actor, submissionId);
  if (!hasAccess) notFound();

  const detail = await getPublicSubmissionDetail(submissionId);
  if (!detail) notFound();

  return (
    <OperatorFrame
      activeNavHref="/submissions"
      backCurrentLabel={detail.submission.artistName ?? detail.submission.id}
      backHref="/submissions"
      backLabel="← My Submissions"
      headerNavLinks={headerNavLinks}
      width="wide"
    >
      <SubmissionDetailClient initialDetail={detail} />
    </OperatorFrame>
  );
}
