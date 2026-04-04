"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import {
  OperatorMetricCard,
  OperatorNotice,
  operatorUiStyles,
} from "@/components/operator/operator-ui";
import { formatTimestamp } from "@/lib/format";
import {
  sortSubmissionRuns,
  type SubmissionDetailDto,
  type SubmissionRunSortMode,
} from "@/lib/jobs/public";

import styles from "../operator.module.css";
import { StatusPill } from "../status-pill";
import { usePolledJson } from "../use-polled-json";
import { RunRow } from "./run-row";
import { WorkflowTimeline } from "./run-workflow-timeline";

type SubmissionDetailClientProps = {
  initialDetail: SubmissionDetailDto;
};

const RUNS_PAGE_SIZE = 20;

const MODE_LABEL: Record<string, string> = {
  artist: "Artist Discovery",
  curated_artist: "Curated Artist",
  url: "Single Set URL",
};

const detailHasActiveWork = (detail: SubmissionDetailDto) => detail.hasActiveWork;

const getOutcomeBanner = (detail: SubmissionDetailDto) => {
  switch (detail.submission.status) {
    case "completed":
      return {
        body: "All eligible set runs have finished processing.",
        title: "Submission complete",
        tone: "success" as const,
      };
    case "partial":
      return {
        body: "Some set runs completed successfully while others failed or were cancelled.",
        title: "Submission completed with failures",
        tone: "warning" as const,
      };
    case "failed":
      return {
        body: "No remaining active work was able to complete successfully.",
        title: "Submission failed",
        tone: "danger" as const,
      };
    case "cancelled":
      return {
        body: "Queued work was cancelled and active work was asked to stop.",
        title: "Submission cancelled",
        tone: "neutral" as const,
      };
    default:
      return null;
  }
};

export function SubmissionDetailClient({
  initialDetail,
}: SubmissionDetailClientProps) {
  const [sortMode, setSortMode] = useState<SubmissionRunSortMode>("status_first");
  const [runPage, setRunPage] = useState(1);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingActionKey, setPendingActionKey] = useState<string | null>(null);
  const runListRef = useRef<HTMLDivElement>(null);

  const {
    data: detail,
    isRefreshing,
    refreshError,
    lastUpdatedAt,
    refreshNow,
    isPollingPausedForInactivity,
    resumePolling,
  } = usePolledJson<SubmissionDetailDto>({
    getActivityToken: (nextDetail) => nextDetail.lastActivityAt,
    initialData: initialDetail,
    shouldPoll: detailHasActiveWork,
    url: `/api/jobs/${initialDetail.submission.id}`,
  });

  const sortedRuns = sortSubmissionRuns(detail.runs, sortMode);
  const totalRunPages = Math.max(1, Math.ceil(sortedRuns.length / RUNS_PAGE_SIZE));
  const currentRunPage = Math.min(runPage, totalRunPages);
  const pagedRuns = useMemo(
    () => sortedRuns.slice((currentRunPage - 1) * RUNS_PAGE_SIZE, currentRunPage * RUNS_PAGE_SIZE),
    [currentRunPage, sortedRuns],
  );
  const metricCards = [
    { label: "Total Sets", value: detail.counts.totalCount },
    { label: "Queued", value: detail.counts.queuedCount },
    { label: "In Flight", value: detail.counts.inFlightCount },
    { label: "Complete", value: detail.counts.completedCount },
    { label: "Failed", value: detail.counts.failedCount },
  ];

  if (detail.counts.cancelledCount > 0) {
    metricCards.push({ label: "Cancelled", value: detail.counts.cancelledCount });
  }

  const outcomeBanner = getOutcomeBanner(detail);
  const submissionAliases =
    detail.submission.mode === "artist" ? detail.submission.artistAliases.filter(Boolean) : [];

  const runAction = async (url: string, actionKey: string) => {
    setPendingActionKey(actionKey);
    setActionError(null);

    try {
      const response = await fetch(url, {
        headers: {
          accept: "application/json",
          "content-type": "application/json",
        },
        method: "POST",
      });

      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error((body as { error?: string }).error ?? `HTTP ${response.status}`);
      }

      await refreshNow();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Action failed");
    } finally {
      setPendingActionKey(null);
    }
  };

  const updateLabel = detail.hasActiveWork
    ? isPollingPausedForInactivity
      ? "Live updates paused after 5 minutes without new activity"
      : "Live updates active"
    : "Snapshot";

  useEffect(() => {
    setRunPage(1);
  }, [sortMode]);

  useEffect(() => {
    if (runPage > totalRunPages) {
      setRunPage(totalRunPages);
    }
  }, [runPage, totalRunPages]);

  const navigateRunPage = (nextPage: number) => {
    const clampedPage = Math.max(1, Math.min(totalRunPages, nextPage));
    setRunPage(clampedPage);
    requestAnimationFrame(() => {
      runListRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  };

  return (
    <div className={operatorUiStyles.stack}>
      <section className={styles.summaryHeader}>
        <div className={styles.summaryCopy}>
          <h1 className={styles.summaryTitle}>
            {detail.submission.artistName ?? detail.submission.sourceUrl ?? detail.submission.id}
          </h1>
          <div className={styles.summaryMeta}>
            <span>
              <strong>Mode:</strong> {MODE_LABEL[detail.submission.mode] ?? detail.submission.mode}
            </span>
            <span>
              <strong>Submitted:</strong> {formatTimestamp(detail.submission.createdAt)}
            </span>
            <span>
              <strong>Updated:</strong> {formatTimestamp(detail.submission.updatedAt)}
            </span>
          </div>

          {submissionAliases.length > 0 ? (
            <div className={styles.aliasRow}>
              <span className={operatorUiStyles.label}>Aliases</span>
              {submissionAliases.map((alias) => (
                <span className={styles.aliasChip} key={alias}>
                  {alias}
                </span>
              ))}
            </div>
          ) : null}

          <div className={operatorUiStyles.liveMetaRow}>
            <span>
              {updateLabel} · {isRefreshing ? "Refreshing…" : `Updated ${formatTimestamp(lastUpdatedAt)}`}
            </span>
          </div>

          {detail.lastActivityMessage ? (
            <div className={styles.latestPanel}>
              <div className={operatorUiStyles.label}>Latest Activity</div>
              <div className={styles.latestText}>
                {detail.lastActivityMessage} · {formatTimestamp(detail.lastActivityAt)}
              </div>
            </div>
          ) : null}
        </div>

        <div className={styles.summaryAside}>
          <StatusPill status={detail.submission.status} />
          <div className={styles.summaryActions}>
            {detail.hasActiveWork && isPollingPausedForInactivity ? (
              <button
                className={`${operatorUiStyles.button} ${operatorUiStyles.buttonGhost}`}
                onClick={() => void resumePolling()}
                type="button"
              >
                Resume live updates
              </button>
            ) : null}
            {detail.actions.canRetry ? (
              <button
                className={`${operatorUiStyles.button} ${operatorUiStyles.buttonPrimary}`}
                disabled={pendingActionKey === "submission:retry"}
                onClick={() =>
                  void runAction(`/api/jobs/${detail.submission.id}/retry`, "submission:retry")
                }
                type="button"
              >
                {pendingActionKey === "submission:retry" ? "Retrying…" : "Retry Failed Sets"}
              </button>
            ) : null}
            {detail.actions.canCancel ? (
              <button
                className={`${operatorUiStyles.button} ${operatorUiStyles.buttonDanger}`}
                disabled={pendingActionKey === "submission:cancel"}
                onClick={() =>
                  void runAction(`/api/jobs/${detail.submission.id}/cancel`, "submission:cancel")
                }
                type="button"
              >
                {pendingActionKey === "submission:cancel" ? "Cancelling…" : "Cancel Submission"}
              </button>
            ) : null}
          </div>
        </div>
      </section>

      {refreshError ? (
        <OperatorNotice
          body={`Live refresh failed: ${refreshError}`}
          title="Refresh error"
          tone="danger"
        />
      ) : null}

      {actionError ? (
        <OperatorNotice
          body={`Action failed: ${actionError}`}
          title="Action error"
          tone="danger"
        />
      ) : null}

      {outcomeBanner ? (
        <OperatorNotice
          action={
            detail.actions.canRetry ? (
              <button
                className={`${operatorUiStyles.button} ${operatorUiStyles.buttonPrimary}`}
                disabled={pendingActionKey === "submission:retry"}
                onClick={() =>
                  void runAction(`/api/jobs/${detail.submission.id}/retry`, "submission:retry")
                }
                type="button"
              >
                {pendingActionKey === "submission:retry" ? "Retrying…" : "Retry Failed Sets"}
              </button>
            ) : null
          }
          body={outcomeBanner.body}
          title={outcomeBanner.title}
          tone={outcomeBanner.tone}
        />
      ) : null}

      <section className={operatorUiStyles.metricGrid}>
        {metricCards.map(({ label, value }) => (
          <OperatorMetricCard key={label} label={label} value={value} />
        ))}
      </section>

      {detail.recognitionRate !== null ? (
        <section className={operatorUiStyles.factPanel}>
          <div className={operatorUiStyles.factList}>
            <span className={operatorUiStyles.fact}>
              <strong>Tracks identified:</strong> {detail.totalRecognized}
            </span>
            <span className={operatorUiStyles.fact}>
              <strong>Recognition rate:</strong> {detail.recognitionRate}%
            </span>
            {detail.discoveryCandidateCount > 0 ? (
              <span className={operatorUiStyles.fact}>
                <strong>Discovery candidates:</strong> {detail.discoveryCandidateCount}
              </span>
            ) : null}
          </div>
        </section>
      ) : null}

      {detail.submission.mode === "artist" && detail.workflowSteps ? (
        <section className={styles.workflowPanel}>
          <div className={operatorUiStyles.label}>Submission Timeline</div>
          <WorkflowTimeline steps={detail.workflowSteps} />
        </section>
      ) : null}

      {detail.submission.mode === "artist" && detail.runs.length === 0 && detail.hasActiveWork ? (
        <OperatorNotice
          body="Discovery is still running. Set runs will appear here as soon as discovery finishes and queued sets are created."
          title="No set runs yet"
          tone="neutral"
        />
      ) : null}

      <section className={operatorUiStyles.stack}>
        <div className={styles.runSectionHeader}>
          <div className={styles.runSectionLead}>Run order</div>
          <div className={operatorUiStyles.segmentRail}>
            <button
              className={`${operatorUiStyles.segmentItem} ${sortMode === "status_first" ? operatorUiStyles.segmentItemActive : ""}`}
              onClick={() => setSortMode("status_first")}
              type="button"
            >
              Status first
            </button>
            <button
              className={`${operatorUiStyles.segmentItem} ${sortMode === "original_order" ? operatorUiStyles.segmentItemActive : ""}`}
              onClick={() => setSortMode("original_order")}
              type="button"
            >
              Original order
            </button>
          </div>
        </div>

        <div className={styles.runSectionTable} ref={runListRef}>
          {sortedRuns.length > 0 ? (
            <div className={styles.runList}>
              <div className={styles.runHeader}>
                <span>Set Title</span>
                <span>Platform</span>
                <span>Stage</span>
                <span>Actions</span>
                <span className={styles.runHeaderStatus}>Status</span>
                <span />
              </div>
              {pagedRuns.map((run) => (
                <RunRow
                  cancelPending={pendingActionKey === `run:${run.id}:cancel`}
                  key={run.id}
                  onCancel={(runId) =>
                    void runAction(
                      `/api/jobs/${detail.submission.id}/runs/${runId}/cancel`,
                      `run:${runId}:cancel`,
                    )
                  }
                  onRetry={(runId) =>
                    void runAction(
                      `/api/jobs/${detail.submission.id}/runs/${runId}/retry`,
                      `run:${runId}:retry`,
                    )
                  }
                  retryPending={pendingActionKey === `run:${run.id}:retry`}
                  submissionId={detail.submission.id}
                  {...run}
                />
              ))}
            </div>
          ) : (
            <div className={operatorUiStyles.emptyState}>No set runs yet.</div>
          )}

          {sortedRuns.length > RUNS_PAGE_SIZE ? (
            <div className={operatorUiStyles.paginationRow}>
              <button
                className={`${operatorUiStyles.button} ${operatorUiStyles.buttonGhost} ${operatorUiStyles.paginationButtonPrev}`}
                disabled={currentRunPage <= 1}
                onClick={() => navigateRunPage(currentRunPage - 1)}
                type="button"
              >
                Prev
              </button>
              <span className={operatorUiStyles.paginationMeta}>
                Page {currentRunPage} / {totalRunPages} | {sortedRuns.length} sets
              </span>
              <button
                className={`${operatorUiStyles.button} ${operatorUiStyles.buttonGhost} ${operatorUiStyles.paginationButtonNext}`}
                disabled={currentRunPage >= totalRunPages}
                onClick={() => navigateRunPage(currentRunPage + 1)}
                type="button"
              >
                Next
              </button>
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}
