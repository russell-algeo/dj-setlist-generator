export const LISTENED_COVERAGE_THRESHOLD = 0.75;

export type ListenInterval = [number, number];

export type ListenProgressSummary = {
  coverageRatio: number;
  intervals: ListenInterval[];
  listened: boolean;
  listenedAt: string | null;
  setId: string;
};

const INTERVAL_JOIN_EPSILON_SECONDS = 0.5;

const roundSeconds = (value: number) => Math.round(value * 100) / 100;

const normalizeDuration = (duration: number) =>
  Number.isFinite(duration) && duration > 0 ? roundSeconds(duration) : 0;

export const mergeListenIntervals = (
  intervals: readonly (readonly [number, number])[],
  duration: number,
): ListenInterval[] => {
  const safeDuration = normalizeDuration(duration);
  if (safeDuration <= 0) {
    return [];
  }

  const normalized = intervals
    .map((interval) => {
      const start = roundSeconds(Math.max(0, Math.min(safeDuration, Number(interval[0]))));
      const end = roundSeconds(Math.max(0, Math.min(safeDuration, Number(interval[1]))));
      return start < end ? ([start, end] satisfies ListenInterval) : null;
    })
    .filter((interval): interval is ListenInterval => Boolean(interval))
    .sort((left, right) => left[0] - right[0] || left[1] - right[1]);

  const merged: ListenInterval[] = [];
  for (const interval of normalized) {
    const last = merged[merged.length - 1];
    if (!last || interval[0] > last[1] + INTERVAL_JOIN_EPSILON_SECONDS) {
      merged.push([...interval]);
      continue;
    }

    last[1] = Math.max(last[1], interval[1]);
  }

  return merged;
};

export const calculateCoverageRatio = (
  intervals: readonly (readonly [number, number])[],
  duration: number,
) => {
  const safeDuration = normalizeDuration(duration);
  if (safeDuration <= 0) {
    return 0;
  }

  const listenedSeconds = mergeListenIntervals(intervals, safeDuration).reduce(
    (total, [start, end]) => total + Math.max(0, end - start),
    0,
  );

  return Math.min(1, Math.max(0, listenedSeconds / safeDuration));
};

export const isListenedCoverage = (coverageRatio: number) =>
  Number.isFinite(coverageRatio) && coverageRatio >= LISTENED_COVERAGE_THRESHOLD;

export const parseListenIntervals = (value: unknown, duration: number): ListenInterval[] => {
  if (!Array.isArray(value)) {
    return [];
  }

  const intervals = value
    .map((item) =>
      Array.isArray(item) && item.length >= 2
        ? ([Number(item[0]), Number(item[1])] satisfies ListenInterval)
        : null,
    )
    .filter((item): item is ListenInterval => Boolean(item));

  return mergeListenIntervals(intervals, duration);
};
