import { buildArchiveHtmlResponse } from "@/lib/archive/html-response";

export const dynamic = "force-dynamic";

export async function GET() {
  return buildArchiveHtmlResponse("/");
}
