"use client";
import type { ReactNode } from "react";
import { useSession } from "next-auth/react";

// Server page loads and new app API/media-link requests enforce membership.
// Do not recheck membership on a timer, focus, or visibility change: an already
// open page intentionally retains its loaded content after membership revocation.
// Later server requests authorize separately; they do not clear this page.
// Still remove its private content when the session reports sign-out/account change.
export function YoonAccessBoundary({ viewerId, children }: { viewerId: string; children: ReactNode }) {
  const { data: session, status } = useSession();
  if (status === "unauthenticated" || (status === "authenticated" && session.user?.id !== viewerId)) {
    return <p role="alert">Private access is no longer available. Sign in with your authorized account and reload.</p>;
  }
  return children;
}
