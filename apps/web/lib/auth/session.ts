import "server-only";

import { timingSafeEqual } from "node:crypto";

import { and, desc, eq, isNull } from "drizzle-orm";
import { getServerSession } from "next-auth";
import { redirect } from "next/navigation";

import { authOptions } from "@/lib/auth/options";
import { hashApiToken } from "@/lib/security/api-tokens";
import { apiTokens, spotifyConnections, submissions, userProfiles } from "@/lib/db/schema";
import { getDb } from "@/lib/db/client";
import { env } from "@/lib/env";

export type SessionActor = {
  authType: "session" | "api_token";
  userId: string;
  email: string;
  displayName: string | null;
  isAllowlisted: boolean;
  isAdmin: boolean;
};

const db = getDb();

const safeEqualHex = (left: string, right: string) => {
  const leftBuffer = Buffer.from(left, "utf8");
  const rightBuffer = Buffer.from(right, "utf8");

  if (leftBuffer.length !== rightBuffer.length) {
    return false;
  }

  return timingSafeEqual(leftBuffer, rightBuffer);
};

export const getSessionActor = async (): Promise<SessionActor | null> => {
  const session = await getServerSession(authOptions);

  if (!session?.user?.id || !session.user.email) {
    return null;
  }

  return {
    authType: "session",
    userId: session.user.id,
    email: session.user.email,
    displayName: session.user.name ?? null,
    isAllowlisted: Boolean(session.user.isAllowlisted),
    isAdmin: Boolean(session.user.isAdmin),
  };
};

export const requireSessionActor = async (callbackUrl = "/dashboard") => {
  const actor = await getSessionActor();

  if (!actor) {
    redirect(`/signin?callbackUrl=${encodeURIComponent(callbackUrl)}`);
  }

  return actor;
};

export const getBearerTokenActor = async (request: Request): Promise<SessionActor | null> => {
  const authorization = request.headers.get("authorization");

  if (!authorization?.startsWith("Bearer ")) {
    return null;
  }

  const plainToken = authorization.slice("Bearer ".length).trim();
  if (!plainToken) {
    return null;
  }

  const tokenPrefix = plainToken.slice(0, 12);
  const tokenHash = hashApiToken(plainToken);

  const [tokenRecord] = await db
    .select({
      id: apiTokens.id,
      userId: apiTokens.userId,
      tokenHash: apiTokens.tokenHash,
      email: userProfiles.email,
      displayName: userProfiles.displayName,
      isAllowlisted: userProfiles.isAllowlisted,
      isAdmin: userProfiles.isAdmin,
    })
    .from(apiTokens)
    .innerJoin(userProfiles, eq(userProfiles.userId, apiTokens.userId))
    .where(and(eq(apiTokens.tokenPrefix, tokenPrefix), isNull(apiTokens.revokedAt)))
    .limit(1);

  if (!tokenRecord || !safeEqualHex(tokenRecord.tokenHash, tokenHash)) {
    return null;
  }

  await db
    .update(apiTokens)
    .set({
      lastUsedAt: new Date(),
      updatedAt: new Date(),
    })
    .where(eq(apiTokens.id, tokenRecord.id));

  return {
    authType: "api_token",
    userId: tokenRecord.userId,
    email: tokenRecord.email,
    displayName: tokenRecord.displayName,
    isAllowlisted: tokenRecord.isAllowlisted,
    isAdmin: tokenRecord.isAdmin,
  };
};

export const getRequestActor = async (request: Request) => {
  const bearerActor = await getBearerTokenActor(request);
  if (bearerActor) {
    return bearerActor;
  }

  return getSessionActor();
};

export const assertAllowlisted = (actor: SessionActor | null) => {
  if (!actor) {
    return new Response(JSON.stringify({ error: "Authentication required" }), {
      status: 401,
      headers: {
        "content-type": "application/json",
      },
    });
  }

  if (!actor.isAllowlisted) {
    return new Response(JSON.stringify({ error: "Allowlist access required" }), {
      status: 403,
      headers: {
        "content-type": "application/json",
      },
    });
  }

  return null;
};

export const assertAdmin = (actor: SessionActor | null) => {
  const allowlistedResponse = assertAllowlisted(actor);
  if (allowlistedResponse) {
    return allowlistedResponse;
  }

  if (!actor?.isAdmin) {
    return new Response(JSON.stringify({ error: "Admin access required" }), {
      status: 403,
      headers: {
        "content-type": "application/json",
      },
    });
  }

  return null;
};

export const assertInternalRequest = (request: Request) => {
  const secret = request.headers.get("x-internal-secret");

  if (!env.internalWorkerSharedSecret || secret !== env.internalWorkerSharedSecret) {
    return new Response(JSON.stringify({ error: "Invalid internal secret" }), {
      status: 401,
      headers: {
        "content-type": "application/json",
      },
    });
  }

  return null;
};

export const canAccessSubmission = async (actor: SessionActor, submissionId: string) => {
  if (actor.isAdmin) {
    return true;
  }

  const [row] = await db
    .select({ id: submissions.id })
    .from(submissions)
    .where(and(eq(submissions.id, submissionId), eq(submissions.requestedBy, actor.userId)))
    .limit(1);

  return Boolean(row);
};

export const getSpotifyConnectionForUser = async (userId: string) => {
  const [connection] = await db
    .select()
    .from(spotifyConnections)
    .where(eq(spotifyConnections.userId, userId))
    .orderBy(desc(spotifyConnections.updatedAt))
    .limit(1);

  return connection ?? null;
};
