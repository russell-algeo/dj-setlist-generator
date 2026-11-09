"use client";
import { useEffect, useState, type ReactNode } from "react";
import { useSession } from "next-auth/react";

// Server routes are the security boundary. This also removes an already-rendered
// player when the signed-in account changes or a periodic access check fails.
export function YoonAccessBoundary({ viewerId, children }: { viewerId: string; children: ReactNode }) {
  const { data: session, status } = useSession();
  const [permitted, setPermitted] = useState(true);
  useEffect(() => {
    let disposed = false;
    const controller = new AbortController();
    const check = async () => {
      try {
        const response = await fetch("/api/yoon-fest/access", { cache: "no-store", credentials: "same-origin", signal: controller.signal });
        if (!disposed && !response.ok) setPermitted(false);
      } catch { if (!disposed) setPermitted(false); }
    };
    const onVisibility = () => { if (!document.hidden) void check(); };
    const timer = window.setInterval(() => void check(), 60_000);
    window.addEventListener("focus", check);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      disposed = true;
      controller.abort();
      window.clearInterval(timer);
      window.removeEventListener("focus", check);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [viewerId]);
  if (!permitted || status === "unauthenticated" || (status === "authenticated" && session.user?.id !== viewerId)) {
    return <p role="alert">Private access is no longer available. Sign in with your authorized account and reload.</p>;
  }
  return children;
}
