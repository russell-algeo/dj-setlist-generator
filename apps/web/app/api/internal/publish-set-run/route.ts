import { NextResponse } from "next/server";
import { z } from "zod";

import { assertInternalRequest } from "@/lib/auth/session";
import { upsertArchiveSet } from "@/lib/archive/publish-set";
import { readRequestBody } from "@/lib/http/request-body";

const publishPayloadSchema = z.object({
  setRunId: z.string().uuid(),
  html: z.string().min(1),
  legacyPath: z.string().min(1).optional(),
  payload: z.object({
    mix_info: z.record(z.string(), z.unknown()),
    metadata: z.record(z.string(), z.unknown()),
    tracks: z.array(z.record(z.string(), z.unknown())),
  }),
});

export async function POST(request: Request) {
  const denial = assertInternalRequest(request);
  if (denial) {
    return denial;
  }

  const body = publishPayloadSchema.parse(await readRequestBody(request));
  const published = await upsertArchiveSet({
    payload: body.payload,
    html: body.html,
    legacyPath: body.legacyPath,
    provenance: {
      source: "worker",
      setRunId: body.setRunId,
    },
  });

  return NextResponse.json(published);
}
