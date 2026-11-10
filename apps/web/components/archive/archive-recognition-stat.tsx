/** Private recording coverage uses provider windows, not the identified-card list. */
export function ArchiveRecognitionStat({ privateRecording, recognitionRate, cardIdentificationRate }: {
  privateRecording: boolean;
  recognitionRate: number | null;
  cardIdentificationRate: number;
}) {
  const validRate = recognitionRate !== null && Number.isFinite(recognitionRate)
    && recognitionRate >= 0 && recognitionRate <= 100;
  const value = privateRecording
    ? validRate ? `${recognitionRate.toFixed(1)}%` : "Unavailable"
    : `${cardIdentificationRate}%`;
  return <div className="stat">
    <span className="stat-value">{value}</span>
    <span className="stat-label">{privateRecording ? "Windows with a match" : "Identified"}</span>
  </div>;
}

export function ArchiveHeroEmpty({ privateRecording, trackCount }: {
  privateRecording: boolean; trackCount: number;
}) {
  return <div className="set-hero-side-empty">{
    privateRecording && trackCount > 0 ? "Track artwork unavailable. See the tracklist below." : "No track cards available."
  }</div>;
}
