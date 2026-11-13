/* eslint-disable @next/next/no-img-element */
"use client";

import { SetSeekControl } from "@/components/archive/set-seek-control";
import { formatDuration } from "@/lib/archive/utils";

/** Partial-set coverage on the set clock (never the source-file clock). */
export type RecordedSetCoverage = {
  notes: string[];
  gaps: { at: number; label: string }[];
};

function PlayIcon() {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 16 16" width="16" height="16">
      <path d="M4 2.5v11l9-5.5z" fill="currentColor" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 16 16" width="16" height="16">
      <path d="M3.5 2.5h3.25v11H3.5zM9.25 2.5h3.25v11H9.25z" fill="currentColor" />
    </svg>
  );
}

function ReplayIcon() {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 16 16" width="16" height="16">
      <path d="M8 2.5a5.5 5.5 0 1 1-5.2 3.7l1.4.5A4 4 0 1 0 8 4v2L4.75 3.25 8 .5z" fill="currentColor" />
    </svg>
  );
}

// Presentation only: the explorer and its existing native controller own the
// set clock, source-window mapping, playback intent and all media operations.
// The card mirrors the look of the provider embeds on ordinary set pages, but
// it only exposes what the private recording really supports here.
export function RecordedSetControls({
  currentTime, duration, isPlaying, ready, buffering, unavailable, error,
  onTogglePlay, onSeek, title, artworkUrl, nowPlaying, coverage,
}: {
  currentTime: number;
  duration: number;
  isPlaying: boolean;
  ready: boolean;
  buffering: boolean;
  unavailable: boolean;
  error: string | null;
  onTogglePlay: () => void;
  onSeek: (seconds: number) => void;
  title?: string;
  artworkUrl?: string | null;
  nowPlaying?: { title: string; artist: string } | null;
  coverage?: RecordedSetCoverage | null;
}) {
  const total = Number.isFinite(duration) ? Math.max(0, duration) : 0;
  const position = Number.isFinite(currentTime) ? Math.max(0, Math.min(currentTime, total)) : 0;
  const disabled = unavailable || total <= 0;
  const totalLabel = formatDuration(total);
  const ended = !isPlaying && position >= total && total > 0;
  const playLabel = isPlaying ? "Pause set" : ended ? "Replay set" : "Play set";
  const status = error ? null : !ready ? "Loading recording. Press Play to start." :
    buffering ? "Buffering…" : isPlaying ? "Playing" : ended ? "End of set" : "Paused";
  const gaps = total > 0
    ? (coverage?.gaps ?? []).filter((gap) => Number.isFinite(gap.at) && gap.at >= 0 && gap.at <= total)
    : [];
  const notes = (coverage?.notes ?? []).filter((note) => note.trim().length > 0);

  return (
    <div className="recorded-set-controls" role="group" aria-label="Set playback">
      <div className="recorded-set-card">
        <div className="recorded-set-art" aria-hidden="true">
          {artworkUrl ? <img alt="" src={artworkUrl} loading="lazy" /> : <span>♫</span>}
        </div>
        <div className="recorded-set-body">
          <div className="recorded-set-meta">
            <span className="recorded-set-badge">Private recording</span>
            {title ? <span className="recorded-set-title">{title}</span> : null}
            {nowPlaying ? (
              <span className="recorded-set-now">
                {nowPlaying.artist} — {nowPlaying.title}
              </span>
            ) : null}
          </div>
          <SetSeekControl
            className="dock-progress recorded-set-progress"
            appearance="timeline"
            label="Seek within set"
            renderBefore={(displayedTime) => {
              const elapsed = formatDuration(displayedTime);
              return (
                <div className="recorded-set-controls-row">
                  <button
                    className={["recorded-set-play", isPlaying && "is-playing"].filter(Boolean).join(" ")}
                    type="button"
                    aria-label={playLabel}
                    disabled={disabled}
                    onClick={onTogglePlay}
                  >
                    {isPlaying ? <PauseIcon /> : ended ? <ReplayIcon /> : <PlayIcon />}
                    <span>{isPlaying ? "Pause" : ended ? "Replay" : "Play"}</span>
                  </button>
                  <div className="recorded-set-time" aria-label={`${elapsed} elapsed of ${totalLabel}`}>
                    <span>{elapsed}</span><span aria-hidden="true"> / </span><span>{totalLabel}</span>
                  </div>
                </div>
              );
            }}
            currentTime={position}
            duration={total}
            disabled={disabled || !ready}
            onCommit={onSeek}
          />
          {gaps.length > 0 ? (
            <div className="recorded-set-gaps" aria-hidden="true">
              {gaps.map((gap, index) => (
                <span
                  className="recorded-set-gap"
                  key={`${gap.at}-${index}`}
                  style={{ left: `${(gap.at / total) * 100}%` }}
                  title={`${gap.label} at ${formatDuration(gap.at)}`}
                />
              ))}
            </div>
          ) : null}
        </div>
      </div>
      {gaps.length > 0 || notes.length > 0 ? (
        <ul className="recorded-set-coverage" aria-label="Recording coverage">
          {notes.map((note, index) => <li key={`note-${index}`}>{note}</li>)}
          {gaps.map((gap, index) => (
            <li key={`gap-${index}`}>{gap.label} at {formatDuration(gap.at)}</li>
          ))}
        </ul>
      ) : null}
      <div className="recorded-set-status">
        {error ? <p role="alert">{error}</p> : <p role="status" aria-live="polite">{status}</p>}
        <p className="recorded-set-limits">
          Plays in this tab only. Lock-screen and background controls depend on your browser and may not work.
        </p>
      </div>
    </div>
  );
}
