import { redirect } from "next/navigation";

import { AppShell } from "@/components/app-shell";
import { GoogleSignInButton, SpotifySignInButton } from "@/components/google-sign-in-button";
import { getSessionActor } from "@/lib/auth/session";
import { env } from "@/lib/env";

type SignInPageProps = {
  searchParams: Promise<{
    callbackUrl?: string;
  }>;
};

export default async function SignInPage({ searchParams }: SignInPageProps) {
  const actor = await getSessionActor();
  const params = await searchParams;
  const callbackUrl = params.callbackUrl ?? "/dashboard";
  const googleConfigured = Boolean(env.authGoogleId && env.authGoogleSecret);
  const spotifyConfigured = Boolean(env.spotifyClientId && env.spotifyClientSecret);

  if (actor) {
    redirect(callbackUrl);
  }

  return (
    <AppShell
      title="Operator sign-in"
      eyebrow="Auth.js"
      description="The public archive stays open. Sign-in is only required for submissions, Spotify connections, API token minting, and worker controls."
    >
      <section className="panel-grid panel-grid--two">
        <article className="panel">
          <h2>Access policy</h2>
          <p>
            Signed-in users can browse the operator surface, but only allowlisted accounts can submit jobs,
            connect Spotify, or mint API tokens.
          </p>
          <div className="card-list__meta">
            <span>Seed admin: {env.initialAdminEmail}</span>
            <span>Public archive remains anonymous</span>
          </div>
        </article>
        <article className="panel">
          <h2>Sign in</h2>
          {spotifyConfigured ? (
            <div style={{ marginBottom: 12 }}>
              <SpotifySignInButton callbackUrl={callbackUrl} />
            </div>
          ) : null}
          {googleConfigured ? (
            <div style={{ marginBottom: 12 }}>
              <GoogleSignInButton callbackUrl={callbackUrl} />
            </div>
          ) : null}
          {spotifyConfigured ? (
            <p className="muted" style={{ marginTop: 6 }}>
              Spotify sign-in also connects playlist export permissions.
            </p>
          ) : null}
          {!googleConfigured && !spotifyConfigured ? (
            <div className="empty-state">
              OAuth has not been configured yet. Once the Vercel URL exists, add provider credentials
              and this sign-in flow will go live.
            </div>
          ) : null}
        </article>
      </section>
    </AppShell>
  );
}
