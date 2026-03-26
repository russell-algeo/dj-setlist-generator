import { NextResponse } from "next/server";

import { assertInternalRequest } from "@/lib/auth/session";
import { dispatchNextQueuedSetRun, dispatchQueuedArtistSubmission } from "@/lib/jobs/service";

export async function POST(request: Request) {
  const denial = assertInternalRequest(request);
  if (denial) {
    return denial;
  }

  const [artistDispatch, setDispatch] = await Promise.all([
    dispatchQueuedArtistSubmission(),
    dispatchNextQueuedSetRun(),
  ]);

  return NextResponse.json({
    artistDispatch,
    setDispatch,
  });
}
