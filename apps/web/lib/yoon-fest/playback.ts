export type RecordingSpan = {
  recordingId: string;
  startSample: number;
  endSample: number;
  sampleRate: number;
};

export function spanDuration(span: RecordingSpan): number {
  if (!span.recordingId || !Number.isSafeInteger(span.startSample) || !Number.isSafeInteger(span.endSample) ||
    !Number.isSafeInteger(span.sampleRate) || span.sampleRate <= 0 || span.startSample < 0 || span.endSample <= span.startSample) {
    throw new Error("Invalid recording span");
  }
  return (span.endSample - span.startSample) / span.sampleRate;
}

// Half-open spans: a seam belongs to the next file. The set endpoint belongs
// to the final span. Provenance is retained even when playback uses one derivative.
export function locateRecordingTime(spans: RecordingSpan[], seconds: number) {
  if (!spans.length || !Number.isFinite(seconds)) throw new Error("Invalid set position");
  const durations = spans.map(spanDuration);
  const total = durations.reduce((sum, value) => sum + value, 0);
  const target = Math.max(0, Math.min(seconds, total));
  let start = 0;
  for (let index = 0; index < spans.length; index += 1) {
    const span = spans[index]!;
    const duration = durations[index]!;
    if (target < start + duration || index === spans.length - 1) {
      const offset = Math.min(duration, target - start);
      return { recordingId: span.recordingId, spanIndex: index,
        sourceSeconds: span.startSample / span.sampleRate + offset,
        sourceSample: Math.min(span.endSample, span.startSample + Math.floor(offset * span.sampleRate)),
        setSeconds: target };
    }
    start += duration;
  }
  throw new Error("Invalid set position");
}

export type NativeAudioSegment = { src: string; startSeconds: number; durationSeconds: number };
export type NativeAudioPort = Pick<HTMLAudioElement, "src" | "load" | "paused" | "currentTime" | "readyState" | "play" | "pause"> & { readonly ended?: boolean };

// The set clock spans original files. Only the selected source window is played;
// source URLs are same-origin authorized redirects, never bearer URLs in props.
export function createNativeAudioController(audio: NativeAudioPort, duration: number, onError: (message: string) => void, sourceSegments?: NativeAudioSegment[]) {
  const segments = sourceSegments ?? [{ src: audio.src, startSeconds: 0, durationSeconds: duration }];
  if (!segments.length || segments.some((part) => !Number.isFinite(part.startSeconds) || part.startSeconds < 0 || !Number.isFinite(part.durationSeconds) || part.durationSeconds <= 0) ||
    Math.abs(segments.reduce((sum, part) => sum + part.durationSeconds, 0) - duration) > 0.25) throw new Error("Invalid playback segments");
  const offsets = segments.map((_, index) => segments.slice(0, index).reduce((sum, part) => sum + part.durationSeconds, 0));
  let version = 0;
  let disposed = false;
  let activeIndex = 0;
  let awaitingMetadata = false;
  let pending: { seconds: number; autoplay: boolean } | null = null;
  let playRequested = false;
  let playAttempt: { version: number; settled: Promise<void> } | null = null;
  const startPlayback = (request: number) => {
    // Keep the pending play promise separate from the pending source seek.
    // A seek may be applied while play() is still starting or being denied.
    const attempt = { version: request, settled: Promise.resolve() };
    playAttempt = attempt;
    attempt.settled = audio.play().then(() => {
      if (playAttempt === attempt) playAttempt = null;
    }, () => {
      if (playAttempt === attempt) playAttempt = null;
      if (disposed || request !== version) return;
      playRequested = false;
      if (pending) pending = { ...pending, autoplay: false };
      audio.pause();
      onError("Playback could not start. Press Play to try again.");
    });
  };
  const pause = () => {
    version += 1;
    playRequested = false;
    if (pending) pending = { ...pending, autoplay: false };
    audio.pause();
  };
  const seek = (seconds: number, autoplay: boolean) => {
    if (disposed || !Number.isFinite(seconds)) return;
    const request = ++version;
    const target = Math.max(0, Math.min(duration, seconds));
    const index = segments.findIndex((part, index) => target < offsets[index]! + part.durationSeconds);
    const selected = index < 0 ? segments.length - 1 : index;
    // The endpoint is a stopped position, never permission to play beyond it.
    playRequested = autoplay && target < duration;
    pending = { seconds: target, autoplay: playRequested };
    audio.pause();
    if (selected !== activeIndex) {
      activeIndex = selected;
      awaitingMetadata = true;
      audio.src = segments[selected]!.src;
      audio.load();
    }
    if (audio.readyState < 1 || awaitingMetadata) {
      // Invoke play in the user's gesture even when a mobile browser defers
      // metadata. loadedmetadata applies the pending offset before audio plays.
      if (playRequested) startPlayback(request);
      return;
    }
    try {
      audio.currentTime = Math.min(segments[selected]!.startSeconds + segments[selected]!.durationSeconds, segments[selected]!.startSeconds + target - offsets[selected]!);
      pending = null;
      if (playRequested) startPlayback(request);
    } catch {
      playRequested = false;
      pending = null;
      audio.pause();
      onError("This recording could not seek. Reload the page to try again.");
    }
  };
  const position = () => pending?.seconds ?? Math.max(offsets[activeIndex]!, Math.min(offsets[activeIndex]! + segments[activeIndex]!.durationSeconds,
    offsets[activeIndex]! + audio.currentTime - segments[activeIndex]!.startSeconds));
  const resume = (replayAtEnd = true) => {
    if (disposed) return;
    // A normal pause keeps the decoder, buffer and exact media position.
    // Seeking to our displayed (polled) clock would discard that warm state.
    const part = segments[activeIndex]!;
    const target = position();
    if (target >= duration && !replayAtEnd) { pause(); return; }
    if (pending || awaitingMetadata || audio.readyState < 1 || audio.ended || audio.currentTime < part.startSeconds ||
      audio.currentTime >= part.startSeconds + part.durationSeconds) {
      seek(target >= duration ? 0 : target, true);
      return;
    }
    playRequested = true;
    startPlayback(++version);
  };
  const ended = () => {
    if (disposed) return duration;
    // ended events can already be queued when a user or Spotify pauses us.
    // They cannot grant a new autoplay request after that pause.
    if (!playRequested) return position();
    if (activeIndex < segments.length - 1) { seek(offsets[activeIndex + 1]!, true); return position(); }
    seek(duration, false);
    return duration;
  };
  return {
    seek,
    resume,
    position,
    ended,
    isPlayRequested: () => playRequested,
    isPending: () => pending !== null || awaitingMetadata,
    async observePause(onPaused: () => void) {
      const observedVersion = version;
      const attempt = playAttempt;
      // pause events are queued. An internal seek's pause must not cancel a
      // newer play just because metadata/seek completed before play settled.
      if (attempt?.version === observedVersion) await attempt.settled;
      if (disposed || observedVersion !== version || !audio.paused || (pending && playRequested)) return;
      // Native media emits pause before ended at a natural file boundary.
      // Preserve intent for that transition, but never undo an explicit pause.
      if (audio.ended && playRequested) return;
      pause();
      onPaused();
    },
    tick() {
      if (disposed || pending || awaitingMetadata || audio.readyState < 1) return position();
      const part = segments[activeIndex]!;
      if (audio.currentTime < part.startSeconds) seek(offsets[activeIndex]!, !audio.paused);
      else if (audio.currentTime >= part.startSeconds + part.durationSeconds) {
        if (!audio.paused) return ended();
        if (audio.currentTime > part.startSeconds + part.durationSeconds) seek(offsets[activeIndex]! + part.durationSeconds, false);
      }
      return position();
    },
    ready() { awaitingMetadata = false; if (pending) seek(pending.seconds, pending.autoplay); },
    pause,
    dispose() { disposed = true; version += 1; playRequested = false; pending = null; audio.pause(); },
  };
}
