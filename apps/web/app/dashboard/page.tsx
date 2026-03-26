import Link from "next/link";

import { AppShell } from "@/components/app-shell";
import { SignOutButton } from "@/components/google-sign-in-button";
import { requireSessionActor } from "@/lib/auth/session";
import { getLatestImportedPages } from "@/lib/archive/repository";
import { getDashboardSummary } from "@/lib/jobs/service";

export default async function DashboardPage() {
  const actor = await requireSessionActor("/dashboard");
  const [summary, recentPages] = await Promise.all([
    getDashboardSummary(actor),
    getLatestImportedPages(),
  ]);

  return (
    <AppShell
      title="Remote control plane"
      eyebrow="Operator dashboard"
      description="This dashboard owns submissions, queue state, imported archive visibility, and downstream worker orchestration."
    >
      <section className="panel-grid panel-grid--three">
        <article className="panel">
          <p className="app-shell__eyebrow">Signed in as</p>
          <h2>{actor.displayName ?? actor.email}</h2>
          <p className="muted">{actor.email}</p>
          <div className="card-list__meta">
            <span>{actor.isAdmin ? "Admin" : "Operator"}</span>
            <span>{actor.isAllowlisted ? "Allowlisted" : "Read-only"}</span>
          </div>
        </article>
        <article className="panel">
          <p className="app-shell__eyebrow">Submissions</p>
          <p className="stat-value">{summary.totalSubmissions}</p>
          <p className="muted">{summary.activeSubmissions} active / {summary.failedSubmissions} failed</p>
        </article>
        <article className="panel">
          <p className="app-shell__eyebrow">Session</p>
          <div className="inline-actions">
            <Link className="pill-link" href="/dashboard/submit">
              Submit work
            </Link>
            <Link className="pill-link" href="/dashboard/jobs">
              View jobs
            </Link>
            <SignOutButton />
          </div>
        </article>
      </section>

      {!actor.isAllowlisted ? (
        <section className="panel" style={{ marginTop: 24 }}>
          <h2>Allowlist required for operator actions</h2>
          <p>
            Your account is authenticated but not allowlisted. Public archive routes work, but job submission, Spotify
            connect, and API tokens remain disabled until an admin promotes this account.
          </p>
        </section>
      ) : null}

      <section className="panel-grid panel-grid--two" style={{ marginTop: 24 }}>
        <article className="panel">
          <div className="list-toolbar">
            <h2>Recent set runs</h2>
            <Link className="pill-link" href="/dashboard/jobs">
              Full queue
            </Link>
          </div>
          {summary.recentRuns.length > 0 ? (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Status</th>
                  <th>Stage</th>
                </tr>
              </thead>
              <tbody>
                {summary.recentRuns.map((run) => (
                  <tr key={run.id}>
                    <td>
                      <div>{run.setTitle ?? run.sourceUrl}</div>
                      <div className="muted mono">{run.id}</div>
                    </td>
                    <td>{run.status}</td>
                    <td>{run.stage ?? "queued"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="empty-state">No set runs have been queued yet.</div>
          )}
        </article>

        <article className="panel">
          <div className="list-toolbar">
            <h2>Latest imported pages</h2>
            <Link className="pill-link" href="/">
              Open archive
            </Link>
          </div>
          {recentPages.length > 0 ? (
            <ul className="card-list">
              {recentPages.map((page) => (
                <li className="card-list__item" key={page.path}>
                  <div className="inline-actions" style={{ justifyContent: "space-between" }}>
                    <div>
                      <strong>{page.pageType}</strong>
                      <p className="muted mono">{page.path}</p>
                    </div>
                    <Link className="pill-link" href={page.path}>
                      Open
                    </Link>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <div className="empty-state">The historical archive is still importing.</div>
          )}
        </article>
      </section>
    </AppShell>
  );
}
