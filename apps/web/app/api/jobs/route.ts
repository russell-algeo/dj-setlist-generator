import { NextResponse } from "next/server";

import { assertAllowlisted, getRequestActor } from "@/lib/auth/session";
import { isJsonRequest, readRequestBody } from "@/lib/http/request-body";
import {
  createSubmission,
  dispatchNextQueuedSetRun,
  dispatchQueuedArtistSubmission,
  parseSubmissionInput,
} from "@/lib/jobs/service";

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

export async function POST(request: Request) {
  const actor = await getRequestActor(request);
  const denial = assertAllowlisted(actor);
  if (denial) {
    return denial;
  }

  const body = await readRequestBody(request);
  const input = parseSubmissionInput({
    mode: String(body.mode ?? "url"),
    sourceUrl: body.sourceUrl ? String(body.sourceUrl) : undefined,
    sourceUrls: parseSourceUrls(body.sourceUrls),
    artistName: body.artistName ? String(body.artistName) : undefined,
    createPlaylist:
      body.createPlaylist === "true" || body.createPlaylist === "on",
    maxSetsOverride: body.maxSetsOverride ? Number(body.maxSetsOverride) : undefined,
  });

  const submission = await createSubmission(actor!, input);

  if (input.mode === "artist") {
    await dispatchQueuedArtistSubmission();
  } else {
    await dispatchNextQueuedSetRun();
  }

  if (isJsonRequest(request) || actor?.authType === "api_token") {
    return NextResponse.json({ submissionId: submission.id }, { status: 201 });
  }

  return NextResponse.redirect(new URL(`/dashboard/jobs/${submission.id}`, request.url), {
    status: 303,
  });
}
