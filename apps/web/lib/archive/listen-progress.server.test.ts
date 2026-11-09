import { SQL } from "drizzle-orm";
import { PgDialect } from "drizzle-orm/pg-core";
import { describe, expect, it, vi } from "vitest";

import { listUserSetListenProgress, setUserSetListened, upsertUserSetListenProgress } from "./listen-progress.server";
import type { AppDb } from "@/lib/db/client";
import { sets, userSetListenProgress } from "@/lib/db/schema";

vi.mock("@/lib/db/client", () => ({
  getDb: () => { throw new Error("Tests must supply their database"); },
}));

const setId = "4e1b45fc-1a38-4bfd-8831-5b7e98fb2c99";
const now = new Date("2026-11-06T12:00:00Z");
type ProgressRow = typeof userSetListenProgress.$inferSelect;

// Exercise the persistence boundary without accessing the application's live database.
// Decode real Drizzle WHERE parameters so an unscoped read fails the isolation tests.
const createProgressStore = (duration: number | null = 100, canRead = { value: true }) => {
  const records = new Map<string, ProgressRow>();
  const dialect = new PgDialect();
  const db = {
    select: () => ({
      from: (table: unknown) => ({
        where: (condition: SQL) => {
          const { params, sql } = dialect.sqlToQuery(condition);
          if (table === sets) {
            expect(sql).toContain("visibility");
            expect(sql).toContain("archive_collection_members");
          }
          const rows = table === sets
            ? params[0] === setId && canRead.value ? [{ id: setId, durationSeconds: duration, sourceUrl: null }] : []
            : [...records.values()].filter((row) => row.userId === params[0] && params.slice(1).includes(row.setId));
          return Object.assign(Promise.resolve(rows), { limit: async (limit: number) => rows.slice(0, limit) });
        },
      }),
    }),
    insert: () => ({
      values: (values: ProgressRow) => ({
        onConflictDoUpdate: ({ target, set }: { target: unknown[]; set: ProgressRow }) => {
          expect(target).toEqual([userSetListenProgress.userId, userSetListenProgress.setId]);
          const key = `${values.userId}:${values.setId}`;
          const previous = records.get(key);
          const saved = previous ? { ...previous, ...set } : values;
          records.set(key, saved);
          return Object.assign(Promise.resolve(), { returning: async () => [saved] });
        },
      }),
    }),
  } as unknown as AppDb;
  return { db, records };
};

describe("persisted listened markers", () => {
  it("rechecks collection access for reads and both mutations after revocation", async () => {
    const access = { value: true };
    const { db, records } = createProgressStore(100, access);
    await setUserSetListened("user-a", setId, true, { db, now });
    const saved = JSON.stringify([...records]);
    access.value = false;
    await expect(listUserSetListenProgress("user-a", [setId], { db })).resolves.toEqual([]);
    await expect(setUserSetListened("user-a", setId, false, { db, now })).resolves.toBeNull();
    await expect(upsertUserSetListenProgress("user-a", {
      duration: 100, intervals: [[0, 80]], lastPosition: 80, setId, sourceUrl: null,
    }, { db, now })).rejects.toThrow("Set not found");
    expect(JSON.stringify([...records])).toBe(saved);
  });

  it("marks an externally heard set and preserves its timestamp on repeated requests", async () => {
    const { db, records } = createProgressStore();
    const first = await setUserSetListened("user-a", setId, true, { db, now });
    expect(first).toEqual({
      coverageRatio: 1, intervals: [[0, 100]], listened: true, listenedAt: now.toISOString(), setId,
    });
    const repeated = await setUserSetListened("user-a", setId, true, {
      db, now: new Date(now.getTime() + 1000),
    });
    expect(repeated).toEqual(first);
    expect(records.size).toBe(1);
    await expect(listUserSetListenProgress("user-a", [setId], { db })).resolves.toEqual([first]);
  });

  it("removes an automatically earned marker and stays cleared on repeated requests and reads", async () => {
    const { db } = createProgressStore();
    await upsertUserSetListenProgress("user-a", {
      duration: 100, intervals: [[0, 80]], lastPosition: 80, setId, sourceUrl: null,
    }, { db, now });
    const removed = await setUserSetListened("user-a", setId, false, { db, now });
    expect(removed).toEqual({ coverageRatio: 0, intervals: [], listened: false, listenedAt: null, setId });
    await expect(setUserSetListened("user-a", setId, false, { db, now })).resolves.toEqual(removed);
    await expect(listUserSetListenProgress("user-a", [setId], { db })).resolves.toEqual([removed]);
  });

  it("keeps a manual marker during playback and allows fresh playback to count after removal", async () => {
    const { db } = createProgressStore();
    const playback = { duration: 100, intervals: [[10, 20]] as [number, number][], lastPosition: 20, setId, sourceUrl: null };
    await setUserSetListened("user-a", setId, true, { db, now });
    expect((await upsertUserSetListenProgress("user-a", playback, { db, now })).listened).toBe(true);
    await setUserSetListened("user-a", setId, false, { db, now });
    expect((await upsertUserSetListenProgress("user-a", playback, { db, now })).listened).toBe(false);
    expect((await upsertUserSetListenProgress("user-a", {
      ...playback, intervals: [[20, 95]], lastPosition: 95,
    }, { db, now })).listened).toBe(true);
  });

  it("only changes the authenticated listener's progress", async () => {
    const { db } = createProgressStore();
    await setUserSetListened("user-a", setId, true, { db, now });
    await setUserSetListened("user-b", setId, true, { db, now });
    await setUserSetListened("user-a", setId, false, { db, now });
    const [userA] = await listUserSetListenProgress("user-a", [setId], { db });
    const [userB] = await listUserSetListenProgress("user-b", [setId], { db });
    expect(userA.listened).toBe(false);
    expect(userB.listened).toBe(true);
  });

  it("supports blocked sources with unknown duration", async () => {
    const { db } = createProgressStore(null);
    expect((await setUserSetListened("user-a", setId, true, { db, now }))?.listened).toBe(true);
    const [progress] = await listUserSetListenProgress("user-a", [setId], { db });
    expect(progress.listened).toBe(true);
    expect((await setUserSetListened("user-a", setId, false, { db, now }))?.listened).toBe(false);
  });

  it("preserves the saved playback position and source when changing the marker", async () => {
    const { db, records } = createProgressStore();
    await upsertUserSetListenProgress("user-a", {
      duration: 100, intervals: [[0, 10]], lastPosition: 10, setId,
      sourceUrl: "https://soundcloud.com/artist/set",
    }, { db, now });
    for (const listened of [true, false]) {
      await setUserSetListened("user-a", setId, listened, { db, now });
      expect(records.get(`user-a:${setId}`)).toMatchObject({
        lastPositionSeconds: "10.00", sourceUrl: "https://soundcloud.com/artist/set",
      });
    }
  });

  it("does not create progress for a missing set", async () => {
    const { db, records } = createProgressStore();
    await expect(setUserSetListened("user-a", "missing-set", true, { db, now })).resolves.toBeNull();
    expect(records.size).toBe(0);
  });
});
