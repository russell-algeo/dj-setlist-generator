import { describe, expect, it } from "vitest";
import { sharedRecognitionExhausted, sharedRecognitionNeedsReview } from "./shared-recognition";

const now = 2000000;
const state = { version: 1, policy_version: 3, created_at: 1, deadline: 604801,
  requests: 1000005, throttle_requests: 1000000, request_limit: 16, continuations: 10000,
  geometry: { segment_count: 2 }, next_allowed_at: now + 3600, in_flight: false, review_required: false };

describe("durable actual-429 scheduling", () => {
  it("retains pending cooldowns across arbitrarily many bounded workflows", () => {
    expect(sharedRecognitionNeedsReview(state)).toBe(false);
    expect(sharedRecognitionExhausted(state, 2, now)).toBe(false);
  });
  it("still exhausts the non-throttle budget", () => {
    expect(sharedRecognitionExhausted({ ...state, requests: 1000016 }, 2, now)).toBe(true);
  });
  it.each([{ throttle_requests: undefined }, { throttle_requests: -1 }, { throttle_requests: 1000006 },
    { throttle_requests: 0.5 }, { requests: Infinity }, { requests: Number.MAX_SAFE_INTEGER + 1 },
    { continuations: -1 }, { deadline: Infinity }, { next_allowed_at: NaN }, { next_allowed_at: -1 },
    { policy_version: 4 }, { in_flight: true }, { review_required: true }])("requires reconciliation for malformed or uncertain %j", patch => {
    expect(sharedRecognitionNeedsReview({ ...state, ...patch })).toBe(true);
  });
  it("rejects mismatched geometry", () => {
    expect(sharedRecognitionExhausted(state, 3, now)).toBe(true);
  });
  it.each([1, 2])("keeps policy %s lifetime fences", policy_version => {
    expect(sharedRecognitionExhausted({ ...state, policy_version }, 2, now)).toBe(true);
  });
});


describe("non-provider workflow recovery budget", () => {
  it("only exempts clean recognition continuation reasons", async () => {
    const { sharedRecognitionConsumesRecoveryAttempt: consumes } = await import("./shared-recognition");
    for (const reason of ["workflow_time_budget", "recognition_retry_pending", "cooldown_pending", "recognition_requests_in_flight"])
      expect(consumes({ reason })).toBe(false);
    for (const reason of ["preparation_failed", "worker_or_storage_error", "cancelled_or_interrupted", "unknown", null])
      expect(consumes({ reason })).toBe(true);
    expect(consumes(null)).toBe(true);
  });
});
