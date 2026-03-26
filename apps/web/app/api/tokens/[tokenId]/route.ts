import { NextResponse } from "next/server";

import { assertAllowlisted, getSessionActor } from "@/lib/auth/session";
import { revokeApiTokenForUser } from "@/lib/jobs/service";

type Params = {
  params: Promise<{
    tokenId: string;
  }>;
};

const revoke = async (request: Request, tokenId: string) => {
  const actor = await getSessionActor();
  const denial = assertAllowlisted(actor);
  if (denial) {
    return denial;
  }

  const revoked = await revokeApiTokenForUser(tokenId, actor!);
  if (!revoked) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  if ((request.headers.get("content-type") ?? "").includes("application/json")) {
    return NextResponse.json({ ok: true });
  }

  return NextResponse.redirect(new URL("/dashboard/tokens", request.url), {
    status: 303,
  });
};

export async function DELETE(request: Request, { params }: Params) {
  const { tokenId } = await params;
  return revoke(request, tokenId);
}

export async function POST(request: Request, { params }: Params) {
  const { tokenId } = await params;
  return revoke(request, tokenId);
}
