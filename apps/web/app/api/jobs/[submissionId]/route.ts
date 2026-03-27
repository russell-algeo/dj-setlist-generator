import { NextResponse } from "next/server";

import { canAccessSubmission, getRequestActor } from "@/lib/auth/session";
import { getSubmissionDetail } from "@/lib/jobs/submissions";

type Params = {
  params: Promise<{
    submissionId: string;
  }>;
};

export async function GET(request: Request, { params }: Params) {
  const actor = await getRequestActor(request);
  if (!actor) {
    return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  }

  const { submissionId } = await params;
  const allowed = await canAccessSubmission(actor, submissionId);
  if (!allowed) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const detail = await getSubmissionDetail(submissionId);
  if (!detail) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  return NextResponse.json(detail);
}
