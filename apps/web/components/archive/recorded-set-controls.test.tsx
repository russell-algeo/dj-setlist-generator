import { Children, isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { SetSeekControl } from "./set-seek-control";
import { RecordedSetControls } from "./recorded-set-controls";

const base = {
  currentTime: 0, duration: 7200, isPlaying: false, ready: true, buffering: false,
  unavailable: false, error: null, onTogglePlay: vi.fn(), onSeek: vi.fn(),
};
function input(node: ReactNode): ReactElement<{ onCommit: (seconds: number) => void; disabled: boolean; duration: number }> | undefined {
  for (const child of Children.toArray(node)) {
    if (!isValidElement<{ children?: ReactNode }>(child)) continue;
    if (child.type === SetSeekControl) return child as ReturnType<typeof input>;
    const nested = input(child.props.children);
    if (nested) return nested;
  }
}

describe("set-relative recording controls", () => {
  it("shows only the set clock with a keyboard-accessible bounded range", () => {
    const html = renderToStaticMarkup(<RecordedSetControls {...base} />);
    expect(html).toContain('aria-label="Play set"');
    expect(html).toContain('aria-label="Seek within set"');
    expect(html).toMatch(/type="range" min="0" max="7200" step="1"/);
    expect(html).toContain('aria-valuetext="0:00 of 2:00:00"');
    expect(html).not.toContain("52:00");
    expect(html).not.toContain("disabled");
  });

  it("labels pause, buffering and the replay endpoint", () => {
    const playing = renderToStaticMarkup(<RecordedSetControls {...base} currentTime={3600} isPlaying buffering />);
    expect(playing).toContain('aria-label="Pause set"');
    expect(playing).toContain('aria-valuetext="1:00:00 of 2:00:00"');
    expect(playing).toContain("Buffering");
    const ended = renderToStaticMarkup(<RecordedSetControls {...base} currentTime={9000} />);
    expect(ended).toContain('aria-label="Replay set"');
    expect(ended).toContain('value="7200"');
    expect(ended).toContain("End of set");
  });

  it("allows a mobile play gesture while metadata loads, disabling only scrubbing", () => {
    const html = renderToStaticMarkup(<RecordedSetControls {...base} ready={false} />);
    expect(html).toContain("Loading recording");
    expect(html.match(/<button[^>]*>/)?.[0]).not.toContain("disabled");
    expect(html.match(/<input[^>]*>/)?.[0]).toContain("disabled");
  });

  it("announces errors and distinguishes retriable play denial from unavailable media", () => {
    const retriable = renderToStaticMarkup(<RecordedSetControls {...base} error="Press Play to try again." />);
    expect(retriable).toContain('role="alert"');
    expect(retriable).not.toContain("disabled");
    const unavailable = renderToStaticMarkup(<RecordedSetControls {...base} unavailable error="Reload to try again." />);
    expect(unavailable.match(/<button[^>]*>/)?.[0]).toContain("disabled");
    expect(unavailable.match(/<input[^>]*>/)?.[0]).toContain("disabled");
  });

  it("delegates committed seeks and availability to the shared control", () => {
    const onSeek = vi.fn();
    const range = input(RecordedSetControls({ ...base, onSeek }))!;
    expect(range.props.onCommit).toBe(onSeek);
    expect(range.props.duration).toBe(7200);
    expect(range.props.disabled).toBe(false);
    expect(input(RecordedSetControls({ ...base, ready: false }))!.props.disabled).toBe(true);
    expect(input(RecordedSetControls({ ...base, unavailable: true }))!.props.disabled).toBe(true);
  });
});
