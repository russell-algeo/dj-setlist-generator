import { NextResponse } from "next/server";
import { ZodError, z } from "zod";

import {
  executeSpotifyExport,
  SpotifyExportNoTracksError,
  SpotifyExportNotFoundError,
  SpotifyExportRemoteError,
  SpotifyExportScopeError,
} from "@/lib/archive/spotify-export.server";
import type { SpotifyExportRequest } from "@/lib/archive/types";
import { getRequestActor } from "@/lib/auth/session";
import { readRequestBody } from "@/lib/http/request-body";
import {
  SpotifyConfigurationError,
  SpotifyConnectionError,
  SpotifyTokenRefreshError,
} from "@/lib/spotify/server";

const spotifyExportSchema = z.object({
  confidenceFilter: z.enum(["all", "HIGH", "MEDIUM", "LOW"]),
  entityType: z.enum(["artist", "set"]),
  scope: z.enum(["global", "mine"]).optional(),
  slug: z.string().trim().min(1),
});

export async function POST(request: Request) {
  const actor = await getRequestActor(request);
  if (!actor) {
    return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  }

  let input: SpotifyExportRequest;

  try {
    input = spotifyExportSchema.parse(await readRequestBody(request));
  } catch (error) {
    if (error instanceof ZodError) {
      return NextResponse.json(
        { error: error.issues[0]?.message ?? "Invalid export payload" },
        { status: 400 },
      );
    }

    throw error;
  }

  try {
    const result = await executeSpotifyExport(actor.userId, input);
    return NextResponse.json(result, { status: 201 });
  } catch (error) {
    if (error instanceof SpotifyExportNotFoundError) {
      return NextResponse.json({ error: error.message }, { status: 404 });
    }

    if (
      error instanceof SpotifyConnectionError ||
      error instanceof SpotifyConfigurationError ||
      error instanceof SpotifyExportScopeError
    ) {
      return NextResponse.json({ error: error.message }, { status: 409 });
    }

    if (error instanceof SpotifyExportNoTracksError) {
      return NextResponse.json({ error: error.message }, { status: 422 });
    }

    if (error instanceof SpotifyTokenRefreshError || error instanceof SpotifyExportRemoteError) {
      return NextResponse.json({ error: error.message }, { status: 502 });
    }

    throw error;
  }
}
