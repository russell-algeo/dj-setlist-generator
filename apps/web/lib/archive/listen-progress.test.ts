import { describe, expect, it } from "vitest";

import {
  calculateCoverageRatio,
  isListenedCoverage,
  mergeListenIntervals,
  parseListenIntervals,
} from "./listen-progress";

describe("listen progress interval utilities", () => {
  it("merges overlapping and adjacent listened intervals", () => {
    expect(
      mergeListenIntervals(
        [
          [20, 30],
          [0, 10],
          [9.8, 20.2],
          [90, 120],
          [120.3, 150],
        ],
        180,
      ),
    ).toEqual([
      [0, 30],
      [90, 150],
    ]);
  });

  it("clamps invalid interval input to the known duration", () => {
    expect(
      parseListenIntervals(
        [
          [-5, 5],
          [10, 7],
          [95, 105],
          ["bad", 30],
        ],
        100,
      ),
    ).toEqual([
      [0, 5],
      [95, 100],
    ]);
  });

  it("calculates unique coverage and applies the 75 percent listened threshold", () => {
    const coverageRatio = calculateCoverageRatio(
      [
        [0, 30],
        [20, 50],
        [70, 95],
      ],
      100,
    );

    expect(coverageRatio).toBe(0.75);
    expect(isListenedCoverage(coverageRatio)).toBe(true);
    expect(isListenedCoverage(0.7499)).toBe(false);
  });
});
