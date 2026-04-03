import { describe, expect, it } from "vitest";

import { maxArtistAliases, prepareArtistAliases } from "./artist-aliases";

describe("prepareArtistAliases", () => {
  it("normalizes aliases for artist discovery submissions", () => {
    const result = prepareArtistAliases({
      mode: "artist",
      artistName: "A:RPIA:R",
      artistAliases: ["  arpiar  ", "", "Danilo   Plessow", "ARPIAR"],
    });

    expect(result).toEqual({
      aliases: ["arpiar", "Danilo Plessow"],
      exceedsLimit: false,
    });
  });

  it("removes aliases that duplicate the primary artist name", () => {
    const result = prepareArtistAliases({
      mode: "artist",
      artistName: "Motor City Drum Ensemble",
      artistAliases: ["motor city   drum ensemble", "Danilo Plessow"],
    });

    expect(result.aliases).toEqual(["Danilo Plessow"]);
  });

  it("preserves distinct aliases in first-seen order", () => {
    const result = prepareArtistAliases({
      mode: "artist",
      artistName: "MCDE",
      artistAliases: ["Danilo Plessow", "Motor City Drum Ensemble", "MCDE Live"],
    });

    expect(result.aliases).toEqual(["Danilo Plessow", "Motor City Drum Ensemble", "MCDE Live"]);
  });

  it("flags when the unique normalized alias count exceeds the limit", () => {
    const result = prepareArtistAliases({
      mode: "artist",
      artistName: "DJ Test",
      artistAliases: Array.from({ length: maxArtistAliases + 1 }, (_, index) => `Alias ${index + 1}`),
    });

    expect(result.aliases).toHaveLength(maxArtistAliases);
    expect(result.exceedsLimit).toBe(true);
  });

  it("discards aliases for curated submissions", () => {
    const result = prepareArtistAliases({
      mode: "curated_artist",
      artistName: "DJ Test",
      artistAliases: ["Alias One", "Alias Two"],
    });

    expect(result).toEqual({
      aliases: [],
      exceedsLimit: false,
    });
  });
});
