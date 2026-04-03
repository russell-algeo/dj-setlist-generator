import { buildYouTubeThumbnail } from "./utils";

const SET_SPECIFIC_IMAGE_KEYS = [
  "thumbnail_url",
  "thumbnail",
  "image_url",
  "image",
  "artwork_url",
  "artwork",
  "cover_image",
  "coverUrl",
  "poster_url",
] as const;

const ARTIST_IMAGE_KEYS = ["artist_profile_image", "artist_image"] as const;

const normalizeImageUrl = (value: unknown) => {
  if (typeof value !== "string") {
    return null;
  }

  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
};

const artistImageSet = (mixInfo: Record<string, unknown>) =>
  new Set(
    ARTIST_IMAGE_KEYS.map((key) => normalizeImageUrl(mixInfo[key])).filter(
      (value): value is string => value != null,
    ),
  );

export const isArtistImageDuplicate = (
  mixInfo: Record<string, unknown>,
  candidate: unknown,
) => {
  const normalizedCandidate = normalizeImageUrl(candidate);
  if (!normalizedCandidate) {
    return false;
  }

  return artistImageSet(mixInfo).has(normalizedCandidate);
};

export const resolveSetSpecificImageUrl = (mixInfo: Record<string, unknown>) => {
  for (const key of SET_SPECIFIC_IMAGE_KEYS) {
    const candidate = normalizeImageUrl(mixInfo[key]);
    if (!candidate || isArtistImageDuplicate(mixInfo, candidate)) {
      continue;
    }

    return candidate;
  }

  return null;
};

export const resolveSetVisualImageUrl = (value: {
  imageUrl: string | null | undefined;
  metadata?: unknown;
  sourcePlatform: string | null | undefined;
  sourceUrl: string | null | undefined;
}) => {
  const setMetadata =
    value.metadata && typeof value.metadata === "object" && !Array.isArray(value.metadata)
      ? (value.metadata as Record<string, unknown>)
      : {};
  const mixInfo =
    setMetadata.mixInfo && typeof setMetadata.mixInfo === "object" && !Array.isArray(setMetadata.mixInfo)
      ? (setMetadata.mixInfo as Record<string, unknown>)
      : {};
  const persistedImage =
    value.imageUrl && !isArtistImageDuplicate(mixInfo, value.imageUrl) ? value.imageUrl : null;

  return (
    resolveSetSpecificImageUrl(mixInfo) ??
    persistedImage ??
    (value.sourcePlatform === "youtube" ? buildYouTubeThumbnail(value.sourceUrl ?? null) : null)
  );
};
