"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import { formatDuration } from "@/lib/archive/utils";

const seekKeys = new Set(["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "PageUp", "PageDown"]);

/** Preview a gesture locally; the owning player receives only its final seek.
 * Key this component by source identity so an old gesture cannot seek a new set.
 */
export function SetSeekControl({
  currentTime, duration, disabled = false, className, id, label = "Seek within set", onCommit,
  appearance = "native", renderBefore,
}: {
  currentTime: number;
  duration: number;
  disabled?: boolean;
  className?: string;
  id?: string;
  label?: string;
  onCommit: (seconds: number) => void;
  appearance?: "native" | "timeline";
  renderBefore?: (displayedTime: number) => ReactNode;
}) {
  const total = Number.isFinite(duration) ? Math.max(0, duration) : 0;
  const clampPosition = (value: number) => Math.max(0, Math.min(value, total));
  const position = Number.isFinite(currentTime) ? clampPosition(currentTime) : 0;
  const unavailable = disabled || total <= 0;
  const [draft, setDraft] = useState<number | null>(null);
  const gesture = useRef<{ kind: "pointer" | "keyboard"; pointerId?: number; value: number | null; cancelled?: boolean } | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; gesture.current = null; };
  }, []);

  const cancel = () => {
    if (gesture.current) gesture.current.cancelled = true;
    setDraft(null);
  };
  useEffect(() => {
    if (gesture.current) gesture.current.cancelled = true;
    setDraft(null);
  }, [unavailable, total]);
  const commit = (value: number) => {
    gesture.current = null;
    setDraft(null);
    if (mounted.current && !unavailable && Number.isFinite(value)) onCommit(clampPosition(value));
  };
  const displayed = unavailable ? position : draft ?? position;
  const valueText = `${formatDuration(displayed)} of ${formatDuration(total)}`;

  return (
    <div className="set-seek-control">
      {renderBefore?.(displayed)}
      <div className={appearance === "timeline" ? "set-seek-timeline" : undefined}>
        <input
          id={id}
          className={appearance === "timeline" ? "set-seek-input" : className}
          type="range"
          min={0}
          max={total}
          step={1}
          value={displayed}
          aria-label={label}
          aria-valuetext={valueText}
          disabled={unavailable}
          onPointerDown={(event) => {
            if (unavailable || event.button !== 0 || event.isPrimary === false || (gesture.current && !gesture.current.cancelled)) return;
            gesture.current = { kind: "pointer", pointerId: event.pointerId, value: null };
            setDraft(position);
            event.currentTarget.setPointerCapture?.(event.pointerId);
          }}
          onChange={(event) => {
            if (unavailable || gesture.current?.cancelled) return;
            const seconds = Number(event.currentTarget.value);
            if (!Number.isFinite(seconds)) return;
            const value = clampPosition(seconds);
            if (gesture.current) {
              gesture.current.value = value;
              setDraft(value);
            } else {
              // Screen readers and other native range controls may change the
              // value without a pointer/key gesture. Each is a complete action.
              commit(value);
            }
          }}
          onPointerUp={(event) => {
            const current = gesture.current;
            if (current?.kind !== "pointer" || current.pointerId !== event.pointerId) return;
            const value = current.value;
            if (current.cancelled || value === null) { cancel(); gesture.current = null; }
            else commit(value);
            if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
          }}
          onPointerCancel={(event) => {
            if (gesture.current?.pointerId === event.pointerId) cancel();
          }}
          onLostPointerCapture={(event) => {
            if (gesture.current?.pointerId === event.pointerId) cancel();
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") { event.preventDefault(); cancel(); return; }
            if (event.repeat && gesture.current?.cancelled) return;
            if (!unavailable && seekKeys.has(event.key) && (!gesture.current || gesture.current.cancelled)) {
              gesture.current = { kind: "keyboard", value: null };
              setDraft(position);
            }
          }}
          onKeyUp={(event) => {
            if (!seekKeys.has(event.key) || gesture.current?.kind !== "keyboard") return;
            const value = gesture.current.value;
            if (gesture.current.cancelled || value === null) { cancel(); gesture.current = null; }
            else commit(value);
          }}
          onFocus={() => { if (gesture.current?.cancelled) gesture.current = null; }}
          onBlur={cancel}
        />
        {appearance === "timeline" ? (
          <div className={className} aria-hidden="true">
            <div className="dock-progress-fill" id={id ? `${id}Fill` : undefined}
              style={{ width: `${total > 0 ? displayed / total * 100 : 0}%` }} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
