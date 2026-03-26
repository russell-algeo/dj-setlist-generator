import { redirect } from "next/navigation";

import { AppShell } from "@/components/app-shell";
import { GoogleSignInButton } from "@/components/google-sign-in-button";
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

  if (actor) {
    redirect(callbackUrl);
  }

  return (
    <AppShell
      title="Operator sign-in"
      eyebrow="Auth.js + Google"
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
          <h2>Google sign-in</h2>
          {env.authGoogleId && env.authGoogleSecret ? (
            <>
              <p style={{ marginBottom: 18 }}>
                Use the seeded Google account to bootstrap the first admin session once the OAuth app is configured.
              </p>
              <GoogleSignInButton callbackUrl={callbackUrl} />
            </>
          ) : (
            <div className="empty-state">
              Google OAuth has not been configured yet. Once the Vercel URL exists, add the Google app credentials
              and this sign-in flow will go live.
            </div>
          )}
        </article>
      </section>
    </AppShell>
  );
}
