"use client";

import Link from "next/link";
import { startTransition, useEffect, useRef, useState } from "react";

import type { ArchiveHomeConnection, ArchiveHomeConnectionsResponse } from "@/lib/archive/types";

import { buildArtistHref } from "./archive-hrefs";
import styles from "./archive-page.module.css";

const ConnectionCards = ({
  connections,
  preview,
}: {
  connections: ArchiveHomeConnection[];
  preview: boolean;
}) => {
  if (connections.length === 0) {
    return <div className={styles.emptyState}>No cross-artist track overlap is available yet.</div>;
  }

  return (
    <>
      {connections.map((connection) => (
        <article className={styles.connectionCard} key={`${connection.artistASlug}:${connection.artistBSlug}`}>
          <div className={styles.cardEyebrow}>{connection.sharedTracks} shared tracks</div>
          <h3 className={styles.cardTitle}>
            {connection.artistA} × {connection.artistB}
          </h3>
          <div className={styles.actionRow}>
            <Link
              className={styles.linkButton}
              href={buildArtistHref({
                preview,
                slug: connection.artistASlug,
                legacyPath: connection.artistALegacyPath,
              })}
            >
              {connection.artistA}
            </Link>
            <Link
              className={styles.linkButton}
              href={buildArtistHref({
                preview,
                slug: connection.artistBSlug,
                legacyPath: connection.artistBLegacyPath,
              })}
            >
              {connection.artistB}
            </Link>
          </div>
        </article>
      ))}
    </>
  );
};

export function ArchiveHomeConnectionsSection({
  preview,
}: {
  preview: boolean;
}) {
  const sectionRef = useRef<HTMLElement | null>(null);
  const [payload, setPayload] = useState<ArchiveHomeConnectionsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hasStarted, setHasStarted] = useState(false);

  useEffect(() => {
    const node = sectionRef.current;
    if (!node || hasStarted) {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) {
          return;
        }

        setHasStarted(true);
        observer.disconnect();
      },
      {
        rootMargin: "240px 0px",
      },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, [hasStarted]);

  useEffect(() => {
    if (!hasStarted || payload || error) {
      return;
    }

    let cancelled = false;

    const load = async () => {
      try {
        const response = await fetch("/api/archive/home/connections", {
          method: "GET",
          headers: {
            accept: "application/json",
          },
        });

        if (!response.ok) {
          throw new Error(`Connection load failed with ${response.status}`);
        }

        const nextPayload = (await response.json()) as ArchiveHomeConnectionsResponse;
        if (!cancelled) {
          startTransition(() => {
            setPayload(nextPayload);
          });
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Connection load failed");
        }
      }
    };

    void load();

    return () => {
      cancelled = true;
    };
  }, [error, hasStarted, payload]);

  return (
    <section className={styles.section} id="connections" ref={sectionRef}>
      <div className={styles.kicker}>Artist Connection Map</div>
      <h2 className={styles.sectionHeading}>Shared Track Signals</h2>
      <p className={styles.sectionLead}>
        This section now loads on demand so initial home requests do not precompute the full cross-artist overlap graph.
      </p>
      <div className={styles.gridTwo} style={{ marginTop: 18 }}>
        {payload ? (
          <ConnectionCards connections={payload.connections} preview={preview} />
        ) : error ? (
          <div className={styles.emptyState}>Unable to load shared-track connections right now.</div>
        ) : (
          <div className={styles.emptyState}>
            {hasStarted ? "Loading shared-track connections…" : "Connection data will load when this section enters view."}
          </div>
        )}
      </div>
    </section>
  );
}
