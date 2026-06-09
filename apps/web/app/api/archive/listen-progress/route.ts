import { NextResponse } from "next/server";
import { ZodError, z } from "zod";

import { parseListenIntervals } from "@/lib/archive/listen-progress";
import {
  listUserSetListenProgress,
  upsertUserSetListenProgress,
} from "@/lib/archive/listen-progress.server";
import { getRequestActor } from "@/lib/auth/session";
import { readRequestBody } from "@/lib/http/request-body";

const uuidSchema = z.string().uuid();

const upsertProgressSchema = z.object({
  duration: z.coerce.number().finite().positive(),
  intervals: z.array(z.tuple([z.coerce.number().finite(), z.coerce.number().finite()])).min(1),
  lastPosition: z.coerce.number().finite().nonnegative(),
  setId: uuidSchema,
  sourceUrl: z.string().url().nullable().optional(),
});

const parseSetIds = (request: Request) => {
  const { searchParams } = new URL(request.url);
  const rawSetIds = [
    ...searchParams.getAll("setId"),
    ...searchParams.getAll("setIds").flatMap((value) => value.split(",")),
  ];

  return z.array(uuidSchema).max(200).parse(
    rawSetIds
      .map((value) => value.trim())
      .filter(Boolean),
  );
};

export async function GET(request: Request) {
  const actor = await getRequestActor(request);
  if (!actor) {
    return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  }

  try {
    const setIds = parseSetIds(request);
    const progress = await listUserSetListenProgress(actor.userId, setIds);
    return NextResponse.json({ progress });
  } catch (error) {
    if (error instanceof ZodError) {
      return NextResponse.json(
        { error: error.issues[0]?.message ?? "Invalid set ids" },
        { status: 400 },
      );
    }

    throw error;
  }
}

export async function POST(request: Request) {
  const actor = await getRequestActor(request);
  if (!actor) {
    return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  }

  try {
    const input = upsertProgressSchema.parse(await readRequestBody(request));
    const intervals = parseListenIntervals(input.intervals, input.duration);
    if (intervals.length === 0) {
      return NextResponse.json({ error: "No listened intervals supplied" }, { status: 400 });
    }

    const progress = await upsertUserSetListenProgress(actor.userId, {
      duration: input.duration,
      intervals,
      lastPosition: input.lastPosition,
      setId: input.setId,
      sourceUrl: input.sourceUrl ?? null,
    });

    return NextResponse.json({ progress });
  } catch (error) {
    if (error instanceof ZodError) {
      return NextResponse.json(
        { error: error.issues[0]?.message ?? "Invalid listen progress payload" },
        { status: 400 },
      );
    }

    throw error;
  }
}
