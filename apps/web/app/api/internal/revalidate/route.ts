import { revalidatePath, revalidateTag } from "next/cache";
import { NextResponse } from "next/server";

import { assertInternalRequest } from "@/lib/auth/session";
import { readRequestBody } from "@/lib/http/request-body";

export async function POST(request: Request) {
  const denial = assertInternalRequest(request);
  if (denial) {
    return denial;
  }

  const body = await readRequestBody(request);
  const paths = body.paths
    ? Array.isArray(body.paths)
      ? body.paths.map((value) => String(value))
      : String(body.paths)
          .split(/\r?\n|,/u)
          .map((value) => value.trim())
          .filter(Boolean)
    : ["/", "/artists", "/sets"];
  const tags = body.tags
    ? Array.isArray(body.tags)
      ? body.tags.map((value) => String(value))
      : String(body.tags)
          .split(/\r?\n|,/u)
          .map((value) => value.trim())
          .filter(Boolean)
    : [];

  for (const path of paths) {
    revalidatePath(path);
  }

  for (const tag of tags) {
    revalidateTag(tag);
  }

  return NextResponse.json({ revalidated: { paths, tags } });
}
