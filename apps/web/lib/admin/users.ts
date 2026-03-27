import "server-only";

import { asc, eq } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { userProfiles } from "@/lib/db/schema";

const db = getDb();

export const listUsers = async () => {
  return db.select().from(userProfiles).orderBy(asc(userProfiles.email));
};

export const updateUserProfile = async (
  userId: string,
  updates: { isAllowlisted?: boolean; isAdmin?: boolean },
) => {
  const [updated] = await db
    .update(userProfiles)
    .set({ ...updates, updatedAt: new Date() })
    .where(eq(userProfiles.userId, userId))
    .returning();
  return updated ?? null;
};
