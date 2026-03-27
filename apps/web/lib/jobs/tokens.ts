import "server-only";

import { and, desc, eq, isNull } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { apiTokens } from "@/lib/db/schema";
import type { SessionActor } from "@/lib/auth/session";

const db = getDb();

export const createApiTokenForUser = async (values: {
  userId: string;
  name: string;
  tokenPrefix: string;
  tokenHash: string;
}) => {
  const [token] = await db
    .insert(apiTokens)
    .values({
      userId: values.userId,
      name: values.name,
      tokenPrefix: values.tokenPrefix,
      tokenHash: values.tokenHash,
    })
    .returning();

  return token;
};

export const listApiTokensForUser = async (userId: string) =>
  db
    .select()
    .from(apiTokens)
    .where(and(eq(apiTokens.userId, userId), isNull(apiTokens.revokedAt)))
    .orderBy(desc(apiTokens.createdAt));

export const revokeApiTokenForUser = async (tokenId: string, actor: SessionActor) => {
  const [existing] = await db
    .select()
    .from(apiTokens)
    .where(
      and(
        eq(apiTokens.id, tokenId),
        actor.isAdmin ? undefined : eq(apiTokens.userId, actor.userId),
      ),
    )
    .limit(1);

  if (!existing) {
    return null;
  }

  await db
    .update(apiTokens)
    .set({
      revokedAt: new Date(),
      updatedAt: new Date(),
    })
    .where(eq(apiTokens.id, tokenId));

  return existing;
};
