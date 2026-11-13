import { z } from "zod";

// Display-only coverage of a partial recording. Everything is on the recorded
// (set) clock: modeled gaps are markers, never padded silence.
const seconds = z.number().finite().nonnegative();
export const partialCoverageSchema = z.object({
  recordedSeconds: seconds.positive(), scheduledSeconds: seconds.positive(),
  openingUnmappedSeconds: seconds, tailUnmappedSeconds: seconds,
  gaps: z.array(z.object({ atRecordedSeconds: seconds.positive(), estimatedMissingSeconds: seconds.positive() }).strict()),
}).strict().superRefine((value, ctx) => {
  const missing = value.openingUnmappedSeconds + value.tailUnmappedSeconds
    + value.gaps.reduce((sum, gap) => sum + gap.estimatedMissingSeconds, 0);
  if (missing <= 0 || Math.abs(value.recordedSeconds + missing - value.scheduledSeconds) > 0.01) {
    ctx.addIssue({ code: "custom", message: "Partial coverage does not reconcile" });
  }
  let last = 0;
  for (const gap of value.gaps) {
    if (gap.atRecordedSeconds <= last || gap.atRecordedSeconds >= value.recordedSeconds) {
      ctx.addIssue({ code: "custom", message: "Invalid gap ordering" });
    }
    last = gap.atRecordedSeconds;
  }
});
export type PartialCoverage = z.infer<typeof partialCoverageSchema>;

export type RecordedCoverageView = { notes: string[]; gaps: { at: number; label: string }[] };

function minutes(value: number): string {
  if (value < 90) return `about ${Math.max(1, Math.round(value))} seconds`;
  return `about ${Math.round(value / 60)} minutes`;
}

const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

export function partialCoverageView(coverage: PartialCoverage): RecordedCoverageView {
  const notes = [
    `Partial recording: ${Math.round(coverage.recordedSeconds / 60)} of ${Math.round(coverage.scheduledSeconds / 60)} scheduled minutes were captured. Track times are provisional.`,
  ];
  if (coverage.openingUnmappedSeconds >= 1) notes.push(`${capital(minutes(coverage.openingUnmappedSeconds))} at the start of the slot were not recorded.`);
  if (coverage.tailUnmappedSeconds >= 1) notes.push(`${capital(minutes(coverage.tailUnmappedSeconds))} at the end of the slot were not recorded.`);
  return {
    notes,
    gaps: coverage.gaps.map((gap) => ({
      at: gap.atRecordedSeconds,
      label: `Recording gap, ${minutes(gap.estimatedMissingSeconds)} missing`,
    })),
  };
}
