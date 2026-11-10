/** One audible source on a set page. All commands use current player refs. */
export function createSetAudioFocus(port: {
  isSetPlaying: () => boolean;
  pauseSet: () => void;
  resumeSet: () => void;
}) {
  const previews = new Map<string, () => void>();
  const awaitingPreviewPause = new Set<string>();
  let active: string | null = null;
  let resumeSet = false;
  let disposed = false;
  let awaitingSetPause = false;
  let automaticReturnPending = false;
  let pendingSetPlayback: (() => void) | undefined;
  let pendingResume: ReturnType<typeof setTimeout> | undefined;

  const pausePreview = (id: string) => {
    const pause = previews.get(id);
    if (!pause) return;
    awaitingPreviewPause.add(id);
    pause();
  };
  const cancelResume = () => {
    if (pendingResume !== undefined) clearTimeout(pendingResume);
    pendingResume = undefined;
    automaticReturnPending = false;
  };
  const flushSetPlayback = () => {
    if (disposed || active !== null || awaitingPreviewPause.size > 0) return;
    if (pendingSetPlayback) {
      const play = pendingSetPlayback;
      pendingSetPlayback = undefined;
      awaitingSetPause = false;
      play();
      return;
    }
    if (!automaticReturnPending || pendingResume !== undefined || !resumeSet) return;
    automaticReturnPending = false;
    resumeSet = false;
    awaitingSetPause = false;
    port.resumeSet();
  };
  const release = (id: string) => {
    if (id !== active) return;
    active = null;
    if (!resumeSet || disposed) return;
    automaticReturnPending = true;
    // A sole embed cannot hand over to another. For multiple embeds, allow
    // the new PLAY notification to arrive before returning to the source.
    // In both cases all previously requested pauses must be acknowledged.
    if (previews.size > 1) {
      pendingResume = setTimeout(() => {
        pendingResume = undefined;
        flushSetPlayback();
      }, 150);
    } else flushSetPlayback();
  };

  return {
    register(id: string, pause: () => void) {
      previews.set(id, pause);
      awaitingPreviewPause.delete(id);
      return () => {
        if (previews.get(id) !== pause) return;
        previews.delete(id);
        awaitingPreviewPause.delete(id);
        release(id);
        flushSetPlayback();
      };
    },
    playing(id: string) {
      if (disposed || !previews.has(id) || awaitingPreviewPause.has(id) || active === id) return;
      pendingSetPlayback = undefined;
      const previous = active;
      const wasPlaying = port.isSetPlaying();
      if (previous === null && !automaticReturnPending) resumeSet = wasPlaying;
      cancelResume();
      // Transfer focus before pausing: a synchronous old pause callback must
      // not resume the set between two Spotify previews.
      active = id;
      awaitingSetPause = awaitingSetPause || wasPlaying;
      if (previous !== null) pausePreview(previous);
      port.pauseSet();
    },
    stopped(id: string) {
      awaitingPreviewPause.delete(id);
      release(id);
      flushSetPlayback();
    },
    // Explicit set controls supersede any pending automatic resume.
    setIntent() {
      pendingSetPlayback = undefined;
      cancelResume();
      const previous = active;
      active = null;
      resumeSet = false;
      // Keep an outstanding source-pause acknowledgement across user Pause.
      // A queued old PLAY cannot become a fresh takeover after this intent.
      if (previous !== null) pausePreview(previous);
    },
    requestSetPlayback(play: () => void) {
      if (disposed) return;
      this.setIntent();
      // Do not overlap a fast warm resume with Spotify's asynchronous pause.
      // A user request skips the automatic handover timer once silence is
      // acknowledged. Newer controls/navigation cancel this callback.
      pendingSetPlayback = play;
      flushSetPlayback();
    },
    setPaused() { awaitingSetPause = false; },
    // Before the pause acknowledgement, a delayed PLAY must not restart the
    // set. A new PLAY afterwards is a user taking back its embedded controls.
    guardSetPlayback() {
      if (awaitingSetPause || (pendingSetPlayback && awaitingPreviewPause.size > 0)) {
        port.pauseSet();
        return true;
      }
      // A genuine embedded Play supersedes a queued automatic/explicit
      // return even when Spotify already released active ownership. Otherwise
      // a later user Pause can be undone by the old 150 ms timer.
      pendingSetPlayback = undefined;
      cancelResume();
      const previous = active;
      active = null;
      resumeSet = false;
      if (previous !== null) pausePreview(previous);
      if (awaitingPreviewPause.size > 0) {
        port.pauseSet();
        pendingSetPlayback = () => port.resumeSet();
        return true;
      }
      return false;
    },
    reset() {
      pendingSetPlayback = undefined;
      cancelResume();
      active = null;
      resumeSet = false;
      awaitingSetPause = false;
      for (const id of previews.keys()) pausePreview(id);
    },
    dispose() {
      pendingSetPlayback = undefined;
      cancelResume();
      disposed = true;
      active = null;
      resumeSet = false;
      awaitingSetPause = false;
      for (const id of previews.keys()) pausePreview(id);
      previews.clear();
      awaitingPreviewPause.clear();
    },
  };
}
