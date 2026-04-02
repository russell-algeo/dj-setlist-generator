import { describe, expect, it } from "vitest";

import {
  isArtistImageDuplicate,
  resolveSetSpecificImageUrl,
} from "./set-images";

describe("resolveSetSpecificImageUrl", () => {
  it("returns the first set-specific image field", () => {
    expect(
      resolveSetSpecificImageUrl({
        poster_url: "https://example.com/poster.jpg",
        thumbnail_url: "https://example.com/thumb.jpg",
      }),
    ).toBe("https://example.com/thumb.jpg");
  });

  it("skips candidates that duplicate the artist profile image", () => {
    expect(
      resolveSetSpecificImageUrl({
        artist_profile_image: "https://example.com/artist.jpg",
        image_url: "https://example.com/artist.jpg",
        cover_image: "https://example.com/cover.jpg",
      }),
    ).toBe("https://example.com/cover.jpg");
  });

  it("returns null when only artist-level images are present", () => {
    expect(
      resolveSetSpecificImageUrl({
        artist_profile_image: "https://example.com/artist.jpg",
        image_url: "https://example.com/artist.jpg",
      }),
    ).toBeNull();
  });
});

describe("isArtistImageDuplicate", () => {
  it("detects duplicates against artist image fields", () => {
    expect(
      isArtistImageDuplicate(
        {
          artist_profile_image: "https://example.com/artist.jpg",
        },
        "https://example.com/artist.jpg",
      ),
    ).toBe(true);
  });

  it("ignores empty candidates", () => {
    expect(
      isArtistImageDuplicate(
        {
          artist_profile_image: "https://example.com/artist.jpg",
        },
        "",
      ),
    ).toBe(false);
  });
});
