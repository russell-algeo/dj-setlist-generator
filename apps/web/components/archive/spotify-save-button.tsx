"use client";

import { signIn, useSession } from "next-auth/react";
import { useState } from "react";

type SaveState = "idle" | "busy" | "saved" | "connect" | "signin" | "error";

function reconnectCallbackUrl() {
  const url = new URL(window.location.href);
  url.searchParams.set("spotify", "connected");
  return url.toString();
}

// Saves the track to the viewer's Spotify "Liked Songs" through the site's own
// Spotify connection, so the listener never leaves the set page. The embed's
// built-in "+" cannot be driven from here (cross-origin iframe, separate login).
export function SpotifySaveButton({ trackId, label }: { trackId: string; label: string }) {
  const [state, setState] = useState<SaveState>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const { status } = useSession();

  const update = async (saved: boolean) => {
    setState("busy");
    setMessage(null);
    try {
      const response = await fetch("/api/spotify/library", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ trackId, saved }),
      });
      const payload = (await response.json().catch(() => ({}))) as { error?: string; reason?: string };
      if (response.ok) {
        setState(saved ? "saved" : "idle");
        return;
      }
      if (payload.reason === "connect") { setState("connect"); setMessage(payload.error ?? null); return; }
      if (payload.reason === "signin") { setState("signin"); return; }
      setState("error");
      setMessage(payload.error ?? "Spotify could not save this track.");
    } catch {
      setState("error");
      setMessage("Spotify could not be reached.");
    }
  };

  if (status !== "authenticated") return null;

  return <div className="spotify-save" data-state={state}>
    {state === "saved" ? <>
      <span className="spotify-save-done" role="status">Saved to your Spotify library</span>
      <button type="button" className="btn track-tool-btn spotify-save-undo" onClick={() => void update(false)}>Undo</button>
    </> : state === "connect" ? <>
      <button type="button" className="btn track-tool-btn spotify-save-btn" onClick={() => void signIn("spotify", { callbackUrl: reconnectCallbackUrl() })}>
        Allow saving in Spotify
      </button>
      {message ? <span className="spotify-save-note">{message}</span> : null}
    </> : state === "signin" ? (
      <span className="spotify-save-note">Sign in to save tracks to Spotify.</span>
    ) : <>
      <button
        type="button"
        className="btn track-tool-btn spotify-save-btn"
        aria-label={`Save ${label} to your Spotify library`}
        disabled={state === "busy"}
        onClick={() => void update(true)}
      >
        {state === "busy" ? "Saving…" : "+ Save to Spotify"}
      </button>
      {state === "error" && message ? <span className="spotify-save-note" role="alert">{message}</span> : null}
    </>}
  </div>;
}
