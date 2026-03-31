import "server-only";

import { asc, desc, eq } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { submissions, userProfiles } from "@/lib/db/schema";
import type { SessionActor } from "@/lib/auth/session";

const db = getDb();

export const listUsers = async () => {
  return db.select().from(userProfiles).orderBy(asc(userProfiles.email));
};

export const resolveViewAsActor = async (
  sessionActor: SessionActor,
  viewAsUserId: string | undefined,
): Promise<SessionActor | null> => {
  if (!viewAsUserId || !sessionActor.isAdmin) return null;

  const [profile] = await db
    .select()
    .from(userProfiles)
    .where(eq(userProfiles.userId, viewAsUserId))
    .limit(1);

  if (!profile) return null;

  return {
    authType: "session",
    userId: profile.userId,
    email: profile.email,
    displayName: profile.displayName,
    isAllowlisted: profile.isAllowlisted,
    isAdmin: profile.isAdmin,
  };
};

export const listAllSubmissionsWithUser = async () => {
  return db
    .select({
      id: submissions.id,
      mode: submissions.mode,
      status: submissions.status,
      artistName: submissions.artistName,
      sourceUrl: submissions.sourceUrl,
      createdAt: submissions.createdAt,
      userEmail: userProfiles.email,
      userDisplayName: userProfiles.displayName,
    })
    .from(submissions)
    .innerJoin(userProfiles, eq(userProfiles.userId, submissions.requestedBy))
    .orderBy(desc(submissions.createdAt))
    .limit(200);
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
