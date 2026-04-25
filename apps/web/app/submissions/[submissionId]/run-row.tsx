"use client";

import Link from "next/link";
import { useState, type KeyboardEvent } from "react";

import {
  OperatorNotice,
  operatorUiStyles,
} from "@/components/operator/operator-ui";
import { formatTimestamp } from "@/lib/format";
import type { SubmissionRunDto, SubmissionRunEventsPageDto } from "@/lib/jobs/public";

import { StatusPill } from "../status-pill";
import styles from "../operator.module.css";
import { RunWorkflowTimeline } from "./run-workflow-timeline";

type RunRowProps = SubmissionRunDto & {
  cancelPending: boolean;
  onCancel: (runId: string) => void;
  onRetry: (runId: string) => void;
  retryPending: boolean;
  submissionId: string;
};

export function RunRow({
  actions,
  attemptCount,
  cancelPending,
  displayStatus,
  errorSummary,
  id,
  lastActivityAt,
  lastActivityMessage,
  onCancel,
  onRetry,
  publishedSetSlug,
  retryPending,
  sourcePlatform,
  sourceUrl,
  stage,
  status,
  submissionId,
  title,
  updatedAt,
  workflowSteps,
}: RunRowProps) {
  const EVENTS_PAGE_SIZE = 6;
  const [expanded, setExpanded] = useState(false);
  const [eventsOpen, setEventsOpen] = useState(false);
  const [eventsData, setEventsData] = useState<SubmissionRunEventsPageDto | null>(null);
  const [eventsError, setEventsError] = useState<string | null>(null);
  const [eventsLoading, setEventsLoading] = useState(false);
  const toggleExpanded = () => setExpanded((value) => !value);
  const handleSummaryKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      toggleExpanded();
    }
  };
  const loadEventsPage = async (page: number) => {
    setEventsLoading(true);
    setEventsError(null);

    try {
      const response = await fetch(
        `/api/jobs/${submissionId}/runs/${id}/events?page=${page}&pageSize=${EVENTS_PAGE_SIZE}`,
        { headers: { accept: "application/json" } },
      );

      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error((body as { error?: string }).error ?? `HTTP ${response.status}`);
      }

      const body = (await response.json()) as SubmissionRunEventsPageDto;
      setEventsData(body);
    } catch (error) {
      setEventsError(error instanceof Error ? error.message : "Unable to load recent events");
    } finally {
      setEventsLoading(false);
    }
  };
  const toggleEvents = async () => {
    if (eventsOpen) {
      setEventsOpen(false);
      return;
    }

    setEventsOpen(true);
    if (!eventsData) {
      await loadEventsPage(1);
    }
  };

  return (
    <article className={styles.runRow}>
      <div
        aria-expanded={expanded}
        className={`${styles.runSummary} ${styles.runSummaryInteractive}`}
        onClick={toggleExpanded}
        onKeyDown={handleSummaryKeyDown}
        role="button"
        tabIndex={0}
      >
        <div className={styles.runSummaryButton}>
          <div className={operatorUiStyles.cellTitle}>{title ?? sourceUrl ?? id}</div>
          <div className={styles.runSubtitle}>{sourceUrl}</div>
        </div>
        <span className={operatorUiStyles.muted}>{sourcePlatform ?? "—"}</span>
        <span className={operatorUiStyles.muted}>{stage ?? "—"}</span>
        <div className={styles.runActions} onClick={(event) => event.stopPropagation()}>
          {actions.canRetry ? (
            <button
              className={`${operatorUiStyles.button} ${operatorUiStyles.buttonGhost}`}
              disabled={retryPending}
              onClick={() => onRetry(id)}
              type="button"
            >
              {retryPending ? "Retrying…" : "Retry"}
            </button>
          ) : null}
          {actions.canCancel ? (
            <button
              className={`${operatorUiStyles.button} ${operatorUiStyles.buttonGhost}`}
              disabled={cancelPending}
              onClick={() => onCancel(id)}
              type="button"
            >
              {cancelPending ? "Cancelling…" : "Cancel"}
            </button>
          ) : null}
          {!actions.canRetry && actions.retryExhausted ? (
            <span className={styles.retryExhausted}>Max retries</span>
          ) : null}
        </div>
        <StatusPill align="right" status={displayStatus} />
        <button
          aria-expanded={expanded}
          className={styles.runExpandButton}
          onClick={(event) => {
            event.stopPropagation();
            toggleExpanded();
          }}
          type="button"
        >
          {expanded ? "∨" : "›"}
        </button>
      </div>

      {expanded ? (
        <div className={styles.runExpanded}>
          <div className={styles.runMetaGrid}>
            {[
              { label: "Attempts", value: String(attemptCount) },
              { label: "Last activity", value: formatTimestamp(lastActivityAt ?? updatedAt) },
              { label: "Stage", value: stage ?? "—" },
              { label: "Retry budget", value: `${actions.retryBudgetRemaining} remaining` },
            ].map(({ label, value }) => (
              <div className={styles.metaBlock} key={label}>
                <div className={operatorUiStyles.label}>{label}</div>
                <div className={styles.metaValue}>{value}</div>
              </div>
            ))}
          </div>

          {lastActivityMessage ? (
            <div className={styles.inlinePanel}>
              <div className={operatorUiStyles.label}>Latest Update</div>
              <div className={styles.metaValue}>{lastActivityMessage}</div>
            </div>
          ) : null}

          <div className={styles.workflowPanel}>
            <div className={operatorUiStyles.label}>Processing Timeline</div>
            <RunWorkflowTimeline steps={workflowSteps} />
          </div>

          {eventsOpen ? (
            <div className={styles.workflowPanel}>
              <div className={styles.eventsHeader}>
                <div className={operatorUiStyles.label}>Recent Events</div>
              </div>

              {eventsError ? (
                <OperatorNotice
                  body={`Unable to load recent events: ${eventsError}`}
                  title="Recent events error"
                  tone="danger"
                />
              ) : eventsLoading && !eventsData ? (
                <div className={styles.eventsLoading}>Loading recent events…</div>
              ) : eventsData && eventsData.events.length > 0 ? (
                <div className={styles.events}>
                  {eventsData.events.map((event) => (
                    <div
                      className={`${styles.eventCard} ${event.tone === "danger" ? styles.eventCardDanger : ""} ${event.tone === "success" ? styles.eventCardSuccess : ""}`}
                      key={event.id}
                    >
                      <div className={styles.eventSummary}>{event.summary}</div>
                      {event.message !== event.summary ? (
                        <div className={styles.eventMessage}>{event.message}</div>
                      ) : null}
                      <div className={styles.eventTime}>{formatTimestamp(event.createdAt)}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className={styles.eventsLoading}>No recent events for this run.</div>
              )}

              {eventsData && eventsData.totalPages > 1 ? (
                <div className={operatorUiStyles.paginationRow}>
                  <button
                    className={`${operatorUiStyles.button} ${operatorUiStyles.buttonGhost} ${operatorUiStyles.paginationButtonPrev}`}
                    disabled={eventsLoading || eventsData.page <= 1}
                    onClick={() => void loadEventsPage(eventsData.page - 1)}
                    type="button"
                  >
                    Prev
                  </button>
                  <span className={operatorUiStyles.paginationMeta}>
                    Page {eventsData.page} / {eventsData.totalPages} | {eventsData.totalCount} events
                  </span>
                  <button
                    className={`${operatorUiStyles.button} ${operatorUiStyles.buttonGhost} ${operatorUiStyles.paginationButtonNext}`}
                    disabled={eventsLoading || eventsData.page >= eventsData.totalPages}
                    onClick={() => void loadEventsPage(eventsData.page + 1)}
                    type="button"
                  >
                    Next
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}

          {errorSummary ? (
            <div className={`${styles.inlinePanel} ${styles.inlinePanelDanger}`}>
              <div className={operatorUiStyles.label}>Error</div>
              <div className={styles.errorText}>{errorSummary}</div>
            </div>
          ) : null}

          <div className={styles.expandedFooter}>
            <div className={styles.expandedFooterActions}>
              <button
                className={`${operatorUiStyles.button} ${operatorUiStyles.buttonGhost}`}
                onClick={() => void toggleEvents()}
                type="button"
              >
                {eventsOpen ? "Hide Recent Events" : "See Recent Events"}
              </button>
              {status === "completed" && publishedSetSlug ? (
                <Link
                  className={`${operatorUiStyles.buttonLink} ${operatorUiStyles.buttonGhost}`}
                  href={`/sets/${publishedSetSlug}`}
                >
                  View Set in Archive →
                </Link>
              ) : null}
            </div>

            {!actions.canRetry && actions.retryExhausted ? (
              <OperatorNotice
                body="The retry budget has been exhausted for this set run."
                title="Retry budget exhausted"
                tone="warning"
              />
            ) : null}
          </div>
        </div>
      ) : null}
    </article>
  );
}
