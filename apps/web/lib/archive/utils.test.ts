import { describe, expect, it } from "vitest";

import {
  buildArchiveEmbed,
  buildTrackKey,
  buildYouTubeThumbnail,
  normalizeArchiveConfidence,
  normalizeLegacyPath,
} from "./utils";

describe("archive utils", () => {
  it("normalizes legacy paths", () => {
    expect(normalizeLegacyPath("Ben UFO/artist_summary.html")).toBe("/Ben UFO/artist_summary.html");
    expect(normalizeLegacyPath("//Ben UFO///artist_summary.html")).toBe("/Ben UFO/artist_summary.html");
    expect(normalizeLegacyPath("/Ben%20UFO/artist_summary.html")).toBe("/Ben UFO/artist_summary.html");
    expect(normalizeLegacyPath("/Ben%2520UFO/artist_summary.html")).toBe("/Ben UFO/artist_summary.html");
  });

  it("normalizes archive confidence values", () => {
    expect(normalizeArchiveConfidence("high")).toBe("HIGH");
    expect(normalizeArchiveConfidence("nope")).toBe("UNCERTAIN");
  });

  it("builds stable fallback track keys", () => {
    expect(buildTrackKey("Ben UFO", "Needle and Thread")).toBe(
      "ben ufo::needle and thread",
    );
    expect(buildTrackKey("Ben UFO", "Needle and Thread", "abc")).toBe("track:abc");
  });

  it("derives a YouTube thumbnail and embed URL", () => {
    const sourceUrl = "https://youtu.be/p6ozF0Y-PzU?si=test";

    expect(buildYouTubeThumbnail(sourceUrl)).toBe(
      "https://img.youtube.com/vi/p6ozF0Y-PzU/hqdefault.jpg",
    );
    expect(
      buildArchiveEmbed({
        sourcePlatform: "youtube",
        sourceUrl,
      }),
    ).toContain("youtube-nocookie.com/embed/p6ozF0Y-PzU");
  });
});
