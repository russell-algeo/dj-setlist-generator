import { describe, expect, it } from "vitest";
import { yoonCollectionSchema } from "./collection-model.server";
import { toYoonSetDetail } from "./data.server";
import { fixture } from "./fixtures.test-support";
describe("validated private collection DTO", () => {
  it.each(["audio/flac", "audio/mp4", "audio/wav", "audio/mpeg"] as const)("supports the selected recording MIME without imposing a lossy encoding: %s", (contentType) => {
    const recording = structuredClone(fixture); recording.sets[0]!.audio.contentType = contentType;
    expect(yoonCollectionSchema.parse(recording).sets[0]!.audio.contentType).toBe(contentType);
  });
  it("validates sample spans and timeline", () => expect(yoonCollectionSchema.parse(fixture)).toEqual(fixture));
  it("rejects other collections, arbitrary fields and invalid spans", () => { expect(() => yoonCollectionSchema.parse({ ...fixture, collection: "other" })).toThrow(); expect(() => yoonCollectionSchema.parse({ ...fixture, sourceUrl: "https://example.test" })).toThrow(); const bad = structuredClone(fixture); bad.sets[0]!.spans[0]!.endSample = 0; expect(() => yoonCollectionSchema.parse(bad)).toThrow(); });
  it("never serializes provenance, asset identities or public recording links", () => { const detail = toYoonSetDetail(fixture.sets[0]!); const text = JSON.stringify(detail); expect(text).not.toContain("synthetic-a"); expect(text).not.toContain("startSample"); expect(text).not.toContain("dropbox"); expect(text).not.toContain("rlkey"); expect(text).not.toContain(fixture.sets[0]!.audio.assetId); expect(detail.sourceUrl).toBeNull(); expect(detail.sourceLinks).toEqual([]); expect(detail.artists).toEqual([]); });
});
