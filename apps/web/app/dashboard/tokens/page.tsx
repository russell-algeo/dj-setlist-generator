import { AppShell } from "@/components/app-shell";
import { requireSessionActor } from "@/lib/auth/session";
import { formatTimestamp } from "@/lib/format";
import { listApiTokensForUser } from "@/lib/jobs/service";

export default async function DashboardTokensPage() {
  const actor = await requireSessionActor("/dashboard/tokens");
  const tokens = actor.isAllowlisted ? await listApiTokensForUser(actor.userId) : [];

  return (
    <AppShell
      title="API tokens"
      eyebrow="CLI auth"
      description="Mint bearer tokens for the remote Python CLI. Tokens are hashed at rest and only shown once when the API returns them."
    >
      {!actor.isAllowlisted ? (
        <section className="panel">
          <h2>Allowlist required</h2>
          <p>Only allowlisted operators can mint CLI tokens.</p>
        </section>
      ) : (
        <>
          <section className="panel">
            <h2>Create token</h2>
            <p style={{ marginBottom: 16 }}>
              This form posts to the token API and returns the plain token once. Use it with
              <span className="mono"> python -m worker.cli auth login --token ...</span>.
            </p>
            <form action="/api/tokens" className="stack-form" method="post" target="_blank">
              <input name="name" placeholder="Laptop CLI token" required type="text" />
              <button className="button" type="submit">
                Mint token
              </button>
            </form>
          </section>

          <section className="panel" style={{ marginTop: 24 }}>
            <h2>Active tokens</h2>
            {tokens.length > 0 ? (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Prefix</th>
                    <th>Last used</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {tokens.map((token) => (
                    <tr key={token.id}>
                      <td>{token.name}</td>
                      <td className="mono">{token.tokenPrefix}</td>
                      <td>{token.lastUsedAt ? formatTimestamp(token.lastUsedAt) : "never"}</td>
                      <td>
                        <form action={`/api/tokens/${token.id}`} method="post">
                          <input name="_method" type="hidden" value="delete" />
                          <button className="button button--ghost" type="submit">
                            Revoke
                          </button>
                        </form>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="empty-state">No active tokens yet.</div>
            )}
          </section>
        </>
      )}
    </AppShell>
  );
}
