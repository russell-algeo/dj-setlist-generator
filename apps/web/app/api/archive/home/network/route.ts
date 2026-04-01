import { NextRequest, NextResponse } from "next/server";

import {
  getArchiveHomeNetworkPayload,
  getWorkspaceNetworkPayload,
} from "@/lib/archive/home-explorer-data";
import { getSessionActor } from "@/lib/auth/session";

export async function GET(request: NextRequest) {
  const scope = request.nextUrl.searchParams.get("scope");

  if (scope === "mine") {
    const actor = await getSessionActor();
    if (actor) {
      const payload = await getWorkspaceNetworkPayload(actor.userId);
      return NextResponse.json(payload);
    }
  }

  const payload = await getArchiveHomeNetworkPayload();
  return NextResponse.json(payload);
}
