import { NextResponse } from "next/server";

import { getArchiveHomeNetworkPayload } from "@/lib/archive/home-explorer-data";

export async function GET() {
  const payload = await getArchiveHomeNetworkPayload();
  return NextResponse.json(payload);
}
