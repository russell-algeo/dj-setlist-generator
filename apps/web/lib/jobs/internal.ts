import "server-only";

import { getDb } from "@/lib/db/client";
import { workerEvents } from "@/lib/db/schema";
import { setRunRetryAttemptLimit } from "./policy";

const db = getDb();

// How many automatic recovery attempts the scheduler will make before giving up.
export const automaticRecoveryAttemptLimit = setRunRetryAttemptLimit;

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
