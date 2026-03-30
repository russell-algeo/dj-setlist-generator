/* eslint-disable @next/next/no-img-element */
// Archive artwork comes from third-party sources with unbounded hosts, so the preview uses raw img tags for parity.
import Link from "next/link";

import { ArchiveArtistExplorer } from "@/components/archive/archive-artist-explorer";
import { ArchiveHomeConnectionsSection } from "@/components/archive/archive-home-connections";
import { ArchiveScrollRoot } from "@/components/archive/archive-scroll-root";
import { ArchiveSetExplorer } from "@/components/archive/archive-set-explorer";
import type {
  ArchiveArtistSummary,
  ArchiveHomeBaseSummary,
  ArchiveSetDetail,
} from "@/lib/archive/types";

import { buildArtistHref, buildSetHref } from "./archive-hrefs";
import styles from "./archive-page.module.css";

const TrackMetaPill = ({ children }: { children: React.ReactNode }) => (
  <span className={styles.pill}>{children}</span>
);

export function ArchiveHomePage({
  summary,
  preview,
}: {
  summary: ArchiveHomeBaseSummary;
  preview: boolean;
}) {
  const totalPages = Math.max(1, Math.ceil(summary.setLibrary.totalItems / summary.setLibrary.pageSize));
  const searchBase = preview ? "/archive-preview" : "/";
  const encodedQuery = summary.setLibrary.query
    ? `&q=${encodeURIComponent(summary.setLibrary.query)}`
    : "";

  return (
    <div className={styles.page}>
      <ArchiveScrollRoot />
      <header className={styles.topbar}>
        <div className={styles.topbarInner}>
          <div className={styles.brand}>[SET SIGNAL ARCHIVE]</div>
          <nav className={styles.nav}>
            <a href="#artists">Artist Atlas</a>
            <a href="#connections">Artist Connections</a>
            <a href="#sets">Set Library</a>
          </nav>
        </div>
      </header>

      <main className={styles.shell}>
        <section className={styles.section}>
          <div className={styles.kicker}>Outcome-Driven Music Intelligence</div>
          <div className={styles.heroGrid}>
            <div className={styles.heroMain}>
              <div className={styles.heroVisual}>
                <div className={styles.heroOverlay}>
                  <h1 className={styles.heroTitle}>Set Signal Archive</h1>
                  <p className={styles.heroCopy}>
                    React-native archive surfaces backed by structured data only. No page HTML is read from Neon at runtime.
                  </p>
                  <div className={styles.pillRow}>
                    <TrackMetaPill>{summary.globalStats.totalArtists} artists</TrackMetaPill>
                    <TrackMetaPill>{summary.globalStats.totalSets} sets</TrackMetaPill>
                    <TrackMetaPill>{summary.globalStats.totalRecognizedTracks} recognized tracks</TrackMetaPill>
                    <TrackMetaPill>
                      {Math.round((1 - summary.globalStats.unknownRatio) * 100)}% identified
                    </TrackMetaPill>
                  </div>
                </div>
              </div>
              <div className={styles.statGrid}>
                <article className={styles.statCard}>
                  <span className={styles.statValue}>{summary.globalStats.totalArtists}</span>
                  <span className={styles.statLabel}>Artists</span>
                </article>
                <article className={styles.statCard}>
                  <span className={styles.statValue}>{summary.globalStats.totalSets}</span>
                  <span className={styles.statLabel}>Sets</span>
                </article>
                <article className={styles.statCard}>
                  <span className={styles.statValue}>{summary.globalStats.totalTrackEntries}</span>
                  <span className={styles.statLabel}>Track entries</span>
                </article>
                <article className={styles.statCard}>
                  <span className={styles.statValue}>
                    {Math.round(summary.globalStats.unknownRatio * 100)}%
                  </span>
                  <span className={styles.statLabel}>Unknown ratio</span>
                </article>
              </div>
            </div>

            <aside className={styles.heroSide}>
              <div className={styles.cardColumn}>
                {summary.featuredArtists.slice(0, 4).map((artist) => (
                  <Link
                    className={styles.heroCard}
                    href={buildArtistHref({
                      preview,
                      slug: artist.slug,
                      legacyPath: artist.legacyPath,
                    })}
                    key={artist.id}
                  >
                    <div className={styles.cardMedia}>
                      {artist.imageUrl ? <img alt="" src={artist.imageUrl} /> : null}
                    </div>
                    <div>
                      <div className={styles.cardEyebrow}>{artist.setCount} sets</div>
                      <p className={styles.cardTitle}>{artist.name}</p>
                      <div className={styles.muted}>
                        {artist.latestSetTitle ?? "Structured archive artist route"}
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            </aside>
          </div>
        </section>

        <section className={styles.section} id="artists">
          <div className={styles.kicker}>Artist Atlas</div>
          <h2 className={styles.sectionHeading}>Featured Artists</h2>
          <p className={styles.sectionLead}>
            Stable aliases continue to exist, but the target state is React-rendered archive pages driven by structured data and invalidated on publish.
          </p>
          <div className={styles.entityGrid} style={{ marginTop: 18 }}>
            {summary.featuredArtists.map((artist) => (
              <article className={styles.entityCard} key={artist.id}>
                <div className={styles.cardMedia}>
                  {artist.imageUrl ? <img alt="" src={artist.imageUrl} /> : null}
                </div>
                <div className={styles.cardEyebrow}>{artist.setCount} sets</div>
                <h3 className={styles.cardTitle}>{artist.name}</h3>
                <div className={styles.muted}>
                  {artist.latestSetTitle ?? "No canonical legacy set recorded yet."}
                </div>
                <div className={styles.actionRow}>
                  <Link
                    className={styles.linkButton}
                    href={buildArtistHref({
                      preview,
                      slug: artist.slug,
                      legacyPath: artist.legacyPath,
                    })}
                  >
                    Open artist
                  </Link>
                  {!preview && artist.legacyPath ? (
                    <Link className={styles.linkButton} href={artist.legacyPath}>
                      Legacy URL
                    </Link>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        </section>

        <ArchiveHomeConnectionsSection preview={preview} />

        <section className={styles.section} id="sets">
          <div className={styles.kicker}>Full Set Library</div>
          <h2 className={styles.sectionHeading}>Browse Imported Sets</h2>
          <div className={styles.searchBar}>
            <form action={searchBase} className={styles.inlineForm}>
              <input
                defaultValue={summary.setLibrary.query}
                name="q"
                placeholder="Search set title or uploader"
                type="search"
              />
              <button type="submit">Search</button>
            </form>
            <span className={styles.muted}>
              Page {summary.setLibrary.page} of {totalPages}
            </span>
          </div>
          <div className={styles.entityGrid} style={{ marginTop: 18 }}>
            {summary.setLibrary.items.map((setCard) => (
              <article className={styles.entityCard} key={setCard.id}>
                <div className={styles.cardMedia}>
                  {setCard.thumbnailUrl ? <img alt="" src={setCard.thumbnailUrl} /> : null}
                </div>
                <div className={styles.cardEyebrow}>
                  {setCard.artistName ?? "Unknown artist"} · {setCard.durationFmt}
                </div>
                <h3 className={styles.cardTitle}>{setCard.title}</h3>
                <div className={styles.metaRow}>
                  <TrackMetaPill>{setCard.totalTracks} tracks</TrackMetaPill>
                  {setCard.recognitionRate != null ? (
                    <TrackMetaPill>{Math.round(setCard.recognitionRate)}% recognition</TrackMetaPill>
                  ) : null}
                </div>
                <div className={styles.actionRow}>
                  <Link
                    className={styles.linkButton}
                    href={buildSetHref({
                      preview,
                      slug: setCard.slug,
                      legacyPath: setCard.legacyPath,
                    })}
                  >
                    Open set
                  </Link>
                  {setCard.sourceUrl ? (
                    <Link className={styles.linkButton} href={setCard.sourceUrl} rel="noreferrer" target="_blank">
                      Source
                    </Link>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
          <div className={styles.actionRow} style={{ marginTop: 18 }}>
            {summary.setLibrary.page > 1 ? (
              <Link
                className={styles.linkButton}
                href={`${searchBase}?page=${summary.setLibrary.page - 1}${encodedQuery}`}
              >
                Previous
              </Link>
            ) : null}
            {summary.setLibrary.page < totalPages ? (
              <Link
                className={styles.linkButton}
                href={`${searchBase}?page=${summary.setLibrary.page + 1}${encodedQuery}`}
              >
                Next
              </Link>
            ) : null}
          </div>
        </section>

        <footer className={styles.footer}>
          Generated from normalized archive rows at {summary.generatedAt ?? "unknown time"}.
        </footer>
      </main>
    </div>
  );
}

export function ArchiveArtistPage({
  artist,
  preview,
  query,
}: {
  artist: ArchiveArtistSummary;
  preview: boolean;
  query: string;
}) {
  return <ArchiveArtistExplorer artist={artist} initialQuery={query} preview={preview} />;
}

export function ArchiveSetPage({
  detail,
  query,
}: {
  detail: ArchiveSetDetail;
  preview: boolean;
  query: string;
}) {
  return <ArchiveSetExplorer detail={detail} initialQuery={query} />;
}
