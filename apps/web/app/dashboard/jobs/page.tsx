import Link from "next/link";

import { AppShell } from "@/components/app-shell";
import { ViewingAsBanner } from "@/components/viewing-as-banner";
import { requireSessionActor } from "@/lib/auth/session";
import { resolveViewAsActor } from "@/lib/admin/users";
import { formatTimestamp } from "@/lib/format";
import { listSubmissionsForActor } from "@/lib/jobs/service";

type DashboardJobsPageProps = {
  searchParams: Promise<{ viewAs?: string }>;
};

export default async function DashboardJobsPage({ searchParams }: DashboardJobsPageProps) {
  const sessionActor = await requireSessionActor("/dashboard/jobs");
  const { viewAs } = await searchParams;
  const viewAsActor = await resolveViewAsActor(sessionActor, viewAs);
  const actor = viewAsActor ?? sessionActor;

  const submissions = await listSubmissionsForActor(actor);

  const vq = viewAsActor ? `?viewAs=${viewAsActor.userId}` : "";

  return (
    <>
      {viewAsActor && <ViewingAsBanner email={viewAsActor.email} userId={viewAsActor.userId} />}
    <AppShell
      title="Job queue"
      eyebrow="Operations"
      description="Submission-level history for discovery jobs, direct set runs, and curated batches."
      viewAs={viewAsActor?.userId}
    >
      <section className="panel">
        <div className="list-toolbar">
          <h2>Recent submissions</h2>
          {!viewAsActor && (
            <Link className="pill-link" href="/dashboard/submit">
              New submission
            </Link>
          )}
        </div>
        {submissions.length > 0 ? (
          <table className="data-table">
            <thead>
              <tr>
                <th>Submission</th>
                <th>Mode</th>
                <th>Status</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {submissions.map((submission) => (
                <tr key={submission.id}>
                  <td>
                    <Link href={`/dashboard/jobs/${submission.id}${vq}`}>{submission.artistName ?? submission.sourceUrl ?? submission.id}</Link>
                    <div className="muted mono">{submission.id}</div>
                  </td>
                  <td>{submission.mode}</td>
                  <td>{submission.status}</td>
                  <td>{formatTimestamp(submission.createdAt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="empty-state">No submissions exist for this operator yet.</div>
        )}
      </section>
    </AppShell>
    </>
  );
}
