"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";

type UserStatusResponse = {
  spotifyConfigured: boolean;
  spotifyConnected: boolean;
};

export const useSpotifyExportStatus = () => {
  const { data: session, status } = useSession();
  const [spotifyConnected, setSpotifyConnected] = useState<boolean | null>(null);
  const [spotifyConfigured, setSpotifyConfigured] = useState<boolean | null>(null);

  useEffect(() => {
    if (!session?.user) {
      setSpotifyConnected(null);
      setSpotifyConfigured(null);
      return;
    }

    let cancelled = false;

    fetch("/api/user/status")
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        return response.json() as Promise<UserStatusResponse>;
      })
      .then((payload) => {
        if (!cancelled) {
          setSpotifyConnected(payload.spotifyConnected);
          setSpotifyConfigured(payload.spotifyConfigured);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSpotifyConnected(false);
          setSpotifyConfigured(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [session?.user]);

  const isAuthenticated = Boolean(session?.user);
  const isLoading =
    status === "loading" ||
    (isAuthenticated && (spotifyConnected === null || spotifyConfigured === null));

  return {
    isAuthenticated,
    isLoading,
    spotifyConfigured: spotifyConfigured ?? false,
    spotifyConnected: spotifyConnected ?? false,
  };
};
