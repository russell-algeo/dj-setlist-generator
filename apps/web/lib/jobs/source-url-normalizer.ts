const SOUNDCLOUD_SHORT_HOSTS = new Set(["on.soundcloud.com", "snd.sc"]);
const SOUNDCLOUD_HOSTS = new Set(["soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"]);
const SOUNDCLOUD_SHARE_PARAMS = new Set([
  "c",
  "p",
  "ref",
  "si",
  "utm_campaign",
  "utm_medium",
  "utm_source",
]);

const getHost = (sourceUrl: string) => {
  try {
    return new URL(sourceUrl).hostname.toLowerCase();
  } catch {
    return "";
  }
};

export const isSoundCloudShortUrl = (sourceUrl: string) =>
  SOUNDCLOUD_SHORT_HOSTS.has(getHost(sourceUrl));

export const isSoundCloudUrl = (sourceUrl: string) =>
  SOUNDCLOUD_HOSTS.has(getHost(sourceUrl));

export const cleanSoundCloudUrl = (sourceUrl: string) => {
  if (!isSoundCloudUrl(sourceUrl)) {
    return sourceUrl;
  }

  const parsed = new URL(sourceUrl);
  const next = new URL(parsed);
  next.protocol = "https:";
  next.hostname = "soundcloud.com";
  next.hash = "";

  for (const key of [...next.searchParams.keys()]) {
    if (SOUNDCLOUD_SHARE_PARAMS.has(key.toLowerCase())) {
      next.searchParams.delete(key);
    }
  }

  return next.toString();
};

const fetchRedirectTarget = async (sourceUrl: string, method: "GET" | "HEAD", timeoutMs: number) => {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(sourceUrl, {
      method,
      redirect: "follow",
      signal: controller.signal,
    });
    return response.url;
  } finally {
    clearTimeout(timeout);
  }
};

export const resolveCanonicalSourceUrl = async (
  sourceUrl: string,
  { timeoutMs = 8_000 }: { timeoutMs?: number } = {},
) => {
  if (isSoundCloudUrl(sourceUrl)) {
    return cleanSoundCloudUrl(sourceUrl);
  }

  if (!isSoundCloudShortUrl(sourceUrl)) {
    return sourceUrl;
  }

  for (const method of ["HEAD", "GET"] as const) {
    try {
      const resolvedUrl = await fetchRedirectTarget(sourceUrl, method, timeoutMs);
      if (isSoundCloudUrl(resolvedUrl)) {
        return cleanSoundCloudUrl(resolvedUrl);
      }
    } catch {
      // Fall through to the next method, then ultimately preserve the submitted URL.
    }
  }

  return sourceUrl;
};

export const resolveCanonicalSourceUrls = async (sourceUrls: string[]) => {
  const resolved = await Promise.all(sourceUrls.map((sourceUrl) => resolveCanonicalSourceUrl(sourceUrl)));
  return [...new Set(resolved)];
};
