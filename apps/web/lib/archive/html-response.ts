import { getSitePageHtml } from "@/lib/archive/repository";

export const htmlHeaders = {
  "content-type": "text/html; charset=utf-8",
  "cache-control": "public, max-age=60, stale-while-revalidate=300",
};

export const buildArchiveHtmlResponse = async (pagePath: string) => {
  const html = await getSitePageHtml(pagePath);

  if (!html) {
    return new Response("Not Found", {
      status: 404,
      headers: {
        "content-type": "text/plain; charset=utf-8",
      },
    });
  }

  return new Response(html, {
    status: 200,
    headers: htmlHeaders,
  });
};
