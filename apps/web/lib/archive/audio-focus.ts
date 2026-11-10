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
  };
  const release = (id: string) => {
    if (id !== active) return;
    active = null;
    if (!resumeSet || disposed) return;
    // Spotify can pause the previous embed just before it reports the new
    // one playing. Coalesce that handover instead of briefly starting the set.
    pendingResume = setTimeout(() => {
      pendingResume = undefined;
      if (active !== null || disposed || !resumeSet) return;
      resumeSet = false;
      awaitingSetPause = false;
      port.resumeSet();
    }, 150);
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
      };
    },
    playing(id: string) {
      if (disposed || !previews.has(id) || awaitingPreviewPause.has(id) || active === id) return;
      const previous = active;
      const wasPlaying = port.isSetPlaying();
      if (previous === null && pendingResume === undefined) resumeSet = wasPlaying;
      cancelResume();
      // Transfer focus before pausing: a synchronous old pause callback must
      // not resume the set between two Spotify previews.
      active = id;
      awaitingSetPause = awaitingSetPause || wasPlaying;
      if (previous !== null) pausePreview(previous);
      port.pauseSet();
    },
    stopped(id: string) { awaitingPreviewPause.delete(id); release(id); },
    // Explicit set controls supersede any pending automatic resume.
    setIntent() {
      cancelResume();
      const previous = active;
      active = null;
      resumeSet = false;
      awaitingSetPause = false;
      if (previous !== null) pausePreview(previous);
    },
    setPaused() { awaitingSetPause = false; },
    // Before the pause acknowledgement, a delayed PLAY must not restart the
    // set. A new PLAY afterwards is a user taking back its embedded controls.
    guardSetPlayback() {
      if (active === null) return false;
      if (awaitingSetPause) { port.pauseSet(); return true; }
      const previous = active;
      active = null;
      resumeSet = false;
      pausePreview(previous);
      return false;
    },
    reset() {
      cancelResume();
      active = null;
      resumeSet = false;
      awaitingSetPause = false;
      for (const id of previews.keys()) pausePreview(id);
    },
    dispose() {
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
