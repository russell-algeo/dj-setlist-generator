"use client";

import { startTransition, useCallback, useEffect, useRef, useState } from "react";

type UsePolledJsonOptions<T> = {
  initialData: T;
  url: string;
  shouldPoll: (data: T) => boolean;
  parseResponse?: (response: Response) => Promise<T>;
  intervalMs?: number;
  getActivityToken?: (data: T) => string | null;
  inactivityTimeoutMs?: number;
};

const defaultParseResponse = async <T,>(response: Response) => (await response.json()) as T;

export const usePolledJson = <T,>({
  initialData,
  url,
  shouldPoll,
  parseResponse = defaultParseResponse<T>,
  intervalMs = 5_000,
  getActivityToken,
  inactivityTimeoutMs = 5 * 60_000,
}: UsePolledJsonOptions<T>) => {
  const [data, setData] = useState(initialData);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState(() => new Date().toISOString());
  const [isPollingPausedForInactivity, setIsPollingPausedForInactivity] = useState(false);
  const urlRef = useRef(url);
  const parseResponseRef = useRef(parseResponse);
  const shouldPollRef = useRef(shouldPoll);
  const getActivityTokenRef = useRef(getActivityToken);
  const activityTokenRef = useRef<string | null>(getActivityToken?.(initialData) ?? null);
  const lastObservedActivityAtRef = useRef(Date.now());

  urlRef.current = url;
  parseResponseRef.current = parseResponse;
  shouldPollRef.current = shouldPoll;
  getActivityTokenRef.current = getActivityToken;

  useEffect(() => {
    setData(initialData);
    setRefreshError(null);
    setLastUpdatedAt(new Date().toISOString());
    setIsPollingPausedForInactivity(false);
    activityTokenRef.current = getActivityTokenRef.current?.(initialData) ?? null;
    lastObservedActivityAtRef.current = Date.now();
  }, [initialData, url]);

  useEffect(() => {
    const nextActivityToken = getActivityTokenRef.current?.(data) ?? null;
    if (nextActivityToken === activityTokenRef.current) {
      return;
    }

    activityTokenRef.current = nextActivityToken;
    lastObservedActivityAtRef.current = Date.now();
    setIsPollingPausedForInactivity(false);
  }, [data]);

  const refreshNow = useCallback(async () => {
    if (typeof document !== "undefined" && document.visibilityState === "hidden") {
      return;
    }

    setIsRefreshing(true);

    try {
      const response = await fetch(urlRef.current, {
        cache: "no-store",
        headers: {
          accept: "application/json",
        },
      });

      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error((body as { error?: string }).error ?? `HTTP ${response.status}`);
      }

      const next = await parseResponseRef.current(response);
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
  }, []);

  const pauseForInactivityIfNeeded = useCallback(() => {
    if (!getActivityTokenRef.current) {
      return false;
    }

    if (Date.now() - lastObservedActivityAtRef.current < inactivityTimeoutMs) {
      return false;
    }

    setIsPollingPausedForInactivity(true);
    return true;
  }, [inactivityTimeoutMs]);

  useEffect(() => {
    if (shouldPollRef.current(data)) {
      return;
    }

    setIsPollingPausedForInactivity(false);
  }, [data]);

  useEffect(() => {
    if (!shouldPoll(data) || isPollingPausedForInactivity) {
      return;
    }

    if (pauseForInactivityIfNeeded()) {
      return;
    }

    const handleVisibility = () => {
      if (document.visibilityState !== "visible") {
        return;
      }

      if (pauseForInactivityIfNeeded()) {
        return;
      }

      void refreshNow();
    };

    const intervalId = window.setInterval(() => {
      if (pauseForInactivityIfNeeded()) {
        return;
      }

      void refreshNow();
    }, intervalMs);

    document.addEventListener("visibilitychange", handleVisibility);
    window.addEventListener("focus", handleVisibility);

    return () => {
      window.clearInterval(intervalId);
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("focus", handleVisibility);
    };
  }, [data, intervalMs, isPollingPausedForInactivity, pauseForInactivityIfNeeded, refreshNow, shouldPoll]);

  const resumePolling = useCallback(async () => {
    lastObservedActivityAtRef.current = Date.now();
    setIsPollingPausedForInactivity(false);
    await refreshNow();
  }, [refreshNow]);

  return {
    data,
    isRefreshing,
    refreshError,
    lastUpdatedAt,
    isPollingPausedForInactivity,
    refreshNow,
    resumePolling,
    setData,
  };
};
