import { describe, expect, it } from "vitest";
import { partialCoverageSchema, partialCoverageView } from "./partial-coverage";

const gapSet = { recordedSeconds: 5376.033469387755, scheduledSeconds: 5400, openingUnmappedSeconds: 0,
  tailUnmappedSeconds: 0, gaps: [{ atRecordedSeconds: 381.6171428571429, estimatedMissingSeconds: 23.9665306122449 }] };

describe("partial recording coverage", () => {
  it("marks a modeled gap on the recorded clock without padding", () => {
    const view = partialCoverageView(partialCoverageSchema.parse(gapSet));
    expect(view.gaps).toEqual([{ at: 381.6171428571429, label: "Recording gap, about 24 seconds missing" }]);
    expect(view.notes[0]).toContain("90 of 90 scheduled minutes");
  });
  it("describes unrecorded opening and tail time", () => {
    const view = partialCoverageView(partialCoverageSchema.parse({ recordedSeconds: 3927.2228571428573, scheduledSeconds: 7200,
      openingUnmappedSeconds: 0, tailUnmappedSeconds: 3272.7771428571427, gaps: [] }));
    expect(view.notes).toEqual([expect.stringContaining("65 of 120"), "About 55 minutes at the end of the slot were not recorded."]);
    expect(view.gaps).toEqual([]);
  });
  it("rejects coverage that does not reconcile or a gap outside the recording", () => {
    expect(() => partialCoverageSchema.parse({ ...gapSet, scheduledSeconds: 6000 })).toThrow();
    expect(() => partialCoverageSchema.parse({ ...gapSet, recordedSeconds: 300, scheduledSeconds: 323.9665306122449 })).toThrow();
    expect(() => partialCoverageSchema.parse({ ...gapSet, source: "x" })).toThrow();
  });
});
