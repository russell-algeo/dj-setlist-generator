import "server-only";

// Only reviewed Dropbox file-sharing URLs may be released. This is a bearer
// link, not identity-bound media authorization. Never fetch or log it here.
export function dropboxPlaybackUrl(value: string): string | null {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password || url.port || url.hash ||
      !["dropbox.com", "www.dropbox.com", "dl.dropboxusercontent.com"].includes(url.hostname) ||
      !/^\/(?:scl\/fi|s)\/[^/]+\/[^/]+$/.test(url.pathname)) return null;
    url.searchParams.delete("dl");
    url.searchParams.set("raw", "1");
    return url.toString();
  } catch { return null; }
}
