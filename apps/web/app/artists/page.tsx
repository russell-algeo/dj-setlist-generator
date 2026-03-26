import Link from "next/link";

import { AppShell } from "@/components/app-shell";
import { getArchiveStats, listArtists } from "@/lib/archive/repository";

type ArtistsPageProps = {
  searchParams: Promise<{
    q?: string;
  }>;
};

export default async function ArtistsPage({ searchParams }: ArtistsPageProps) {
  const params = await searchParams;
  const query = params.q?.trim();
  const [artistRows, stats] = await Promise.all([listArtists(query), getArchiveStats()]);

  return (
    <AppShell
      title="Artist index"
      eyebrow="Public archive"
      description="Canonical routes for the imported archive. Each artist resolves back to the exact legacy explorer page stored in Neon."
    >
      <section className="panel-grid panel-grid--three">
        <article className="panel">
          <p className="app-shell__eyebrow">Artists</p>
          <p className="stat-value">{stats.artistCount}</p>
        </article>
        <article className="panel">
          <p className="app-shell__eyebrow">Imported sets</p>
          <p className="stat-value">{stats.setCount}</p>
        </article>
        <article className="panel">
          <p className="app-shell__eyebrow">Search mode</p>
          <p className="muted">{query ? `Filtering for “${query}”` : "Showing the strongest imported artist entities first."}</p>
        </article>
      </section>

      <section className="panel" style={{ marginTop: 24 }}>
        <div className="list-toolbar">
          <h2>Browse artists</h2>
          <form className="search-form" action="/artists">
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
                      {artist.setCount} imported set{artist.setCount === 1 ? "" : "s"}
                    </p>
                  </div>
                  <div className="inline-actions">
                    <Link className="pill-link" href={`/artists/${artist.slug}`}>
                      Canonical route
                    </Link>
                    {artist.legacyPath ? (
                      <Link className="pill-link" href={artist.legacyPath}>
                        Legacy page
                      </Link>
                    ) : null}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <div className="empty-state">No artists matched that search.</div>
        )}
      </section>
    </AppShell>
  );
}
