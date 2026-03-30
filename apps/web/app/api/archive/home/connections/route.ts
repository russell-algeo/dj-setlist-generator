import { NextResponse } from "next/server";

import { getArchiveHomeConnections } from "@/lib/archive/data";

export async function GET() {
  const payload = await getArchiveHomeConnections();
  return NextResponse.json(payload);
}
