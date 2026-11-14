/* eslint-disable @next/next/no-img-element */
"use client";

import { SetSeekControl } from "@/components/archive/set-seek-control";
import { formatDuration } from "@/lib/archive/utils";

/** Partial-set coverage on the set clock (never the source-file clock). */
export type RecordedSetCoverage = {
  notes: string[];
  gaps: { at: number; label: string }[];
};

/** Window layouts under review (N08). Each mirrors an existing provider frame. */
export type RecordedSetVariant = "widget" | "video" | "artwork";

function PlayIcon() {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 16 16" width="16" height="16">
      <path d="M4.5 2.5v11l9-5.5z" fill="currentColor" />
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
// The window follows the SoundCloud embed on ordinary set pages: one set-wide
// artwork for the whole set (like SoundCloud), the current track as text. It
// never renders the private audio URL.
export function RecordedSetControls({
  currentTime, duration, isPlaying, ready, buffering, unavailable, error,
  onTogglePlay, onSeek, title, artworkUrl, nowPlaying, coverage, variant = "widget",
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
  variant?: RecordedSetVariant;
}) {
  const total = Number.isFinite(duration) ? Math.max(0, duration) : 0;
  const position = Number.isFinite(currentTime) ? Math.max(0, Math.min(currentTime, total)) : 0;
  const disabled = unavailable || total <= 0;
  const totalLabel = formatDuration(total);
  const ended = !isPlaying && position >= total && total > 0;
  const playLabel = isPlaying ? "Pause set" : ended ? "Replay set" : "Play set";
  const status = error ? null : !ready ? "Loading recording. Press Play to start." :
    buffering ? "Buffering…" : isPlaying ? "Playing" : ended ? "End of set" : "Paused";
  const waiting = !error && (buffering || (!ready && isPlaying));
  const gaps = total > 0
    ? (coverage?.gaps ?? []).filter((gap) => Number.isFinite(gap.at) && gap.at >= 0 && gap.at <= total)
    : [];
  const notes = (coverage?.notes ?? []).filter((note) => note.trim().length > 0);

  const playButton = (
    <button
      className={["recorded-set-play", isPlaying && "is-playing", waiting && "is-waiting"].filter(Boolean).join(" ")}
      type="button"
      aria-label={playLabel}
      disabled={disabled}
      onClick={onTogglePlay}
    >
      {isPlaying ? <PauseIcon /> : ended ? <ReplayIcon /> : <PlayIcon />}
    </button>
  );

  return (
    <div className={`recorded-set-controls is-${variant}`} role="group" aria-label="Set playback">
      <div className="recorded-set-window">
        <div className="recorded-set-backdrop" aria-hidden="true">
          {artworkUrl && variant !== "widget" ? <img alt="" src={artworkUrl} loading="lazy" /> : null}
        </div>
        <div className="recorded-set-art" aria-hidden="true">
          {artworkUrl ? <img alt="" src={artworkUrl} loading="lazy" /> : <span>♫</span>}
        </div>
        {variant === "video" ? <div className="recorded-set-center">{playButton}</div> : null}
        <div className="recorded-set-body">
          <div className="recorded-set-head">
            {variant !== "video" ? playButton : null}
            <div className="recorded-set-meta">
              {title ? <span className="recorded-set-title">{title}</span> : null}
              {nowPlaying ? (
                <span className="recorded-set-now">
                  {nowPlaying.title} — {nowPlaying.artist}
                </span>
              ) : null}
            </div>
          </div>
          <div className="recorded-set-track">
            <SetSeekControl
              className="dock-progress recorded-set-progress"
              appearance="timeline"
              label="Seek within set"
              renderBefore={(displayedTime) => {
                const elapsed = formatDuration(displayedTime);
                return (
                  <div className="recorded-set-time" aria-label={`${elapsed} elapsed of ${totalLabel}`}>
                    <span>{elapsed}</span>
                    {waiting ? <span className="recorded-set-wait" aria-hidden="true">{ready ? "Buffering" : "Loading"}</span> : null}
                    <span>{totalLabel}</span>
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
      </div>
      {error ? <p className="recorded-set-error" role="alert">{error}</p> : (
        <p className="recorded-set-sr" role="status" aria-live="polite">{status}</p>
      )}
      {gaps.length > 0 || notes.length > 0 ? (
        <ul className="recorded-set-coverage" aria-label="Recording coverage">
          {notes.map((note, index) => <li key={`note-${index}`}>{note}</li>)}
          {gaps.map((gap, index) => (
            <li key={`gap-${index}`}>{gap.label} at {formatDuration(gap.at)}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
