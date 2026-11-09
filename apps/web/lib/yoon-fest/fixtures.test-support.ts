// Synthetic test data only. Never imported by runtime routes.
import type { SessionActor } from "@/lib/auth/session";
import type { YoonCollection } from "./collection-model.server";
export const principals = { russellUserId: "synthetic-russell", halUserId: "synthetic-hal" };
export const actor = (userId = principals.russellUserId, overrides: Partial<SessionActor> = {}): SessionActor => ({ authType: "session", userId, email: "synthetic@example.invalid", displayName: null, isAllowlisted: false, isAdmin: false, ...overrides });
export const fixture: YoonCollection = { collection: "yoon-fest", revision: "synthetic-v1", sets: [{
  id: "10000000-0000-4000-8000-000000000001", slug: "synthetic-set", title: "Synthetic Set", performer: "Synthetic Performer",
  boundaryStatus: "provisional", boundaryNote: "Synthetic boundaries, not a real recording.",
  spans: [{ recordingId: "synthetic-a", startSample: 44100, endSample: 485100, sampleRate: 44100 }, { recordingId: "synthetic-b", startSample: 0, endSample: 441000, sampleRate: 44100 }],
  audio: { assetId: "20000000-0000-4000-8000-000000000001", revision: "synthetic-v1", durationSeconds: 20, contentType: "audio/wav", sources: [
    { recordingId: "synthetic-a", url: "https://www.dropbox.com/scl/fi/synthetic-a/fixture.wav?rlkey=synthetic&raw=1" },
    { recordingId: "synthetic-b", url: "https://www.dropbox.com/scl/fi/synthetic-b/fixture.wav?rlkey=synthetic&raw=1" },
  ] },
  tracks: [{ position: 1, artist: "Synthetic Artist", title: "Synthetic Track A", startSeconds: 0, endSeconds: 12, confidence: "HIGH", spotifyUrl: "https://open.spotify.com/track/syntheticA" }, { position: 2, artist: "Synthetic Artist", title: "Synthetic Track B", startSeconds: 12, endSeconds: 20, confidence: "LOW", spotifyUrl: "https://open.spotify.com/track/syntheticB" }],
}] };
export function syntheticWave() {
  const bytes = new Uint8Array(172); const data = new DataView(bytes.buffer);
  const text = (offset: number, value: string) => [...value].forEach((char, index) => data.setUint8(offset + index, char.charCodeAt(0)));
  text(0, "RIFF"); data.setUint32(4, bytes.length - 8, true); text(8, "WAVE"); text(12, "fmt "); data.setUint32(16, 16, true); data.setUint16(20, 1, true); data.setUint16(22, 1, true);
  data.setUint32(24, 8000, true); data.setUint32(28, 16000, true); data.setUint16(32, 2, true); data.setUint16(34, 16, true); text(36, "data"); data.setUint32(40, 128, true);
  for (let i = 0; i < 64; i += 1) data.setInt16(44 + i * 2, Math.round(Math.sin(i * Math.PI / 8) * 1000), true);
  return bytes;
}

export const authorizeFixture = async (viewer: SessionActor | null) => Boolean(viewer?.authType === "session" && [principals.russellUserId, principals.halUserId].includes(viewer.userId));
