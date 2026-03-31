"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { signIn, signOut, useSession } from "next-auth/react";

import styles from "./auth-dropdown.module.css";

function getInitials(name: string | null | undefined, email: string | null | undefined): string {
  if (name) {
    return name
      .split(" ")
      .map((part) => part[0])
      .join("")
      .toUpperCase()
      .slice(0, 2);
  }
  return email?.slice(0, 2).toUpperCase() ?? "?";
}

export function AuthDropdown() {
  const { data: session } = useSession();
  const [open, setOpen] = useState(false);
  const [spotifyConnected, setSpotifyConnected] = useState<boolean | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Fetch Spotify status when dropdown opens
  useEffect(() => {
    if (open && session?.user && spotifyConnected === null) {
      fetch("/api/user/status")
        .then((r) => r.json())
        .then((data: { spotifyConnected: boolean }) => setSpotifyConnected(data.spotifyConnected))
        .catch(() => setSpotifyConnected(false));
    }
  }, [open, session, spotifyConnected]);

  if (!session?.user) {
    return (
      <button
        className={styles.trigger}
        onClick={() => signIn()}
        type="button"
      >
        Sign In
      </button>
    );
  }

  const { user } = session;
  const initials = getInitials(user.name, user.email);

  return (
    <div className={styles.container} ref={containerRef}>
      <div
        className={styles.avatar}
        onClick={() => setOpen((v) => !v)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === "Enter" && setOpen((v) => !v)}
      >
        {initials}
      </div>

      {open && (
        <div className={styles.dropdown}>
          <div className={styles.userRow}>
            <div className={styles.avatarLg}>{initials}</div>
            <div>
              <div className={styles.userName}>
                {user.name ?? user.email}
                {user.isAdmin && <span className={styles.badge}>Admin</span>}
              </div>
              <div className={styles.userEmail}>{user.email}</div>
            </div>
          </div>

          <div className={styles.menuRow}>
            <span className={styles.menuLabel}>Spotify</span>
            {spotifyConnected === null ? (
              <span className={styles.menuAction}>…</span>
            ) : spotifyConnected ? (
              <span className={styles.menuActionGreenActive}>● Connected</span>
            ) : (
              <a
                className={styles.menuActionGreen}
                href="/api/spotify/start"
              >
                + Connect
              </a>
            )}
          </div>

          <div className={styles.menuRow}>
            <span className={styles.menuLabel}>My Submissions</span>
            <Link
              className={styles.menuAction}
              href="/submissions"
              onClick={() => setOpen(false)}
            >
              View →
            </Link>
          </div>

          {user.isAdmin && (
            <div className={styles.menuRow}>
              <span className={styles.menuLabel}>Admin Panel</span>
              <Link
                className={styles.menuAction}
                href="/admin"
                onClick={() => setOpen(false)}
              >
                Open →
              </Link>
            </div>
          )}

          <div className={styles.menuRow}>
            <span className={styles.menuLabel}>Sign out</span>
            <button
              className={styles.menuActionDanger}
              onClick={() => signOut({ callbackUrl: "/" })}
              type="button"
            >
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
