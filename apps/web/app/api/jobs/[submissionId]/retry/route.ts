import { NextResponse } from "next/server";

import { canAccessSubmission, getRequestActor } from "@/lib/auth/session";
import { isJsonRequest } from "@/lib/http/request-body";
import { retryFailedSetRuns } from "@/lib/jobs/submissions";
import { dispatchPendingWork } from "@/lib/jobs/dispatch";

type Params = {
  params: Promise<{
    submissionId: string;
  }>;
};

export async function POST(request: Request, { params }: Params) {
  const actor = await getRequestActor(request);
  if (!actor) {
    return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  }

  const { submissionId } = await params;
  const allowed = await canAccessSubmission(actor, submissionId);
  if (!allowed) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const result = await retryFailedSetRuns(submissionId);

  if (result.nothingToRetry) {
    return NextResponse.json(
      {
        error: "No failed or cancelled runs are eligible to retry",
        result,
      },
      { status: 409 },
    );
  }

  await dispatchPendingWork();

  if (isJsonRequest(request)) {
    return NextResponse.json(result);
  }

  return NextResponse.redirect(new URL(`/submissions/${submissionId}`, request.url), {
    status: 303,
  });
}
