import { describe, expect, it } from "vitest";

import {
  isArtistImageDuplicate,
  resolveSetSpecificImageUrl,
  resolveSetVisualImageUrl,
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

describe("resolveSetVisualImageUrl", () => {
  it("falls back to a YouTube thumbnail when no persisted image exists", () => {
    expect(
      resolveSetVisualImageUrl({
        imageUrl: null,
        metadata: {
          mixInfo: {},
        },
        sourcePlatform: "youtube",
        sourceUrl: "https://www.youtube.com/watch?v=2bf6M-XM_fI",
      }),
    ).toBe("https://img.youtube.com/vi/2bf6M-XM_fI/hqdefault.jpg");
  });

  it("prefers a set-specific image over the persisted image", () => {
    expect(
      resolveSetVisualImageUrl({
        imageUrl: "https://example.com/persisted.jpg",
        metadata: {
          mixInfo: {
            thumbnail_url: "https://example.com/thumbnail.jpg",
          },
        },
        sourcePlatform: "soundcloud",
        sourceUrl: "https://soundcloud.com/example/set",
      }),
    ).toBe("https://example.com/thumbnail.jpg");
  });
});
