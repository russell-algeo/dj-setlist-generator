/**
 * Previous/next skip targets for the set player (N04).
 *
 * Targets are every track start plus any provisional starts inside Unknown
 * entries, so skipping through a long unidentified stretch lands on the
 * estimated start of the next unidentified track instead of jumping past the
 * whole stretch.
 */
export type SkipTrack = {
  start: number;
  provisionalStarts?: number[];
};

export const buildSkipTargets = (tracks: SkipTrack[]): number[] => {
  const values = new Set<number>();
  for (const track of tracks) {
    if (Number.isFinite(track.start)) values.add(track.start);
    for (const value of track.provisionalStarts ?? []) {
      if (Number.isFinite(value)) values.add(value);
    }
  }
  return [...values].sort((left, right) => left - right);
};

/** First target strictly after the current time (1s grace), or null. */
export const nextSkipTarget = (targets: number[], currentTime: number): number | null =>
  targets.find((value) => value > currentTime + 1) ?? null;

/**
 * Previous-press behaviour: restart the current segment, or go to the one
 * before it when pressed again within the double-press window.
 */
export const previousSkipTarget = (
  targets: number[],
  currentTime: number,
  isDoublePress: boolean,
): number => {
  let currentIndex = -1;
  for (let index = 0; index < targets.length; index += 1) {
    if (targets[index] <= currentTime) currentIndex = index;
  }
  if (currentIndex < 0) return 0;
  if (isDoublePress && currentIndex > 0) return targets[currentIndex - 1];
  return targets[currentIndex];
};

/**
 * Where the current time sits inside an Unknown entry's estimated parts:
 * 1-based part number and total estimated parts, or null without estimates.
 */
export const provisionalPart = (
  track: { start: number; provisionalStarts?: number[] },
  currentTime: number,
): { part: number; total: number } | null => {
  const starts = track.provisionalStarts ?? [];
  if (starts.length === 0) return null;
  const part = 1 + starts.filter((value) => value <= currentTime).length;
  return { part, total: starts.length + 1 };
};
