import { NextResponse } from "next/server";

import { canManageSubmission, getRequestActor } from "@/lib/auth/session";
import { cancelSubmissionSetRun, getSubmissionSetRun } from "@/lib/jobs/submissions";

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
  const allowed = await canManageSubmission(actor, submissionId);
  if (!allowed) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const run = await getSubmissionSetRun(submissionId, setRunId);
  if (!run) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const result = await cancelSubmissionSetRun(submissionId, setRunId);
  if (result.nothingToCancel) {
    return NextResponse.json(
      {
        error: "This run can no longer be cancelled. Publication may already have started.",
        result,
      },
      { status: 409 },
    );
  }

  return NextResponse.json(result);
}
