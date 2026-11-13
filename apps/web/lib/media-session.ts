// System media controls (iPhone lock screen, Control Center, desktop media keys).
//
// What the page can drive depends on which document owns the playing media:
// - native-audio (Yoon recordings) plays in an <audio> element in this page, so
//   these handlers, metadata and position state are what iOS shows.
// - YouTube, SoundCloud and Spotify play inside cross-origin iframes. Browsers
//   attach system controls to the frame that owns the playing element, so the
//   provider's own session wins there and this page's handlers are not used.

export type MediaSessionHandlers = {
  play: () => void;
  pause: () => void;
  seekTo: (seconds: number) => void;
  previousTrack: () => void;
  nextTrack: () => void;
};

export type NowPlayingInput = {
  setTitle: string;
  setArtist: string;
  track: { title: string; artist: string; isUnknownTrack?: boolean } | null;
  artworkUrl: string | null;
};

const getSession = (): MediaSession | null =>
  typeof navigator !== "undefined" && "mediaSession" in navigator ? navigator.mediaSession : null;

// iOS shows +/- seek buttons instead of previous/next track whenever
// seekbackward/seekforward handlers exist, so those are always cleared.
const OWNED_ACTIONS = ["play", "pause", "seekto", "previoustrack", "nexttrack"] as const;
const SUPPRESSED_ACTIONS = ["seekbackward", "seekforward"] as const;

const trySetAction = (session: MediaSession, action: MediaSessionAction, handler: MediaSessionActionHandler | null) => {
  try {
    session.setActionHandler(action, handler);
  } catch {
    // Browser support varies by action and platform.
  }
};

/**
 * Registers system media actions once. The handlers object is read at call
 * time, so later renders never leave the lock screen calling stale closures.
 */
export function registerMediaSessionActions(getHandlers: () => MediaSessionHandlers): () => void {
  const session = getSession();
  if (!session) return () => {};

  trySetAction(session, "play", () => getHandlers().play());
  trySetAction(session, "pause", () => getHandlers().pause());
  trySetAction(session, "seekto", (details) => {
    if (typeof details.seekTime !== "number" || !Number.isFinite(details.seekTime)) return;
    getHandlers().seekTo(details.seekTime);
  });
  trySetAction(session, "previoustrack", () => getHandlers().previousTrack());
  trySetAction(session, "nexttrack", () => getHandlers().nextTrack());
  for (const action of SUPPRESSED_ACTIONS) trySetAction(session, action, null);

  return () => {
    for (const action of OWNED_ACTIONS) trySetAction(session, action, null);
  };
}

const imageType = (url: string): string | undefined => {
  const path = url.split(/[?#]/)[0]!.toLowerCase();
  if (path.endsWith(".png")) return "image/png";
  if (path.endsWith(".webp")) return "image/webp";
  if (path.endsWith(".jpg") || path.endsWith(".jpeg")) return "image/jpeg";
  return undefined;
};

export function buildNowPlayingMetadata({ setTitle, setArtist, track, artworkUrl }: NowPlayingInput): MediaMetadataInit {
  const knownTrack = track && !track.isUnknownTrack && track.title.trim() ? track : null;
  const artwork: MediaImage[] = artworkUrl
    ? [{ src: artworkUrl, sizes: "512x512", ...(imageType(artworkUrl) ? { type: imageType(artworkUrl) } : {}) }]
    : [];
  // Lock screens show title and artist most prominently: the current track
  // there, with the DJ and set kept in the album line.
  return knownTrack
    ? {
      title: knownTrack.title,
      artist: knownTrack.artist || setArtist,
      album: `${setArtist} · ${setTitle}`,
      artwork,
    }
    : { title: setTitle, artist: setArtist, album: "Set Signal Archive", artwork };
}

export function publishNowPlaying(input: NowPlayingInput): void {
  const session = getSession();
  if (!session || typeof window === "undefined" || !("MediaMetadata" in window)) return;
  try {
    session.metadata = new window.MediaMetadata(buildNowPlayingMetadata(input));
  } catch {
    // An invalid artwork URL must not break playback.
  }
}

export function clearNowPlaying(): void {
  const session = getSession();
  if (session) session.metadata = null;
}

export function publishPlaybackState(duration: number, position: number, playing: boolean): void {
  const session = getSession();
  if (!session) return;
  session.playbackState = playing ? "playing" : "paused";
  if (typeof session.setPositionState !== "function") return;
  try {
    if (!Number.isFinite(duration) || duration <= 0) {
      session.setPositionState();
      return;
    }
    session.setPositionState({
      duration,
      playbackRate: 1,
      position: Math.min(duration, Math.max(0, Number.isFinite(position) ? position : 0)),
    });
  } catch {
    // Position state support is uneven.
  }
}
