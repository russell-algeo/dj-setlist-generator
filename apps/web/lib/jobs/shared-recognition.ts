import { sql, type SQL } from "drizzle-orm";
import { segmentHits, setRuns } from "@/lib/db/schema";
import { isSamplingCapacityReason } from "./sampling-capacity";

export const sharedRecognition = (metadata: Record<string, unknown>) => {
  const value = metadata.shared_recognition;
  return value && typeof value === "object" && (value as Record<string, unknown>).version === 1
    ? value as Record<string, unknown> : null;
};

const validThrottleCounters = (state: Record<string, unknown>) => {
  const integer = (key: string) => typeof state[key] === "number" && Number.isSafeInteger(state[key]) && (state[key] as number) >= 0;
  const positive = (key: string) => typeof state[key] === "number" && Number.isFinite(state[key]) && (state[key] as number) > 0;
  return integer("requests") && integer("throttle_requests") && integer("continuations") &&
    (state.throttle_requests as number) <= (state.requests as number) &&
    positive("created_at") && positive("deadline") && integer("request_limit") &&
    (state.request_limit as number) > 0 && (state.request_limit as number) <= 8192 &&
    typeof state.next_allowed_at === "number" && Number.isFinite(state.next_allowed_at) && state.next_allowed_at >= 0;
};

// Only clean bounded recognition progress is exempt from ordinary recovery
// attempts. Preparation/storage failures can occur before any provider request.
export const sharedRecognitionConsumesRecoveryAttempt = (state: Record<string, unknown> | null) =>
  !state || (!isSamplingCapacityReason(state.reason) && !["workflow_time_budget", "recognition_retry_pending", "cooldown_pending",
    "recognition_requests_in_flight"].includes(String(state.reason)));

// Do not infer validity from row presence, recognized=false, or a legacy response.
export const sharedRecognitionNeedsReview = (state: Record<string, unknown>, inFlight = 0) =>
  state.review_required !== false || state.in_flight !== false || inFlight > 0 ||
  (state.policy_version !== undefined && ![1, 2, 3].includes(state.policy_version as number)) ||
  (state.policy_version === 3 && !validThrottleCounters(state));

export const sharedRecognitionExhausted = (state: Record<string, unknown>, segments: number, now = Date.now() / 1000) => {
  const number = (key: string) => typeof state[key] === "number" && Number.isFinite(state[key]) ? state[key] as number : NaN;
  const created = number("created_at"), deadline = number("deadline"), requests = number("requests"), continuations = number("continuations");
  const requestLimit = number("request_limit");
  const geometry = state.geometry as Record<string, unknown> | undefined;
  const prepared = Number.isInteger(segments) && segments > 0;
  const limit = prepared ? Math.min(8192, segments * 8, requestLimit) : requestLimit;
  const validGeometry = requests === 0 || (prepared && geometry?.segment_count === segments);
  if (state.policy_version === 3) {
    const throttleRequests = number("throttle_requests"), nextAllowed = number("next_allowed_at");
    // Deadline is retained as audit data. Only non-429 requests exhaust policy 3.
    return ["window_attempt_budget", "lifetime_request_budget"].includes(String(state.reason)) ||
      !(created > 0 && deadline > 0 && Number.isFinite(nextAllowed) && nextAllowed >= 0 &&
        Number.isSafeInteger(continuations) && continuations >= 0 &&
        Number.isSafeInteger(requestLimit) && requestLimit > 0 && requestLimit <= 8192 && validGeometry &&
        Number.isSafeInteger(requests) && requests >= 0 &&
        Number.isSafeInteger(throttleRequests) && throttleRequests >= 0 && throttleRequests <= requests &&
        requests - throttleRequests < limit);
  }
  const terminal = ["window_attempt_budget", "lifetime_request_budget", "lifetime_time_budget", "continuation_budget"];
  return terminal.includes(String(state.reason)) || !(created > 0 && deadline > now && deadline <= created + 7 * 86400 &&
    Number.isInteger(continuations) && continuations >= 0 && continuations < 256 &&
    Number.isInteger(requestLimit) && requestLimit > 0 && requestLimit <= 8192 && validGeometry &&
    Number.isInteger(requests) && requests >= 0 && requests < limit);
};

// The DB admission function is authoritative. Recheck its predicate while assigning
// the generation too, so a concurrent review flag/cooldown cannot be bypassed.
export const sharedRecognitionDispatchable = () =>
  sql`ops.shared_recognition_dispatchable(${setRuns.id}, ${setRuns.sourceMetadata})`;

const validProviderData = (data: SQL) => sql`(
  jsonb_typeof(${data}) = 'object'
  and jsonb_typeof(${data}->'matches') = 'array'
  and (not (${data} ? 'track') or jsonb_typeof(${data}->'track') = 'object')
  and (${data}->'matches' = '[]'::jsonb or jsonb_typeof(${data}->'track') = 'object')
)`;

export const validRecognitionHit = (shared: boolean, segmentCount: number, segmentStep?: number) => {
  const evidence = sql`${segmentHits.rawData}->'shared_recognition'`;
  const response = sql`${evidence}->'response'`;
  return sql`(
    ${segmentHits.segmentIndex} >= 0 and ${segmentHits.segmentIndex} < ${segmentCount}
    and case when ${shared} then
      ${typeof segmentStep === "number" && Number.isFinite(segmentStep) && segmentStep > 0}
      and ${evidence}->'version' = '1'::jsonb
      and ${evidence}->'valid' = 'true'::jsonb
      and ${evidence}->'in_flight' = 'false'::jsonb
      and ${response}->'http_status' = '200'::jsonb
      and coalesce(${response}->>'error_type', '') = ''
      and coalesce(${response}->'was_rate_limited', 'false'::jsonb) = 'false'::jsonb
      and ${response}->'segment_index' = to_jsonb(${segmentHits.segmentIndex})
      and ${response}->'timestamp' = to_jsonb(${segmentHits.timestampSeconds})
      and ${response}->'timestamp' = to_jsonb(${segmentHits.segmentIndex} * ${typeof segmentStep === "number" && Number.isFinite(segmentStep) ? segmentStep : null}::numeric)
      and ${validProviderData(sql`${response}->'raw_data'`)}
    else ${validProviderData(sql`${segmentHits.rawData}`)} end
  )`;
};
