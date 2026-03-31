import "server-only";

import { asc, desc, eq } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { submissions, userProfiles } from "@/lib/db/schema";
import type { SessionActor } from "@/lib/auth/session";

const db = getDb();

// Workaround: drizzle-orm version mismatch between monorepo root and worktree causes
// column type inference failures. Cast tables to any to bypass incompatible overloads.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const UP = userProfiles as any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const S = submissions as any;

export type UserRow = {
  userId: string;
  email: string;
  displayName: string | null;
  isAllowlisted: boolean;
  isAdmin: boolean;
  createdAt: Date;
  updatedAt: Date;
};

export type SubmissionWithUserRow = {
  id: string;
  mode: string;
  status: string;
  artistName: string | null;
  sourceUrl: string | null;
  createdAt: Date;
  userEmail: string;
  userDisplayName: string | null;
};

export const listUsers = async (): Promise<UserRow[]> => {
  const rows = await db.select().from(UP).orderBy(asc(UP.email));
  return rows as unknown as UserRow[];
};

export const resolveViewAsActor = async (
  sessionActor: SessionActor,
  viewAsUserId: string | undefined,
): Promise<SessionActor | null> => {
  if (!viewAsUserId || !sessionActor.isAdmin) return null;

  const rows = await db.select().from(UP).where(eq(UP.userId, viewAsUserId)).limit(1);
  const profile = (rows as unknown as UserRow[])[0];

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

export const listAllSubmissionsWithUser = async (): Promise<SubmissionWithUserRow[]> => {
  const rows = await db
    .select({
      id: S.id,
      mode: S.mode,
      status: S.status,
      artistName: S.artistName,
      sourceUrl: S.sourceUrl,
      createdAt: S.createdAt,
      userEmail: UP.email,
      userDisplayName: UP.displayName,
    })
    .from(S)
    .innerJoin(UP, eq(UP.userId, S.requestedBy))
    .orderBy(desc(S.createdAt))
    .limit(200);
  return rows as unknown as SubmissionWithUserRow[];
};

export const updateUserProfile = async (
  userId: string,
  updates: { isAllowlisted?: boolean; isAdmin?: boolean },
) => {
  const rows = await db
    .update(UP)
    .set({ ...updates, updatedAt: new Date() })
    .where(eq(UP.userId, userId))
    .returning();
  return (rows as unknown as UserRow[])[0] ?? null;
};
