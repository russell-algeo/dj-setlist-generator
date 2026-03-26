import { NextResponse } from "next/server";

import { assertInternalRequest } from "@/lib/auth/session";
import { runSchedulerRecovery } from "@/lib/jobs/service";

export async function POST(request: Request) {
  const denial = assertInternalRequest(request);
  if (denial) {
    return denial;
  }

  const result = await runSchedulerRecovery();
  return NextResponse.json(result);
}
