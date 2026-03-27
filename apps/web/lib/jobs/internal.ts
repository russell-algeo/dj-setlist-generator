import "server-only";

import { getDb } from "@/lib/db/client";
import { workerEvents } from "@/lib/db/schema";

const db = getDb();

export const activeSetRunStatuses = [
  "dispatched",
  "resolving",
  "recognizing",
  "aggregating",
  "enriching",
  "publishing",
  "cancelling",
] as const;

export type ActiveSetRunStatus = (typeof activeSetRunStatuses)[number];

export const terminalSetRunStatuses = ["completed", "failed", "cancelled"] as const;

export type TerminalSetRunStatus = (typeof terminalSetRunStatuses)[number];

// How many automatic recovery attempts the scheduler will make before giving up.
export const automaticRecoveryAttemptLimit = 3;

export const createWorkerEvent = async (values: {
  submissionId?: string;
  setRunId?: string;
  eventType: string;
  message: string;
  details?: Record<string, unknown>;
}) => {
  await db.insert(workerEvents).values({
    submissionId: values.submissionId ?? null,
    setRunId: values.setRunId ?? null,
    eventType: values.eventType,
    message: values.message,
    details: values.details ?? {},
  });
};
