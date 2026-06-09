import "server-only";

import { and, eq, inArray } from "drizzle-orm";

import {
  calculateCoverageRatio,
  isListenedCoverage,
  mergeListenIntervals,
  parseListenIntervals,
  type ListenInterval,
  type ListenProgressSummary,
} from "@/lib/archive/listen-progress";
import { getDb, type AppDb } from "@/lib/db/client";
import { userSetListenProgress } from "@/lib/db/schema";

export type UpsertListenProgressInput = {
  duration: number;
  intervals: ListenInterval[];
  lastPosition: number;
  setId: string;
  sourceUrl: string | null;
};

type ListenProgressRow = typeof userSetListenProgress.$inferSelect;

const toNumber = (value: unknown) => {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : 0;
};

const toNumericString = (value: number, scale: number) => {
  const numberValue = Number.isFinite(value) ? value : 0;
  return Math.max(0, numberValue).toFixed(scale);
};

const rowToSummary = (row: ListenProgressRow): ListenProgressSummary => {
  const duration = toNumber(row.durationSeconds);
  const intervals = parseListenIntervals(row.intervals, duration);
  const coverageRatio = toNumber(row.coverageRatio);

  return {
    coverageRatio,
    intervals,
    listened: isListenedCoverage(coverageRatio),
    listenedAt: row.listenedAt?.toISOString() ?? null,
    setId: row.setId,
  };
};

export const listUserSetListenProgress = async (
  userId: string,
  setIds: string[],
  deps: { db?: AppDb } = {},
) => {
  const uniqueSetIds = [...new Set(setIds)].filter(Boolean).slice(0, 200);
  if (uniqueSetIds.length === 0) {
    return [];
  }

  const db = deps.db ?? getDb();
  const rows = await db
    .select()
    .from(userSetListenProgress)
    .where(
      and(
        eq(userSetListenProgress.userId, userId),
        inArray(userSetListenProgress.setId, uniqueSetIds),
      ),
    );

  return rows.map(rowToSummary);
};

export const upsertUserSetListenProgress = async (
  userId: string,
  input: UpsertListenProgressInput,
  deps: { db?: AppDb; now?: Date } = {},
) => {
  const db = deps.db ?? getDb();
  const now = deps.now ?? new Date();
  const incomingDuration = Math.max(0, input.duration, input.lastPosition);

  const [existing] = await db
    .select()
    .from(userSetListenProgress)
    .where(
      and(
        eq(userSetListenProgress.userId, userId),
        eq(userSetListenProgress.setId, input.setId),
      ),
    )
    .limit(1);

  const existingDuration = existing ? toNumber(existing.durationSeconds) : 0;
  const duration = Math.max(incomingDuration, existingDuration);
  const existingIntervals = existing ? parseListenIntervals(existing.intervals, duration) : [];
  const intervals = mergeListenIntervals([...existingIntervals, ...input.intervals], duration);
  const coverageRatio = calculateCoverageRatio(intervals, duration);
  const lastPosition = Math.min(Math.max(0, input.lastPosition), duration);
  const listenedAt = isListenedCoverage(coverageRatio)
    ? existing?.listenedAt ?? now
    : null;

  const values = {
    coverageRatio: toNumericString(coverageRatio, 5),
    durationSeconds: toNumericString(duration, 2),
    intervals,
    lastPositionSeconds: toNumericString(lastPosition, 2),
    listenedAt,
    setId: input.setId,
    sourceUrl: input.sourceUrl,
    updatedAt: now,
    userId,
  };

  await db
    .insert(userSetListenProgress)
    .values(values)
    .onConflictDoUpdate({
      target: [userSetListenProgress.userId, userSetListenProgress.setId],
      set: values,
    });

  const [saved] = await db
    .select()
    .from(userSetListenProgress)
    .where(
      and(
        eq(userSetListenProgress.userId, userId),
        eq(userSetListenProgress.setId, input.setId),
      ),
    )
    .limit(1);

  return saved ? rowToSummary(saved) : {
    coverageRatio,
    intervals,
    listened: isListenedCoverage(coverageRatio),
    listenedAt: listenedAt?.toISOString() ?? null,
    setId: input.setId,
  };
};
