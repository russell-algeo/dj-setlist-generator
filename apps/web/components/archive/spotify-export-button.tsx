"use client";

import React, { useEffect, useRef, useState } from "react";

import {
  SPOTIFY_EXPORT_FILTERS,
  type SpotifyExportCounts,
} from "@/lib/archive/spotify-export";
import type {
  SpotifyExportConfidenceFilter,
  SpotifyExportRequest,
  SpotifyExportResponse,
} from "@/lib/archive/types";

import { useSpotifyExportStatus } from "./use-spotify-export-status";
import styles from "./spotify-export-button.module.css";

type SpotifyExportButtonProps = {
  counts: SpotifyExportCounts;
  entityType: "artist" | "set";
  label?: string;
  scope?: "global" | "mine";
  slug: string;
};

const joinClasses = (...values: Array<string | false | null | undefined>) =>
  values.filter(Boolean).join(" ");

const formatFilterLabel = (filter: SpotifyExportConfidenceFilter, count: number) => {
  if (filter === "all") {
    return `All (${count})`;
  }

  return `${filter.charAt(0)}${filter.slice(1).toLowerCase()} (${count})`;
};

export function SpotifyExportButton({
  counts,
  entityType,
  label = "Export to Spotify",
  scope,
  slug,
}: SpotifyExportButtonProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const { isAuthenticated, isLoading, spotifyConfigured, spotifyConnected } = useSpotifyExportStatus();
  const [open, setOpen] = useState(false);
  const [panelStyle, setPanelStyle] = useState<React.CSSProperties>({});
  const [selectedFilter, setSelectedFilter] =
    useState<SpotifyExportConfidenceFilter>("all");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tooltipVisible, setTooltipVisible] = useState(false);
  const [success, setSuccess] = useState<{
    playlistUrl: string;
    tracksAdded: number;
  } | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target;
      if (containerRef.current && target instanceof Node && !containerRef.current.contains(target)) {
        setOpen(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  const disabledReason = (() => {
    if (success) {
      return null;
    }

    if (isLoading) {
      return null;
    }

    if (!isAuthenticated) {
      return "Sign in and connect Spotify to export playlists";
    }

    if (!spotifyConnected) {
      return "Connect Spotify from your account menu to export playlists";
    }

    if (!spotifyConfigured) {
      return "Spotify export is not configured on this deployment";
    }

    if (counts.all === 0) {
      return "No Spotify-resolved tracks are available for export";
    }

    return null;
  })();

  const isDisabled = !success && (isLoading || Boolean(disabledReason));
  const selectedCount = counts[selectedFilter];

  const handleExport = async () => {
    setSubmitting(true);
    setError(null);

    try {
      const payload: SpotifyExportRequest = {
        confidenceFilter: selectedFilter,
        entityType,
        slug,
        scope,
      };

      const response = await fetch("/api/archive/spotify/export", {
        method: "POST",
        headers: {
          "content-type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      const data = (await response.json().catch(() => ({}))) as unknown;

      if (!response.ok) {
        const errorMessage =
          typeof data === "object" &&
          data !== null &&
          "error" in data &&
          typeof data.error === "string"
            ? data.error
            : `HTTP ${response.status}`;
        throw new Error(errorMessage);
      }

      const result = data as SpotifyExportResponse;
      setSuccess({
        playlistUrl: result.playlistUrl,
        tracksAdded: result.tracksAdded,
      });
      setOpen(false);
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleTriggerClick = () => {
    if (success) {
      window.open(success.playlistUrl, "_blank", "noopener,noreferrer");
      return;
    }

    if (isDisabled) {
      return;
    }

    if (!open && triggerRef.current && window.innerWidth <= 720) {
      const rect = triggerRef.current.getBoundingClientRect();
      const top = rect.bottom + 6;
      const right = Math.max(window.innerWidth - rect.right, 8);
      setPanelStyle({
        position: "fixed",
        top,
        right,
        left: "auto",
        bottom: "auto",
        zIndex: 9999,
        maxHeight: `calc(100dvh - ${top + 16}px)`,
        overflowY: "auto",
        minWidth: Math.min(296, rect.right - 8),
        maxWidth: rect.right - 8,
      });
    } else {
      setPanelStyle({});
    }

    setError(null);
    setOpen((current) => !current);
  };

  return (
    <div className={styles.wrap} ref={containerRef}>
      <button
        ref={triggerRef}
        className={joinClasses(
          styles.trigger,
          isDisabled && styles.triggerDisabled,
          success && styles.triggerSuccess,
        )}
        onClick={handleTriggerClick}
        onMouseEnter={() => {
          if (isDisabled && disabledReason) {
            setTooltipVisible(true);
          }
        }}
        onMouseLeave={() => setTooltipVisible(false)}
        type="button"
      >
        {success ? "Open in Spotify" : label}
      </button>

      {tooltipVisible && disabledReason ? (
        <div className={styles.tooltip}>{disabledReason}</div>
      ) : null}

      {open ? (
        <div className={styles.panel} style={panelStyle}>
          <h3 className={styles.panelTitle}>Create Spotify Playlist</h3>
          <p className={styles.panelSubtitle}>Private playlist in your connected Spotify account</p>

          <div className={styles.filterRow}>
            {SPOTIFY_EXPORT_FILTERS.map((filter) => (
              <button
                className={joinClasses(
                  styles.filterChip,
                  selectedFilter === filter && styles.filterChipActive,
                )}
                key={filter}
                onClick={() => setSelectedFilter(filter)}
                type="button"
              >
                {formatFilterLabel(filter, counts[filter])}
              </button>
            ))}
          </div>

          <p className={styles.summary}>{selectedCount} tracks will be exported</p>

          {selectedCount === 0 ? (
            <p className={styles.helper}>
              No Spotify-resolved tracks match this confidence filter
            </p>
          ) : null}

          {error ? <p className={styles.error}>{error}</p> : null}

          <div className={styles.actions}>
            <button
              className={styles.cancelBtn}
              onClick={() => setOpen(false)}
              type="button"
            >
              Cancel
            </button>
            <button
              className={styles.submitBtn}
              disabled={selectedCount === 0 || submitting}
              onClick={handleExport}
              type="button"
            >
              {submitting ? "Exporting..." : "Export"}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
