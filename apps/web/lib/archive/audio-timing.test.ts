import { afterEach, expect, it, vi } from "vitest";
import { traceAudioTiming } from "./audio-timing";
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
it("keeps playback diagnostics disabled by default", () => {
  const info = vi.spyOn(console, "info").mockImplementation(() => {});
  traceAudioTiming("play-command", "soundcloud");
  vi.stubGlobal("window", { location: { search: "?other=1" } });
  traceAudioTiming("play-command", "soundcloud");
  expect(info).not.toHaveBeenCalled();
});
it("logs only local relative timing when explicitly requested", () => {
  const info = vi.spyOn(console, "info").mockImplementation(() => {});
  vi.stubGlobal("window", { location: { search: "?audioTiming=1" } });
  traceAudioTiming("play-command", "soundcloud");
  expect(info).toHaveBeenCalledWith(expect.stringMatching(/^\[audio-timing\] \d+\.\d soundcloud play-command$/));
});
