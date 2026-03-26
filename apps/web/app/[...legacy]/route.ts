import { buildArchiveHtmlResponse } from "@/lib/archive/html-response";

export const dynamic = "force-dynamic";

type Params = {
  params: Promise<{
    legacy: string[];
  }>;
};

export async function GET(_request: Request, { params }: Params) {
  const { legacy } = await params;
  const pagePath = `/${legacy.join("/")}`;
  return buildArchiveHtmlResponse(pagePath);
}
