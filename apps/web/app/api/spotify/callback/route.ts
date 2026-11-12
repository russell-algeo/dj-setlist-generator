// Retire the obsolete flow only on an explicitly identified Preview deployment.
// Either production signal wins; absent/conflicting/local labels preserve behavior.
function isExplicitPreview(): boolean {
  const app = process.env.APP_ENVIRONMENT?.trim().toLowerCase();
  const vercel = process.env.VERCEL_ENV?.trim().toLowerCase();
  if (app === "production" || vercel === "production") return false;
  if (app && !["preview", "development"].includes(app)) return false;
  if (vercel && !["preview", "development"].includes(vercel)) return false;
  return (app === "preview" && (!vercel || vercel === "preview")) ||
    (vercel === "preview" && (!app || app === "development"));
}

export async function GET(request: Request): Promise<Response> {
  if (isExplicitPreview()) {
    // No session lookup, cookie access, legacy module load, token exchange or DB.
    // Never echo OAuth code/state/error or redirect to a request-supplied URL.
    return new Response(
      'Legacy Spotify sign-in is retired on Preview. Use /api/auth/signin instead.\n',
      { status: 410, headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "private, no-store",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
      } },
    );
  }
  // Lazy load preserves the original handler outside Preview and avoids even its
  // module-level getDb() initialization on the retired Preview path.
  const legacy = await import("./legacy-handler");
  return legacy.GET(request);
}
