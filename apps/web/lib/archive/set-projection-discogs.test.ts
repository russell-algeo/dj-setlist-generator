import { describe, it, expect } from "vitest";
import { mapSetTrack } from "./set-projection";
const row = {
  position: 1, displayArtist: "Tribalation", displayTitle: "Falling Down (Original Mix)",
  startTimeSeconds: 0, endTimeSeconds: 30, confidence: "HIGH", detectionCount: 3,
  clusterDensity: null, clusterSpan: null, sourceDeepLink: null, trackId: null,
  trackSpotifyUrl: null, trackYoutubeUrl: null, trackDiscogsUrl: null,
  entryMetadata: {}, trackMetadata: {},
};
const url = "https://www.discogs.com/release/1118178";
describe("Discogs release metadata projection", () => {
  it("marks validated compilation label as release-level, not original-track label", () => {
    const track = mapSetTrack({ ...row, entryMetadata: {
      discogs_url: url, discogs_matching_version: 1, discogs_metadata_scope: "release",
      discogs_label: "Compilation label", discogs_styles: ["Deep House"],
      platform_matches: { discogs: { status: "matched", url } },
    } });
    expect(track.label).toBe("Compilation label");
    expect(track.labelScope).toBe("release");
    expect(track.discogsUrl).toBe(url);
  });
  it("hides rejected Discogs-derived label/styles while retaining Spotify genres", () => {
    const track = mapSetTrack({ ...row, entryMetadata: {
      discogs_url: null, discogs_matching_version: 1, discogs_label: "Stale label",
      discogs_label_url: "https://www.discogs.com/label/123", discogs_styles: ["Stale Style"],
      discogs_genres: ["Stale Genre"], spotify_genres: ["Deep House"],
      platform_matches: { discogs: { status: "no_match", reason: "reviewed_rejection", rejected_url: url } },
    } });
    expect(track.label).toBeNull(); expect(track.labelUrl).toBeNull();
    expect(track.detailGenres).toEqual(["Deep House"]);
  });
});
