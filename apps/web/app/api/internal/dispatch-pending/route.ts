import { NextResponse } from "next/server";

import { assertInternalRequest } from "@/lib/auth/session";
import { dispatchPendingWork } from "@/lib/jobs/service";

export async function POST(request: Request) {
  const denial = assertInternalRequest(request);
  if (denial) {
    return denial;
  }

  return NextResponse.json(await dispatchPendingWork());
}
