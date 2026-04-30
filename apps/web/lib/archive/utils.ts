import type { ArchiveConfidence } from "@/lib/archive/types";

const CONFIDENCE_ORDER = new Set<ArchiveConfidence>(["HIGH", "MEDIUM", "LOW", "UNCERTAIN"]);

export const normalizeArchiveConfidence = (value: unknown): ArchiveConfidence => {
  const normalized = String(value ?? "UNCERTAIN").toUpperCase() as ArchiveConfidence;
  return CONFIDENCE_ORDER.has(normalized) ? normalized : "UNCERTAIN";
};

export const formatDuration = (seconds: number | null | undefined) => {
  const safeSeconds = Math.max(0, Math.floor(Number(seconds ?? 0)));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const remainder = safeSeconds % 60;

  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
  }

  return `${minutes}:${String(remainder).padStart(2, "0")}`;
};

export const formatCompactDuration = (seconds: number | null | undefined) => {
  const safeSeconds = Math.max(0, Math.floor(Number(seconds ?? 0)));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);

  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }

  return `${minutes}m`;
};

export const normalizeSearchText = (value: string) =>
  value
    .normalize("NFKD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/gu, " ")
    .trim();

export const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

export const getString = (value: unknown) => {
  if (typeof value !== "string") {
    return null;
  }

  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
};

export const getStringArray = (value: unknown) => {
  if (!Array.isArray(value)) {
    return [] as string[];
  }

  return value
    .map((entry) => getString(entry))
    .filter((entry): entry is string => Boolean(entry));
};

export const getNumber = (value: unknown) => {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === "string" && value.trim().length > 0) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  return null;
};

export const buildTrackKey = (artist: string, title: string, trackId?: string | null) => {
  if (trackId) {
    return `track:${trackId}`;
  }

  return `${normalizeSearchText(artist)}::${normalizeSearchText(title)}`;
};

export const buildSearchBlob = (...values: Array<string | null | undefined>) =>
  normalizeSearchText(values.filter(Boolean).join(" "));

export const buildSpotifySearchUrl = (artist: string, title: string) =>
  `https://open.spotify.com/search/${encodeURIComponent(`${artist} ${title}`.trim())}`;

export const buildYouTubeSearchUrl = (artist: string, title: string) =>
  `https://www.youtube.com/results?search_query=${encodeURIComponent(
    `${artist} ${title}`.trim(),
  )}`;

export const buildDiscogsSearchUrl = (artist: string, title: string) =>
  `https://www.discogs.com/search/?q=${encodeURIComponent(
    `${artist} ${title}`.trim(),
  )}&type=all`;

export const extractSpotifyTrackId = (url: string | null | undefined) => {
  if (!url) {
    return null;
  }

  try {
    const parsed = new URL(url);
    const parts = parsed.pathname.split("/").filter(Boolean);
    const trackIndex = parts.indexOf("track");

    if (trackIndex === -1 || trackIndex + 1 >= parts.length) {
      return null;
    }

    return parts[trackIndex + 1] ?? null;
  } catch {
    return null;
  }
};

export const extractYouTubeId = (sourceUrl: string) => {
  try {
    const url = new URL(sourceUrl);
    const host = url.hostname.replace(/^www\./u, "");

    if (host === "youtu.be") {
      return url.pathname.slice(1) || null;
    }

    if (host.endsWith("youtube.com")) {
      return url.searchParams.get("v");
    }
  } catch {
    return null;
  }

  return null;
};

export const buildYouTubeThumbnail = (sourceUrl: string | null) => {
  if (!sourceUrl) {
    return null;
  }

  const videoId = extractYouTubeId(sourceUrl);
  return videoId ? `https://img.youtube.com/vi/${videoId}/hqdefault.jpg` : null;
};

export const isEmbeddableSoundCloudUrl = (sourceUrl: string | null | undefined) => {
  if (!sourceUrl) {
    return false;
  }

  try {
    const host = new URL(sourceUrl).hostname.toLowerCase().replace(/^www\./u, "");
    return host === "soundcloud.com" || host === "m.soundcloud.com";
  } catch {
    return false;
  }
};

export const buildSoundCloudEmbedUrl = (
  sourceUrl: string | null | undefined,
  {
    color = "%23b9975b",
    visual = "true",
    showTeaser = "true",
  }: {
    color?: string;
    showTeaser?: "false" | "true";
    visual?: "false" | "true";
  } = {},
) => {
  if (!sourceUrl || !isEmbeddableSoundCloudUrl(sourceUrl)) {
    return null;
  }

  return (
    `https://w.soundcloud.com/player/?url=${encodeURIComponent(sourceUrl)}` +
    `&color=${color}&auto_play=false&hide_related=false&show_comments=false` +
    `&show_user=true&show_reposts=false&show_teaser=${showTeaser}&visual=${visual}`
  );
};

export const buildArchiveEmbed = ({
  sourcePlatform,
  sourceUrl,
}: {
  sourcePlatform: string | null;
  sourceUrl: string | null;
}) => {
  if (!sourceUrl) {
    return null;
  }

  const normalizedPlatform = String(sourcePlatform ?? "").toLowerCase();

  if (normalizedPlatform === "youtube" || normalizedPlatform === "youtu") {
    const videoId = extractYouTubeId(sourceUrl);
    return videoId
      ? `https://www.youtube-nocookie.com/embed/${videoId}?enablejsapi=1&rel=0&modestbranding=1&iv_load_policy=3&playsinline=1`
      : null;
  }

  if (normalizedPlatform === "soundcloud") {
    return buildSoundCloudEmbedUrl(sourceUrl);
  }

  return null;
};
