// Local opt-in diagnostics for playback QA. No URLs, track IDs, account data or
// server transmission. Times are relative to this page's navigation only.
export function traceAudioTiming(event: string, provider: string) {
  if (typeof window === "undefined" || new URLSearchParams(window.location.search).get("audioTiming") !== "1") return;
  console.info(`[audio-timing] ${performance.now().toFixed(1)} ${provider} ${event}`);
}
