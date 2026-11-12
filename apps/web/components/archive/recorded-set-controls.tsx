"use client";

import { SetSeekControl } from "@/components/archive/set-seek-control";
import { formatDuration } from "@/lib/archive/utils";

// Presentation only: the explorer and its existing native controller own the
// set clock, source-window mapping, playback intent and all media operations.
export function RecordedSetControls({
  currentTime, duration, isPlaying, ready, buffering, unavailable, error,
  onTogglePlay, onSeek,
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
}) {
  const total = Number.isFinite(duration) ? Math.max(0, duration) : 0;
  const position = Number.isFinite(currentTime) ? Math.max(0, Math.min(currentTime, total)) : 0;
  const disabled = unavailable || total <= 0;
  const totalLabel = formatDuration(total);
  const playLabel = isPlaying ? "Pause set" : position >= total && total > 0 ? "Replay set" : "Play set";
  const status = error ? null : !ready ? "Loading recording. Press Play to start." :
    buffering ? "Buffering…" : isPlaying ? "Playing" : position >= total && total > 0 ? "End of set" : "Paused";

  return (
    <div className="recorded-set-controls" role="group" aria-label="Set playback">
      <SetSeekControl
        className="recorded-set-seek"
        renderBefore={(displayedTime) => {
          const elapsed = formatDuration(displayedTime);
          return (
            <div className="recorded-set-controls-row">
              <button
                className="recorded-set-play"
                type="button"
                aria-label={playLabel}
                disabled={disabled}
                onClick={onTogglePlay}
              >
                <span aria-hidden="true">{isPlaying ? "❚❚" : "▶"}</span>
                <span>{isPlaying ? "Pause" : position >= total && total > 0 ? "Replay" : "Play"}</span>
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
      <div className="recorded-set-status">
        {error ? <p role="alert">{error}</p> : <p role="status" aria-live="polite">{status}</p>}
      </div>
    </div>
  );
}
