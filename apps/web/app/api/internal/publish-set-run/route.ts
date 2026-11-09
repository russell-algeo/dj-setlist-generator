import { and, eq, inArray, isNull, sql } from "drizzle-orm";
import { NextResponse } from "next/server";
import { z } from "zod";

import { refreshArchiveHomeMaterializedViews } from "@/lib/archive/home-materialized-views";
import { assertInternalRequest } from "@/lib/auth/session";
import { upsertArchiveSet } from "@/lib/archive/publish-set";
import { readRequestBody } from "@/lib/http/request-body";
import { getDb } from "@/lib/db/client";
import { setRuns, sets } from "@/lib/db/schema";
import { activeSetRunStatuses } from "@/lib/jobs/status";
import { hasUncommittedPublication, matchesWorkflowOwner, publicationCommittedStage } from "@/lib/jobs/publication";

const publishPayloadSchema = z.object({
  setRunId: z.string().uuid(),
  workflowRunId: z.string().min(1).optional(),
  payload: z.object({
    mix_info: z.record(z.string(), z.unknown()),
    metadata: z.record(z.string(), z.unknown()),
    tracks: z.array(z.record(z.string(), z.unknown())),
  }),
});

export async function POST(request: Request) {
  const denial = assertInternalRequest(request);
  if (denial) {
    return denial;
  }

  const body = publishPayloadSchema.parse(await readRequestBody(request));
  const db = getDb();
  // The UPDATE is the cancellation/publication linearization point. A read check
  // alone would let an accepted cancellation race with the archive writes below.
  const [claimed] = await db.update(setRuns).set({
    status: "publishing",
    stage: publicationCommittedStage,
    heartbeatAt: new Date(),
    updatedAt: new Date(),
  }).where(and(
    eq(setRuns.id, body.setRunId),
    inArray(setRuns.status, activeSetRunStatuses.filter((status) => status !== "cancelling")),
    isNull(setRuns.cancelRequestedAt),
    hasUncommittedPublication(),
    matchesWorkflowOwner(body.workflowRunId),
  )).returning({ id: setRuns.id });

  let published: Awaited<ReturnType<typeof upsertArchiveSet>>;
  if (!claimed) {
    const [run] = await db.select().from(setRuns).where(eq(setRuns.id, body.setRunId)).limit(1);
    if (!run) {
      return NextResponse.json({ error: "Set run not found", errorCode: "run_not_found" }, { status: 404 });
    }
    const metadata = (run.sourceMetadata ?? {}) as Record<string, unknown>;
    const owner = metadata.active_workflow_run_id;
    if (typeof owner === "string" && owner !== body.workflowRunId) {
      return NextResponse.json({ error: "Workflow no longer owns this run", errorCode: "workflow_superseded" }, { status: 409 });
    }
    // A response may have been lost after publication. Replay without rewriting
    // archive data; this also preserves legitimately published legacy runs.
    if (run.publishedSetId) {
      const saved = metadata.publication_result as typeof published | undefined;
      if (saved?.setId === run.publishedSetId) {
        published = saved;
      } else {
        const [set] = await db.select({ slug: sets.slug }).from(sets).where(eq(sets.id, run.publishedSetId)).limit(1);
        published = { setId: run.publishedSetId, slug: set?.slug ?? "", affectedArtistSlugs: [] };
      }
    } else {
      const cancelled = run.cancelRequestedAt || run.status === "cancelled" || run.status === "cancelling";
      return NextResponse.json({
        error: cancelled ? "Run cancellation was accepted" : "Run is not available for publication",
        errorCode: cancelled ? "run_cancelled" : run.stage === publicationCommittedStage ? "publication_in_progress" : "run_not_publishable",
      }, { status: 409 });
    }
  } else {
    // Any failure may leave partially applied remote writes. Keep the commit
    // marker on exceptions and caller timeouts; reconciliation, not cancellation
    // or a second writer, is required for an uncertain publication outcome.
    try {
      published = await upsertArchiveSet({
        payload: body.payload,
        provenance: { source: "worker", setRunId: body.setRunId },
      });

      // Persist success before responding or refreshing views. If the worker loses
      // the response, cancellation still cannot erase or relabel the published run.
      const [saved] = await db.update(setRuns).set({
        publishedSetId: published.setId,
        status: "completed",
        stage: "published",
        errorSummary: null,
        completedAt: new Date(),
        updatedAt: new Date(),
        sourceMetadata: sql`coalesce(${setRuns.sourceMetadata}, '{}'::jsonb) || ${JSON.stringify({ publication_result: published })}::jsonb`,
      }).where(and(
        eq(setRuns.id, body.setRunId),
        eq(setRuns.stage, publicationCommittedStage),
        matchesWorkflowOwner(body.workflowRunId),
        isNull(setRuns.publishedSetId),
      )).returning({ id: setRuns.id });
      if (!saved) {
        return NextResponse.json({
          error: "Publication state changed before the result could be recorded",
          errorCode: "workflow_superseded",
        }, { status: 409 });
      }
    } catch (error) {
      // A failed remote response is not proof of rollback. Surface the blocker,
      // but do not clear ownership or allow cancellation/retry to start a writer.
      try {
        await db.update(setRuns).set({
          errorSummary: "Publication outcome is uncertain. Reconcile archive writes before retrying.",
          updatedAt: new Date(),
        }).where(and(
          eq(setRuns.id, body.setRunId),
          eq(setRuns.stage, publicationCommittedStage),
          matchesWorkflowOwner(body.workflowRunId),
          isNull(setRuns.publishedSetId),
        ));
      } catch {
        console.error("publication_reconciliation_status_write_failed", { setRunId: body.setRunId });
      }
      throw error;
    }
  }

  try {
    await refreshArchiveHomeMaterializedViews();
  } catch (error) {
    const refreshError = error instanceof Error ? error.message : String(error);
    console.error("archive_home_materialized_view_refresh_failed", {
      setRunId: body.setRunId,
      refreshError,
    });
    return NextResponse.json(
      {
        ...published,
        error: refreshError,
        errorCode: "archive_home_materialized_view_refresh_failed",
      },
      { status: 500 },
    );
  }

  return NextResponse.json(published);
}
