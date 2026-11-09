import { serveYoonMedia } from "@/lib/yoon-fest/media.server";
export const dynamic = "force-dynamic";
export const revalidate = 0;
type Props = { params: Promise<{ assetId: string }> };
export async function GET(request: Request, { params }: Props) {
  return serveYoonMedia(request, (await params).assetId);
}
export async function HEAD(request: Request, { params }: Props) {
  return serveYoonMedia(request, (await params).assetId);
}
