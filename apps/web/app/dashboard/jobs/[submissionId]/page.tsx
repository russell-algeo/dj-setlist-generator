import { notFound } from "next/navigation";

import { AppShell } from "@/components/app-shell";
import { ViewingAsBanner } from "@/components/viewing-as-banner";
import { canAccessSubmission, requireSessionActor } from "@/lib/auth/session";
import { resolveViewAsActor } from "@/lib/admin/users";
import { formatTimestamp } from "@/lib/format";
import { getSubmissionDetail } from "@/lib/jobs/service";

type DashboardJobDetailPageProps = {
  params: Promise<{
    submissionId: string;
  }>;
  searchParams: Promise<{ viewAs?: string }>;
};

const getPublishedDetails = (sourceMetadata: unknown) => {
  const metadata =
    sourceMetadata && typeof sourceMetadata === "object"
      ? (sourceMetadata as Record<string, unknown>)
      : null;
  const published =
    metadata?.published && typeof metadata.published === "object"
      ? (metadata.published as Record<string, unknown>)
      : null;

  return {
    slug: typeof published?.slug === "string" ? published.slug : null,
    legacyPath: typeof published?.legacy_path === "string" ? published.legacy_path : null,
  };
};

export default async function DashboardJobDetailPage({ params, searchParams }: DashboardJobDetailPageProps) {
  const sessionActor = await requireSessionActor("/dashboard/jobs");
  const { submissionId } = await params;
  const { viewAs } = await searchParams;
  const viewAsActor = await resolveViewAsActor(sessionActor, viewAs);
  const actor = viewAsActor ?? sessionActor;
  const allowed = await canAccessSubmission(actor, submissionId);

  if (!allowed) {
    notFound();
  }

  const detail = await getSubmissionDetail(submissionId);

  if (!detail) {
    notFound();
  }

  return (
    <>
      {viewAsActor && <ViewingAsBanner email={viewAsActor.email} userId={viewAsActor.userId} />}
    <AppShell
      title="Submission detail"
      eyebrow="Operations"
      description="Submission, worker events, discovery candidates, and set-run execution state."
    >
      <section className="panel-grid panel-grid--two">
        <article className="panel">
          <p className="app-shell__eyebrow">Submission</p>
          <h2>{detail.submission.artistName ?? detail.submission.sourceUrl ?? detail.submission.id}</h2>
          <div className="card-list__meta">
            <span>{detail.submission.mode}</span>
            <span>{detail.submission.status}</span>
            <span>{detail.submission.createPlaylist ? "Playlist enabled" : "No playlist"}</span>
          </div>
          <div className="inline-actions" style={{ marginTop: 18 }}>
            <form action={`/api/jobs/${detail.submission.id}/retry`} method="post">
              <button className="button" type="submit">
                Retry
              </button>
            </form>
            <form action={`/api/jobs/${detail.submission.id}/cancel`} method="post">
              <button className="button button--ghost" type="submit">
                Cancel
              </button>
            </form>
          </div>
        </article>
        <article className="panel">
          <p className="app-shell__eyebrow">Metadata</p>
          <table className="data-table">
            <tbody>
              <tr>
                <th>ID</th>
                <td className="mono">{detail.submission.id}</td>
              </tr>
              <tr>
                <th>Requested</th>
                <td>{formatTimestamp(detail.submission.createdAt)}</td>
              </tr>
              <tr>
                <th>Source URL</th>
                <td>{detail.submission.sourceUrl ?? "n/a"}</td>
              </tr>
              <tr>
                <th>Artist</th>
                <td>{detail.submission.artistName ?? "n/a"}</td>
              </tr>
            </tbody>
          </table>
        </article>
      </section>

      <section className="panel" style={{ marginTop: 24 }}>
        <h2>Set runs</h2>
        {detail.runs.length > 0 ? (
          <table className="data-table">
            <thead>
              <tr>
                <th>Run</th>
                <th>Status</th>
                <th>Stage</th>
                <th>Progress</th>
                <th>Heartbeat</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {detail.runs.map((run) => {
                const published = getPublishedDetails(run.sourceMetadata);

                return (
                  <tr key={run.id}>
                    <td>
                      <div className="mono">{run.id}</div>
                      <div className="muted">attempt {run.attemptCount}</div>
                    </td>
                    <td>{run.status}</td>
                    <td>{run.stage ?? "queued"}</td>
                    <td>
                      {run.leaseRollup ? (
                        <div className="muted">
                          {Number(run.leaseRollup.completedCount ?? 0)}/{Number(run.leaseRollup.totalCount ?? 0)} leases
                          · {Number(run.segmentHitRollup?.recognizedCount ?? 0)} recognized
                        </div>
                      ) : (
                        <span className="muted">No leases yet</span>
                      )}
                    </td>
                    <td>{formatTimestamp(run.heartbeatAt ?? run.updatedAt)}</td>
                    <td>
                      <div>{run.sourceUrl}</div>
                      {published.slug ? (
                        <div className="inline-actions" style={{ marginTop: 8 }}>
                          <a className="pill-link" href={`/sets/${published.slug}`}>
                            Stable alias
                          </a>
                          {published.legacyPath ? (
                            <a className="pill-link" href={published.legacyPath}>
                              Stored page
                            </a>
                          ) : null}
                        </div>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <div className="empty-state">No set runs have been created yet for this submission.</div>
        )}
      </section>

      <section className="panel-grid panel-grid--two" style={{ marginTop: 24 }}>
        <article className="panel">
          <h2>Worker events</h2>
          {detail.events.length > 0 ? (
            <ul className="card-list">
              {detail.events.map((event) => (
                <li className="card-list__item" key={event.id}>
                  <strong>{event.eventType}</strong>
                  <p>{event.message}</p>
                  {event.details && Object.keys(event.details).length > 0 ? (
                    <pre className="muted mono" style={{ whiteSpace: "pre-wrap" }}>
                      {JSON.stringify(event.details, null, 2)}
                    </pre>
                  ) : null}
                  <p className="muted mono">{formatTimestamp(event.createdAt)}</p>
                </li>
              ))}
            </ul>
          ) : (
            <div className="empty-state">No worker events recorded yet.</div>
          )}
        </article>
        <article className="panel">
          <h2>Discovery candidates</h2>
          {detail.discoveryCandidates.length > 0 ? (
            <ul className="card-list">
              {detail.discoveryCandidates.map((candidate) => (
                <li className="card-list__item" key={candidate.id}>
                  <strong>{candidate.sourceTitle ?? candidate.sourceUrl}</strong>
                  <div className="card-list__meta">
                    <span>{candidate.status}</span>
                    <span>{candidate.sourcePlatform ?? "unknown"}</span>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <div className="empty-state">No discovery candidates recorded for this submission.</div>
          )}
        </article>
      </section>
    </AppShell>
    </>
  );
}
