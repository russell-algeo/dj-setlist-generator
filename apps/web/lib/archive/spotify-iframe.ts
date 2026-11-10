// Spotify's documented iFrame API. No Web Playback SDK, account tokens, or
// untrusted window-message parsing is required for embed playback events.
export type SpotifyPlaybackEvent = {
  data: { isPaused: boolean; isBuffering: boolean; position: number; duration: number; playingURI?: string };
};
export type SpotifyEmbedController = {
  addListener: (event: "playback_update", callback: (event: SpotifyPlaybackEvent) => void) => void;
  removeListener: (event: "playback_update", callback: (event: SpotifyPlaybackEvent) => void) => void;
  pause: () => void;
  destroy: () => void;
};
export type SpotifyIframeApi = {
  createController: (element: HTMLElement, options: { uri: string; width: string; height: number }, callback: (controller: SpotifyEmbedController) => void) => void;
};
type SpotifyWindow = Window & { onSpotifyIframeApiReady?: (api: SpotifyIframeApi) => void };
let apiPromise: Promise<SpotifyIframeApi> | undefined;

export function loadSpotifyIframeApi(): Promise<SpotifyIframeApi> {
  if (apiPromise) return apiPromise;
  apiPromise = new Promise((resolve, reject) => {
    const target = window as SpotifyWindow;
    const priorReady = target.onSpotifyIframeApiReady;
    const script = document.createElement("script");
    let settled = false;
    const fail = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      script.remove();
      target.onSpotifyIframeApiReady = priorReady;
      apiPromise = undefined;
      reject(new Error("Spotify preview could not load."));
    };
    const timer = window.setTimeout(fail, 15000);
    target.onSpotifyIframeApiReady = (api) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      resolve(api);
      priorReady?.(api);
    };
    script.src = "https://open.spotify.com/embed/iframe-api/v1";
    script.async = true;
    script.onerror = fail;
    document.head.appendChild(script);
  });
  return apiPromise;
}

export function spotifyPlaybackState(event: SpotifyPlaybackEvent): "playing" | "stopped" | "buffering" | null {
  const data = event?.data;
  if (!data || typeof data.isPaused !== "boolean" || typeof data.isBuffering !== "boolean") return null;
  if (data.isBuffering) return "buffering";
  if (data.isPaused || (data.duration > 0 && data.position >= data.duration)) return "stopped";
  return "playing";
}
