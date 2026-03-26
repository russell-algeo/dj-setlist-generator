import { NextResponse } from "next/server";
import { z } from "zod";

import { assertInternalRequest } from "@/lib/auth/session";
import { readRequestBody } from "@/lib/http/request-body";
import { finalizeSetRunWorkflow } from "@/lib/jobs/service";

const finalizePayloadSchema = z.object({
  setRunId: z.string().uuid(),
  workflowRunId: z.string().optional(),
  bootstrapResult: z.string().default("success"),
  recognizeResult: z.string().default("success"),
  publishResult: z.string().default("success"),
});

export async function POST(request: Request) {
  const denial = assertInternalRequest(request);
  if (denial) {
    return denial;
  }

  const body = finalizePayloadSchema.parse(await readRequestBody(request));
  const result = await finalizeSetRunWorkflow(body);
  return NextResponse.json(result);
}
