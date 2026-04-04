import {
  OperatorFrame,
  OperatorPageHeader,
} from "@/components/operator/operator-ui";
import { requireSessionActor } from "@/lib/auth/session";
import {
  normalizePublicSubmissionFilter,
  type PublicSubmissionFilter,
} from "@/lib/jobs/public";
import { listPublicSubmissionsForActor } from "@/lib/jobs/public.server";

import { SubmissionsListClient } from "./submissions-list-client";

type SubmissionsPageProps = {
  searchParams: Promise<{ page?: string; status?: string }>;
};

export default async function SubmissionsPage({ searchParams }: SubmissionsPageProps) {
  const actor = await requireSessionActor("/submissions");
  const { page, status: filterStatus } = await searchParams;
  const activeTab = normalizePublicSubmissionFilter(filterStatus) as PublicSubmissionFilter;
  const submissions = await listPublicSubmissionsForActor(actor, activeTab);
  const requestedPage = Number(page);
  const initialPage =
    Number.isFinite(requestedPage) && requestedPage > 0 ? Math.floor(requestedPage) : 1;

  const headerNavLinks = actor.isAdmin
    ? [
        { href: "/submissions", label: "My Submissions" },
        { href: "/admin", label: "Admin Panel" },
      ]
    : [{ href: "/submissions", label: "My Submissions" }];

  return (
    <OperatorFrame
      activeNavHref="/submissions"
      backHref="/"
      backLabel="← Archive"
      headerNavLinks={headerNavLinks}
      width="wide"
    >
      <OperatorPageHeader
        eyebrow="Operator queue"
        meta={
          <>
          <span>
            <strong>Signed in as</strong> {actor.displayName ?? actor.email}
          </span>
          <span>
            <strong>Access</strong> {actor.isAdmin ? "Admin" : "Operator"}
          </span>
          </>
        }
        subtitle="Work you've submitted for discovery, recognition, enrichment, and publish processing."
        titleFont="sans"
        titleSize="display"
        title="My Submissions"
      />
      <SubmissionsListClient
        filterStatus={activeTab}
        initialPage={initialPage}
        initialSubmissions={submissions}
      />
    </OperatorFrame>
  );
}
