"use client";

import { useEffect, useRef, useState } from "react";
import { loadSpotifyIframeApi, spotifyPlaybackState, type SpotifyEmbedController, type SpotifyPlaybackEvent } from "@/lib/archive/spotify-iframe";

export function SpotifyTrackPreview({ trackId, title, onRegister, onPlaying, onStopped }: {
  trackId: string;
  title: string;
  onRegister: (pause: () => void) => () => void;
  onPlaying: () => void;
  onStopped: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const callbacks = useRef({ onRegister, onPlaying, onStopped });
  callbacks.current = { onRegister, onPlaying, onStopped };
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const root = host.current;
    if (!root) return;
    let cancelled = false;
    let controller: SpotifyEmbedController | undefined;
    let unregister: (() => void) | undefined;
    const listener = (event: SpotifyPlaybackEvent) => {
      if (cancelled) return;
      const state = spotifyPlaybackState(event);
      if (state === "playing") callbacks.current.onPlaying();
      if (state === "stopped") callbacks.current.onStopped();
      // Buffering is not a pause: keep the set silent until Spotify stops.
    };
    setError(false);
    const placeholder = document.createElement("div");
    root.replaceChildren(placeholder);
    void loadSpotifyIframeApi().then((api) => {
      if (cancelled) return;
      api.createController(placeholder, { uri: `spotify:track:${trackId}`, width: "100%", height: 80 }, (created) => {
        if (cancelled) { created.destroy(); return; }
        controller = created;
        unregister = callbacks.current.onRegister(() => created.pause());
        created.addListener("playback_update", listener);
        const iframe = root.querySelector("iframe");
        if (iframe) iframe.title = title;
      });
    }).catch(() => { if (!cancelled) setError(true); });
    return () => {
      cancelled = true;
      controller?.removeListener("playback_update", listener);
      controller?.destroy();
      unregister?.();
      root.replaceChildren();
    };
  }, [trackId, title, attempt]);

  return <div>
    <div ref={host} aria-label={title} />
    {error ? <p role="alert">Spotify preview could not load. <button type="button" onClick={() => setAttempt((value) => value + 1)}>Retry preview</button></p> : null}
  </div>;
}
