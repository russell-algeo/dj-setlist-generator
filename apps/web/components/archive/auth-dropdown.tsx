"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { signIn, signOut, useSession } from "next-auth/react";

import styles from "./auth-dropdown.module.css";

type AuthProviderId = "spotify" | "google";

const SIGN_IN_PROVIDER_ORDER: AuthProviderId[] = ["spotify", "google"];

const SIGN_IN_PROVIDER_LABELS: Record<AuthProviderId, string> = {
  google: "Sign in with Google",
  spotify: "Sign in with Spotify",
};

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

function getSpotifyConnectionCallbackUrl() {
  const url = new URL(window.location.href);
  url.searchParams.set("spotify", "connected");

  return url.toString();
}

function getSignInCallbackUrl() {
  const url = new URL(window.location.href);
  const callbackUrl = url.searchParams.get("callbackUrl");

  if (callbackUrl?.startsWith("/") && !callbackUrl.startsWith("//")) {
    return callbackUrl;
  }

  return window.location.href;
}

export function AuthDropdown() {
  const { data: session } = useSession();
  const [open, setOpen] = useState(false);
  const [spotifyConnected, setSpotifyConnected] = useState<boolean | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const sessionUserEmail = session?.user?.email;

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

  // Fetch a fresh Spotify status every time the signed-in dropdown opens.
  useEffect(() => {
    if (!open || !sessionUserEmail) {
      return;
    }

    const controller = new AbortController();
    setSpotifyConnected(null);

    fetch("/api/user/status", {
      cache: "no-store",
      signal: controller.signal,
    })
      .then((r) => r.json())
      .then((data: { spotifyConnected: boolean }) => setSpotifyConnected(data.spotifyConnected))
      .catch((error: Error) => {
        if (error.name !== "AbortError") {
          setSpotifyConnected(false);
        }
      });

    return () => controller.abort();
  }, [open, sessionUserEmail]);

  if (!session?.user) {
    return (
      <div className={styles.container} ref={containerRef}>
        <button
          aria-expanded={open}
          className={styles.trigger}
          onClick={() => setOpen((value) => !value)}
          type="button"
        >
          Sign in
        </button>

        {open ? (
          <div className={styles.dropdown}>
            <div className={styles.signInMenu}>
              {SIGN_IN_PROVIDER_ORDER.map((provider) => (
                <button
                  className={styles.providerAction}
                  key={provider}
                  onClick={() => signIn(provider, { callbackUrl: getSignInCallbackUrl() })}
                  type="button"
                >
                  {SIGN_IN_PROVIDER_LABELS[provider]}
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </div>
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
              <button
                className={styles.menuActionGreen}
                onClick={() =>
                  signIn("spotify", { callbackUrl: getSpotifyConnectionCallbackUrl() })
                }
                type="button"
              >
                + Connect
              </button>
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
