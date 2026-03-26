import Link from "next/link";

import { AppShell } from "@/components/app-shell";
import { requireSessionActor } from "@/lib/auth/session";
import { formatTimestamp } from "@/lib/format";
import { listSubmissionsForActor } from "@/lib/jobs/service";

export default async function DashboardJobsPage() {
  const actor = await requireSessionActor("/dashboard/jobs");
  const submissions = await listSubmissionsForActor(actor);

  return (
    <AppShell
      title="Job queue"
      eyebrow="Operations"
      description="Submission-level history for discovery jobs, direct set runs, and curated batches."
    >
      <section className="panel">
        <div className="list-toolbar">
          <h2>Recent submissions</h2>
          <Link className="pill-link" href="/dashboard/submit">
            New submission
          </Link>
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
                    <Link href={`/dashboard/jobs/${submission.id}`}>{submission.artistName ?? submission.sourceUrl ?? submission.id}</Link>
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
  );
}
