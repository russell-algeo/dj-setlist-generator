import { describe, expect, it } from "vitest";

import { expandProvisionalTracks } from "./set-projection";
import type { ArchiveSetTrack } from "./types";

const track = (overrides: Partial<ArchiveSetTrack>): ArchiveSetTrack =>
  ({ idx: 1, artist: "Unknown Artist", title: "Unknown Track", start: 0, end: 450, startFmt: "0:00", endFmt: "7:30", conf: "low", provisionalStarts: [], ...overrides }) as ArchiveSetTrack;

describe("expandProvisionalTracks", () => {
  it("splits an Unknown entry into consecutive Unknown rows and renumbers", () => {
    const rows = expandProvisionalTracks([
      track({ idx: 1, provisionalStarts: [207] }),
      track({ idx: 2, title: "Known", artist: "A", start: 450, end: 700, startFmt: "7:30", endFmt: "11:40" }),
    ]);
    expect(rows.map((row) => [row.idx, row.title, row.start, row.end, row.estimatedStart ?? false])).toEqual([
      [1, "Unknown Track", 0, 207, false],
      [2, "Unknown Track", 207, 450, true],
      [3, "Known", 450, 700, false],
    ]);
    expect(rows[1].startFmt).toBe("3:27");
    expect(rows[0].endFmt).toBe("3:27");
    expect(rows[1].endFmt).toBe("7:30");
    expect(rows.every((row) => (row.provisionalStarts ?? []).length === 0)).toBe(true);
  });

  it("returns the same list when nothing is split", () => {
    const input = [track({}), track({ idx: 2, title: "Known" })];
    expect(expandProvisionalTracks(input)).toBe(input);
  });
});
