import type { ArchiveLinkStatus } from "./types";

type Platform = "spotify" | "youtube" | "discogs";
const platforms: Platform[] = ["spotify", "youtube", "discogs"];
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
const text = (value: unknown) => typeof value === "string" && value.trim() ? value : null;

export const resolveArchiveTrackLinks = (input: {
  entryMetadata: unknown;
  trackMetadata: unknown;
  spotifyUrl: string | null;
  youtubeUrl: string | null;
  discogsUrl: string | null;
}) => {
  const entry = record(input.entryMetadata);
  const track = record(input.trackMetadata);
  const urls = { spotifyUrl: null, youtubeUrl: null, discogsUrl: null } as Record<`${Platform}Url`, string | null>;
  const linkStatus = {} as Record<Platform, ArchiveLinkStatus>;
  for (const platform of platforms) {
    const key = `${platform}_url`;
    // A versioned per-entry null is authoritative. A historical null can
    // simply mean enrichment was disabled; preserve that legacy fallback.
    const own = Boolean(text(entry[key])) || Number(entry.link_matching_version) >= 2 ||
      Object.hasOwn(record(entry.platform_matches), platform);
    const metadata = own ? entry : track;
    const url = own ? text(entry[key]) : input[`${platform}Url`] ?? text(track[key]);
    const evidence = record(record(metadata.platform_matches)[platform]);
    const hasEvidence = Object.keys(evidence).length > 0;
    const requiresEvidence = Number(metadata.link_matching_version) >= 2 && platform !== "discogs";
    const confirmed = evidence.status === "matched" && evidence.url === url && Boolean(url);
    const status: ArchiveLinkStatus = confirmed ? "confirmed" : hasEvidence || requiresEvidence ? "unverified" : "legacy";
    urls[`${platform}Url`] = status === "unverified" ? null : url;
    linkStatus[platform] = status;
  }
  return { ...urls, linkStatus };
};

export const selectPrimaryTrackLink = (track: {
  title: string;
  spotifyUrl: string | null;
  youtubeUrl: string | null;
  discogsUrl: string | null;
  linkStatus?: Partial<Record<Platform, ArchiveLinkStatus>>;
}): Platform | null => {
  if (track.title.trim().toLowerCase() === "unknown track") return null;
  for (const confirmedOnly of [true, false]) {
    for (const platform of platforms) {
      const url = track[`${platform}Url`];
      const status = track.linkStatus?.[platform] ?? "legacy";
      if (!url || status === "unverified" || (confirmedOnly && status !== "confirmed")) continue;
      if (platform === "spotify" && !/^https:\/\/open\.spotify\.com\/track\/[^/?#]+/.test(url)) continue;
      return platform;
    }
  }
  return null;
};
