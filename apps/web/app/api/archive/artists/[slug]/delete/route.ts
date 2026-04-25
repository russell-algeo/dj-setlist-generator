import { NextResponse } from "next/server";

import {
  ArchiveDeletionError,
  deleteArchiveArtistBySlug,
} from "@/lib/archive/deletions";
import { getSessionActor } from "@/lib/auth/session";
import { readRequestBody } from "@/lib/http/request-body";

type DeleteArtistRouteProps = {
  params: Promise<{ slug: string }>;
};

const getOptionalString = (value: unknown) => {
  if (typeof value === "string") {
    return value;
  }

  return null;
};

export async function POST(request: Request, { params }: DeleteArtistRouteProps) {
  const actor = await getSessionActor();
  if (!actor) {
    return NextResponse.json({ error: "Authentication required." }, { status: 401 });
  }

  const { slug } = await params;
  const body = await readRequestBody(request);

  try {
    const result = await deleteArchiveArtistBySlug({
      actor,
      reason: getOptionalString(body.reason),
      slug,
    });

    return NextResponse.json(result);
  } catch (error) {
    if (error instanceof ArchiveDeletionError) {
      return NextResponse.json({ error: error.message }, { status: error.status });
    }

    throw error;
  }
}
