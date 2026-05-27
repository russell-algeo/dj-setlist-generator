import { NextResponse } from "next/server";
import { z } from "zod";

import { assertInternalRequest } from "@/lib/auth/session";
import { readRequestBody } from "@/lib/http/request-body";
import { finalizeArtistDiscoveryWorkflow } from "@/lib/jobs/dispatch";

const finalizePayloadSchema = z.object({
  submissionId: z.string().uuid(),
  workflowRunId: z.string().optional(),
  workflowResult: z.string().default("success"),
});

export async function POST(request: Request) {
  const denial = assertInternalRequest(request);
  if (denial) {
    return denial;
  }

  const body = finalizePayloadSchema.parse(await readRequestBody(request));
  const result = await finalizeArtistDiscoveryWorkflow(body);
  return NextResponse.json(result);
}
