import { describe, expect, it } from "vitest";

import {
  buildArchiveEmbed,
  buildSoundCloudEmbedUrl,
  buildTrackKey,
  buildYouTubeThumbnail,
  isEmbeddableSoundCloudUrl,
  normalizeArchiveConfidence,
} from "./utils";

describe("archive utils", () => {
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

  it("builds a SoundCloud embed URL", () => {
    expect(
      buildArchiveEmbed({
        sourcePlatform: "soundcloud",
        sourceUrl: "https://soundcloud.com/platform/channel-one-boiler-room-x-notting-hill-carnival-2017-dj-set",
      }),
    ).toContain("w.soundcloud.com/player/");
  });

  it("does not treat SoundCloud share links as embeddable widget URLs", () => {
    const sourceUrl = "https://on.soundcloud.com/lMS932ioS3yPO7fuGe";

    expect(isEmbeddableSoundCloudUrl(sourceUrl)).toBe(false);
    expect(buildSoundCloudEmbedUrl(sourceUrl)).toBeNull();
    expect(
      buildArchiveEmbed({
        sourcePlatform: "soundcloud",
        sourceUrl,
      }),
    ).toBeNull();
  });
});
