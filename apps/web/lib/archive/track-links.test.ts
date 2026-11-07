import { describe, expect, it } from "vitest";
import { resolveArchiveTrackLinks, selectPrimaryTrackLink } from "./track-links";

const spotifyUrl = "https://open.spotify.com/track/3cuhpRVEXe8tGKDGsYZrR0";
const youtubeUrl = "https://www.youtube.com/watch?v=R2bda4X9v4E";
const empty = { entryMetadata: {}, trackMetadata: {}, spotifyUrl: null, youtubeUrl: null, discogsUrl: null };
const confirmedYoutube = { status: "matched", url: youtubeUrl, title: "So Right", artists: ["U.S. Collective"] };

describe("archive track link evidence", () => {
  it("shows the verified YouTube result when Spotify was rejected, despite a stale canonical URL", () => {
    const links = resolveArchiveTrackLinks({ ...empty, spotifyUrl, entryMetadata: {
      link_matching_version: 2, spotify_url: null, youtube_url: youtubeUrl,
      platform_matches: { spotify: { status: "unverified" }, youtube: confirmedYoutube },
    } });
    expect(links.spotifyUrl).toBeNull();
    expect(links.linkStatus).toEqual({ spotify: "unverified", youtube: "confirmed", discogs: "legacy" });
    expect(selectPrimaryTrackLink({ title: "So Right", ...links })).toBe("youtube");
  });

  it("prefers a confirmed alternative to a legacy Spotify URL", () => {
    expect(selectPrimaryTrackLink({ title: "So Right", spotifyUrl, youtubeUrl, discogsUrl: null,
      linkStatus: { spotify: "legacy", youtube: "confirmed" } })).toBe("youtube");
  });

  it("keeps a valid confirmed Spotify match ahead of confirmed YouTube", () => {
    const links = resolveArchiveTrackLinks({ ...empty, entryMetadata: {
      link_matching_version: 2, spotify_url: spotifyUrl, youtube_url: youtubeUrl,
      platform_matches: { spotify: { status: "matched", url: spotifyUrl }, youtube: confirmedYoutube },
    } });
    expect(selectPrimaryTrackLink({ title: "So Right", ...links })).toBe("spotify");
  });

  it("does not treat missing or mismatched evidence as confirmation", () => {
    for (const evidence of [undefined, { status: "unverified" }, { status: "matched", url: "other" }]) {
      const links = resolveArchiveTrackLinks({ ...empty, entryMetadata: {
        link_matching_version: 2, spotify_url: spotifyUrl, platform_matches: { spotify: evidence },
      } });
      expect(links.spotifyUrl).toBeNull();
      expect(selectPrimaryTrackLink({ title: "So Right", ...links })).toBeNull();
    }
  });

  it("preserves explicit nulls and per-entry URLs without borrowing canonical evidence", () => {
    const links = resolveArchiveTrackLinks({ ...empty, spotifyUrl, entryMetadata: { spotify_url: null, link_matching_version: 2 },
      trackMetadata: { link_matching_version: 2, platform_matches: { spotify: { status: "matched", url: spotifyUrl } } } });
    expect(links.spotifyUrl).toBeNull();
    expect(links.linkStatus.spotify).toBe("unverified");
    const perEntry = "https://open.spotify.com/track/entry";
    expect(resolveArchiveTrackLinks({ ...empty, spotifyUrl, entryMetadata: { spotify_url: perEntry } }).spotifyUrl).toBe(perEntry);
  });

  it("preserves historical URLs as legacy without falsely verifying them", () => {
    const links = resolveArchiveTrackLinks({ ...empty, spotifyUrl, youtubeUrl });
    expect(links.linkStatus.spotify).toBe("legacy");
    expect(selectPrimaryTrackLink({ title: "So Right", ...links })).toBe("spotify");
    expect(resolveArchiveTrackLinks({ ...empty, spotifyUrl, entryMetadata: { spotify_url: null } }).spotifyUrl).toBe(spotifyUrl);
  });

  it("falls back to Discogs and excludes unknown tracks and search URLs", () => {
    const discogsUrl = "https://www.discogs.com/release/437605";
    expect(selectPrimaryTrackLink({ title: "So Right", spotifyUrl: "https://open.spotify.com/search/right", youtubeUrl: null, discogsUrl })).toBe("discogs");
    expect(selectPrimaryTrackLink({ title: "Unknown Track", spotifyUrl, youtubeUrl, discogsUrl })).toBeNull();
  });
});
