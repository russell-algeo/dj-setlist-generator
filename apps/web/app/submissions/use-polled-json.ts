"use client";

import { startTransition, useEffect, useEffectEvent, useState } from "react";

type UsePolledJsonOptions<T> = {
  initialData: T;
  url: string;
  shouldPoll: (data: T) => boolean;
  parseResponse?: (response: Response) => Promise<T>;
  intervalMs?: number;
};

const defaultParseResponse = async <T,>(response: Response) => (await response.json()) as T;

export const usePolledJson = <T,>({
  initialData,
  url,
  shouldPoll,
  parseResponse = defaultParseResponse<T>,
  intervalMs = 5_000,
}: UsePolledJsonOptions<T>) => {
  const [data, setData] = useState(initialData);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState(() => new Date().toISOString());

  useEffect(() => {
    setData(initialData);
    setRefreshError(null);
    setLastUpdatedAt(new Date().toISOString());
  }, [initialData, url]);

  const refreshNow = useEffectEvent(async () => {
    if (typeof document !== "undefined" && document.visibilityState === "hidden") {
      return;
    }

    setIsRefreshing(true);

    try {
      const response = await fetch(url, {
        cache: "no-store",
        headers: {
          accept: "application/json",
        },
      });

      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error((body as { error?: string }).error ?? `HTTP ${response.status}`);
      }

      const next = await parseResponse(response);
      startTransition(() => {
        setData(next);
        setRefreshError(null);
        setLastUpdatedAt(new Date().toISOString());
      });
    } catch (error) {
      setRefreshError(error instanceof Error ? error.message : "Refresh failed");
    } finally {
      setIsRefreshing(false);
    }
  });

  useEffect(() => {
    if (!shouldPoll(data)) {
      return;
    }

    const handleVisibility = () => {
      if (document.visibilityState !== "visible") {
        return;
      }

      void refreshNow();
    };

    const intervalId = window.setInterval(() => {
      void refreshNow();
    }, intervalMs);

    document.addEventListener("visibilitychange", handleVisibility);
    window.addEventListener("focus", handleVisibility);

    return () => {
      window.clearInterval(intervalId);
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("focus", handleVisibility);
    };
  }, [data, intervalMs, refreshNow, shouldPoll]);

  return {
    data,
    isRefreshing,
    refreshError,
    lastUpdatedAt,
    refreshNow,
    setData,
  };
};
