import { createHash } from "node:crypto";
import path from "node:path";

import slugify from "slugify";

export const normalizeText = (value: string) =>
  value.trim().toLowerCase().replace(/\s+/g, " ");

export const makeSlug = (value: string, suffix?: string) => {
  const base = slugify(value, {
    lower: true,
    strict: true,
    trim: true,
  });

  return suffix ? `${base}-${suffix}` : base;
};

export const hashSuffix = (value: string, length = 8) =>
  createHash("sha1").update(value).digest("hex").slice(0, length);

export const detectSourcePlatform = (url?: string | null) => {
  if (!url) {
    return null;
  }

  if (url.includes("youtube.com") || url.includes("youtu.be")) {
    return "youtube";
  }

  if (url.includes("soundcloud.com") || url.includes("snd.sc")) {
    return "soundcloud";
  }

  return "unknown";
};

export const toLegacyPath = (absoluteRoot: string, absoluteFile: string) => {
  const relative = path.relative(absoluteRoot, absoluteFile).split(path.sep).join("/");
  return relative === "index.html" ? "/" : `/${relative}`;
};
