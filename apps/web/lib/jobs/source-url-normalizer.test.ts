import { afterEach, describe, expect, it, vi } from "vitest";

import {
  cleanSoundCloudUrl,
  isSoundCloudShortUrl,
  resolveCanonicalSourceUrl,
  resolveCanonicalSourceUrls,
} from "./source-url-normalizer";

describe("source URL normalizer", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("detects SoundCloud short URLs", () => {
    expect(isSoundCloudShortUrl("https://on.soundcloud.com/lMS932ioS3yPO7fuGe")).toBe(true);
    expect(isSoundCloudShortUrl("https://snd.sc/example")).toBe(true);
    expect(isSoundCloudShortUrl("https://soundcloud.com/djulz/example")).toBe(false);
  });

  it("cleans canonical SoundCloud sharing parameters", () => {
    expect(
      cleanSoundCloudUrl(
        "https://www.soundcloud.com/djulz/djulz-refuge-ny-24-01-26?ref=clipboard&si=abc&utm_source=clipboard&secret_token=s-test",
      ),
    ).toBe("https://soundcloud.com/djulz/djulz-refuge-ny-24-01-26?secret_token=s-test");
  });

  it("resolves SoundCloud short links to canonical URLs", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      url: "https://soundcloud.com/djulz/djulz-refuge-ny-24-01-26?ref=clipboard&p=i&c=0&si=abc&utm_source=clipboard",
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(resolveCanonicalSourceUrl("https://on.soundcloud.com/lMS932ioS3yPO7fuGe")).resolves.toBe(
      "https://soundcloud.com/djulz/djulz-refuge-ny-24-01-26",
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "https://on.soundcloud.com/lMS932ioS3yPO7fuGe",
      expect.objectContaining({ method: "HEAD", redirect: "follow" }),
    );
  });

  it("falls back to GET if HEAD resolution fails", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error("HEAD failed"))
      .mockResolvedValueOnce({ url: "https://soundcloud.com/example/set" });
    vi.stubGlobal("fetch", fetchMock);

    await expect(resolveCanonicalSourceUrl("https://snd.sc/example")).resolves.toBe(
      "https://soundcloud.com/example/set",
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "https://snd.sc/example",
      expect.objectContaining({ method: "GET", redirect: "follow" }),
    );
  });

  it("dedupes URLs after canonicalization", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      url: "https://soundcloud.com/example/set?ref=clipboard",
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      resolveCanonicalSourceUrls([
        "https://on.soundcloud.com/example",
        "https://soundcloud.com/example/set",
      ]),
    ).resolves.toEqual(["https://soundcloud.com/example/set"]);
  });
});
