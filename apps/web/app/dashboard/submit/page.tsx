import { AppShell } from "@/components/app-shell";
import { requireSessionActor } from "@/lib/auth/session";

export default async function DashboardSubmitPage() {
  const actor = await requireSessionActor("/dashboard/submit");

  return (
    <AppShell
      title="Submit work"
      eyebrow="Operator actions"
      description="Queue single-set processing, artist discovery, or curated artist batches. Forms post directly to the remote job API."
    >
      {!actor.isAllowlisted ? (
        <section className="panel">
          <h2>Allowlist required</h2>
          <p>Your account is authenticated but cannot submit jobs until an admin promotes it.</p>
        </section>
      ) : (
        <section className="panel-grid panel-grid--three">
          <article className="panel">
            <h2>Single set URL</h2>
            <form action="/api/jobs" className="stack-form" method="post">
              <input name="mode" type="hidden" value="url" />
              <input name="sourceUrl" placeholder="https://www.youtube.com/watch?v=..." required type="url" />
              <label>
                <input name="createPlaylist" type="checkbox" value="true" /> Create Spotify playlist
              </label>
              <button className="button" type="submit">
                Queue set
              </button>
            </form>
          </article>

          <article className="panel">
            <h2>Artist discovery</h2>
            <form action="/api/jobs" className="stack-form" method="post">
              <input name="mode" type="hidden" value="artist" />
              <input name="artistName" placeholder="Artist name" required type="text" />
              <input min="1" name="maxSetsOverride" placeholder="Max sets override (optional)" type="number" />
              <label>
                <input name="createPlaylist" type="checkbox" value="true" /> Create Spotify playlist
              </label>
              <button className="button" type="submit">
                Discover sets
              </button>
            </form>
          </article>

          <article className="panel">
            <h2>Curated artist batch</h2>
            <form action="/api/jobs" className="stack-form" method="post">
              <input name="mode" type="hidden" value="curated_artist" />
              <input name="artistName" placeholder="Artist name" required type="text" />
              <textarea
                name="sourceUrls"
                placeholder={"One URL per line\nhttps://...\nhttps://..."}
                required
              />
              <label>
                <input name="createPlaylist" type="checkbox" value="true" /> Create Spotify playlist
              </label>
              <button className="button" type="submit">
                Queue curated batch
              </button>
            </form>
          </article>
        </section>
      )}
    </AppShell>
  );
}
