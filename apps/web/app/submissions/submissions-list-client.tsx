"use client";

import type { CSSProperties } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  OperatorNotice,
  operatorUiStyles,
} from "@/components/operator/operator-ui";
import { formatTimestamp } from "@/lib/format";
import type {
  PublicSubmissionFilter,
  SubmissionListItemDto,
} from "@/lib/jobs/public";

import { StatusPill } from "./status-pill";
import { usePolledJson } from "./use-polled-json";

type SubmissionsListClientProps = {
  filterStatus: PublicSubmissionFilter;
  initialPage: number;
  initialSubmissions: SubmissionListItemDto[];
};

const PAGE_SIZE = 20;
const FILTER_TABS: Array<{ label: string; value: PublicSubmissionFilter }> = [
  { label: "All", value: "all" },
  { label: "Active", value: "active" },
  { label: "Partial", value: "partial" },
  { label: "Complete", value: "completed" },
  { label: "Failed", value: "failed" },
  { label: "Cancelled", value: "cancelled" },
];

const MODE_LABEL: Record<string, string> = {
  url: "Single Set URL",
  artist: "Artist Discovery",
  curated_artist: "Curated Artist",
};

const tableColumns = {
  "--operator-columns": "minmax(240px, 2fr) 160px minmax(180px, 1.25fr) 160px 120px",
  "--operator-min-width": "860px",
} as CSSProperties;

const submissionsHaveActiveWork = (items: SubmissionListItemDto[]) =>
  items.some((submission) => submission.hasActiveWork);

const getListActivityToken = (items: SubmissionListItemDto[]) =>
  items
    .filter((submission) => submission.hasActiveWork)
    .map((submission) => `${submission.id}:${submission.lastActivityAt}`)
    .join("|");

const describeCounts = (submission: SubmissionListItemDto) => {
  const parts = [`${submission.counts.completedCount}/${submission.counts.totalCount} complete`];

  if (submission.counts.queuedCount > 0) {
    parts.push(`${submission.counts.queuedCount} queued`);
  }

  if (submission.counts.inFlightCount > 0) {
    parts.push(`${submission.counts.inFlightCount} in flight`);
  }

  if (submission.counts.failedCount > 0) {
    parts.push(`${submission.counts.failedCount} failed`);
  }

  if (submission.counts.cancelledCount > 0) {
    parts.push(`${submission.counts.cancelledCount} cancelled`);
  }

  return parts.join(" · ");
};

export function SubmissionsListClient({
  filterStatus,
  initialPage,
  initialSubmissions,
}: SubmissionsListClientProps) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const listAnchorRef = useRef<HTMLDivElement>(null);
  const [page, setPage] = useState(initialPage);
  const {
    data: submissions,
    isRefreshing,
    refreshError,
    lastUpdatedAt,
    isPollingPausedForInactivity,
    resumePolling,
  } = usePolledJson<SubmissionListItemDto[]>({
    getActivityToken: getListActivityToken,
    initialData: initialSubmissions,
    parseResponse: async (response) => {
      const body = await response.json();
      return (body as { submissions: SubmissionListItemDto[] }).submissions;
    },
    shouldPoll: submissionsHaveActiveWork,
    url: filterStatus === "all" ? "/api/jobs" : `/api/jobs?status=${filterStatus}`,
  });
  const totalPages = Math.max(1, Math.ceil(submissions.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const pageSubmissions = useMemo(
    () => submissions.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE),
    [currentPage, submissions],
  );

  useEffect(() => {
    setPage(initialPage);
  }, [filterStatus, initialPage]);

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  const navigateToPage = (nextPage: number) => {
    const clampedPage = Math.max(1, Math.min(totalPages, nextPage));
    setPage(clampedPage);

    const params = new URLSearchParams(searchParams.toString());
    if (clampedPage <= 1) {
      params.delete("page");
    } else {
      params.set("page", String(clampedPage));
    }

    const href = params.toString() ? `${pathname}?${params.toString()}` : pathname;
    router.replace(href, { scroll: false });
    requestAnimationFrame(() => {
      listAnchorRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  };

  return (
    <div className={operatorUiStyles.stack} ref={listAnchorRef}>
      <div className={operatorUiStyles.liveMetaRow}>
        <span>
          {submissionsHaveActiveWork(submissions)
            ? isPollingPausedForInactivity
              ? "Live updates paused after 5 minutes without new activity"
              : "Live updates active"
            : "Snapshot"}
          {" · "}
          {isRefreshing ? "Refreshing…" : `Updated ${formatTimestamp(lastUpdatedAt)}`}
        </span>
        {submissionsHaveActiveWork(submissions) && isPollingPausedForInactivity ? (
          <button
            className={`${operatorUiStyles.button} ${operatorUiStyles.buttonGhost}`}
            onClick={() => void resumePolling()}
            type="button"
          >
            Resume live updates
          </button>
        ) : null}
      </div>

      {refreshError ? (
        <OperatorNotice
          body={`Live refresh failed: ${refreshError}`}
          title="Refresh error"
          tone="danger"
        />
      ) : null}

      <section className={operatorUiStyles.panel}>
        <div className={operatorUiStyles.panelBody}>
          <div className={operatorUiStyles.segmentRail}>
            {FILTER_TABS.map((tab) => (
              <Link
                className={`${operatorUiStyles.segmentLink} ${filterStatus === tab.value ? operatorUiStyles.segmentLinkActive : ""}`}
                href={tab.value === "all" ? "/submissions" : `/submissions?status=${tab.value}`}
                key={tab.value}
              >
                {tab.label}
              </Link>
            ))}
          </div>

          <div className={operatorUiStyles.tableScroller}>
            <div className={operatorUiStyles.tableGrid} style={tableColumns}>
              <div className={operatorUiStyles.tableHeaderRow} style={tableColumns}>
                <span>Submission</span>
                <span>Mode</span>
                <span>Sets</span>
                <span>Submitted</span>
                <span className={operatorUiStyles.alignRight}>Status</span>
              </div>

              {submissions.length === 0 ? (
                <div className={operatorUiStyles.emptyState}>No submissions yet.</div>
              ) : (
                pageSubmissions.map((submission) => (
                  <Link
                    className={`${operatorUiStyles.tableRow} ${operatorUiStyles.tableRowInteractive}`}
                    href={`/submissions/${submission.id}`}
                    key={submission.id}
                    style={tableColumns}
                  >
                    <div>
                      <div className={operatorUiStyles.cellTitle}>{submission.displayTitle}</div>
                      <div className={operatorUiStyles.cellMeta}>
                        {submission.id.slice(0, 8)}…
                      </div>
                    </div>
                    <span className={operatorUiStyles.muted}>
                      {MODE_LABEL[submission.mode] ?? submission.mode}
                    </span>
                    <div className={operatorUiStyles.muted}>{describeCounts(submission)}</div>
                    <span className={operatorUiStyles.dim}>
                      {formatTimestamp(submission.createdAt)}
                    </span>
                    <StatusPill align="right" status={submission.status} />
                  </Link>
                ))
              )}
            </div>
          </div>

          {submissions.length > PAGE_SIZE ? (
            <div className={operatorUiStyles.paginationRow}>
              <button
                className={`${operatorUiStyles.button} ${operatorUiStyles.buttonGhost} ${operatorUiStyles.paginationButtonPrev}`}
                disabled={currentPage <= 1}
                onClick={() => navigateToPage(currentPage - 1)}
                type="button"
              >
                Prev
              </button>
              <span className={operatorUiStyles.paginationMeta}>
                Page {currentPage} / {totalPages} | {submissions.length} submissions
              </span>
              <button
                className={`${operatorUiStyles.button} ${operatorUiStyles.buttonGhost} ${operatorUiStyles.paginationButtonNext}`}
                disabled={currentPage >= totalPages}
                onClick={() => navigateToPage(currentPage + 1)}
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
