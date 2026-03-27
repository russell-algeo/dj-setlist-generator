import Link from "next/link";

import { AppShell } from "@/components/app-shell";
import { getArchiveStats, listArtists } from "@/lib/archive/repository";
import { getSessionActor } from "@/lib/auth/session";

type ArtistsPageProps = {
  searchParams: Promise<{
    q?: string;
    scope?: string;
  }>;
};

export default async function ArtistsPage({ searchParams }: ArtistsPageProps) {
  const params = await searchParams;
  const query = params.q?.trim();
  const scope = params.scope === "mine" ? "mine" : "global";
  const isPersonal = scope === "mine";

  const actor = await getSessionActor();

  // Build tab hrefs — preserve search query, always land on page 1
  const myWorkspaceHref = `/artists?scope=mine${query ? `&q=${encodeURIComponent(query)}` : ""}`;
  const globalHref = `/artists${query ? `?q=${encodeURIComponent(query)}` : ""}`;

  // Unauthenticated personal scope — skip DB query
  if (isPersonal && !actor) {
    return (
      <AppShell
        title="Artist index"
        eyebrow="Public archive"
        description="Each artist has a stable app-owned alias and a stored legacy explorer page. Today the alias resolves to that stored page."
      >
        <div className="inline-actions" style={{ marginBottom: 18 }}>
          <Link className="pill-link pill-link--active" href={myWorkspaceHref}>
            My workspace
          </Link>
          <Link className="pill-link" href={globalHref}>
            Global
          </Link>
        </div>

        <section className="panel">
          <div className="empty-state">
            <p>
              <strong>Sign in to see your workspace.</strong>
            </p>
            <p style={{ marginTop: 8 }}>
              Your personal workspace shows only the artists from runs you submitted.
            </p>
            <div style={{ marginTop: 14 }}>
              <Link
                className="pill-link"
                href={`/signin?callbackUrl=${encodeURIComponent(`/artists?scope=mine${query ? `&q=${encodeURIComponent(query)}` : ""}`)}`}
              >
                Sign in →
              </Link>
            </div>
          </div>
        </section>
      </AppShell>
    );
  }

  const userId = isPersonal && actor ? actor.userId : undefined;
  const [artistRows, stats] = await Promise.all([
    listArtists(query, userId),
    isPersonal ? Promise.resolve(null) : getArchiveStats(),
  ]);

  return (
    <AppShell
      title="Artist index"
      eyebrow="Public archive"
      description="Each artist has a stable app-owned alias and a stored legacy explorer page. Today the alias resolves to that stored page."
    >
      <div className="inline-actions" style={{ marginBottom: 18 }}>
        {actor ? (
          <Link
            className={`pill-link${isPersonal ? " pill-link--active" : ""}`}
            href={myWorkspaceHref}
          >
            My workspace
          </Link>
        ) : null}
        <Link
          className={`pill-link${!isPersonal ? " pill-link--active" : ""}`}
          href={globalHref}
        >
          Global
        </Link>
      </div>

      {isPersonal ? (
        <section className="panel-grid panel-grid--two" style={{ marginBottom: 18 }}>
          <article className="panel">
            <p className="app-shell__eyebrow">Your artists</p>
            <p className="stat-value">{artistRows.length}</p>
          </article>
          <article className="panel">
            <p className="app-shell__eyebrow">Search mode</p>
            <p className="muted">
              {query ? `Filtering for "${query}"` : "Showing artists from your submitted runs."}
            </p>
          </article>
        </section>
      ) : (
        <section className="panel-grid panel-grid--three" style={{ marginBottom: 18 }}>
          <article className="panel">
            <p className="app-shell__eyebrow">Artists</p>
            <p className="stat-value">{stats!.artistCount}</p>
          </article>
          <article className="panel">
            <p className="app-shell__eyebrow">Imported sets</p>
            <p className="stat-value">{stats!.setCount}</p>
          </article>
          <article className="panel">
            <p className="app-shell__eyebrow">Search mode</p>
            <p className="muted">
              {query
                ? `Filtering for "${query}"`
                : "Showing the strongest imported artist entities first."}
            </p>
          </article>
        </section>
      )}

      <section className="panel">
        <div className="list-toolbar">
          <h2>{isPersonal ? "Your artists" : "Browse artists"}</h2>
          <form className="search-form" action="/artists">
            {isPersonal ? <input type="hidden" name="scope" value="mine" /> : null}
            <input
              aria-label="Search artists"
              defaultValue={query}
              name="q"
              placeholder="Search artist names"
              type="search"
            />
            <button className="button" type="submit">
              Search
            </button>
          </form>
        </div>

        {artistRows.length > 0 ? (
          <ul className="card-list">
            {artistRows.map((artist) => (
              <li className="card-list__item" key={artist.id}>
                <div className="inline-actions" style={{ justifyContent: "space-between" }}>
                  <div>
                    <h3>{artist.name}</h3>
                    <p className="muted">
                      {artist.setCount} {isPersonal ? "set" : "imported set"}
                      {artist.setCount === 1 ? "" : "s"}
                    </p>
                  </div>
                  <div className="inline-actions">
                    <Link className="pill-link" href={`/artists/${artist.slug}`}>
                      Stable alias
                    </Link>
                    {artist.legacyPath ? (
                      <Link className="pill-link" href={artist.legacyPath}>
                        Stored page
                      </Link>
                    ) : null}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <div className="empty-state">
            {isPersonal
              ? "No artists from your runs yet. Submit a URL from the dashboard to get started."
              : "No artists matched that search."}
          </div>
        )}
      </section>
    </AppShell>
  );
}
