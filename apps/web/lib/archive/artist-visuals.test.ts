import { describe, expect, it } from "vitest";

import { buildArtistHeroRail, pickFirstImageUrl } from "./artist-visuals";

describe("pickFirstImageUrl", () => {
  it("returns the first non-empty image candidate", () => {
    expect(
      pickFirstImageUrl([null, "   ", "https://example.com/hero.jpg", "https://example.com/alt.jpg"]),
    ).toBe("https://example.com/hero.jpg");
  });

  it("returns null when no candidate is usable", () => {
    expect(pickFirstImageUrl([null, "", "   "])).toBeNull();
  });
});

describe("buildArtistHeroRail", () => {
  it("cycles through every unique set that has an image", () => {
    const rail = buildArtistHeroRail([
      { id: "set-1", heroImageUrl: "https://example.com/1.jpg" },
      { id: "set-2", heroImageUrl: null },
      { id: "set-3", heroImageUrl: "https://example.com/3.jpg" },
      { id: "set-1", heroImageUrl: "https://example.com/1.jpg" },
    ]);

    expect(rail.map((setItem) => setItem.id)).toEqual([
      "set-1",
      "set-3",
      "set-1",
      "set-3",
    ]);
  });

  it("falls back to the full set list when no set has an image", () => {
    const rail = buildArtistHeroRail([
      { id: "set-1", heroImageUrl: null },
      { id: "set-2", heroImageUrl: null },
    ]);

    expect(rail.map((setItem) => setItem.id)).toEqual([
      "set-1",
      "set-2",
      "set-1",
      "set-2",
    ]);
  });
});
