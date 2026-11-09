import "server-only";

const fileSharePath = /^\/(?:scl\/fi|s)\/[^/]+\/[^/]+$/;
const folderAudioPath = /^\/scl\/fo\/([A-Za-z0-9_-]+)\/([A-Za-z0-9_-]+)\/([^/]+)$/;

// Folder capabilities have only been approved for development and Preview.
// Do not use env.ts's default-to-development target for this release boundary.
function permitsFolderCapability(): boolean {
  const app = process.env.APP_ENVIRONMENT?.trim().toLowerCase();
  const vercel = process.env.VERCEL_ENV?.trim().toLowerCase();
  if (app === "production" || vercel === "production") return false;
  if (app && !["development", "preview"].includes(app)) return false;
  if (vercel && !["development", "preview"].includes(vercel)) return false;
  // APP_ENVIRONMENT=preview is the explicit deployed Preview label, including
  // when Vercel system variables are not exposed. A conflicting local target
  // must not turn that label into permission. APP_ENVIRONMENT=development with
  // VERCEL_ENV=preview remains the supported non-production database target.
  if (app === "preview") return !vercel || vercel === "preview";
  return vercel === "preview" ||
    ((!vercel || vercel === "development") && process.env.NODE_ENV === "development");
}

function safePathSegment(value: string): boolean {
  const decoded = decodeURIComponent(value);
  // Reject separators, double encoding and characters normalized by URL parsers.
  return Boolean(decoded) && decoded !== "." && decoded !== ".." &&
    !/[\u0000-\u001f\u007f/\\%?#]/u.test(decoded);
}

function isApprovedFolderFile(url: URL, pathname: string): boolean {
  if (!permitsFolderCapability() || !["dropbox.com", "www.dropbox.com"].includes(url.hostname)) return false;
  const match = folderAudioPath.exec(pathname);
  if (!match || !/^.+\.(?:wav|flac|m4a|mp4|mp3)$/i.test(decodeURIComponent(match[3]!))) return false;
  // Only the observed capability and media-mode fields are supported. A folder
  // root, listing, ZIP or query-selected path must never become an audio URL.
  const params = url.searchParams;
  if ([...params.keys()].some((key) => !["rlkey", "dl", "raw"].includes(key)) ||
    params.getAll("rlkey").length !== 1 || !/^[A-Za-z0-9_-]+$/.test(params.get("rlkey")!)) return false;
  for (const key of ["dl", "raw"]) {
    if (params.getAll(key).length > 1 || (params.has(key) && !/^[01]$/.test(params.get(key)!))) return false;
  }
  return true;
}

// Only reviewed Dropbox file-sharing URLs may be released. This is a bearer
// link, not identity-bound media authorization. Never fetch or log it here.
export function dropboxPlaybackUrl(value: string): string | null {
  try {
    // Inspect the original spelling before URL() can discard controls, collapse
    // dot segments or hide an explicit default port. This also prevents a folder
    // path from normalizing into the legacy standalone-file path family.
    if (/[\u0000-\u0020\u007f\\]/u.test(value)) return null;
    const original = /^https:\/\/([^/?#]+)(\/[^?#]*)(?:\?[^#]*)?$/i.exec(value);
    const url = new URL(value);
    if (!original || original[1]!.toLowerCase() !== url.hostname ||
      url.protocol !== "https:" || url.username || url.password || url.port || url.hash ||
      !["dropbox.com", "www.dropbox.com", "dl.dropboxusercontent.com"].includes(url.hostname)) return null;
    const pathname = original[2]!;
    if (!pathname.slice(1).split("/").every(safePathSegment) ||
      (!fileSharePath.test(pathname) && !isApprovedFolderFile(url, pathname))) return null;
    url.searchParams.delete("dl");
    url.searchParams.set("raw", "1");
    return url.toString();
  } catch { return null; }
}
