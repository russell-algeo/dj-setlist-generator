import { getYoonActor, YOON_PRIVATE_HEADERS } from "@/lib/yoon-fest/access.server";
export const dynamic = "force-dynamic";
export const revalidate = 0;
export async function GET() {
  return new Response(null, { status: await getYoonActor() ? 204 : 404, headers: YOON_PRIVATE_HEADERS });
}
