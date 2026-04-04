import { NextResponse } from "next/server";

import { canAccessSubmission, getRequestActor } from "@/lib/auth/session";
import { getPublicSubmissionRunEventsPage } from "@/lib/jobs/public.server";

type Params = {
  params: Promise<{
    setRunId: string;
    submissionId: string;
  }>;
};

export async function GET(request: Request, { params }: Params) {
  const actor = await getRequestActor(request);
  if (!actor) {
    return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  }

  const { setRunId, submissionId } = await params;
  const allowed = await canAccessSubmission(actor, submissionId);
  if (!allowed) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const { searchParams } = new URL(request.url);
  const rawPage = Number(searchParams.get("page"));
  const rawPageSize = Number(searchParams.get("pageSize"));

  const eventsPage = await getPublicSubmissionRunEventsPage({
    page: Number.isFinite(rawPage) && rawPage > 0 ? Math.floor(rawPage) : 1,
    pageSize: Number.isFinite(rawPageSize) && rawPageSize > 0 ? Math.floor(rawPageSize) : 6,
    setRunId,
    submissionId,
  });

  if (!eventsPage) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  return NextResponse.json(eventsPage);
}
