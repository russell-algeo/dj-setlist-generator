import Link from "next/link";

import { AppShell } from "@/components/app-shell";
import { listSets } from "@/lib/archive/repository";

type SetsPageProps = {
  searchParams: Promise<{
    page?: string;
    q?: string;
  }>;
};

const formatDuration = (value: number | null) => {
  if (!value) {
    return "Unknown duration";
  }

  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);

  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }

  return `${minutes}m`;
};

export default async function SetsPage({ searchParams }: SetsPageProps) {
  const params = await searchParams;
  const page = Number(params.page ?? "1");
  const query = params.q?.trim();
  const { items, totalItems, pageSize } = await listSets({ page, search: query });
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));

  return (
    <AppShell
      title="Set library"
      eyebrow="Public archive"
      description="Each set has a stable app-owned alias and a stored legacy explorer page. Today the alias resolves to that stored page."
    >
      <section className="panel">
        <div className="list-toolbar">
          <div>
            <h2>Imported sets</h2>
            <p className="muted">
              {totalItems} total set{totalItems === 1 ? "" : "s"}
            </p>
          </div>
          <form action="/sets" className="search-form">
            <input
              aria-label="Search sets"
              defaultValue={query}
              name="q"
              placeholder="Search set title or uploader"
              type="search"
            />
            <button className="button" type="submit">
              Search
            </button>
          </form>
        </div>

        {items.length > 0 ? (
          <ul className="card-list">
            {items.map((item) => (
              <li className="card-list__item" key={item.id}>
                <div className="inline-actions" style={{ justifyContent: "space-between" }}>
                  <div>
                    <h3>{item.title}</h3>
                    <div className="card-list__meta">
                      <span>{item.uploader ?? "Unknown uploader"}</span>
                      <span>{formatDuration(item.durationSeconds ?? null)}</span>
                      <span>{item.sourcePlatform ?? "unknown"}</span>
                      <span>
                        {item.recognitionRate != null ? `${item.recognitionRate}% recognition` : "Recognition pending"}
                      </span>
                    </div>
                  </div>
                  <div className="inline-actions">
                    <Link className="pill-link" href={`/sets/${item.slug}`}>
                      Stable alias
                    </Link>
                    {item.legacyPath ? (
                      <Link className="pill-link" href={item.legacyPath}>
                        Stored page
                      </Link>
                    ) : null}
                    {item.sourceUrl ? (
                      <Link className="pill-link" href={item.sourceUrl} rel="noreferrer" target="_blank">
                        Source
                      </Link>
                    ) : null}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <div className="empty-state">No sets matched that search.</div>
        )}

        <div className="inline-actions" style={{ marginTop: 18 }}>
          {page > 1 ? (
            <Link
              className="pill-link"
              href={`/sets?page=${page - 1}${query ? `&q=${encodeURIComponent(query)}` : ""}`}
            >
              Previous
            </Link>
          ) : null}
          {page < totalPages ? (
            <Link
              className="pill-link"
              href={`/sets?page=${page + 1}${query ? `&q=${encodeURIComponent(query)}` : ""}`}
            >
              Next
            </Link>
          ) : null}
          <span className="muted mono">
            Page {Math.min(Math.max(page, 1), totalPages)} of {totalPages}
          </span>
        </div>
      </section>
    </AppShell>
  );
}
