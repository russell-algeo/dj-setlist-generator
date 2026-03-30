import Link from "next/link";

import { AppShell } from "@/components/app-shell";
import { ViewingAsBanner } from "@/components/viewing-as-banner";
import { listSets } from "@/lib/archive/repository";
import { getSessionActor } from "@/lib/auth/session";
import { resolveViewAsActor } from "@/lib/admin/users";

type SetsPageProps = {
  searchParams: Promise<{
    page?: string;
    q?: string;
    scope?: string;
    viewAs?: string;
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

  const actor = await getSessionActor();
  const viewAsActor = actor ? await resolveViewAsActor(actor, params.viewAs) : null;

  // In viewAs mode, always show the target user's workspace
  const scope = viewAsActor ? "mine" : (params.scope === "mine" ? "mine" : "global");
  const isPersonal = scope === "mine";

  // Build tab hrefs — preserve search query, reset page when switching scope
  const myWorkspaceHref = `/sets?scope=mine${query ? `&q=${encodeURIComponent(query)}` : ""}`;
  const globalHref = `/sets${query ? `?q=${encodeURIComponent(query)}` : ""}`;

  // Unauthenticated personal scope — skip DB query
  if (isPersonal && !actor) {
    return (
      <AppShell
        title="Set library"
        eyebrow="Public archive"
        description="Each set has a stable app-owned alias and a stored legacy explorer page. Today the alias resolves to that stored page."
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
              Your personal workspace shows only the sets from runs you submitted.
            </p>
            <div style={{ marginTop: 14 }}>
              <Link
                className="pill-link"
                href={`/signin?callbackUrl=${encodeURIComponent(`/sets?scope=mine${query ? `&q=${encodeURIComponent(query)}` : ""}`)}`}
              >
                Sign in →
              </Link>
            </div>
          </div>
        </section>
      </AppShell>
    );
  }

  const scopedUserId = viewAsActor ? viewAsActor.userId : (isPersonal && actor ? actor.userId : undefined);
  const { items, totalItems, pageSize } = await listSets({ page, search: query, userId: scopedUserId });
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));

  const paginationBase = `/sets?${isPersonal ? "scope=mine&" : ""}${query ? `q=${encodeURIComponent(query)}&` : ""}`;

  return (
    <>
      {viewAsActor && <ViewingAsBanner email={viewAsActor.email} userId={viewAsActor.userId} />}
    <AppShell
      title="Set library"
      eyebrow="Public archive"
      description="Each set has a stable app-owned alias and a stored legacy explorer page. Today the alias resolves to that stored page."
      viewAs={viewAsActor?.userId}
    >
      {!viewAsActor && (
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
      )}

      <section className="panel">
        <div className="list-toolbar">
          <div>
            <h2>{isPersonal ? "Your sets" : "Imported sets"}</h2>
            <p className="muted">
              {totalItems} total set{totalItems === 1 ? "" : "s"}
            </p>
          </div>
          <form action="/sets" className="search-form">
            {isPersonal ? <input type="hidden" name="scope" value="mine" /> : null}
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
                        {item.recognitionRate != null
                          ? `${item.recognitionRate}% recognition`
                          : "Recognition pending"}
                      </span>
                    </div>
                  </div>
                  <div className="inline-actions">
                    <Link className="pill-link" href={`/sets/${item.slug}`}>
                      Stable alias
                    </Link>
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
          <div className="empty-state">
            {isPersonal
              ? "No sets from your runs yet. Submit a URL from the dashboard to get started."
              : "No sets matched that search."}
          </div>
        )}

        <div className="inline-actions" style={{ marginTop: 18 }}>
          {page > 1 ? (
            <Link className="pill-link" href={`${paginationBase}page=${page - 1}`}>
              Previous
            </Link>
          ) : null}
          {page < totalPages ? (
            <Link className="pill-link" href={`${paginationBase}page=${page + 1}`}>
              Next
            </Link>
          ) : null}
          <span className="muted mono">
            Page {Math.min(Math.max(page, 1), totalPages)} of {totalPages}
          </span>
        </div>
      </section>
    </AppShell>
    </>
  );
}
