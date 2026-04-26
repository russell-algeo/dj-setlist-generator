import { NextResponse } from "next/server";
import { ZodError } from "zod";

import { getRequestActor } from "@/lib/auth/session";
import { isJsonRequest, readRequestBody } from "@/lib/http/request-body";
import { listPublicSubmissionsForActor } from "@/lib/jobs/public.server";
import { createSubmission, parseSubmissionInput } from "@/lib/jobs/submissions";
import type { CreateSubmissionInput } from "@/lib/jobs/submissions";
import { dispatchPendingWork } from "@/lib/jobs/dispatch";

const parseSourceUrls = (value: FormDataEntryValue | FormDataEntryValue[] | undefined) => {
  if (!value) {
    return [];
  }

  const list = Array.isArray(value) ? value : [value];

  return list
    .flatMap((entry) => String(entry).split(/\r?\n|,/u))
    .map((entry) => entry.trim())
    .filter(Boolean);
};

const parseArtistAliases = (value: unknown) => {
  if (!value) {
    return [];
  }

  const entries = Array.isArray(value) ? value : [value];
  return entries.map((entry) => String(entry));
};

export async function GET(request: Request) {
  const actor = await getRequestActor(request);
  if (!actor) {
    return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  }

  const url = new URL(request.url);
  const submissions = await listPublicSubmissionsForActor(
    actor,
    url.searchParams.get("status") ?? undefined,
  );

  return NextResponse.json({ submissions });
}

export async function POST(request: Request) {
  const actor = await getRequestActor(request);
  if (!actor) {
    return new Response(JSON.stringify({ error: "Authentication required" }), {
      status: 401,
      headers: { "content-type": "application/json" },
    });
  }

  const body = await readRequestBody(request);
  let input: CreateSubmissionInput;

  try {
    input = parseSubmissionInput({
      mode: String(body.mode ?? ""),
      sourceUrl: body.sourceUrl ? String(body.sourceUrl) : undefined,
      sourceUrls: parseSourceUrls(body.sourceUrls),
      artistName: body.artistName ? String(body.artistName) : undefined,
      artistAliases: parseArtistAliases(body.artistAliases),
      createPlaylist:
        body.createPlaylist === "true" || body.createPlaylist === "on",
      maxSetsOverride: body.maxSetsOverride ? Number(body.maxSetsOverride) : undefined,
    });
  } catch (error) {
    if (error instanceof ZodError) {
      return NextResponse.json(
        { error: error.issues[0]?.message ?? "Invalid submission payload" },
        { status: 400 },
      );
    }

    throw error;
  }

  const { submission, warnings } = await createSubmission(actor, input);
  await dispatchPendingWork();

  if (isJsonRequest(request) || actor?.authType === "api_token") {
    return NextResponse.json(
      { submissionId: submission.id, warnings: warnings.length > 0 ? warnings : undefined },
      { status: warnings.length > 0 ? 202 : 201 },
    );
  }

  return NextResponse.redirect(new URL(`/submissions/${submission.id}`, request.url), {
    status: 303,
  });
}
