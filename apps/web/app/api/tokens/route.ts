import { NextResponse } from "next/server";

import { assertAllowlisted, getSessionActor } from "@/lib/auth/session";
import { readRequestBody } from "@/lib/http/request-body";
import { createApiTokenForUser } from "@/lib/jobs/tokens";
import { issueApiToken } from "@/lib/security/api-tokens";

export async function POST(request: Request) {
  const actor = await getSessionActor();
  const denial = assertAllowlisted(actor);
  if (denial) {
    return denial;
  }

  const body = await readRequestBody(request);
  const name = String(body.name ?? "").trim();

  if (!name) {
    return NextResponse.json({ error: "Token name is required" }, { status: 400 });
  }

  const token = issueApiToken();

  await createApiTokenForUser({
    userId: actor!.userId,
    name,
    tokenPrefix: token.tokenPrefix,
    tokenHash: token.tokenHash,
  });

  return NextResponse.json(
    {
      name,
      plainTextToken: token.plainTextToken,
      tokenPrefix: token.tokenPrefix,
    },
    { status: 201 },
  );
}
