import Link from "next/link";

import { AppShell } from "@/components/app-shell";
import { getSpotifyConnectionForUser, requireSessionActor } from "@/lib/auth/session";
import { formatTimestamp } from "@/lib/format";

type DashboardSettingsPageProps = {
  searchParams: Promise<{ spotify?: string }>;
};

export default async function DashboardSettingsPage({ searchParams }: DashboardSettingsPageProps) {
  const actor = await requireSessionActor("/dashboard/settings");
  const { spotify: spotifyParam } = await searchParams;
  const spotifyConnection = await getSpotifyConnectionForUser(actor.userId);

  const spotifyStatusMessage = (() => {
    if (spotifyParam === "connected") return "Spotify connected successfully.";
    if (spotifyParam === "disconnected") return "Spotify disconnected.";
    if (spotifyParam === "error") return "Spotify connection failed. Please try again.";
    if (spotifyParam === "invalid_state") return "Spotify connection failed: invalid state. Please try again.";
    if (spotifyParam === "missing_config") return "Spotify OAuth is not configured on this deployment.";
    if (spotifyParam === "token_error") return "Spotify token exchange failed. Please try again.";
    if (spotifyParam === "profile_error") return "Could not fetch your Spotify profile. Please try again.";
    return null;
  })();

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
          {spotifyStatusMessage ? (
            <p className="muted" style={{ marginBottom: 12 }}>{spotifyStatusMessage}</p>
          ) : null}
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
            {spotifyConnection && !spotifyConnection.revokedAt ? (
              <form action="/api/spotify/disconnect" method="post">
                <button className="button button--ghost" type="submit">
                  Disconnect Spotify
                </button>
              </form>
            ) : null}
            <Link className="pill-link" href="/dashboard/tokens">
              Manage API tokens
            </Link>
          </div>
        </article>
      </section>
    </AppShell>
  );
}
