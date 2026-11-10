import { NextResponse } from "next/server";
import { z } from "zod";
import { assertInternalRequest } from "@/lib/auth/session";
import { dispatchPrivateYoon } from "@/lib/jobs/private-yoon-dispatch";

const requestSchema = z.union([
  z.object({ setRunId: z.uuid(), generation: z.uuid() }).strict(),
  z.object({ setRunId: z.uuid(), controller: z.literal(true), workflowRunId: z.string().regex(/^[1-9][0-9]{0,19}$/), runAttempt: z.string().regex(/^[1-9][0-9]{0,19}$/) }).strict(),
]);
export async function POST(request: Request) {
  const denial = assertInternalRequest(request);
  if (denial) return denial;
  const input = requestSchema.safeParse(await request.json().catch(() => null));
  if (!input.success) return NextResponse.json({ error: "Invalid private dispatch" }, { status: 400 });
  const result = await dispatchPrivateYoon(input.data);
  return NextResponse.json(result, { status: result.dispatched ? 200 : 409 });
}
