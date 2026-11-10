import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ArchiveHeroEmpty, ArchiveRecognitionStat } from "./archive-recognition-stat";

describe("rendered recognition metric", () => {
  it("shows matched-window coverage even when all retained cards are identified", () => {
    const html = renderToStaticMarkup(<ArchiveRecognitionStat privateRecording recognitionRate={376 / 479 * 100} cardIdentificationRate={100} />);
    expect(html).toContain("78.5%");
    expect(html).toContain("Windows with a match");
    expect(html).not.toContain("100%");
  });
  it("preserves ordinary card metric and label", () => {
    const html = renderToStaticMarkup(<ArchiveRecognitionStat privateRecording={false} recognitionRate={78.5} cardIdentificationRate={100} />);
    expect(html).toContain("100%"); expect(html).toContain("Identified");
    expect(html).not.toContain("Windows with a match");
  });
  it.each([null, NaN, Infinity, -1, 101])("does not invent missing/invalid coverage: %s", rate => {
    expect(renderToStaticMarkup(<ArchiveRecognitionStat privateRecording recognitionRate={rate} cardIdentificationRate={100} />)).toContain("Unavailable");
  });
  it("keeps genuine zero distinct from unavailable", () => {
    expect(renderToStaticMarkup(<ArchiveRecognitionStat privateRecording recognitionRate={0} cardIdentificationRate={100} />)).toContain("0.0%");
  });
  it("does not claim tracks are absent when just artwork is missing", () => {
    expect(renderToStaticMarkup(<ArchiveHeroEmpty privateRecording trackCount={22} />)).toContain("Track artwork unavailable");
    expect(renderToStaticMarkup(<ArchiveHeroEmpty privateRecording={false} trackCount={22} />)).toContain("No track cards available");
    expect(renderToStaticMarkup(<ArchiveHeroEmpty privateRecording trackCount={0} />)).toContain("No track cards available");
  });
});
