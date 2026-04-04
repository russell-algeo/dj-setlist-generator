import { describe, expect, it } from "vitest";

import { applyArtistCardImageFallbacks, buildHomeHeroPayload } from "./home-visuals";

describe("applyArtistCardImageFallbacks", () => {
  it("fills missing workspace artist images from a set-thumbnail fallback", () => {
    const artistCards = [
      {
        id: "artist-1",
        imageUrl: null,
        name: "Alpha",
        setCount: 3,
        slug: "alpha",
        totalAppearances: 0,
        uniqueTracks: 0,
      },
    ];

    const resolved = applyArtistCardImageFallbacks(
      artistCards,
      new Map([["alpha", "https://example.com/alpha.jpg"]]),
    );

    expect(resolved[0]?.imageUrl).toBe("https://example.com/alpha.jpg");
  });

  it("keeps a persisted artist image when one already exists", () => {
    const artistCards = [
      {
        id: "artist-1",
        imageUrl: "https://example.com/persisted.jpg",
        name: "Alpha",
        setCount: 3,
        slug: "alpha",
        totalAppearances: 0,
        uniqueTracks: 0,
      },
    ];

    const resolved = applyArtistCardImageFallbacks(
      artistCards,
      new Map([["alpha", "https://example.com/fallback.jpg"]]),
    );

    expect(resolved[0]?.imageUrl).toBe("https://example.com/persisted.jpg");
  });
});

describe("buildHomeHeroPayload", () => {
  it("uses workspace hero set candidates to populate the rail and hero fallback image", () => {
    const payload = buildHomeHeroPayload({
      artistCards: [
        {
          id: "artist-1",
          imageUrl: null,
          name: "Alpha",
          setCount: 3,
          slug: "alpha",
          totalAppearances: 0,
          uniqueTracks: 0,
        },
      ],
      heroSetCandidates: [
        {
          artistName: "Alpha",
          artistSlug: "alpha",
          duration: 3600,
          id: "set-1",
          recognitionRate: 92,
          slug: "set-1",
          thumbnailUrl: "https://example.com/set-thumb.jpg",
          title: "Set One",
          totalTracks: 18,
        },
      ],
      tickerItems: ["Artists 1"],
    });

    expect(payload.imageUrl).toBe("https://example.com/set-thumb.jpg");
    expect(payload.railSets).toHaveLength(8);
    expect(payload.railSets.every((setItem) => setItem.id === "set-1")).toBe(true);
  });
});
