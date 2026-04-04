import { describe, expect, it } from "vitest";

import {
  buildArchiveCanonicalUrl,
  buildArtistSpotifyExportCandidates,
  buildArtistSpotifyExportCounts,
  buildSetSpotifyExportCandidates,
  buildSetSpotifyExportCounts,
  buildSpotifyPlaylistDescription,
} from "./spotify-export";

describe("buildSetSpotifyExportCandidates", () => {
  const detail = {
    tracks: [
      {
        idx: 1,
        title: "Alpha",
        conf: "HIGH",
        spotifyUrl: "https://open.spotify.com/track/track-alpha",
      },
      {
        idx: 2,
        title: "Unknown Track",
        conf: "MEDIUM",
        spotifyUrl: "https://open.spotify.com/track/track-unknown",
      },
      {
        idx: 3,
        title: "Beta",
        conf: "LOW",
        spotifyUrl: "https://open.spotify.com/track/track-beta",
      },
      {
        idx: 4,
        title: "Gamma",
        conf: "UNCERTAIN",
        spotifyUrl: "https://open.spotify.com/track/track-gamma",
      },
      {
        idx: 5,
        title: "Delta",
        conf: "HIGH",
        spotifyUrl: "https://open.spotify.com/search/delta",
      },
      {
        idx: 6,
        title: "Alpha (Repeat)",
        conf: "HIGH",
        spotifyUrl: "https://open.spotify.com/track/track-alpha",
      },
    ],
  };

  it("preserves set order and repeated tracks while skipping unknown and unresolved entries", () => {
    expect(buildSetSpotifyExportCandidates(detail as never).map((track) => track.spotifyTrackId)).toEqual([
      "track-alpha",
      "track-beta",
      "track-gamma",
      "track-alpha",
    ]);
  });

  it("counts all filters with all including uncertain candidates", () => {
    expect(buildSetSpotifyExportCounts(detail as never)).toEqual({
      all: 4,
      HIGH: 2,
      MEDIUM: 0,
      LOW: 1,
    });
  });
});

describe("buildArtistSpotifyExportCandidates", () => {
  const artist = {
    atlasTracks: [
      {
        confidence: "LOW",
        spotifyUrl: "https://open.spotify.com/track/track-a",
        trackKey: "track-a",
      },
      {
        confidence: "HIGH",
        spotifyUrl: "https://open.spotify.com/track/track-b",
        trackKey: "track-b",
      },
      {
        confidence: "HIGH",
        spotifyUrl: "https://open.spotify.com/track/track-a",
        trackKey: "track-a",
      },
      {
        confidence: "MEDIUM",
        spotifyUrl: "https://open.spotify.com/track/track-b",
        trackKey: "track-c",
      },
      {
        confidence: "HIGH",
        spotifyUrl: "https://open.spotify.com/search/track-d",
        trackKey: "track-d",
      },
      {
        confidence: "HIGH",
        spotifyUrl: "https://open.spotify.com/track/track-e",
        trackKey: "track-e",
      },
    ],
  };

  it("uses atlas order and dedupes by track key then spotify track id", () => {
    expect(buildArtistSpotifyExportCandidates(artist as never).map((track) => track.spotifyTrackId)).toEqual([
      "track-a",
      "track-b",
      "track-e",
    ]);
  });

  it("uses the first qualifying occurrence when a confidence filter is selected", () => {
    expect(
      buildArtistSpotifyExportCandidates(artist as never, "HIGH").map((track) => track.spotifyTrackId),
    ).toEqual(["track-b", "track-a", "track-e"]);
  });

  it("builds filter counts from the artist export rules", () => {
    expect(buildArtistSpotifyExportCounts(artist as never)).toEqual({
      all: 3,
      HIGH: 3,
      MEDIUM: 1,
      LOW: 1,
    });
  });
});

describe("spotify export url helpers", () => {
  it("builds canonical archive urls and playlist descriptions", () => {
    const canonicalUrl = buildArchiveCanonicalUrl({
      baseUrl: "https://dj-setlist-generator.vercel.app",
      entityType: "artist",
      slug: "arpiar",
    });

    expect(canonicalUrl).toBe("https://dj-setlist-generator.vercel.app/artists/arpiar");
    expect(buildSpotifyPlaylistDescription(canonicalUrl)).toBe(
      "Built from Set Signal Archive - https://dj-setlist-generator.vercel.app/artists/arpiar",
    );
  });
});
