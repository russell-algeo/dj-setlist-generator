import { NextResponse } from "next/server";

import { assertAllowlisted, canAccessSubmission, getRequestActor } from "@/lib/auth/session";
import { retryFailedSetRuns } from "@/lib/jobs/submissions";
import { dispatchPendingWork } from "@/lib/jobs/dispatch";

type Params = {
  params: Promise<{
    submissionId: string;
  }>;
};

export async function POST(request: Request, { params }: Params) {
  const actor = await getRequestActor(request);
  const denial = assertAllowlisted(actor);
  if (denial) {
    return denial;
  }

  const { submissionId } = await params;
  const allowed = await canAccessSubmission(actor!, submissionId);
  if (!allowed) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const result = await retryFailedSetRuns(submissionId);

  if (result === "nothing_to_retry") {
    return NextResponse.json(
      { error: "No failed or cancelled runs to retry" },
      { status: 409 },
    );
  }

  await dispatchPendingWork();

  if ((request.headers.get("content-type") ?? "").includes("application/json")) {
    return NextResponse.json({ ok: true });
  }

  return NextResponse.redirect(new URL(`/dashboard/jobs/${submissionId}`, request.url), {
    status: 303,
  });
}
