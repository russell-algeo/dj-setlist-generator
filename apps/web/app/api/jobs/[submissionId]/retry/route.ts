import { NextResponse } from "next/server";

import { assertAllowlisted, canAccessSubmission, getRequestActor } from "@/lib/auth/session";
import { dispatchPendingWork, retrySubmission } from "@/lib/jobs/service";

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

  await retrySubmission(submissionId);
  await dispatchPendingWork();

  if ((request.headers.get("content-type") ?? "").includes("application/json")) {
    return NextResponse.json({ ok: true });
  }

  return NextResponse.redirect(new URL(`/dashboard/jobs/${submissionId}`, request.url), {
    status: 303,
  });
}
