import Link from "next/link";

import { AppShell } from "@/components/app-shell";
import { getSpotifyConnectionForUser, requireSessionActor } from "@/lib/auth/session";
import { formatTimestamp } from "@/lib/format";

export default async function DashboardSettingsPage() {
  const actor = await requireSessionActor("/dashboard/settings");
  const spotifyConnection = await getSpotifyConnectionForUser(actor.userId);

  return (
    <AppShell
      title="Settings"
      eyebrow="Operator identity"
      description="Account role, OAuth connections, and deployment-level integration state."
    >
      <section className="panel-grid panel-grid--two">
        <article className="panel">
          <h2>Account</h2>
          <table className="data-table">
            <tbody>
              <tr>
                <th>Email</th>
                <td>{actor.email}</td>
              </tr>
              <tr>
                <th>Allowlisted</th>
                <td>{actor.isAllowlisted ? "Yes" : "No"}</td>
              </tr>
              <tr>
                <th>Admin</th>
                <td>{actor.isAdmin ? "Yes" : "No"}</td>
              </tr>
            </tbody>
          </table>
        </article>
        <article className="panel">
          <h2>Spotify</h2>
          {spotifyConnection && !spotifyConnection.revokedAt ? (
            <>
              <p>Connected as {spotifyConnection.spotifyUserId}</p>
              <p className="muted">Last refresh: {formatTimestamp(spotifyConnection.lastRefreshAt)}</p>
            </>
          ) : (
            <p className="muted">No Spotify account connected yet.</p>
          )}

          <div className="inline-actions" style={{ marginTop: 18 }}>
            <Link className="pill-link" href="/api/spotify/start">
              {spotifyConnection && !spotifyConnection.revokedAt ? "Reconnect Spotify" : "Connect Spotify"}
            </Link>
            <Link className="pill-link" href="/dashboard/tokens">
              Manage API tokens
            </Link>
          </div>
        </article>
      </section>
    </AppShell>
  );
}
