import { describe, expect, it } from "vitest";
import { buildSkipTargets, nextSkipTarget, previousSkipTarget, provisionalPart } from "./skip-targets";
import { readProvisionalStarts } from "./set-projection";

const tracks = [
  { start: 0 },
  { start: 300, provisionalStarts: [620, 900] }, // Unknown 300-1200 with two estimated starts
  { start: 1200 },
];

describe("N04 skip targets", () => {
  it("includes provisional starts between track starts", () => {
    expect(buildSkipTargets(tracks)).toEqual([0, 300, 620, 900, 1200]);
  });

  it("next lands on the next estimated start inside an Unknown entry", () => {
    const targets = buildSkipTargets(tracks);
    expect(nextSkipTarget(targets, 310)).toBe(620);
    expect(nextSkipTarget(targets, 620)).toBe(900);
    expect(nextSkipTarget(targets, 900.5)).toBe(1200);
    expect(nextSkipTarget(targets, 1300)).toBeNull();
  });

  it("previous restarts the current part, double press goes one further back", () => {
    const targets = buildSkipTargets(tracks);
    expect(previousSkipTarget(targets, 700, false)).toBe(620);
    expect(previousSkipTarget(targets, 700, true)).toBe(300);
    expect(previousSkipTarget(targets, 0, true)).toBe(0);
  });

  it("without provisional starts behaves like plain track starts", () => {
    const plain = buildSkipTargets([{ start: 0 }, { start: 300 }, { start: 1200 }]);
    expect(nextSkipTarget(plain, 310)).toBe(1200);
    expect(previousSkipTarget(plain, 700, false)).toBe(300);
  });

  it("reports the estimated part", () => {
    expect(provisionalPart(tracks[1], 400)).toEqual({ part: 1, total: 3 });
    expect(provisionalPart(tracks[1], 950)).toEqual({ part: 3, total: 3 });
    expect(provisionalPart(tracks[0], 10)).toBeNull();
  });
});

describe("readProvisionalStarts", () => {
  it("keeps valid in-span values, sorted and spaced", () => {
    const metadata = {
      provisional_boundaries: [
        { start_seconds: 900, method: "audio-novelty-v1" },
        { start_seconds: 620.4 },
        { start_seconds: 630 }, // within 30s of 620: dropped
        { start_seconds: 310 }, // too close to entry start: dropped
        { start_seconds: "bad" },
        null,
        5000, // outside entry: dropped
      ],
    };
    expect(readProvisionalStarts(metadata, 300, 1200)).toEqual([620, 900]);
  });

  it("ignores missing or malformed data", () => {
    expect(readProvisionalStarts({}, 0, 100)).toEqual([]);
    expect(readProvisionalStarts({ provisional_boundaries: "x" }, 0, 100)).toEqual([]);
    expect(readProvisionalStarts({ provisional_boundaries: [50] }, 0, null)).toEqual([]);
  });
});
