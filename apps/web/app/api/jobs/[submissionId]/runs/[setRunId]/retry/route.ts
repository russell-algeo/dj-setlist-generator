import { NextResponse } from "next/server";

import { canAccessSubmission, getRequestActor } from "@/lib/auth/session";
import { dispatchPendingWork } from "@/lib/jobs/dispatch";
import { getSubmissionSetRun, retrySubmissionSetRun } from "@/lib/jobs/submissions";

type Params = {
  params: Promise<{
    submissionId: string;
    setRunId: string;
  }>;
};

export async function POST(_request: Request, { params }: Params) {
  const actor = await getRequestActor(_request);
  if (!actor) {
    return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  }

  const { submissionId, setRunId } = await params;
  const allowed = await canAccessSubmission(actor, submissionId);
  if (!allowed) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const run = await getSubmissionSetRun(submissionId, setRunId);
  if (!run) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const result = await retrySubmissionSetRun(submissionId, setRunId);
  if (result.nothingToRetry) {
    return NextResponse.json(
      {
        error: "This run is not eligible to retry",
        result,
      },
      { status: 409 },
    );
  }

  await dispatchPendingWork();
  return NextResponse.json(result);
}
