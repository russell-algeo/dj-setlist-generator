import { NextResponse } from "next/server";
import { z } from "zod";

import { refreshArchiveHomeMaterializedViews } from "@/lib/archive/home-materialized-views";
import { assertInternalRequest } from "@/lib/auth/session";
import { upsertArchiveSet } from "@/lib/archive/publish-set";
import { readRequestBody } from "@/lib/http/request-body";

const publishPayloadSchema = z.object({
  setRunId: z.string().uuid(),
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
    provenance: {
      source: "worker",
      setRunId: body.setRunId,
    },
  });
  try {
    await refreshArchiveHomeMaterializedViews();
  } catch (error) {
    const refreshError = error instanceof Error ? error.message : String(error);
    console.error("archive_home_materialized_view_refresh_failed", {
      setRunId: body.setRunId,
      refreshError,
    });
    return NextResponse.json(
      {
        ...published,
        error: refreshError,
        errorCode: "archive_home_materialized_view_refresh_failed",
      },
      { status: 500 },
    );
  }

  return NextResponse.json(published);
}
