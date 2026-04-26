import { NextResponse } from "next/server";

import { eq } from "drizzle-orm";

import { requireSessionActor } from "@/lib/auth/session";
import { getDb } from "@/lib/db/client";
import { spotifyConnections } from "@/lib/db/schema";

const db = getDb();

export async function POST(request: Request) {
  const actor = await requireSessionActor("/");

  await db
    .update(spotifyConnections)
    .set({
      revokedAt: new Date(),
      refreshTokenCiphertext: null,
      updatedAt: new Date(),
    })
    .where(eq(spotifyConnections.userId, actor.userId));

  if ((request.headers.get("content-type") ?? "").includes("application/json")) {
    return NextResponse.json({ ok: true });
  }

  return NextResponse.redirect(new URL("/?spotify=disconnected", request.url), {
    status: 303,
  });
}
